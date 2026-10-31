"""Adım 3b: ajan tanımları (config/agents/*.yaml)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kayaai.agents.definitions import AgentDefinitionError, build_workers, load_definitions
from kayaai.config import PROJECT_ROOT, OrchestratorSettings
from kayaai.core.task import TaskStatus
from kayaai.llm.registry import ModelRegistry
from kayaai.workers import default_workers

from .conftest import good_answer


@pytest.fixture
def reg2() -> ModelRegistry:
    return ModelRegistry.from_dict(
        {
            "models": {
                "general-8b": {"name": "qwen3:8b", "context_length": 4096, "think": False},
                "coder-7b": {"name": "qwen2.5-coder:7b", "status": "candidate"},
            },
            "workers": {"general": "general-8b"},
        }
    )


def _write(d: Path, name: str, body: str) -> None:
    (d / f"{name}.yaml").write_text(body, encoding="utf-8")


def test_project_agents_load():
    reg = ModelRegistry.load(PROJECT_ROOT / "config" / "models.yaml")
    defs = {d.name: d for d in load_definitions(PROJECT_ROOT / "config" / "agents", reg)}
    assert {"general", "reviewer", "coder"} <= set(defs)
    assert defs["reviewer"].output == "review"
    workers = default_workers(reg, PROJECT_ROOT / "config" / "agents")
    assert workers.get("coder").model_spec(reg).name == "qwen2.5-coder:7b"


@pytest.mark.parametrize(
    "body,match",
    [
        ("name: other\ndescription: x\nlocal_model: general-8b\n", "dosya adıyla"),
        ("name: a1\ndescription: x\nlocal_model: yok\n", "kayıtlı değil"),
        ("name: a1\ndescription: x\nlocal_model: coder-7b\n", "aday model"),
        ("name: a1\ndescription: x\nlocal_model: general-8b\npermissions: [root]\n", "bilinmeyen izin"),
        ("name: a1\ndescription: x\nlocal_model: general-8b\noutput: poem\n", "output"),
        ("name: a1\ndescription: x\n", "local_model"),
        ("name: [bozuk\n", "a1.yaml"),
    ],
)
def test_invalid_definitions_rejected(tmp_path: Path, reg2, body, match):
    _write(tmp_path, "a1", body)
    with pytest.raises(AgentDefinitionError, match=match):
        load_definitions(tmp_path, reg2)


def test_defined_agent_uses_its_model_role_and_timeout(tmp_path: Path, reg2, store, client, fake_ollama):
    _write(tmp_path, "translator", (
        "name: translator\ndescription: çevirmen\nlocal_model: general-8b\n"
        "role: You are a careful translator.\nlimits:\n  timeout_s: 42\n"
    ))
    from kayaai.core.orchestrator import Orchestrator

    workers = build_workers(tmp_path, reg2)
    orch = Orchestrator(store, workers, client, reg2, OrchestratorSettings())
    fake_ollama.chat_replies = [good_answer("Good morning.", language="en", task_type="translation")]
    task = orch.ask("Translate to English: Günaydın", worker="translator")
    assert task.status == TaskStatus.SUCCEEDED, task.error
    assert task.timeout_s == 42
    body = fake_ollama.chat_paths()[0]
    assert body["model"] == "qwen3:8b"
    assert body["messages"][0]["content"].startswith("You are a careful translator.")


def test_reviewer_flow_and_validation(store, client, fake_ollama):
    reg = ModelRegistry.load(PROJECT_ROOT / "config" / "models.yaml")
    from kayaai.core.orchestrator import Orchestrator

    orch = Orchestrator(store, default_workers(reg, PROJECT_ROOT / "config" / "agents"), client, reg,
                        OrchestratorSettings(max_output_attempts=2))
    bad = json.dumps({"verdict": "issues", "issues": [], "suggestion": ""})
    good = json.dumps({"verdict": "issues", "issues": ["Cevap Türkçe değil"], "suggestion": "Türkçe yaz"})
    fake_ollama.chat_replies = [bad, good]
    task = orch.ask("Bu cevabı kontrol et", worker="reviewer",
                    input={"request": "Başkent?", "answer": "The capital is Ankara."})
    assert task.status == TaskStatus.SUCCEEDED, task.error
    assert task.result["issues"] == ["Cevap Türkçe değil"]
    assert task.metrics["validation_retries"] == 1
    assert fake_ollama.chat_paths()[0]["format"]["title"] == "ReviewResult"
