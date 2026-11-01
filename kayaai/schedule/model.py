"""Zamanlanmış görev modeli ve sıklık hesabı (Adım 13). Saatler bu bilgisayarın YEREL saatidir (Görev Zamanlayıcı gibi)."""

from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Kind = Literal["docs_digest", "sales_report", "reindex", "free"]
Freq = Literal["daily", "weekly", "monthly", "once"]
KIND_LABEL = {"docs_digest": "Belge klasörü özeti", "sales_report": "Satış raporu", "reindex": "Belge dizini yenileme",
              "free": "Serbest görev"}
DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class Cadence(BaseModel):
    freq: Freq = "daily"
    at: str = Field("09:00", description="HH:MM (yerel saat)")
    days: list[int] = Field(default_factory=list, description="weekly: 0=Pazartesi … 6=Pazar")
    day: int = Field(1, ge=1, le=28, description="monthly: ayın günü (1-28, her ay var)")
    on: str | None = Field(None, description="once: YYYY-MM-DD")

    @field_validator("at")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", v.strip())
        if not m:
            raise ValueError("saat HH:MM olmalı (ör. 09:00)")
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    @model_validator(mode="after")
    def _check(self) -> "Cadence":
        if self.freq == "weekly":
            if not self.days or any(d not in range(7) for d in self.days):
                raise ValueError("haftalık görev için en az bir gün (0=Pazartesi … 6=Pazar)")
            self.days = sorted(set(self.days))
        if self.freq == "once":
            if not self.on:
                raise ValueError("tek seferlik görev için tarih (YYYY-MM-DD)")
            date.fromisoformat(self.on)
        return self

    @property
    def clock(self) -> time:
        h, m = self.at.split(":")
        return time(int(h), int(m))

    def next_after(self, now: datetime) -> datetime | None:
        """`now`dan SONRAKİ ilk çalışma zamanı (yerel, saniyesiz). Tek seferlik geçmişteyse None."""
        t = self.clock
        if self.freq == "once":
            when = datetime.combine(date.fromisoformat(self.on or ""), t)
            return when if when > now else None
        if self.freq == "daily":
            when = datetime.combine(now.date(), t)
            return when if when > now else when + timedelta(days=1)
        if self.freq == "weekly":
            for i in range(8):
                d = now.date() + timedelta(days=i)
                when = datetime.combine(d, t)
                if d.weekday() in self.days and when > now:
                    return when
            return None  # olmaz
        y, m = now.year, now.month
        for _ in range(13):
            when = datetime.combine(date(y, m, self.day), t)
            if when > now:
                return when
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return None

    def describe(self) -> str:
        if self.freq == "daily":
            return f"her gün {self.at}"
        if self.freq == "weekly":
            return "her " + ", ".join(DAY_NAMES[d] for d in self.days) + f" {self.at}"
        if self.freq == "monthly":
            return f"her ayın {self.day}. günü {self.at}"
        return f"bir kez: {self.on} {self.at}"


class Schedule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = Field(min_length=1, max_length=80)
    kind: Kind
    params: dict[str, Any] = Field(default_factory=dict)
    cadence: Cadence
    enabled: bool = True
    catch_up: bool = True                 # bilgisayar kapalıyken kaçırılan çalışmayı açılınca yap
    skip_holidays: bool = False           # Adım 14c: resmi tatilde çalışma (tatil takvimi açık olmalı)
    created_at: datetime = Field(default_factory=datetime.now)
    registered: bool = False              # Windows Görev Zamanlayıcı'da kayıtlı mı
    register_note: str | None = None
    last_run: datetime | None = None
    last_status: str | None = None
    last_message: str | None = None

    @model_validator(mode="after")
    def _params(self) -> "Schedule":
        p = self.params
        if self.kind == "sales_report" and not str(p.get("path", "")).strip():
            raise ValueError("satış raporu için Excel/CSV dosyası (path) gerekli")
        if self.kind == "free" and len(str(p.get("request", "")).strip()) < 5:
            raise ValueError("serbest görev için istek metni (request) gerekli")
        if self.kind == "sales_report":
            fmts = p.get("formats") or ["xlsx", "pdf"]
            if any(f not in ("md", "xlsx", "docx", "pdf") for f in fmts):
                raise ValueError("rapor biçimleri: md, xlsx, docx, pdf")
            p["formats"] = list(fmts)
        if self.kind == "docs_digest":
            p["max_files"] = int(p.get("max_files", 10))
            if not 1 <= p["max_files"] <= 50:
                raise ValueError("max_files 1-50")
        return self

    def next_run(self, now: datetime | None = None) -> datetime | None:
        if not self.enabled:
            return None
        return self.cadence.next_after(now or datetime.now())

    def summary(self) -> str:
        what = KIND_LABEL[self.kind]
        if self.kind == "sales_report":
            what += f" ({self.params['path']})"
        elif self.kind == "free":
            what += f": {str(self.params['request'])[:80]}"
        elif self.kind == "docs_digest" and self.params.get("folder"):
            what += f" ({self.params['folder']})"
        return f"{self.name} — {what}, {self.cadence.describe()}" + (" (resmi tatilde çalışmaz)" if self.skip_holidays else "")


class Run(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    schedule_id: str
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    trigger: Literal["windows", "manual", "run-due"] = "manual"
    status: Literal["running", "succeeded", "failed", "skipped"] = "running"
    message: str = ""
    files: list[str] = Field(default_factory=list)
    conv_id: str | None = None
    message_id: str | None = None
    seconds: float | None = None


def month_days(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
