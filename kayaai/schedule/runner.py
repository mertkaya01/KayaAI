"""Zamanlanmış görevi çalıştırma (Adım 13): `kayaai schedule run <id>` — Windows Görev Zamanlayıcı bunu çağırır.

Claude Code açık olmasa da çalışır (kabul ölçütü): tamamen yerel ekip; Claude modu açık olsa bile şef yerelde yapar.
Sonuç Asistan'daki "Zamanlanmış görevler" sohbetine mesaj olarak bırakılır; raporlar izinli klasöre (yeni dosya R1).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .model import KIND_LABEL, Run, Schedule

if TYPE_CHECKING:
    from ..runtime import Runtime

CONV_META = "schedule_conv"
LOCK_STALE_S = 3 * 3600
OLLAMA_WAIT_S = 120


class ScheduleError(ValueError):
    pass


def load(rt: "Runtime", sid: str) -> Schedule:
    raw = rt.store.get_schedule(sid)
    if raw is None:
        raise ScheduleError(f"Zamanlanmış görev bulunamadı: {sid}")
    return Schedule.model_validate(raw)


def save(rt: "Runtime", s: Schedule) -> None:
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))


def state_dir(rt: "Runtime"):  # -> Path
    return rt.settings.data_dir / "schedule"


# ---------------------------------------------------------------------------- işleyiciler


def _summarize(rt: "Runtime", name: str, text: str) -> str:
    task = rt.orchestrator.ask(f"Şu belgeyi 2-3 cümlede Türkçe özetle: {name}", worker="document",
                               input={"document": {"name": name, "content": text[:3500]}})
    if task.status.value != "succeeded":
        return f"(özetlenemedi: {task.error or task.status.value})"
    return str((task.result or {}).get("answer", "")).strip()


def docs_digest(rt: "Runtime", s: Schedule) -> tuple[str, list[str]]:
    from ..business.readers import BINARY_SUFFIXES, ReadError, extract_text
    from ..memory.documents import IndexReport

    since = s.last_run or (datetime.now() - timedelta(days=1))
    folder = str(s.params.get("folder") or "").strip()
    base = None
    if folder:
        assert rt.files is not None
        base, _ = rt.files.resolve(folder)  # izinli klasör dışı → PathNotAllowed
    files = []
    for path, _root in rt.memory.docs._walk(IndexReport(roots=[])):  # gizli dosya ve klasör kuralları burada
        if base is not None and not str(path).startswith(str(base)):
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime > since:
            files.append((mtime, path))
    files.sort(reverse=True)
    files = files[: int(s.params.get("max_files", 10))]
    if not files:
        return f"**{s.name}** — {since:%d.%m.%Y %H:%M}'den beri değişen belge yok.", []
    lines = [f"**{s.name}** — {since:%d.%m.%Y %H:%M}'den beri değişen {len(files)} belge:", ""]
    for mtime, path in files:
        try:
            raw = path.read_bytes()
            text = extract_text(raw, path.name)[0] if path.suffix.lower() in BINARY_SUFFIXES else raw.decode("utf-8", "replace")
        except (OSError, ReadError) as exc:
            lines.append(f"- **{path.name}** ({mtime:%d.%m %H:%M}) — okunamadı: {exc}")
            continue
        lines.append(f"- **{path.name}** ({mtime:%d.%m %H:%M}) — {_summarize(rt, path.name, text)}")
    return "\n".join(lines), []


def sales_report(rt: "Runtime", s: Schedule) -> tuple[str, list[str]]:
    from ..business import from_result, run_mode
    from ..business import save as save_report

    assert rt.files is not None
    path, _ = rt.files.resolve(str(s.params["path"]))
    if not path.is_file():
        raise ScheduleError(f"Dosya yok: {path}")
    question = str(s.params.get("question") or "Bu dönemin satışlarını özetle: toplamlar, öne çıkanlar, değişim.")
    res = run_mode(rt, "analyze", path.read_bytes(), path.name, question)
    files = []
    report = from_result(res.model_dump(mode="json"), title=f"{s.name} — {datetime.now():%d.%m.%Y}")
    for fmt in s.params.get("formats", ["xlsx", "pdf"]):
        r = save_report(rt, report, fmt, requested_by=f"schedule:{s.id}")
        if r.status == "done" and r.result:
            files.append(str(r.result.get("path")))
    md = res.markdown()
    if files:
        md += "\n\n**Rapor dosyaları:** " + ", ".join(f"`{f}`" for f in files)
    return md, files


def reindex(rt: "Runtime", s: Schedule) -> tuple[str, list[str]]:
    r = rt.memory.docs.index()
    md = (f"**{s.name}** — belge dizini yenilendi: {r.scanned} dosya tarandı, {r.indexed} güncellendi, "
          f"{r.unchanged} değişmedi, {r.removed} kaldırıldı ({r.duration_s:.1f} sn).")
    if not r.embed_available:
        md += " Anlam araması modeli (bge-m3) yoktu; kelime araması güncel."
    if r.errors:
        md += "\n\nUyarılar: " + "; ".join(r.errors[:3])
    return md, []


def free(rt: "Runtime", s: Schedule) -> tuple[str, list[str]]:
    from ..conductor import Conductor

    res = Conductor(rt).run(str(s.params["request"]), force="local")  # zamanlanmış görev her zaman yerelde
    if res.status != "succeeded":
        raise ScheduleError(f"Şef işi tamamlanamadı: {res.error or res.status}")
    return res.answer, []


HANDLERS = {"docs_digest": docs_digest, "sales_report": sales_report, "reindex": reindex, "free": free}


# ---------------------------------------------------------------------------- çalıştırıcı


def _conversation(rt: "Runtime") -> str:
    from ..assistant.chat import ChatBook, ChatError

    book = ChatBook(rt)
    cid = rt.store.get_meta(CONV_META)
    if cid:
        try:
            book.get(cid)
            return cid
        except ChatError:
            pass
    c = book.create("Zamanlanmış görevler")
    rt.store.set_meta(CONV_META, c.id)
    return c.id


def _post(rt: "Runtime", s: Schedule, run: Run, content: str) -> None:
    from ..assistant.chat import ChatBook, ChatMessage

    book = ChatBook(rt)
    cid = _conversation(rt)
    msg = ChatMessage(conv_id=cid, role="assistant", agent="zamanlayıcı", content=content,
                      status="done" if run.status == "succeeded" else "failed",
                      meta={"schedule": {"id": s.id, "name": s.name, "kind": s.kind, "run": run.id, "files": run.files},
                            "agents": ["zamanlayıcı"]})
    book._save_msg(msg)
    book._touch(book.get(cid))
    rt.store.emit("chat.message", {"conv_id": cid, "message_id": msg.id, "role": "assistant", "status": msg.status})
    run.conv_id, run.message_id = cid, msg.id


def _lock(rt: "Runtime", sid: str):  # -> Path | None
    d = state_dir(rt)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.lock"
    if p.exists() and time.time() - p.stat().st_mtime > LOCK_STALE_S:
        p.unlink(missing_ok=True)  # çökmüş eski çalışma
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return p


def _wait_ollama(rt: "Runtime", wait_s: float) -> bool:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            rt.llm.version()
            return True
        except Exception:  # noqa: BLE001
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(10, max(0.1, deadline - time.monotonic())))


def run_schedule(rt: "Runtime", sid: str, trigger: str = "manual", ollama_wait_s: float = OLLAMA_WAIT_S) -> Run:
    s = load(rt, sid)
    run = Run(schedule_id=s.id, trigger=trigger)  # type: ignore[arg-type]
    from ..automation import is_paused

    if trigger != "manual" and is_paused(rt):  # Adım 14a: otomasyon duraklatıldı (görev Windows'ta kalır)
        run.status, run.message, run.finished_at = "skipped", "otomasyon duraklatıldı", datetime.now()
        rt.store.save_schedule_run(run.id, s.id, run.started_at.isoformat(), run.model_dump(mode="json"))
        rt.store.emit("schedule.run", {"id": s.id, "name": s.name, "status": "skipped", "trigger": trigger})
        return run
    if not s.enabled and trigger != "manual":
        run.status, run.message, run.finished_at = "skipped", "görev kapalı", datetime.now()
        rt.store.save_schedule_run(run.id, s.id, run.started_at.isoformat(), run.model_dump(mode="json"))
        return run
    lock = _lock(rt, s.id)
    if lock is None:
        run.status, run.message, run.finished_at = "skipped", "önceki çalışma sürüyor", datetime.now()
        rt.store.save_schedule_run(run.id, s.id, run.started_at.isoformat(), run.model_dump(mode="json"))
        return run
    rt.store.save_schedule_run(run.id, s.id, run.started_at.isoformat(), run.model_dump(mode="json"))
    rt.store.emit("schedule.run", {"id": s.id, "name": s.name, "status": "running", "trigger": trigger})
    t0 = time.monotonic()
    try:
        if not _wait_ollama(rt, ollama_wait_s):
            raise ScheduleError("Ollama'ya ulaşılamadı (çalışıyor mu?). Görev sonraki zamanında yeniden denenecek.")
        content, run.files = HANDLERS[s.kind](rt, s)
        run.status = "succeeded"
        run.message = content.splitlines()[0][:200] if content else "tamam"
    except Exception as exc:  # noqa: BLE001 - kayıt her durumda yazılmalı
        run.status, run.message = "failed", f"{type(exc).__name__}: {exc}"[:400]
        content = f"**{s.name}** ({KIND_LABEL[s.kind]}) çalışamadı: {exc}"
    finally:
        lock.unlink(missing_ok=True)
    run.finished_at, run.seconds = datetime.now(), round(time.monotonic() - t0, 1)
    try:
        _post(rt, s, run, content + f"\n\n*Zamanlanmış görev · {s.cadence.describe()} · {run.seconds} sn*")
    except Exception as exc:  # noqa: BLE001 - sohbete yazılamasa da çalışma kaydı kalsın
        run.message += f" (sohbete yazılamadı: {exc})"
    rt.store.save_schedule_run(run.id, s.id, run.started_at.isoformat(), run.model_dump(mode="json"))
    s = load(rt, sid)  # çalışırken değişmiş olabilir
    s.last_run, s.last_status, s.last_message = run.started_at, run.status, run.message
    if s.cadence.freq == "once" and run.status == "succeeded":
        s.enabled = False
    save(rt, s)
    rt.store.emit("schedule.run", {"id": s.id, "name": s.name, "status": run.status, "seconds": run.seconds,
                                   "trigger": trigger})
    return run


def due(s: Schedule, now: datetime) -> bool:
    """Son çalışmadan (yoksa oluşturulmadan) sonraki ilk zaman geldi mi? (Windows dışı `run-due` için.)"""
    if not s.enabled:
        return False
    nxt = s.cadence.next_after(s.last_run or s.created_at)
    return nxt is not None and nxt <= now


def run_due(rt: "Runtime", now: datetime | None = None) -> list[Run]:
    now = now or datetime.now()
    return [run_schedule(rt, s.id, "run-due") for s in (Schedule.model_validate(r) for r in rt.store.list_schedules())
            if due(s, now)]


def history(rt: "Runtime", sid: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    return rt.store.list_schedule_runs(sid, limit)
