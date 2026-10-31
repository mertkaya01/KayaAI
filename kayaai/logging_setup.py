"""Dosya + konsol loglama. Loglar data/logs/ altında döner (rotating)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Settings

_CONFIGURED = False


def setup_logging(settings: Settings, console: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("kayaai")
    root.setLevel(settings.logging.level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        settings.log_path,
        maxBytes=settings.logging.max_bytes,
        backupCount=settings.logging.backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.setLevel(logging.WARNING)
        root.addHandler(ch)
    _CONFIGURED = True
