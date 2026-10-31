"""Adım 11a: şef işinin akış grafiği (iş kaydı + alt görevler + olaylardan türetilir)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.api import create_app
from kayaai.conductor import Conductor
from kayaai.conductor.graph import build_graph, list_jobs
from kayaai.config import load_settings
from kayaai.core.task import Task, TaskStatus
from kayaai.runtime import build_runtime

from .conductor_helpers import Script, answer, plan_direct, plan_steps, review, revision, step_review

GOOD = "Fonksiyon şöyle:\n\n```python\ndef f(x):\n    return x\n```"
BAD = "Fonksiyon şöyle:\n\n```python\ndef f(x:\n    return x\n```"


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 1})
    s = load_settings()
    s.ollama.max_retries = 0
    r = build_runtime(s)
    yield r
    r.close()


def kinds(g):
    return [n.kind for n in g.nodes]


def test_direct_job_graph(rt, fake_ollama):
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Ankara.")])] * 5
    res = Conductor(rt).run("Türkiye'nin başkenti neresi?")
    g = build_graph(rt.store, res.job_id)
    assert kinds(g) == ["request", "planner", "step", "result"]
    assert all(n.status == "succeeded" for n in g.nodes)
    step = g.nodes[2]
    assert step.agent == "general" and step.model == "qwen3:8b" and step.task_id
    assert {(e.source, e.target) for e in g.edges} == {("request", "planner"), ("planner", "step-s1"), ("step-s1", "result")}


def test_plan_with_review_revision_and_final_check(rt, fake_ollama):
    s = Script(planner=[plan_steps([("s1", "coder", "Kodu yaz", []), ("s2", "general", "Açıkla", ["s1"])])],
               answers=[answer(BAD), answer("Bu kod x'i döndürür ve basittir.")],
               revisions=[revision(GOOD, accepted=["c1"])], reviews=[review("ok")])
    fake_ollama.chat_replies = [s] * 20
    res = Conductor(rt).run("Bir Python fonksiyonu yaz ve sonra yöneticiye açıkla.")
    g = build_graph(rt.store, res.job_id)
    assert kinds(g) == ["request", "planner", "step", "check", "revise", "step", "review", "result"]
    edges = {(e.source, e.target) for e in g.edges}
    assert ("step-s1", "check-s1") in edges and ("check-s1", "revise-s1") in edges
    assert ("revise-s1", "step-s2") in edges  # s2, s1'in son düğümüne bağlı
    assert ("step-s2", "tail-1") in edges and ("tail-1", "result") in edges
    coder = next(n for n in g.nodes if n.id == "step-s1")
    assert coder.review["revised"] and coder.model == "qwen2.5-coder:7b"
    assert g.mode == "plan" and g.status == "succeeded"


def test_graph_while_running_uses_plan_event(rt):
    job = Task(worker="conductor", objective="İki parçalı iş", status=TaskStatus.RUNNING)
    rt.store.save(job)
    rt.store.log_event(job.id, "plan.created", {"mode": "plan", "agent": None, "steps": [
        {"id": "s1", "agent": "coder", "objective": "Kod", "depends_on": []},
        {"id": "s2", "agent": "general", "objective": "Açıkla", "depends_on": ["s1"]}]})
    rt.store.save(Task(worker="planner", objective="İki parçalı iş", parent_id=job.id, status=TaskStatus.SUCCEEDED))
    rt.store.save(Task(worker="coder", objective="Kod", parent_id=job.id, status=TaskStatus.RUNNING))
    g = build_graph(rt.store, job.id)
    by = {n.id: n for n in g.nodes}
    assert by["planner"].status == "succeeded" and by["step-s1"].status == "running"
    assert by["step-s2"].status == "pending" and by["result"].status == "pending"


def test_claude_inbox_graph(rt, fake_ollama):
    rt.claude.enable()
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general", needs_claude=True, reason="karmaşık")],
                                       answers=[])] * 5
    res = Conductor(rt).run("Karmaşık bir mimari tasarla.")
    g = build_graph(rt.store, res.job_id)
    assert g.nodes[-1].kind == "claude" and g.nodes[-1].status == "waiting" and g.routing == "claude_inbox"


def test_list_jobs_and_api(rt, fake_ollama):
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Ankara.")])] * 5
    res = Conductor(rt).run("Türkiye'nin başkenti neresi?")
    assert list_jobs(rt.store)[0]["id"] == res.job_id
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as c:
        assert c.get("/api/jobs").status_code == 401
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        assert c.get("/api/jobs").json()[0]["id"] == res.job_id
        assert len(c.get(f"/api/jobs/{res.job_id}/graph").json()["nodes"]) == 4
        assert c.get("/api/jobs/yok/graph").status_code == 404
    with pytest.raises(KeyError):
        build_graph(rt.store, "yok")
