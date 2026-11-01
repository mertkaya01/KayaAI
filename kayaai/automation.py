"""Otomasyonu duraklat anahtarı (Adım 14a; loop-engineering "kill switch" fikri).

Duraklatılınca: Windows Görev Zamanlayıcı'nın başlattığı zamanlanmış görevler "duraklatıldı" diye atlanır (görevler
Windows'ta kalır, kayıt bozulmaz), yeni tarayıcı işi başlamaz, süren tarayıcı işi güvenle durdurulur. Sahibin elle
yaptığı işler (sohbet, "şimdi çalıştır") etkilenmez. Durum `kayaai.db` içinde (süreçler arası: Windows'un başlattığı
`pythonw` süreci de görür).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runtime import Runtime

META_KEY = "automation_paused"


def state(rt: "Runtime") -> dict[str, Any]:
    raw = rt.store.get_meta(META_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return {"paused": bool(data.get("paused")), "at": data.get("at"), "by": data.get("by"), "reason": data.get("reason")}


def is_paused(rt: "Runtime") -> bool:
    return state(rt)["paused"]


def set_paused(rt: "Runtime", paused: bool, by: str = "user", reason: str = "") -> dict[str, Any]:
    data = {"paused": paused, "at": datetime.now().isoformat(timespec="seconds"), "by": by, "reason": reason[:200]}
    rt.store.set_meta(META_KEY, json.dumps(data, ensure_ascii=False))
    stopped = []
    if paused:  # süren tarayıcı işlerini güvenle durdur
        from .browser.agent import _JOBS

        for job in list(_JOBS.values()):
            if job.state.status in ("running", "waiting"):
                job.stop_event.set()
                stopped.append(job.state.id)
    rt.store.emit("automation.paused" if paused else "automation.resumed", {"by": by, "reason": reason[:200],
                                                                            "stopped_browser_jobs": stopped})
    return {**state(rt), "stopped_browser_jobs": stopped}
