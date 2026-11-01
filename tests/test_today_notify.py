"""Adım 16: Bugün özeti ve bildirimler (tercihler, sessiz saatler, Windows bildirimi, zamanlanmış görev bağlantısı)."""

from __future__ import annotations

import base64
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai import notify
from kayaai.config import load_settings
from kayaai.notify import NotifyPrefs, allowed, in_quiet, windows_toast
from kayaai.runtime import build_runtime
from kayaai.today import greeting, long_date, summary


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def rt(env):
    r = build_runtime(env)
    yield r
    r.close()


@pytest.mark.parametrize("h,g", [(6, "Günaydın"), (13, "İyi günler"), (20, "İyi akşamlar"), (2, "İyi geceler")])
def test_greeting(h, g):
    assert greeting(datetime(2026, 11, 2, h)) == g


def test_long_date():
    assert long_date(date(2026, 11, 2)) == "2 Kasım 2026, Pazartesi"


def test_quiet_hours_wrap_midnight():
    p = NotifyPrefs(quiet_start="22:30", quiet_end="08:00")
    assert in_quiet(p, datetime(2026, 1, 1, 23, 0)) and in_quiet(p, datetime(2026, 1, 1, 7, 59))
    assert not in_quiet(p, datetime(2026, 1, 1, 8, 0)) and not in_quiet(p, datetime(2026, 1, 1, 12, 0))
    day = NotifyPrefs(quiet_start="12:00", quiet_end="13:00")
    assert in_quiet(day, datetime(2026, 1, 1, 12, 30)) and not in_quiet(day, datetime(2026, 1, 1, 13, 30))
    with pytest.raises(ValueError):
        NotifyPrefs(quiet_start="25:00")


def test_allowed_by_channel_and_kind():
    p = NotifyPrefs(windows=False, kinds={"approval": True, "reply": False})
    noon = datetime(2026, 1, 1, 12)
    assert allowed(p, "approval", "browser", noon) and not allowed(p, "approval", "windows", noon)
    assert not allowed(p, "reply", "browser", noon)
    assert p.kinds == {"approval": True, "reply": False, "schedule": True, "error": True}


def test_toast_passes_text_via_env_not_command():
    seen = {}

    def fake(args, env, **kw):
        seen["args"], seen["env"] = args, env
        return type("R", (), {"returncode": 0})()

    evil = "'; Remove-Item C:\\ -Recurse; '<x>"
    assert windows_toast("Başlık", evil, runner=fake)
    script = base64.b64decode(seen["args"][-1]).decode("utf-16-le")
    assert "Remove-Item" not in script and "$env:KAYA_TOAST_BODY" in script and "SecurityElement]::Escape" in script
    assert seen["env"]["KAYA_TOAST_BODY"] == evil and seen["args"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"]


def test_toast_off_windows_is_noop(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    assert windows_toast("a", "b") is False


def test_scheduled_run_notifies_unless_manual_or_quiet(rt, monkeypatch):
    from kayaai.schedule import Cadence, Schedule
    from kayaai.schedule.runner import run_schedule

    sent = []
    monkeypatch.setattr(notify, "windows_toast", lambda t, b, runner=None: sent.append((t, b)) or True)
    s = Schedule(name="Gece dizini", kind="reindex", cadence=Cadence())
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    run_schedule(rt, s.id, "manual")
    assert sent == []  # sahip başındaydı
    run_schedule(rt, s.id, "windows")
    assert sent and sent[0][0] == "kayaAI · Gece dizini"
    notify.set_prefs(rt, NotifyPrefs(kinds={"schedule": False}))
    run_schedule(rt, s.id, "windows")
    assert len(sent) == 1
    ev = [e["data"] for e in rt.store.events_since(0, 500) if e["type"] == "notify.sent"]
    assert ev == [{"kind": "schedule", "channel": "windows", "ok": True, "title": "kayaAI · Gece dizini"}]


def test_summary(rt, fake_ollama):
    from kayaai.assistant.chat import ChatBook
    from kayaai.schedule import Cadence, Schedule

    ChatBook(rt).create("Satış soruları")
    s = Schedule(name="Haftalık", kind="reindex", cadence=Cadence(freq="weekly", days=[0], at="09:00"))
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    from kayaai.integrations import request_enable

    request_enable(rt, "holidays")  # R2 → onay bekler
    out = summary(rt, datetime(2026, 11, 1, 9, 30))
    assert out["approvals"]["count"] == 1 and out["approvals"]["items"][0]["risk"] == "R2"
    assert out["greeting"] == "Günaydın" and out["date"] == "1 Kasım 2026, Pazar"
    assert out["schedules"][0]["name"] == "Haftalık" and out["schedules"][0]["next_run"] == "2026-11-02T09:00:00"
    assert out["chats"][0]["title"] == "Satış soruları"
    assert out["system"]["ollama"] is True and out["system"]["automation"]["paused"] is False
    assert out["holiday"] is None and out["rates"] is None  # dış veri kapalı → istek yok
    assert out["notifications"]["browser"] is True


def test_summary_survives_ollama_down(env, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", "http://127.0.0.1:9")
    with build_runtime(load_settings()) as r:
        assert summary(r)["system"]["ollama"] is False


def test_api(env, tmp_path):
    from kayaai.api import create_app

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.get("/api/today", headers=h).json()["approvals"]["count"] == 0
        p = c.get("/api/notifications", headers=h).json()
        assert p["windows"] is True and "approval" in p["labels"]
        r = c.post("/api/notifications", headers=h, json={"browser": False, "quiet_start": "23:00", "quiet_end": "07:30"})
        assert r.status_code == 200 and r.json()["browser"] is False and r.json()["quiet_end"] == "07:30"
        assert c.post("/api/notifications", headers=h, json={"quiet_start": "99:00"}).status_code == 422
        assert c.get("/api/notifications", headers=h).json()["quiet_start"] == "23:00"
        assert c.get("/api/today", headers={}).status_code == 401
