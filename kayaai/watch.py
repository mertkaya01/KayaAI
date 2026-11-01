"""`kayaai watch` (Adım 18b): kayaAI'de olanları terminalde canlı, Türkçe ve renkli izle.

Kaynak, arayüzdeki "Son olaylar" ile aynı: SQLite olay tablosu (başka süreçlerin — API, zamanlanmış görev, Claude
Code/MCP — olayları da görünür). Yalnız okur; hiçbir şeyi değiştirmez. Ctrl+C ile çıkılır.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

AGENT = {"general": "Genel", "data": "Veri", "document": "Belge", "coder": "Kod", "vision": "Görsel",
         "planner": "Planlayıcı", "reviewer": "Denetçi", "conductor": "Şef", "browser": "Tarayıcı", "memory": "Hafıza"}

# renk adları → ANSI
_C = {"dim": "2", "green": "32", "red": "31", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "bold": "1"}

IMPORTANT = ("task.status", "approval.", "chat.message", "schedule.run", "dispute.", "automation.", "claude.mode",
             "model.pull", "agent.", "memory.indexed", "browser.step")


def agent_name(worker: str) -> str:
    base = worker.split(".")[0]
    name = AGENT.get(base, base)
    if worker.endswith(".check"):
        return f"{name} (kontrol)"
    if worker.endswith(".revise"):
        return f"{name} (düzeltme)"
    return name


def _short(text: Any, n: int = 80) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(ev: dict[str, Any]) -> tuple[str, str] | None:
    """Olay → (renk, Türkçe satır). None: bu olay satır üretmez (ör. 'sırada' görev durumu)."""
    t, d = ev["type"], ev.get("data") or {}
    if t == "task.status":
        who, st = agent_name(str(d.get("worker", "?"))), d.get("status")
        obj = _short(d.get("objective"), 70)
        step = "  " if d.get("parent_id") else ""  # şef işinin adımları girintili
        model = f" · {d['model']}" if d.get("model") else ""
        if st == "running":
            return "blue", f"{step}▶ {who} başladı: {obj}"
        if st == "succeeded":
            return "green", f"{step}✓ {who} bitti{model}"
        if st in ("failed", "timed_out"):
            return "red", f"{step}✗ {who} {'zaman aşımı' if st == 'timed_out' else 'başarısız'}: {obj}"
        if st == "cancelled":
            return "yellow", f"{step}■ {who} iptal edildi"
        if st == "awaiting_approval":
            return "yellow", f"{step}⏸ {who} onay bekliyor"
        if st == "waiting_claude":
            return "magenta", f"{step}⏸ {who}: Claude kutusunda"
        return None
    if t == "task.progress":
        tail, field = d.get("tail") or "", d.get("field")
        # yalnız okunur metin: plan numarası, karar ("s1", "approve") gibi kısa alanlar satır üretmez
        if not tail or (field not in (None, "answer") and len(tail) < 20):
            return None
        return "dim", f"    … {agent_name(str(d.get('worker', '?')))} yazıyor: {_short(tail, 90)}"
    if t == "approval.requested":
        return "yellow", (f"🔔 Onay bekliyor [{d.get('risk')}]: {_short(d.get('summary'), 70)}  →  "
                          f"kayaai approvals approve {d.get('approval_id')}")
    if t == "approval.decided":
        st = d.get("status")
        text = {"approved": "✓ Onaylandı", "rejected": "✗ Reddedildi", "expired": "⌛ Süresi doldu",
                "failed": "✗ Onaylandı ama çalıştırılamadı"}.get(str(st), f"Onay: {st}")
        return ("green" if st == "approved" else "red" if st in ("rejected", "failed") else "yellow"), f"{text} ({d.get('approval_id')})"
    if t == "chat.message":
        if d.get("role") == "assistant" and d.get("status") == "done":
            return "cyan", "💬 Asistan cevabı hazır"
        if d.get("role") == "assistant" and d.get("status") in ("failed", "cancelled"):
            return "red", "💬 Asistan cevap üretemedi"
        if d.get("role") == "user":
            return "cyan", "💬 Yeni mesaj"
        return None
    if t == "schedule.run":
        st = d.get("status")
        if st == "running":
            return "blue", f"⏰ Zamanlanmış görev başladı: {d.get('name')}"
        color = {"succeeded": "green", "failed": "red", "skipped": "yellow"}.get(str(st), "dim")
        text = {"succeeded": "bitti", "failed": "başarısız", "skipped": "atlandı"}.get(str(st), str(st))
        return color, f"⏰ Zamanlanmış görev {text}: {d.get('name')}" + (f" ({d['seconds']} sn)" if d.get("seconds") else "")
    if t == "dispute.opened":
        return "magenta", f"⚖ Anlaşmazlık: {agent_name(str(d.get('producer', '?')))} ↔ {agent_name(str(d.get('reviewer', '?')))}: {_short(d.get('issue'), 60)}"
    if t == "automation.paused":
        return "red", "⏸ Otomasyon duraklatıldı"
    if t == "automation.resumed":
        return "green", "▶ Otomasyon sürdürüldü"
    if t == "claude.mode":
        return "magenta", f"Claude modu {'açıldı' if d.get('enabled') else 'kapatıldı'}"
    if t == "model.pull":
        pct = f" %{d['percent']}" if d.get("percent") is not None else ""
        return ("red" if d.get("status") == "hata" else "dim"), f"⬇ Model indirme {d.get('name')}: {d.get('status')}{pct}"
    if t == "memory.indexed":
        return "dim", f"🧠 Belge dizini: {d.get('indexed', 0)} dosya yenilendi, {d.get('chunks', 0)} parça"
    if t == "browser.step":
        return "blue", f"🌐 Tarayıcı: {_short(d.get('description') or d.get('status'), 80)}"
    if t.startswith("agent."):
        return "dim", f"Ajan {t.split('.', 1)[1]}: {d.get('name', '')}"
    return "dim", f"{t} {_short(d, 90)}"


def wanted(ev_type: str, mode: str, live: bool) -> bool:
    if ev_type == "task.progress":
        return live
    if mode == "all":
        return True
    if mode == "approvals":
        return ev_type.startswith("approval.")
    if mode == "jobs":
        return ev_type in ("task.status", "schedule.run")
    return ev_type.startswith(IMPORTANT)


def local_time(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%H:%M:%S")
    except ValueError:
        return ts[11:19]


def color_on(stream: Any) -> bool:
    if os.environ.get("NO_COLOR") or not getattr(stream, "isatty", lambda: False)():
        return False
    if sys.platform == "win32":
        os.system("")  # Windows 10+ konsolunda ANSI renklerini açar
    return True


def format_line(ev: dict[str, Any], color: bool) -> str | None:
    got = describe(ev)
    if got is None:
        return None
    c, text = got
    stamp = local_time(ev.get("ts", ""))
    if not color:
        return f"{stamp}  {text}"
    return f"\033[2m{stamp}\033[0m  \033[{_C.get(c, '0')}m{text}\033[0m"


def run(store: Any, out: Callable[[str], None], *, mode: str = "important", live: bool = False, backlog: int = 15,
        color: bool = False, interval_s: float = 0.5, stop: Callable[[], bool] = lambda: False) -> int:
    """Olayları izler; dönüş: yazılan satır sayısı. `stop` True dönünce biter (testler için)."""
    last_progress: dict[str, float] = {}
    printed = 0
    start = store.last_event_id()
    history = [e for e in store.events_since(max(0, start - 400), 400) if wanted(e["type"], mode, False)][-backlog:] if backlog else []
    for ev in history:
        line = format_line(ev, color)
        if line:
            out(line)
            printed += 1
    last = start
    while not stop():
        batch = store.events_since(last, 200)
        for ev in batch:
            last = ev["id"]
            if not wanted(ev["type"], mode, live):
                continue
            if ev["type"] == "task.progress":  # aynı görev için en çok 2 sn'de bir satır
                key, now = str(ev.get("task_id")), time.monotonic()
                if now - last_progress.get(key, 0) < 2:
                    continue
                last_progress[key] = now
            line = format_line(ev, color)
            if line:
                out(line)
                printed += 1
        if not batch:
            time.sleep(interval_s)
    return printed
