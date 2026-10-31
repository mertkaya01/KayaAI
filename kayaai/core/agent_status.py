"""Ajan durumu (MASTER_PROMPT v2 D10): görev geçmişinden türetilir — ayrı bir durum deposu yok.

idle | running | waiting | completed | failed + şu anki/son görev + sonuç var mı.
Özel düşünce (reasoning) gösterilmez; yalnızca gözlemlenebilir görev bilgisi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel

from .store import TaskStore
from .task import TaskStatus, utcnow

AgentState = Literal["idle", "running", "waiting", "completed", "failed"]
RECENT = timedelta(minutes=10)  # bu süreden eski bitmiş görev ajanı "idle" yapar


class AgentStatus(BaseModel):
    name: str
    state: AgentState
    current_task_id: str | None = None
    current_task: str | None = None
    result_available: bool = False
    last_finished_at: str | None = None


def agent_statuses(store: TaskStore, names: list[str], scan: int = 500) -> list[AgentStatus]:
    tasks = store.list_tasks(limit=scan)  # en yeni önce
    now = utcnow()
    out: list[AgentStatus] = []
    for name in names:
        mine = [t for t in tasks if t.worker == name]
        active = next((t for t in mine if t.status == TaskStatus.RUNNING), None)
        waiting = next((t for t in mine if t.status in (TaskStatus.AWAITING_APPROVAL, TaskStatus.PENDING,
                                                        TaskStatus.WAITING_CLAUDE)), None)
        last = mine[0] if mine else None
        st: dict[str, Any] = {"name": name, "state": "idle"}
        if active:
            st.update(state="running", current_task_id=active.id, current_task=active.objective[:200])
        elif waiting:
            st.update(state="waiting", current_task_id=waiting.id, current_task=waiting.objective[:200])
        elif last and last.finished_at and now - last.finished_at <= RECENT:
            ok = last.status == TaskStatus.SUCCEEDED
            st.update(state="completed" if ok else "failed", current_task_id=last.id,
                      current_task=last.objective[:200], result_available=ok and bool(last.result))
        if last and last.finished_at:
            st["last_finished_at"] = last.finished_at.isoformat()
        out.append(AgentStatus(**st))
    return out
