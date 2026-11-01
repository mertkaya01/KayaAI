"""Bugün ekranı (Adım 16b): açılışta tek istekle özet — onaylar, işler, zamanlanmış görevler, son sohbetler, sistem,
isteğe bağlı kur/tatil. Hepsi yerel kayıtlardan; dış veri yalnız sahip açtıysa (önbellekten, günde/yılda bir istek)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runtime import Runtime

DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def greeting(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 12:
        return "Günaydın"
    if 12 <= h < 18:
        return "İyi günler"
    if 18 <= h < 23:
        return "İyi akşamlar"
    return "İyi geceler"


def long_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}, {DAYS[d.weekday()]}"


def _holiday(rt: "Runtime", today: date) -> dict[str, Any] | None:
    from .integrations import IntegrationError, holidays, is_enabled

    if not is_enabled(rt, "holidays"):
        return None
    try:
        days = holidays(rt, today.year)
        if today.month == 12:
            try:
                days = days + holidays(rt, today.year + 1)
            except IntegrationError:
                pass
    except IntegrationError as exc:
        return {"error": str(exc)}
    upcoming = sorted((h for h in days if h["date"] >= today.isoformat()), key=lambda h: h["date"])
    nxt = upcoming[0] if upcoming else None
    return {"today": nxt["name"] if nxt and nxt["date"] == today.isoformat() else None,
            "next": nxt, "days_left": (date.fromisoformat(nxt["date"]) - today).days if nxt else None}


def _rates(rt: "Runtime") -> dict[str, Any] | None:
    from .integrations import IntegrationError, is_enabled, rates

    if not is_enabled(rt, "exchange_rates"):
        return None
    try:
        r = rates(rt)
        return {"date": r["date"], "per_try": {k: v for k, v in r["per_try"].items() if k in ("USD", "EUR", "GBP")}}
    except IntegrationError as exc:
        return {"error": str(exc)}


def _schedules(rt: "Runtime", now: datetime) -> list[dict[str, Any]]:
    from .schedule import Schedule

    out = []
    for raw in rt.store.list_schedules():
        s = Schedule.model_validate(raw)
        nxt = s.next_run(now)
        out.append({"id": s.id, "name": s.name, "enabled": s.enabled, "cadence": s.cadence.describe(),
                    "next_run": nxt.isoformat() if nxt else None,
                    "last_run": s.last_run.isoformat() if s.last_run else None, "last_status": s.last_status,
                    "last_message": (s.last_message or "")[:200]})
    return sorted(out, key=lambda x: x["next_run"] or "9999")


def summary(rt: "Runtime", now: datetime | None = None, *, external: bool = True) -> dict[str, Any]:
    from .automation import state as automation_state
    from .conductor.graph import list_jobs
    from .core.task import TaskStatus
    from .notify import get_prefs

    now = now or datetime.now()
    pending = rt.permissions.list_approvals("pending", limit=50) if rt.permissions else []
    jobs = list_jobs(rt.store, 8)
    chats = rt.store.list_conversations(limit=6)
    loaded: list[dict[str, Any]] = []
    ollama_ok = True
    try:
        loaded = [{"name": m.get("name"), "vram_gb": round((m.get("size_vram") or 0) / 1024**3, 1)}
                  for m in rt.llm.running_models()]
    except Exception:  # noqa: BLE001 - Ollama kapalıysa da ekran açılsın
        ollama_ok = False
    claude = rt.claude.status().model_dump(mode="json") if rt.claude else None
    return {
        "greeting": greeting(now),
        "date": long_date(now.date()),
        "now": now.isoformat(timespec="seconds"),
        "approvals": {"count": len(pending),
                      "items": [{"id": a.id, "risk": a.action.risk.value, "summary": a.action.summary,
                                 "requested_by": a.action.requested_by, "created_at": a.created_at.isoformat()}
                                for a in pending[:5]]},
        "jobs": jobs,
        "running": sum(1 for j in jobs if j["status"] in (TaskStatus.RUNNING.value, TaskStatus.PENDING.value)),
        "schedules": _schedules(rt, now),
        "chats": [{"id": c["id"], "title": c.get("title", ""), "updated_at": c.get("updated_at")} for c in chats],
        "system": {"ollama": ollama_ok, "loaded": loaded, "claude": claude, "automation": automation_state(rt)},
        "holiday": _holiday(rt, now.date()) if external else None,
        "rates": _rates(rt) if external else None,
        "notifications": get_prefs(rt).model_dump(),
    }
