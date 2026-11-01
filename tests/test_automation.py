"""Adım 14a: otomasyonu duraklat anahtarı."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.automation import is_paused, set_paused, state
from kayaai.browser.agent import BrowserJobError, start_job
from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.schedule import Cadence, Schedule
from kayaai.schedule.runner import run_schedule

from .test_browser import FakeDriver, act


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


def test_pause_skips_windows_runs_but_not_manual(rt, env):
    s = Schedule(name="Gece", kind="reindex", cadence=Cadence())
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    set_paused(rt, True, by="owner", reason="tatil")
    assert is_paused(rt) and state(rt)["reason"] == "tatil"
    with build_runtime(env) as other:  # başka süreç (Windows'un başlattığı) de görür
        run = run_schedule(other, s.id, "windows")
    assert run.status == "skipped" and run.message == "otomasyon duraklatıldı"
    assert run_schedule(rt, s.id, "manual").status == "succeeded"  # sahibin elle çalıştırması etkilenmez
    set_paused(rt, False)
    assert run_schedule(rt, s.id, "windows").status == "succeeded"
    types = [e["type"] for e in rt.store.events_since(0)]
    assert "automation.paused" in types and "automation.resumed" in types


def test_pause_blocks_and_stops_browser_jobs(rt, fake_ollama):
    fake_ollama.chat_replies = [act("type", 1, "python")]
    job = start_job(rt, "Python ara", "https://kitap.example.com/ara", driver_factory=FakeDriver, background=True)
    t0 = time.monotonic()
    while not rt.permissions.list_approvals("pending") and time.monotonic() - t0 < 10:
        time.sleep(0.05)
    st = set_paused(rt, True)
    assert job.state.id in st["stopped_browser_jobs"] and job.finished.wait(10) and job.state.status == "stopped"
    with pytest.raises(BrowserJobError, match="duraklatıldı"):
        start_job(rt, "Python ara", "https://kitap.example.com/ara", driver_factory=FakeDriver)
    set_paused(rt, False)


def test_api_and_cli(env, tmp_path, capsys):
    from kayaai.api import create_app
    from kayaai.cli import main

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.get("/api/automation", headers=h).json()["paused"] is False
        assert c.post("/api/automation/pause", headers=h).json()["paused"] is True
    assert main(["automation"]) == 0 and "DURAKLATILDI" in capsys.readouterr().out
    assert main(["resume"]) == 0 and "sürüyor" in capsys.readouterr().out
    assert main(["pause", "bakım"]) == 0 and "duraklatıldı" in capsys.readouterr().out
    with build_runtime(env) as rt:
        assert state(rt)["reason"] == "bakım"
