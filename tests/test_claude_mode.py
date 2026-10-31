"""Adım 3a: Claude modu (aç/kapa, kalıcılık, son temas, waiting_claude)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from mcp import Client

from kayaai.config import PROJECT_ROOT, ClaudeSettings, load_settings
from kayaai.core.claude_mode import ClaudeMode
from kayaai.core.store import TaskStore
from kayaai.core.task import Task, TaskStatus, utcnow
from kayaai.mcp_server import create_server


def test_default_off_and_yaml_default(store):
    assert ClaudeMode(store).status().state == "off"
    assert ClaudeMode(store, ClaudeSettings(enabled=True)).is_enabled()


def test_toggle_overrides_yaml_and_survives_restart(tmp_path: Path):
    db = tmp_path / "k.db"
    s1 = TaskStore(db)
    ClaudeMode(s1, ClaudeSettings(enabled=False)).enable()
    s1.close()
    s2 = TaskStore(db)
    assert ClaudeMode(s2, ClaudeSettings(enabled=False)).is_enabled()  # meta, YAML'ı ezer
    ClaudeMode(s2, ClaudeSettings(enabled=True)).disable()
    assert not ClaudeMode(s2, ClaudeSettings(enabled=True)).is_enabled()
    s2.close()


def test_contact_states(store):
    mode = ClaudeMode(store, ClaudeSettings(contact_window_min=15))
    mode.enable()
    assert mode.status().state == "on_no_contact"
    mode.record_contact()
    st = mode.status()
    assert st.state == "on_recent_contact" and st.last_contact is not None
    later = utcnow() + timedelta(minutes=40)
    stale = mode.status(now=later)
    assert stale.state == "on_stale_contact" and stale.minutes_since_contact >= 39
    mode.disable()
    assert mode.status().state == "off"  # kapalıyken temas olsa da kapalı


def test_waiting_tasks_counted_and_kept_after_restart(tmp_path: Path):
    db = tmp_path / "k.db"
    s1 = TaskStore(db)
    t = Task(worker="general", objective="Claude için", status=TaskStatus.WAITING_CLAUDE)
    s1.save(t)
    mode = ClaudeMode(s1)
    mode.enable()
    assert mode.status().waiting_tasks == 1
    assert "1 görev bekliyor" in mode.status().label
    s1.close()
    s2 = TaskStore(db)
    assert s2.recover_interrupted() == []  # waiting_claude yarım iş sayılmaz
    assert s2.get(t.id).status == TaskStatus.WAITING_CLAUDE
    s2.close()


def test_waiting_claude_task_can_be_cancelled(make_orchestrator, store):
    orch = make_orchestrator()
    t = orch.submit("Claude bekleyen")
    t.status = TaskStatus.WAITING_CLAUDE
    store.save(t)
    assert orch.cancel(t.id)
    assert store.get(t.id).status == TaskStatus.CANCELLED


def _cli(env: dict[str, str], *args: str) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "kayaai", *args],
        env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_cli_claude_on_off_status(tmp_path: Path):
    import os

    env = dict(os.environ, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    assert "kapalı" in _cli(env, "claude")
    assert "[AÇIK]" in _cli(env, "claude", "on")
    assert "açık" in _cli(env, "claude", "status")  # ayrı süreç: kalıcı
    assert '"enabled": true' in _cli(env, "claude", "status", "--json")
    assert "[KAPALI]" in _cli(env, "claude", "off")
    assert "kapalı" in _cli(env, "claude")


def test_mcp_tool_call_records_contact(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    settings = load_settings()
    store = TaskStore(settings.db_path)
    ClaudeMode(store, settings.claude).enable()
    store.close()

    async def go():
        async with Client(create_server(settings)) as c:
            return (await c.call_tool("kayaai_health", {})).structured_content

    health = asyncio.run(go())
    assert health["claude_mode"]["enabled"] is True
    assert health["claude_mode"]["state"] == "on_recent_contact"
    assert health["claude_mode"]["last_contact"]
