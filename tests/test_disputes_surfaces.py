"""Adım 7b: anlaşmazlıkların CLI / API / MCP yüzeyleri. Karar yalnızca sahipte (CLI, anahtarlı API)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from kayaai import cli
from kayaai.api import create_app
from kayaai.config import load_settings
from kayaai.core.disputes import DisputeBook, DisputeRecord
from kayaai.core.store import TaskStore
from kayaai.mcp_server import create_server
from kayaai.runtime import build_runtime


def _open(db: Path, **kw) -> DisputeRecord:
    store = TaskStore(db)
    try:
        return DisputeBook(store).open(DisputeRecord(
            job_id="job1", step_id="s1", request="Fonksiyon yaz", producer="coder", reviewer="reviewer",
            issue_id="i1", issue="Toplama yerine çıkarma yapıyor", evidence="return a + b",
            producer_position="Kod a + b döndürüyor.", **kw))
    finally:
        store.close()


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    return load_settings()


def test_cli_list_show_resolve(env, capsys):
    d = _open(env.db_path)
    assert cli.main(["disputes"]) == 0
    assert d.id in capsys.readouterr().out
    assert cli.main(["disputes", "show", d.id]) == 0
    out = capsys.readouterr().out
    assert "Kod a + b döndürüyor." in out and "return a + b" in out and "sahip (sen)" in out
    assert cli.main(["disputes", "resolve", d.id]) == 2  # taraf gerekli
    assert cli.main(["disputes", "resolve", d.id, "--side", "producer", "--note", "kod doğru"]) == 0
    assert "coder haklı" in capsys.readouterr().out
    assert cli.main(["disputes", "resolve", d.id, "--side", "reviewer"]) == 1  # zaten kapandı
    assert cli.main(["disputes"]) == 0 and "Açık anlaşmazlık yok" in capsys.readouterr().out
    assert cli.main(["disputes", "list", "--all"]) == 0 and "producer" in capsys.readouterr().out


def test_api_list_and_resolve(env):
    d = _open(env.db_path)
    rt = build_runtime(env)
    app = create_app(env, runtime=rt)
    with TestClient(app) as c:
        assert c.get("/api/disputes").status_code == 401
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        [item] = c.get("/api/disputes").json()
        assert item["id"] == d.id and item["status"] == "open"
        assert c.post(f"/api/disputes/{d.id}/resolve", json={"side": "kimse"}).status_code == 422
        r = c.post(f"/api/disputes/{d.id}/resolve", json={"side": "reviewer", "note": "gözden geçirici haklı"})
        assert r.status_code == 200 and r.json()["resolution"] == "reviewer" and r.json()["decided_by"] == "api"
        assert c.post(f"/api/disputes/{d.id}/resolve", json={"side": "producer"}).status_code == 409
        assert c.post("/api/disputes/yok/resolve", json={"side": "producer"}).status_code == 404
        assert c.get("/api/disputes").json() == []
        assert len(c.get("/api/disputes?status=all").json()) == 1
    rt.close()
    types = [e["type"] for e in TaskStore(env.db_path).events_since(0)]
    assert types.count("dispute.opened") == 1 and types.count("dispute.resolved") == 1


def test_mcp_can_read_but_not_resolve(env):
    d = _open(env.db_path, escalated_to="claude")

    async def go():
        async with Client(create_server(env)) as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            r = await c.call_tool("kayaai_disputes", {})
            return tools, r

    tools, r = asyncio.run(go())
    assert not any("resolve" in t or "decide" in t for t in tools)
    assert r.structured_content["open"][0]["id"] == d.id
    assert r.structured_content["open"][0]["producer_position"] == "Kod a + b döndürüyor."
