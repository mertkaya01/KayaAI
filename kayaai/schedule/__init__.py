"""Zamanlanmış görevler (Adım 13; sahip kararı: Windows Görev Zamanlayıcı).

Oluşturma, değiştirme ve silme Windows'un görev kayıtlarını değiştirdiği için **R2 sahip onayı** ister (önizleme:
sıklık, sonraki çalışma, tam komut). Aç/kapat ve "şimdi çalıştır" R1 (kayda geçer).
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..core.permissions import Risk, SubmitResult, ToolAction
from . import windows
from .model import KIND_LABEL, Cadence, Run, Schedule
from .runner import ScheduleError, load, run_schedule, save, state_dir

if TYPE_CHECKING:
    from ..runtime import Runtime

__all__ = ["Cadence", "KIND_LABEL", "Run", "Schedule", "ScheduleError", "executors", "list_schedules",
           "request_create", "request_delete", "request_enable", "request_run", "sync_report"]


def list_schedules(rt: "Runtime") -> list[dict[str, Any]]:
    ids = windows.registered_ids()
    out = []
    for raw in rt.store.list_schedules():
        s = Schedule.model_validate(raw)
        nxt = s.next_run()
        out.append({**s.model_dump(mode="json"), "summary": s.summary(), "cadence_text": s.cadence.describe(),
                    "next_run": nxt.isoformat() if nxt else None,
                    "in_windows": (s.id in ids) if ids is not None else None})
    return out


def _validate(rt: "Runtime", s: Schedule) -> None:
    if s.kind == "sales_report":
        assert rt.files is not None
        p, _ = rt.files.resolve(str(s.params["path"]))
        if not p.is_file():
            raise ScheduleError(f"Dosya yok: {p}")
        if p.suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".tsv"):
            raise ScheduleError("Satış raporu için Excel (.xlsx) ya da CSV dosyası gerekli")
    if s.kind == "docs_digest" and s.params.get("folder"):
        assert rt.files is not None
        p, _ = rt.files.resolve(str(s.params["folder"]))
        if not p.is_dir():
            raise ScheduleError(f"Klasör yok: {p}")
    if s.skip_holidays:
        from ..integrations import is_enabled

        if not is_enabled(rt, "holidays"):
            raise ScheduleError("'Resmi tatilde çalışma' için önce tatil takvimini aç (kayaai integrations enable holidays)")
    if s.cadence.next_after(datetime.now()) is None:
        raise ScheduleError("Tek seferlik görevin zamanı geçmiş")


def request_create(rt: "Runtime", s: Schedule, requested_by: str = "user") -> SubmitResult:
    _validate(rt, s)
    if rt.store.get_schedule(s.id):
        raise ScheduleError(f"Bu kimlikte görev zaten var: {s.id}")
    exe, args = windows.command(s)
    nxt = s.next_run()
    where = (f"Windows Görev Zamanlayıcı: \\{windows.task_name(s.id)} (oturum açıkken, senin hesabınla, yönetici yetkisi yok)"
             if windows.supported() else "Windows dışı: Görev Zamanlayıcı yok — `kayaai schedule run-due` ile çalışır")
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="schedule.create", params={"schedule": s.model_dump(mode="json")}, risk=Risk.R2,
        summary=f"Zamanlanmış görev ekle: {s.summary()}",
        reason="Windows'un görev kayıtlarına ekleme yapılır; görev kayaAI kapalıyken de kendiliğinden çalışır.",
        preview={"new_head": f"{s.summary()}\nİlk çalışma: {nxt:%d.%m.%Y %H:%M}\n"
                             f"Kaçırılanı telafi: {'evet' if s.catch_up else 'hayır'}\n{where}\nKomut: {exe} {args}"
                 if nxt else s.summary()},
        undo=f"kayaai schedule rm {s.id} (ya da Zamanlama sekmesinde Sil)", requested_by=requested_by))


def request_delete(rt: "Runtime", sid: str, requested_by: str = "user") -> SubmitResult:
    s = load(rt, sid)
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="schedule.delete", params={"id": sid}, risk=Risk.R2, summary=f"Zamanlanmış görevi sil: {s.summary()}",
        reason="Görev ve Windows Görev Zamanlayıcı kaydı silinir (çalışma geçmişi kalır).",
        undo="Aynı görevi yeniden ekle", requested_by=requested_by))


def request_enable(rt: "Runtime", sid: str, enabled: bool, requested_by: str = "user") -> SubmitResult:
    s = load(rt, sid)
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="schedule.enable", params={"id": sid, "enabled": enabled}, risk=Risk.R1,
        summary=f"Zamanlanmış görevi {'aç' if enabled else 'kapat'}: {s.name}", requested_by=requested_by))


def request_run(rt: "Runtime", sid: str, requested_by: str = "user") -> SubmitResult:
    s = load(rt, sid)
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="schedule.run", params={"id": sid}, risk=Risk.R1, summary=f"Zamanlanmış görevi şimdi çalıştır: {s.name}",
        requested_by=requested_by))


def sync_report(rt: "Runtime") -> dict[str, Any]:
    """kayaAI kaydı ↔ Windows Görev Zamanlayıcı tutarlılığı (yalnız rapor)."""
    ids = windows.registered_ids()
    mine = {r["id"]: r for r in rt.store.list_schedules()}
    if ids is None:
        return {"supported": False, "missing": [], "orphans": []}
    return {"supported": True, "missing": sorted(i for i, r in mine.items() if r.get("enabled") and i not in ids),
            "orphans": sorted(ids - set(mine))}


# ---------------------------------------------------------------------------- yürütücüler (onaylanınca)


def _exec_create(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    s = Schedule.model_validate(params["schedule"])
    try:
        windows.register(s, state_dir(rt))
        s.registered, s.register_note = True, None
    except windows.SchedulerError as exc:
        s.registered, s.register_note = False, str(exc)
    save(rt, s)
    rt.store.emit("schedule.created", {"id": s.id, "name": s.name, "registered": s.registered})
    return {"id": s.id, "registered": s.registered, "note": s.register_note}


def _exec_delete(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    s = load(rt, params["id"])
    note = None
    if s.registered:
        try:
            windows.unregister(s.id)
        except windows.SchedulerError as exc:
            note = str(exc)  # zaten silinmişse de kayıttan kaldır
    rt.store.delete_schedule(s.id)
    (state_dir(rt) / f"{s.id}.xml").unlink(missing_ok=True)
    rt.store.emit("schedule.deleted", {"id": s.id, "name": s.name})
    return {"id": s.id, "deleted": True, "note": note}


def _exec_enable(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    s = load(rt, params["id"])
    s.enabled = bool(params["enabled"])
    if s.registered:
        windows.set_enabled(s.id, s.enabled)
    save(rt, s)
    return {"id": s.id, "enabled": s.enabled}


def _exec_run(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    if getattr(rt, "background_ok", False):
        threading.Thread(target=run_schedule, args=(rt, params["id"], "manual"), name="kayaai-schedule-run",
                         daemon=True).start()
        return {"id": params["id"], "started": True}
    run = run_schedule(rt, params["id"], "manual")
    return {"id": params["id"], "status": run.status, "message": run.message}


def executors(rt: "Runtime") -> dict[str, Any]:
    return {"schedule.create": lambda p: _exec_create(rt, p), "schedule.delete": lambda p: _exec_delete(rt, p),
            "schedule.enable": lambda p: _exec_enable(rt, p), "schedule.run": lambda p: _exec_run(rt, p)}
