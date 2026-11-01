"""Bildirimler (Adım 16c): tercihler, sessiz saatler ve Windows bildirimi.

- Tarayıcı bildirimi arayüzde (sekme arka plandayken) gösterilir; tercihleri buradan okur.
- Windows bildirimi kayaAI arayüzü kapalıyken de çalışan süreçlerden (zamanlanmış görev) gönderilir: Windows PowerShell'in
  yerleşik bildirim API'si (ek paket yok). Başlık ve metin ortam değişkeniyle geçer, XML'e kaçışla girer (komut/işaretleme
  enjeksiyonu yok). Bildirim yalnız bu bilgisayarda görünür; dışarı bir şey gitmez.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from .runtime import Runtime

META_KEY = "notifications"
Kind = Literal["approval", "reply", "schedule", "error"]
KINDS: dict[str, str] = {
    "approval": "Onay bekleyen işlem",
    "reply": "Cevap hazır (sekme arka plandayken)",
    "schedule": "Zamanlanmış görev sonucu",
    "error": "Hata (iş ya da görev başarısız)",
}


class NotifyPrefs(BaseModel):
    browser: bool = True
    windows: bool = True
    kinds: dict[str, bool] = Field(default_factory=lambda: {k: True for k in KINDS})
    quiet_start: str | None = None   # "22:30" — sessiz saatler (bildirim yok)
    quiet_end: str | None = None     # "08:00"

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        h, _, m = v.strip().partition(":")
        if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError("saat HH:MM olmalı")
        return f"{int(h):02d}:{int(m):02d}"

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, v: dict[str, bool]) -> dict[str, bool]:
        return {k: bool(v.get(k, True)) for k in KINDS}


def get_prefs(rt: "Runtime") -> NotifyPrefs:
    raw = rt.store.get_meta(META_KEY)
    try:
        return NotifyPrefs.model_validate(json.loads(raw)) if raw else NotifyPrefs()
    except ValueError:
        return NotifyPrefs()


def set_prefs(rt: "Runtime", prefs: NotifyPrefs) -> NotifyPrefs:
    rt.store.set_meta(META_KEY, prefs.model_dump_json())
    rt.store.emit("notify.prefs", {"browser": prefs.browser, "windows": prefs.windows})
    return prefs


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_quiet(prefs: NotifyPrefs, now: datetime) -> bool:
    if not prefs.quiet_start or not prefs.quiet_end:
        return False
    a, b, t = _t(prefs.quiet_start), _t(prefs.quiet_end), now.time()
    return (a <= t < b) if a <= b else (t >= a or t < b)  # gece yarısını aşan aralık (22:00–08:00)


def allowed(prefs: NotifyPrefs, kind: str, channel: Literal["browser", "windows"], now: datetime | None = None) -> bool:
    if not getattr(prefs, channel) or not prefs.kinds.get(kind, False):
        return False
    return not in_quiet(prefs, now or datetime.now())


# PowerShell 5.1 (Windows'ta yerleşik): metin $env üzerinden, XML kaçışlı
_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$t = [System.Security.SecurityElement]::Escape($env:KAYA_TOAST_TITLE)
$b = [System.Security.SecurityElement]::Escape($env:KAYA_TOAST_BODY)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def windows_toast(title: str, body: str, runner: Any = subprocess.run) -> bool:
    """Windows bildirimi gösterir. Windows dışında ya da hata olursa False (sessizce; iş akışını bozmaz)."""
    if sys.platform != "win32" and runner is subprocess.run:
        return False
    env = dict(os.environ, KAYA_TOAST_TITLE=title[:120], KAYA_TOAST_BODY=body[:300])
    encoded = base64.b64encode(_PS.encode("utf-16-le")).decode()
    try:
        r = runner(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], env=env,
                   capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def notify_windows(rt: "Runtime", kind: str, title: str, body: str, runner: Any = subprocess.run,
                   now: datetime | None = None) -> bool:
    prefs = get_prefs(rt)
    if not allowed(prefs, kind, "windows", now):
        return False
    ok = windows_toast(title, body, runner)
    rt.store.emit("notify.sent", {"kind": kind, "channel": "windows", "ok": ok, "title": title[:120]})
    return ok
