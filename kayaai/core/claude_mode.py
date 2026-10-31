"""Claude modu: aç/kapa durumu ve "son temas" bilgisi (MASTER_PROMPT v2 D2).

- kayaAI, Claude'u kendisi çağıramaz (ücretli API yok). Claude yalnızca Claude Code üzerinden,
  kayaAI'nin MCP sunucusunu kullanarak devreye girer.
- Bu yüzden "Claude bağlı mı?" kesin bilinemez. Dürüst gösterge: Claude Code'un MCP sunucusunu
  EN SON ne zaman kullandığı ("son temas").
- Aç/kapa durumu SQLite meta tablosunda saklanır (yeniden başlatmada korunur, arayüzden değiştirilebilir).
  Hiç değiştirilmediyse config/settings.yaml'daki varsayılan geçerlidir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from ..config import ClaudeSettings
from .store import TaskStore
from .task import TaskStatus, utcnow

log = logging.getLogger(__name__)

KEY_ENABLED = "claude.enabled"
KEY_LAST_CONTACT = "claude.last_contact"
KEY_CHANGED_AT = "claude.changed_at"

State = Literal["off", "on_no_contact", "on_recent_contact", "on_stale_contact"]


class ClaudeStatus(BaseModel):
    enabled: bool
    state: State
    last_contact: datetime | None = None
    minutes_since_contact: float | None = None
    waiting_tasks: int = 0
    label: str


class ClaudeMode:
    def __init__(self, store: TaskStore, settings: ClaudeSettings | None = None):
        self.store = store
        self.settings = settings or ClaudeSettings()

    # ------------------------------------------------------------------ aç/kapa

    def is_enabled(self) -> bool:
        value = self.store.get_meta(KEY_ENABLED)
        if value is None:
            return self.settings.enabled
        return value == "1"

    def enable(self) -> ClaudeStatus:
        return self._set(True)

    def disable(self) -> ClaudeStatus:
        return self._set(False)

    def _set(self, enabled: bool) -> ClaudeStatus:
        previous = self.is_enabled()
        self.store.set_meta(KEY_ENABLED, "1" if enabled else "0")
        self.store.set_meta(KEY_CHANGED_AT, utcnow().isoformat())
        if previous != enabled:
            log.info("Claude modu %s", "AÇILDI" if enabled else "KAPATILDI")
        return self.status()

    # ------------------------------------------------------------------ temas

    def record_contact(self) -> None:
        """Claude Code (MCP istemcisi) kayaAI'yi kullandığında çağrılır."""
        self.store.set_meta(KEY_LAST_CONTACT, utcnow().isoformat())

    def last_contact(self) -> datetime | None:
        value = self.store.get_meta(KEY_LAST_CONTACT)
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    # ------------------------------------------------------------------ durum

    def status(self, now: datetime | None = None) -> ClaudeStatus:
        now = now or utcnow()
        enabled = self.is_enabled()
        contact = self.last_contact()
        minutes = round((now - contact).total_seconds() / 60, 1) if contact else None
        waiting = self.store.count_by_status(TaskStatus.WAITING_CLAUDE)

        if not enabled:
            state: State = "off"
            label = "Claude modu kapalı — kayaAI tamamen yerel çalışıyor"
        elif contact is None:
            state = "on_no_contact"
            label = "Claude modu açık — Claude Code henüz kayaAI'ye bağlanmadı"
        elif minutes is not None and minutes <= self.settings.contact_window_min:
            state = "on_recent_contact"
            label = f"Claude modu açık — Claude Code son temas {_fmt_minutes(minutes)} önce"
        else:
            state = "on_stale_contact"
            label = f"Claude modu açık — Claude Code son temas {_fmt_minutes(minutes)} önce (oturum kapalı olabilir)"
        if waiting:
            label += f" · Claude kutusunda {waiting} görev bekliyor"
        return ClaudeStatus(
            enabled=enabled,
            state=state,
            last_contact=contact,
            minutes_since_contact=minutes,
            waiting_tasks=waiting,
            label=label,
        )


def _fmt_minutes(minutes: float | None) -> str:
    if minutes is None:
        return "?"
    if minutes < 1:
        return "1 dk'dan az"
    if minutes < 120:
        return f"{int(minutes)} dk"
    return f"{minutes / 60:.1f} saat"
