"""Anlaşmazlık defteri (Adım 7, MASTER_PROMPT v2 §6).

Gözden geçirici bir sorun bildirir, üretici ajan gerekçesiyle itiraz ederse bu bir anlaşmazlıktır. Ajanlar birbirine
körü körüne güvenmez; şef anlaşmazlığı kendi çözmez, iki görüşü özetleyip yükseltir:
- Claude modu açıksa ve politika `claude_first` ise → iş Claude kutusuna (Opus karar verir),
- değilse → sahibe (CLI / API / Control Center). Kararı yalnızca sahip ya da (kutudaki işi tamamlayan) Claude verir;
  MCP üzerinden karar verme aracı yoktur.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .store import TaskStore
from .task import utcnow

Resolution = Literal["producer", "reviewer", "claude", "superseded"]
EscalatedTo = Literal["owner", "claude"]


class DisputeError(ValueError):
    pass


class DisputeRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: datetime = Field(default_factory=utcnow)
    status: Literal["open", "resolved"] = "open"
    job_id: str | None = None
    step_id: str = ""
    request: str = ""
    producer: str
    reviewer: str
    issue_id: str
    severity: str = "major"
    issue: str
    evidence: str = ""
    producer_position: str
    escalated_to: EscalatedTo = "owner"
    resolution: Resolution | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str = ""


class DisputeBook:
    def __init__(self, store: TaskStore):
        self.store = store

    def _save(self, d: DisputeRecord) -> None:
        self.store.save_dispute(d.id, d.created_at.isoformat(), d.status, d.job_id, d.model_dump(mode="json"))

    def open(self, d: DisputeRecord) -> DisputeRecord:
        self._save(d)
        self.store.emit("dispute.opened", {
            "id": d.id, "producer": d.producer, "reviewer": d.reviewer, "issue": d.issue[:200],
            "escalated_to": d.escalated_to,
        }, task_id=d.job_id)
        return d

    def get(self, dispute_id: str) -> DisputeRecord | None:
        raw = self.store.get_dispute(dispute_id)
        return DisputeRecord.model_validate(raw) if raw else None

    def list(self, status: str | None = None, job_id: str | None = None, limit: int = 100) -> list[DisputeRecord]:
        return [DisputeRecord.model_validate(r) for r in self.store.list_disputes(status, job_id, limit)]

    def resolve(self, dispute_id: str, resolution: Resolution, decided_by: str, note: str = "") -> DisputeRecord:
        d = self.get(dispute_id)
        if d is None:
            raise DisputeError(f"Anlaşmazlık bulunamadı: {dispute_id}")
        if d.status != "open":
            raise DisputeError(f"Anlaşmazlık zaten kapandı ({d.resolution})")
        d.status, d.resolution, d.decided_by, d.decided_at = "resolved", resolution, decided_by, utcnow()
        d.note = (note or "").strip()[:1000]
        self._save(d)
        self.store.emit("dispute.resolved", {
            "id": d.id, "resolution": resolution, "decided_by": decided_by, "producer": d.producer,
            "reviewer": d.reviewer,
        }, task_id=d.job_id)
        return d

    def close_for_job(self, job_id: str, resolution: Resolution, decided_by: str, note: str = "") -> int:
        """Bir işin açık anlaşmazlıklarını toplu kapatır (Claude tamamladı / iş yeniden yapıldı)."""
        n = 0
        for d in self.list(status="open", job_id=job_id, limit=500):
            self.resolve(d.id, resolution, decided_by, note)
            n += 1
        return n
