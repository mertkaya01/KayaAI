"""Worker'lar arası iletişimin temel birimi: yapılandırılmış görev nesnesi."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"        # kullanıcı onay vermedi
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    WAITING_CLAUDE = "waiting_claude"  # Claude kutusunda bekliyor (terminal değil, yeniden başlatmada korunur)

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.REJECTED,
    TaskStatus.CANCELLED,
    TaskStatus.TIMED_OUT,
}


class Permission(str, Enum):
    """Worker'ların talep edebileceği izinler. auto_approve dışındakiler kullanıcı onayı ister."""

    LLM_INFERENCE = "llm.inference"
    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    NETWORK = "net"
    EXEC = "exec"
    SCREEN = "screen"
    AUDIO = "audio"
    DESKTOP = "desktop.control"


class ValidationResult(BaseModel):
    passed: bool
    validator: str
    errors: list[str] = Field(default_factory=list)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None
    worker: str
    objective: str
    input: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    timeout_s: float = 240
    permissions: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    validation: ValidationResult | None = None
    attempts: int = 0
    model: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_s(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
