"""Claude kutusu (Adım 3d): Claude gerektiren işler burada bekler, Claude Code MCP ile alır.

kayaAI, Claude'a iş GÖNDEREMEZ (ücretli API yok); Claude Code oturumu kutuyu okur, işi yapar ve
sonucu `complete` ile geri yazar. Claude kapatılırsa ya da kullanıcı isterse iş yerel ekibe geri verilir.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..core.task import TaskStatus, ValidationResult, utcnow
from ..runtime import Runtime
from .conductor import Conductor, ConductorResult

CLAUDE_MODEL_LABEL = "claude (Claude Code)"
MAX_ANSWER_CHARS = 20_000


class InboxItem(BaseModel):
    job_id: str
    request: str
    reason: str = ""
    suggested_steps: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    # Adım 7: ajanlar anlaşamadıysa yerel taslak cevap ve iki görüş (karar Claude'da)
    local_draft: str = ""
    disputes: list[dict[str, str]] = Field(default_factory=list)


class InboxView(BaseModel):
    claude_mode_enabled: bool
    items: list[InboxItem]
    note: str


class ClaudeInbox:
    def __init__(self, runtime: Runtime):
        self.rt = runtime

    def items(self) -> list[InboxItem]:
        out = []
        for job in self.rt.store.list_tasks(limit=200, status=TaskStatus.WAITING_CLAUDE):
            res = job.result or {}
            disputes = [
                {"id": d.id, "producer": d.producer, "reviewer": d.reviewer, "issue": d.issue,
                 "evidence": d.evidence, "producer_position": d.producer_position}
                for d in (self.rt.disputes.list(status="open", job_id=job.id) if self.rt.disputes else [])
            ]
            out.append(InboxItem(
                local_draft=str(res.get("answer", ""))[:MAX_ANSWER_CHARS] if disputes else "",
                disputes=disputes,
                job_id=job.id,
                request=job.objective,
                reason=(res.get("routing") or {}).get("reason", ""),
                suggested_steps=[{"agent": s.get("agent"), "objective": s.get("objective")} for s in res.get("steps", [])],
                created_at=job.created_at,
            ))
        return sorted(out, key=lambda i: i.created_at)

    def view(self) -> InboxView:
        enabled = bool(self.rt.claude and self.rt.claude.is_enabled())
        items = self.items()
        if not enabled:
            note = "Claude modu KAPALI. Bekleyen işler yerelde yapılmalı (kayaai inbox run <id>)."
        elif not items:
            note = "Claude kutusu boş."
        else:
            note = (f"{len(items)} iş bekliyor. Her biri için işi yap ve kayaai_claude_complete ile sonucu yaz; "
                    "yerel ekibe bırakmak için kayaai_claude_release kullan.")
        return InboxView(claude_mode_enabled=enabled, items=items, note=note)

    def complete(self, job_id: str, answer: str, summary: str = "") -> ConductorResult:
        job = self.rt.store.get(job_id)
        if job is None or job.worker != "conductor":
            raise KeyError(f"Şef işi bulunamadı: {job_id}")
        if job.status != TaskStatus.WAITING_CLAUDE:
            raise ValueError(f"İş Claude kutusunda değil (durum: {job.status.value})")
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("Cevap boş olamaz")
        if len(answer) > MAX_ANSWER_CHARS:
            raise ValueError(f"Cevap en fazla {MAX_ANSWER_CHARS} karakter olabilir")
        result = ConductorResult.model_validate(job.result or {"job_id": job.id, "status": job.status.value})
        result.status = TaskStatus.SUCCEEDED.value
        result.answer = answer
        result.error = None
        result.warnings = [w for w in result.warnings if "Claude kutusuna" not in w]
        if summary.strip():
            result.warnings.append(f"Claude özeti: {summary.strip()[:500]}")
        job.status = TaskStatus.SUCCEEDED
        job.model = CLAUDE_MODEL_LABEL
        job.result = result.model_dump(mode="json") | {"completed_by": CLAUDE_MODEL_LABEL}
        job.error = None
        job.validation = ValidationResult(passed=True, validator="claude.complete")
        job.finished_at = utcnow()
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, "claude.completed", {"chars": len(answer)})
        if self.rt.disputes:
            self.rt.disputes.close_for_job(job.id, "claude", "claude", summary.strip()[:500] or "Claude işi tamamladı")
        return result

    def release(self, job_id: str) -> ConductorResult:
        return Conductor(self.rt).resume_local(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.rt.store.get(job_id)
        if job is None or job.status != TaskStatus.WAITING_CLAUDE:
            return False
        job.status, job.error, job.finished_at = TaskStatus.CANCELLED, "kullanıcı iptal etti", utcnow()
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, "cancelled", {"from": "claude_inbox"})
        return True
