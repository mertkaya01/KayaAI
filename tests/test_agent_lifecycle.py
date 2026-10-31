"""Adım 7c: geçici ajanlar — oluşturma, izin tavanı, doğrulayıcı kapısı, sahip onayıyla kalıcı yapma, kaldırma."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp import Client

from kayaai.agents.definitions import AgentDefinition, register_definition
from kayaai.agents.lifecycle import (
    AgentLifecycleError,
    AgentProposal,
    claude_definitions,
    create_temporary,
    remove_temporary,
    request_promotion,
    sync_user_agents,
    usage,
)
from kayaai.api import create_app
from kayaai.conductor import Conductor
from kayaai.config import load_settings
from kayaai.mcp_server import create_server
from kayaai.runtime import build_runtime
from kayaai.workers.planner import RoutePlan, validate_plan

from .conductor_helpers import Script, answer
from .conftest import good_answer

LEGAL = AgentProposal(name="legal", description="Sözleşme ve hukuk metinlerini sade dille açıklar",
                      role="You explain legal texts in plain language. Never give definitive legal advice.",
                      base="document")


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    settings = load_settings()
    settings.ollama.max_retries = 0
    r = build_runtime(settings)
    yield r
    r.close()


def _use(rt, fake_ollama, name: str) -> None:
    fake_ollama.chat_replies = [good_answer("Bu madde, kiracının depozitoyu geri alma hakkını anlatır.")]
    task = rt.orchestrator.ask("Bu sözleşme maddesini sade dille açıkla.", worker=name)
    assert task.status.value == "succeeded"


# ---------------------------------------------------------------- oluşturma

def test_create_temporary_inherits_from_base_and_is_reviewed(rt, tmp_path):
    d = create_temporary(rt, LEGAL, created_by="owner")
    assert d.status == "temporary" and d.base == "document" and d.created_by == "owner"
    assert d.local_model == "general-8b" and d.claude_tier == "haiku" and d.permissions == ["llm.inference"]
    assert d.review.required and d.review.reviewer == "reviewer"
    assert "legal" in rt.workers.names() and "legal.revise" in rt.workers.internal_names()
    saved = yaml.safe_load((tmp_path / "agents" / "legal.yaml").read_text(encoding="utf-8"))
    assert saved["status"] == "temporary" and saved["role"].startswith("You explain")
    assert any(e["type"] == "agent.created" for e in rt.store.events_since(0))


@pytest.mark.parametrize("over,err", [
    ({"name": "coder"}, "zaten var"),
    ({"base": "planner"}, "temel alınamaz"),
    ({"base": "reviewer"}, "temel alınamaz"),
    ({"base": "yok"}, "bulunamadı"),
])
def test_create_rejects_bad_proposals(rt, over, err):
    with pytest.raises(AgentLifecycleError, match=err):
        create_temporary(rt, LEGAL.model_copy(update=over), created_by="owner")


def test_bad_name_is_rejected_by_schema():
    with pytest.raises(ValueError):
        AgentProposal(name="../evil", description="x" * 5, role="y" * 20, base="general")


def test_temporary_cannot_be_based_on_temporary_and_cap_is_enforced(rt):
    create_temporary(rt, LEGAL, created_by="owner")
    with pytest.raises(AgentLifecycleError, match="geçici ajana dayanamaz"):
        create_temporary(rt, LEGAL.model_copy(update={"name": "legal2", "base": "legal"}), created_by="owner")
    rt.settings.conductor.max_temp_agents = 1
    with pytest.raises(AgentLifecycleError, match="En fazla 1"):
        create_temporary(rt, LEGAL.model_copy(update={"name": "legal2"}), created_by="owner")


def test_permission_ceiling(rt):
    rich = AgentDefinition(name="reader", description="okur", local_model="general-8b",
                           permissions=["llm.inference", "fs.read"],
                           review={"required": True, "reviewer": "reviewer"})
    register_definition(rt.workers, rich)
    from_planner = create_temporary(rt, LEGAL.model_copy(update={"name": "p1", "base": "reader"}),
                                    created_by="planner", ceiling={"llm.inference"})
    assert from_planner.permissions == ["llm.inference"]  # yaratıcıdan fazla izin yok
    from_owner = create_temporary(rt, LEGAL.model_copy(update={"name": "p2", "base": "reader"}), created_by="owner")
    assert from_owner.permissions == ["llm.inference", "fs.read"]  # base'den fazla da yok
    with pytest.raises(AgentLifecycleError, match="izinleri"):
        create_temporary(rt, LEGAL.model_copy(update={"name": "p3", "base": "reader"}), created_by="planner",
                         ceiling={"fs.read"})


# ---------------------------------------------------------------- senkron (süreçler arası)

def test_sync_picks_up_other_process_files_and_skips_broken(rt, tmp_path):
    folder = tmp_path / "agents"
    folder.mkdir(exist_ok=True)
    (folder / "bozuk.yaml").write_text("name: [", encoding="utf-8")
    (folder / "coder.yaml").write_text(yaml.safe_dump({"name": "coder", "description": "x",
                                                       "local_model": "general-8b"}), encoding="utf-8")
    (folder / "ceviri.yaml").write_text(yaml.safe_dump({
        "name": "ceviri", "description": "çeviri", "local_model": "general-8b", "status": "temporary",
        "base": "general", "created_by": "claude", "review": {"required": True, "reviewer": "reviewer"}}),
        encoding="utf-8")
    warnings = sync_user_agents(rt)
    assert "ceviri" in rt.workers.names()
    assert any("bozuk.yaml" in w for w in warnings) and any("repo ajanı" in w for w in warnings)
    assert rt.workers.get("coder").definition.local_model == "coder-7b"  # repo ajanı ezilmedi
    (folder / "ceviri.yaml").unlink()
    sync_user_agents(rt)
    assert "ceviri" not in rt.workers and "ceviri.revise" not in rt.workers


# ---------------------------------------------------------------- kalıcı yapma

def test_promotion_requires_success_and_owner_approval(rt, fake_ollama, tmp_path):
    create_temporary(rt, LEGAL, created_by="claude")
    with pytest.raises(AgentLifecycleError, match="denenmeli"):
        request_promotion(rt, "legal", requested_by="cli")
    _use(rt, fake_ollama, "legal")
    assert usage(rt, "legal") == (1, 1)
    res = request_promotion(rt, "legal", requested_by="api")
    assert res.status == "awaiting_approval" and res.risk.value == "R2"
    a = rt.permissions.get(res.approval_id)
    assert "status: permanent" in a.action.preview["new_head"] and a.action.preview["successes"] == 1
    assert rt.workers.get("legal").definition.status == "temporary"  # onaysız değişmez
    assert "legal" not in [d.name for d in claude_definitions(rt)]
    done = rt.permissions.approve(res.approval_id, decided_by="cli")
    assert done.status == "approved" and done.result["status"] == "permanent"
    assert yaml.safe_load((tmp_path / "agents" / "legal.yaml").read_text(encoding="utf-8"))["status"] == "permanent"
    assert rt.workers.get("legal").definition.status == "permanent"
    assert "legal" in [d.name for d in claude_definitions(rt)]
    assert any(e["type"] == "agent.promoted" for e in rt.store.events_since(0))
    with pytest.raises(AgentLifecycleError, match="zaten kalıcı"):
        request_promotion(rt, "legal", requested_by="cli")
    with pytest.raises(AgentLifecycleError, match="kalıcı bir ajan"):
        remove_temporary(rt, "legal")


def test_remove_temporary_only(rt, tmp_path):
    create_temporary(rt, LEGAL, created_by="owner")
    remove_temporary(rt, "legal")
    assert not (tmp_path / "agents" / "legal.yaml").exists() and "legal" not in rt.workers
    with pytest.raises(AgentLifecycleError, match="sonradan oluşturulmuş"):
        remove_temporary(rt, "coder")


# ---------------------------------------------------------------- planlayıcı

def test_validate_plan_new_agent_rules():
    agents = {"general", "document", "planner", "reviewer"}
    na = {"name": "legal", "description": "hukuk", "role": "You explain legal texts.", "base": "document"}
    plan = RoutePlan.model_validate({"mode": "direct", "agent": "legal", "new_agent": na})
    assert validate_plan(plan, agents, allow_new_agent=True) == []
    assert any("kullanılamaz" in e for e in validate_plan(plan, agents, allow_new_agent=False))
    taken = RoutePlan.model_validate({"mode": "direct", "agent": "general", "new_agent": {**na, "name": "general"}})
    assert any("zaten var" in e for e in validate_plan(taken, agents, allow_new_agent=True))
    bad_base = RoutePlan.model_validate({"mode": "direct", "agent": "legal", "new_agent": {**na, "base": "planner"}})
    assert any("base" in e for e in validate_plan(bad_base, agents, allow_new_agent=True))


def _plan_with_new_agent() -> str:
    return json.dumps({"mode": "direct", "agent": "legal", "steps": [], "needs_claude": False, "claude_reason": "",
                       "key_topics": [], "new_agent": {"name": "legal", "description": "Hukuk metinlerini açıklar",
                                                       "role": "You explain legal texts in plain language.",
                                                       "base": "document"}})


def test_planner_creates_and_uses_temporary_agent(rt, fake_ollama):
    s = Script(planner=[_plan_with_new_agent()], answers=[answer("Bu madde depozitonun iadesini düzenler.")])
    fake_ollama.chat_replies = [s] * 20
    res = Conductor(rt).run("Bu kira sözleşmesi maddesini sade dille açıkla: depozito iadesi.")
    assert res.status == "succeeded" and res.steps[0].agent == "legal"
    assert res.steps[0].review is not None  # geçici ajan her zaman gözden geçirilir
    d = rt.workers.get("legal").definition
    assert d.created_by == "planner" and d.status == "temporary"
    assert any("geçici ajan" in w.lower() for w in res.warnings)
    assert '"allow_new_agent": true' in s.user_messages["RoutePlan"][0]


def test_planner_proposal_falls_back_to_base_when_creation_fails(rt, fake_ollama, monkeypatch):
    import kayaai.agents.lifecycle as lc

    def boom(*a, **k):
        raise lc.AgentLifecycleError("disk dolu")
    monkeypatch.setattr(lc, "create_temporary", boom)
    s = Script(planner=[_plan_with_new_agent()], answers=[answer("Bu madde depozitonun iadesini düzenler.")])
    fake_ollama.chat_replies = [s] * 20
    res = Conductor(rt).run("Bu kira sözleşmesi maddesini sade dille açıkla: depozito iadesi.")
    assert res.status == "succeeded" and res.steps[0].agent == "document"
    assert any("oluşturulamadı" in w for w in res.warnings)


def test_new_agents_not_offered_when_disabled_or_full(rt, fake_ollama):
    rt.settings.conductor.allow_temp_agents = False
    s = Script(planner=[json.dumps({"mode": "direct", "agent": "general", "steps": [], "needs_claude": False,
                                    "claude_reason": "", "key_topics": []})], answers=[answer("Merhaba!")])
    fake_ollama.chat_replies = [s] * 20
    Conductor(rt).run("Merhaba nasılsın?")
    assert '"allow_new_agent": false' in s.user_messages["RoutePlan"][0]


# ---------------------------------------------------------------- API / MCP

def test_api_lifecycle(rt, fake_ollama):
    create_temporary(rt, LEGAL, created_by="owner")
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        agents = {a["name"]: a for a in c.get("/api/agents").json()}
        assert agents["legal"]["lifecycle"] == "temporary" and agents["legal"]["base"] == "document"
        assert agents["legal"]["uses"] == 0 and agents["coder"]["lifecycle"] == "permanent"
        assert agents["coder"]["uses"] is None
        assert c.post("/api/agents/legal/promote").status_code == 409  # denenmedi
        _use(rt, fake_ollama, "legal")
        r = c.post("/api/agents/legal/promote")
        assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
        assert c.post("/api/agents/coder/remove").status_code == 409
        assert c.post("/api/agents/legal/remove").status_code == 200


def test_mcp_propose(fake_ollama, tmp_path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    settings = load_settings()

    async def go():
        async with Client(create_server(settings)) as c:
            ok = await c.call_tool("kayaai_agent_propose", LEGAL.model_dump())
            dup = await c.call_tool("kayaai_agent_propose", LEGAL.model_dump())
            listed = await c.call_tool("kayaai_list_agents", {})
            internal = await c.call_tool("kayaai_ask", {"question": "x", "worker": "legal.revise"})
            return ok, dup, listed, internal

    ok, dup, listed, internal = asyncio.run(go())
    assert not ok.is_error and ok.structured_content["status"] == "temporary"
    assert ok.structured_content["base"] == "document"
    assert dup.is_error
    assert any(a["name"] == "legal" and a["status"] == "temporary" for a in listed.structured_content["agents"])
    assert internal.is_error  # iç yardımcılar dışarıdan çağrılamaz
    saved = yaml.safe_load((tmp_path / "agents" / "legal.yaml").read_text(encoding="utf-8"))
    assert saved["created_by"] == "claude"


def test_cli_agents_new_promote_remove(fake_ollama, tmp_path, monkeypatch, capsys):
    from kayaai import cli

    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    assert cli.main(["agents", "new", "legal"]) == 2
    assert cli.main(["agents", "new", "legal", "--base", "document", "--description", "Hukuk metni açıklar",
                     "--role", "You explain legal texts in plain language."]) == 0
    assert "Geçici ajan oluşturuldu: legal" in capsys.readouterr().out
    assert cli.main(["agents"]) == 0
    out = capsys.readouterr().out
    assert "GEÇİCİ, temel: document, oluşturan: owner, kullanım: 0/0" in out and "gözden geçiren: reviewer" in out
    assert cli.main(["agents", "promote", "legal"]) == 1 and "denenmeli" in capsys.readouterr().out
    assert cli.main(["agents", "remove", "legal"]) == 0
    assert not (tmp_path / "agents" / "legal.yaml").exists()
