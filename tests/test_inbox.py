"""Adım 3d: Claude kutusu (MCP inbox/complete/release, CLI inbox, claude off ile geri verme)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from kayaai.conductor import ClaudeInbox, Conductor
from kayaai.config import PROJECT_ROOT, load_settings
from kayaai.core.task import TaskStatus
from kayaai.mcp_server import create_server
from kayaai.runtime import build_runtime

from .conductor_helpers import Script, answer, plan_direct
from .test_conductor import rt  # noqa: F401  (fixture)

HARD = plan_direct("general", needs_claude=True, reason="karmaşık mimari")


def _waiting_job(rt, fake_ollama, request="Zor bir mimari iş"):
    rt.claude.enable()
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[])] * 5
    res = Conductor(rt).run(request)
    assert res.status == "waiting_claude"
    return res.job_id


def test_inbox_lists_waiting_jobs_with_reason(rt, fake_ollama):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    view = ClaudeInbox(rt).view()
    assert view.claude_mode_enabled and len(view.items) == 1
    item = view.items[0]
    assert item.job_id == job_id and "karmaşık mimari" in item.reason
    assert item.suggested_steps and item.suggested_steps[0]["agent"] == "general"
    rt.claude.disable()
    assert "KAPALI" in ClaudeInbox(rt).view().note


def test_complete_writes_claude_answer(rt, fake_ollama):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    inbox = ClaudeInbox(rt)
    res = inbox.complete(job_id, "Claude'un ayrıntılı mimari cevabı.", summary="3 servis önerildi")
    assert res.status == "succeeded" and res.answer.startswith("Claude'un")
    job = rt.store.get(job_id)
    assert job.status == TaskStatus.SUCCEEDED and job.model == "claude (Claude Code)"
    assert job.result["completed_by"] == "claude (Claude Code)"
    assert "claude.completed" in [e["event"] for e in rt.store.events(job_id)]
    assert inbox.items() == []
    with pytest.raises(ValueError, match="kutusunda değil"):
        inbox.complete(job_id, "tekrar")


@pytest.mark.parametrize("bad,match", [("", "boş"), ("   ", "boş"), ("x" * 20_001, "en fazla")])
def test_complete_rejects_bad_answers(rt, fake_ollama, bad, match):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    with pytest.raises(ValueError, match=match):
        ClaudeInbox(rt).complete(job_id, bad)
    assert rt.store.get(job_id).status == TaskStatus.WAITING_CLAUDE


def test_complete_unknown_job(rt):  # noqa: F811
    with pytest.raises(KeyError):
        ClaudeInbox(rt).complete("yok", "cevap")


def test_release_runs_locally_on_same_job_with_warning(rt, fake_ollama):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("Yerel ekibin cevabı.")])] * 5
    res = ClaudeInbox(rt).release(job_id)
    assert res.job_id == job_id and res.status == "succeeded" and res.answer == "Yerel ekibin cevabı."
    assert any("geri verildi" in w for w in res.warnings)
    assert any("Claude ile muhtemelen daha iyi" in w for w in res.warnings)
    assert rt.store.get(job_id).status == TaskStatus.SUCCEEDED
    with pytest.raises(ValueError):
        ClaudeInbox(rt).release(job_id)


def test_cancel_waiting_job(rt, fake_ollama):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    assert ClaudeInbox(rt).cancel(job_id)
    assert rt.store.get(job_id).status == TaskStatus.CANCELLED
    assert not ClaudeInbox(rt).cancel(job_id)


def test_inbox_survives_restart(rt, fake_ollama):  # noqa: F811
    job_id = _waiting_job(rt, fake_ollama)
    settings = rt.settings
    rt.close()
    rt2 = build_runtime(settings)
    try:
        assert [i.job_id for i in ClaudeInbox(rt2).items()] == [job_id]
    finally:
        rt2.close()


def test_mcp_inbox_complete_release(rt, fake_ollama):  # noqa: F811
    a = _waiting_job(rt, fake_ollama, "Birinci zor iş")
    b = _waiting_job(rt, fake_ollama, "İkinci zor iş")

    async def go():
        async with Client(create_server(rt.settings, runtime=rt)) as c:
            inbox = (await c.call_tool("kayaai_claude_inbox", {})).structured_content
            done = await c.call_tool("kayaai_claude_complete", {"job_id": a, "answer": "Claude cevabı"})
            empty = await c.call_tool("kayaai_claude_complete", {"job_id": b, "answer": ""})
            fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("Yerel cevap.")])] * 5
            released = await c.call_tool("kayaai_claude_release", {"job_id": b})
            after = (await c.call_tool("kayaai_claude_inbox", {})).structured_content
            return inbox, done, empty, released, after

    inbox, done, empty, released, after = asyncio.run(go())
    assert {i["job_id"] for i in inbox["items"]} == {a, b}
    assert not done.is_error and done.structured_content["answer"] == "Claude cevabı"
    assert empty.is_error
    assert not released.is_error and released.structured_content["answer"] == "Yerel cevap."
    assert after["items"] == [] and "boş" in after["note"]


def _cli(env, *args, stdin: str = ""):
    return subprocess.run([sys.executable, "-m", "kayaai", *args], env=env, cwd=str(PROJECT_ROOT), input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=90)


@pytest.mark.parametrize("off_args,stdin,expect_done", [
    (["--keep"], "", False),
    (["--yes"], "", True),
    ([], "\n", True),     # varsayılan cevap: evet (D16)
    ([], "h\n", False),
])
def test_cli_claude_off_hands_back_inbox(fake_ollama, tmp_path: Path, monkeypatch, off_args, stdin, expect_done):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))  # test içindeki runtime da geçici klasörü kullanmalı
    env = dict(os.environ, PYTHONUTF8="1")
    settings = load_settings()
    rt = build_runtime(settings)
    job_id = _waiting_job(rt, fake_ollama)
    rt.close()
    assert job_id in _cli(env, "inbox").stdout
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("Kapatınca yerelde yapıldı.")])] * 5
    r = _cli(env, "claude", "off", *off_args, stdin=stdin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("Kapatınca yerelde yapıldı." in r.stdout) is expect_done
    listing = _cli(env, "inbox").stdout
    assert (job_id in listing) is (not expect_done)


def test_cli_inbox_run_and_cancel(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    env = dict(os.environ, PYTHONUTF8="1")
    rt = build_runtime(load_settings())
    a = _waiting_job(rt, fake_ollama, "A işi")
    b = _waiting_job(rt, fake_ollama, "B işi")
    rt.close()
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("A yerelde.")])] * 5
    r = _cli(env, "inbox", "run", a)
    assert r.returncode == 0 and "A yerelde." in r.stdout
    assert _cli(env, "inbox", "cancel", b).returncode == 0
    assert "boş" in _cli(env, "inbox").stdout
    assert _cli(env, "inbox", "run").returncode == 2
