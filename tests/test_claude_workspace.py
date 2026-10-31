"""Adım 3e: Claude çalışma alanı üreticisi (CLAUDE.md, .claude/agents, .mcp.json)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from kayaai.agents.definitions import load_definitions
from kayaai.claude_workspace import MARKER, WorkspaceError, sync_workspace
from kayaai.config import PROJECT_ROOT, load_settings
from kayaai.llm.registry import ModelRegistry


@pytest.fixture
def agents():
    reg = ModelRegistry.load(PROJECT_ROOT / "config" / "models.yaml")
    return load_definitions(PROJECT_ROOT / "config" / "agents", reg)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    return load_settings()


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "frontmatter ilk satırda başlamalı (yoksa Claude Code dosyayı sessizce atlar)"
    return yaml.safe_load(text.split("---")[1])


def test_generates_expected_files(tmp_path, settings, agents):
    ws = tmp_path / "ws"
    rep = sync_workspace(settings, agents, ws)
    assert set(rep.written) == {"CLAUDE.md", "README.md", ".mcp.json", ".claude/agents/kayaai-coder.md",
                                ".claude/agents/kayaai-general.md", ".claude/agents/kayaai-reviewer.md"}
    assert not (ws / ".claude/agents/kayaai-planner.md").exists()  # claude_tier: none


def test_agent_files_valid_for_claude_code(tmp_path, settings, agents):
    sync_workspace(settings, agents, tmp_path / "ws")
    tiers = {d.name: d.claude_tier for d in agents}
    for f in (tmp_path / "ws/.claude/agents").glob("*.md"):
        fm = _frontmatter(f)
        assert fm["name"].startswith("kayaai-") and ":" not in fm["name"]
        assert fm["description"] and fm["model"] in {"haiku", "sonnet", "opus"}
        assert fm["model"] == tiers[fm["name"].removeprefix("kayaai-")]
        body = f.read_text(encoding="utf-8")
        assert MARKER in body
        assert "running locally" not in body and "cannot run code" not in body  # yerel talimat sızmamalı


def test_claude_md_contains_rules(tmp_path, settings, agents):
    sync_workspace(settings, agents, tmp_path / "ws")
    md = (tmp_path / "ws/CLAUDE.md").read_text(encoding="utf-8")
    for needle in ("Önce yerel", "kayaai_ask", "kayaai_do", "kayaai_claude_inbox", "kayaai_claude_complete",
                   "Her mesajı araca yollama", "kayaai-coder", "`coder`", MARKER):
        assert needle in md
    assert "`planner`" not in md  # şef içindir, kullanıcıya/Claude'a ajan olarak sunulmaz


def test_mcp_json_valid_and_absolute(tmp_path, settings, agents):
    sync_workspace(settings, agents, tmp_path / "ws")
    cfg = json.loads((tmp_path / "ws/.mcp.json").read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["kayaai"]
    assert srv["type"] == "stdio" and Path(srv["command"]).is_absolute()
    assert srv["args"] == ["-m", "kayaai.mcp_server"]


def test_second_sync_is_idempotent(tmp_path, settings, agents):
    ws = tmp_path / "ws"
    sync_workspace(settings, agents, ws)
    rep = sync_workspace(settings, agents, ws)
    assert rep.written == [] and len(rep.unchanged) == 6


def test_foreign_files_are_never_overwritten(tmp_path, settings, agents):
    ws = tmp_path / "ws"
    (ws / ".claude/agents").mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("# kullanıcının kendi notları\n", encoding="utf-8")
    (ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"baska": {"command": "x"}}}), encoding="utf-8")
    (ws / ".claude/agents/kayaai-coder.md").write_text("---\nname: elle\n---\n", encoding="utf-8")
    (ws / ".claude/agents/benim.md").write_text("kendi ajanım", encoding="utf-8")
    rep = sync_workspace(settings, agents, ws)
    assert set(rep.skipped_foreign) == {"CLAUDE.md", ".mcp.json", ".claude/agents/kayaai-coder.md"}
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "# kullanıcının kendi notları\n"
    assert (ws / ".claude/agents/benim.md").read_text(encoding="utf-8") == "kendi ajanım"


def test_stale_generated_agent_removed(tmp_path, settings, agents):
    ws = tmp_path / "ws"
    sync_workspace(settings, agents, ws)
    reduced = [d for d in agents if d.name != "reviewer"]
    rep = sync_workspace(settings, reduced, ws)
    assert rep.removed == [".claude/agents/kayaai-reviewer.md"]
    assert not (ws / ".claude/agents/kayaai-reviewer.md").exists()


def test_workspace_inside_repo_refused(settings, agents):
    with pytest.raises(WorkspaceError, match="içinde olamaz"):
        sync_workspace(settings, agents, PROJECT_ROOT / "workspace")
    with pytest.raises(WorkspaceError):
        sync_workspace(settings, agents, PROJECT_ROOT)


def test_cli_claude_on_generates_workspace(tmp_path):
    env = dict(os.environ, KAYAAI_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    ws = tmp_path / "ws"
    r = subprocess.run([sys.executable, "-m", "kayaai", "claude", "on", "--workspace", str(ws)], env=env,
                       cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[AÇIK]" in r.stdout and "claude" in r.stdout and (ws / "CLAUDE.md").exists()
    r2 = subprocess.run([sys.executable, "-m", "kayaai", "claude", "sync", "--workspace", str(PROJECT_ROOT / "x")],
                        env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r2.returncode == 1 and "içinde olamaz" in r2.stdout
