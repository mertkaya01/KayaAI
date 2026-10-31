"""İzin motoru v2 ve kalıcı onay kuyruğu (Adım 5 — MASTER_PROMPT v2 §8).

Risk sınıfları:
  R0 güvenli   — otomatik (ör. okuma, listeleme)
  R1 düşük     — otomatik, kayda geçer (ör. yeni dosya yazma)
  R2 riskli    — önizlemeyle SAHİP onayı (ör. var olan dosyanın üzerine yazma)
  R3 kritik    — her seferinde SAHİP onayı; toplu onay yok (ör. dışarı gönderme — ileride)

Akış: araç bir `ToolAction` üretir → `PermissionEngine.submit(action)`:
  - R0/R1: araç hemen çalışır, sonuç döner, `tool.used` olayı yazılır.
  - R2/R3: onay talebi SQLite'a yazılır (yeniden başlatmada korunur), `approval.requested` olayı yazılır,
    çağırana `awaiting_approval` + talep numarası döner. Sahip onaylayınca kayıtlı işlem ÇALIŞTIRILIR ve sonucu
    talebe yazılır; reddederse hiçbir şey yapılmaz.
Onayı yalnızca sahip verir (CLI, anahtarlı API). MCP'de onay aracı YOKTUR: ajan kendi isteğini onaylayamaz.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .store import TaskStore
from .task import utcnow

log = logging.getLogger(__name__)


class Risk(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"

    @property
    def needs_approval(self) -> bool:
        return self in (Risk.R2, Risk.R3)


RISK_LABELS = {
    Risk.R0: "güvenli (otomatik)",
    Risk.R1: "düşük (otomatik, kayda geçer)",
    Risk.R2: "riskli (sahip onayı gerekir)",
    Risk.R3: "kritik (her seferinde sahip onayı; toplu onay yok)",
}

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "failed"]


class ToolAction(BaseModel):
    """Bir aracın yapmak istediği somut işlem (önizlenebilir, saklanabilir, sonradan çalıştırılabilir)."""

    tool: str
    params: dict[str, Any]
    risk: Risk
    summary: str                      # tek satır: "C:\\...\\rapor.md dosyasının üzerine yaz"
    reason: str = ""                  # neden riskli
    preview: dict[str, Any] = Field(default_factory=dict)
    undo: str = ""                    # nasıl geri alınır
    requested_by: str = "user"        # cli | api | mcp | agent:<ad> | task:<id>


class Approval(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: datetime = Field(default_factory=utcnow)
    status: ApprovalStatus = "pending"
    action: ToolAction
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class SubmitResult(BaseModel):
    status: Literal["done", "awaiting_approval", "failed"]
    risk: Risk
    result: dict[str, Any] | None = None
    approval_id: str | None = None
    error: str | None = None
    message: str = ""


class ApprovalError(ValueError):
    pass


Executor = Callable[[dict[str, Any]], dict[str, Any]]


class PermissionEngine:
    def __init__(self, store: TaskStore, executors: dict[str, Executor], expire_hours: int = 24):
        self.store = store
        self.executors = executors
        self.expire_after = timedelta(hours=expire_hours)

    # ------------------------------------------------------------------ talep

    def submit(self, action: ToolAction) -> SubmitResult:
        if action.tool not in self.executors:
            raise ApprovalError(f"Bilinmeyen araç: {action.tool}")
        if not action.risk.needs_approval:
            return self._run(action)
        approval = Approval(action=action)
        self._save(approval)
        self.store.emit("approval.requested", {
            "approval_id": approval.id, "risk": action.risk.value, "tool": action.tool,
            "summary": action.summary, "requested_by": action.requested_by,
        })
        log.info("onay talebi %s [%s] %s", approval.id, action.risk.value, action.summary)
        return SubmitResult(status="awaiting_approval", risk=action.risk, approval_id=approval.id,
                            message=f"Sahip onayı bekleniyor ({RISK_LABELS[action.risk]}): kayaai approvals show {approval.id}")

    def _run(self, action: ToolAction) -> SubmitResult:
        try:
            result = self.executors[action.tool](action.params)
        except Exception as exc:  # noqa: BLE001 - araç hatası çağırana dürüstçe döner
            self.store.emit("tool.failed", {"tool": action.tool, "risk": action.risk.value, "error": str(exc)[:300]})
            return SubmitResult(status="failed", risk=action.risk, error=f"{type(exc).__name__}: {exc}")
        self.store.emit("tool.used", {"tool": action.tool, "risk": action.risk.value, "summary": action.summary,
                                      "requested_by": action.requested_by})
        return SubmitResult(status="done", risk=action.risk, result=result)

    # ------------------------------------------------------------------ kuyruk

    def _save(self, a: Approval) -> None:
        self.store.save_approval(a.id, a.created_at.isoformat(), a.status, a.action.risk.value, a.action.tool,
                                 a.model_dump(mode="json"))

    def get(self, approval_id: str) -> Approval:
        data = self.store.get_approval(approval_id)
        if data is None:
            raise ApprovalError(f"Onay talebi bulunamadı: {approval_id}")
        return self._expire_if_old(Approval.model_validate(data))

    def list_approvals(self, status: ApprovalStatus | None = None, limit: int = 100) -> list[Approval]:
        items = [self._expire_if_old(Approval.model_validate(d)) for d in self.store.list_approvals(None, limit * 3)]
        if status:
            items = [a for a in items if a.status == status]
        return items[:limit]

    def _expire_if_old(self, a: Approval) -> Approval:
        created = a.created_at if a.created_at.tzinfo else a.created_at.replace(tzinfo=timezone.utc)
        if a.status == "pending" and utcnow() - created > self.expire_after:
            a.status, a.decided_at, a.decided_by = "expired", utcnow(), "system"
            a.decision_note = f"{int(self.expire_after.total_seconds() // 3600)} saat içinde karar verilmedi"
            self._save(a)
            self.store.emit("approval.decided", {"approval_id": a.id, "status": "expired"})
        return a

    # ------------------------------------------------------------------ karar (yalnızca sahip)

    def approve(self, approval_id: str, decided_by: str, note: str = "") -> Approval:
        a = self._pending(approval_id)
        a.decided_at, a.decided_by, a.decision_note = utcnow(), decided_by, note or None
        run = self._run(a.action)
        if run.status == "done":
            a.status, a.result = "approved", run.result
        else:
            a.status, a.error = "failed", run.error
        self._save(a)
        self.store.emit("approval.decided", {"approval_id": a.id, "status": a.status, "decided_by": decided_by})
        return a

    def reject(self, approval_id: str, decided_by: str, note: str = "") -> Approval:
        a = self._pending(approval_id)
        a.status, a.decided_at, a.decided_by, a.decision_note = "rejected", utcnow(), decided_by, note or None
        self._save(a)
        self.store.emit("approval.decided", {"approval_id": a.id, "status": "rejected", "decided_by": decided_by})
        return a

    def _pending(self, approval_id: str) -> Approval:
        a = self.get(approval_id)
        if a.status != "pending":
            raise ApprovalError(f"Talep artık beklemede değil (durum: {a.status})")
        return a
