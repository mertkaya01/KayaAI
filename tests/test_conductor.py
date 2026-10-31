"""Adım 3c: yerel şef (planlayıcı + yürütme + birleştirme + gözden geçirme + Claude yönlendirmesi)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from kayaai.conductor import Conductor
from kayaai.config import load_settings
from kayaai.core.task import TaskStatus
from kayaai.mcp_server import create_server
from kayaai.runtime import build_runtime
from kayaai.workers.planner import RoutePlan, validate_plan

from .conductor_helpers import Script, answer, plan_direct, plan_steps, review


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4_700_000_000})
    settings = load_settings()
    settings.ollama.max_retries = 0
    r = build_runtime(settings)
    yield r
    r.close()


def run(rt, fake_ollama, script: Script, request: str, **kw):
    fake_ollama.chat_replies = [script] * 50
    return Conductor(rt).run(request, **kw)


# ---------------------------------------------------------------- planlayıcı doğrulaması

AGENTS = {"general", "coder", "planner", "reviewer"}


@pytest.mark.parametrize("plan,err", [
    (RoutePlan(mode="direct"), "agent"),
    (RoutePlan(mode="direct", agent="hacker"), "bilinmeyen"),
    (RoutePlan(mode="direct", agent="planner"), "kullanılamaz"),
    (RoutePlan(mode="plan", steps=[]), "1-4"),
    (RoutePlan.model_validate({"mode": "plan", "steps": [
        {"id": "s1", "agent": "general", "objective": "a", "depends_on": ["s2"]},
        {"id": "s2", "agent": "general", "objective": "b"}]}), "daha önceki"),
    (RoutePlan.model_validate({"mode": "plan", "steps": [
        {"id": "s1", "agent": "reviewer", "objective": "a"}]}), "kullanılamaz"),
    (RoutePlan.model_validate({"mode": "plan", "steps": [
        {"id": f"s{i}", "agent": "general", "objective": "x"} for i in range(5)]}), "1-4"),
    (RoutePlan(mode="direct", agent="general", needs_claude=True), "claude_reason"),
])
def test_validate_plan_errors(plan, err):
    assert any(err in e for e in validate_plan(plan, AGENTS))


def test_validate_plan_ok():
    p = RoutePlan.model_validate({"mode": "plan", "steps": [
        {"id": "s1", "agent": "coder", "objective": "kod"},
        {"id": "s2", "agent": "general", "objective": "açıkla", "depends_on": ["s1"]}]})
    assert validate_plan(p, AGENTS) == []


# ---------------------------------------------------------------- akışlar

def test_direct_request_single_agent_no_review(rt, fake_ollama):
    s = Script(planner=[plan_direct("general")], answers=[answer("Ankara.")])
    res = run(rt, fake_ollama, s, "Türkiye'nin başkenti neresi?")
    assert res.status == "succeeded" and res.answer == "Ankara."
    assert res.mode == "direct" and [st.agent for st in res.steps] == ["general"]
    assert not res.review.performed
    assert s.calls["ReviewResult"] == 0
    job = rt.store.get(res.job_id)
    assert job.worker == "conductor" and job.status == TaskStatus.SUCCEEDED
    children = [t for t in rt.store.list_tasks(50) if t.parent_id == res.job_id]
    assert {t.worker for t in children} == {"planner", "general"}


def test_direct_to_coder_uses_coder_model(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer("```python\nprint(1)\n```")])
    res = run(rt, fake_ollama, s, "Bana 1 yazdıran Python kodu yaz")
    assert res.status == "succeeded"
    assert "qwen2.5-coder:7b" in s.models_used


def test_plan_runs_in_order_passes_results_merges_and_reviews(rt, fake_ollama):
    s = Script(
        planner=[plan_steps([("s1", "coder", "Kodu yaz", []), ("s2", "general", "Kodu açıkla", ["s1"])])],
        answers=[answer("KOD"), answer("AÇIKLAMA"), answer("NİHAİ CEVAP")],
        reviews=[review("ok")],
    )
    res = run(rt, fake_ollama, s, "Bir Python fonksiyonu yaz ve ne yaptığını açıkla")
    assert res.status == "succeeded" and res.answer == "NİHAİ CEVAP"
    assert res.mode == "plan" and [st.status for st in res.steps] == ["succeeded", "succeeded"]
    # s2, s1'in sonucunu input_data içinde görmeli
    s2_user = s.user_messages["GeneralAnswer"][1]
    assert "previous_results" in s2_user and "KOD" in s2_user
    # birleştirme adımı tüm sonuçları görmeli
    merge_user = s.user_messages["GeneralAnswer"][2]
    assert "step_results" in merge_user and "AÇIKLAMA" in merge_user
    assert res.review.performed and res.review.verdict == "ok" and not res.review.revised


def test_review_issues_trigger_one_revision(rt, fake_ollama):
    s = Script(
        planner=[plan_steps([("s1", "general", "a", []), ("s2", "general", "b", ["s1"])])],
        answers=[answer("A"), answer("B"), answer("İLK"), answer("DÜZELTİLMİŞ")],
        reviews=[review("issues", ["eksik"]), review("ok")],
    )
    res = run(rt, fake_ollama, s, "İki parçalı bir iş yap")
    assert res.answer == "DÜZELTİLMİŞ" and res.review.revised and res.review.verdict == "ok"
    assert "reviewer_issues" in s.user_messages["GeneralAnswer"][3]
    assert not res.warnings


def test_review_still_issues_after_revision_warns(rt, fake_ollama):
    s = Script(
        planner=[plan_steps([("s1", "general", "a", []), ("s2", "general", "b", [])])],
        answers=[answer("A"), answer("B"), answer("İLK"), answer("İKİNCİ")],
        reviews=[review("issues", ["yanlış"]), review("issues", ["hâlâ yanlış"])],
    )
    res = run(rt, fake_ollama, s, "İki parçalı bir iş yap")
    assert res.status == "succeeded" and res.answer == "İKİNCİ"
    assert any("hâlâ sorun" in w for w in res.warnings)


def test_reviewer_failure_returns_answer_with_warning(rt, fake_ollama):
    s = Script(
        planner=[plan_steps([("s1", "general", "a", []), ("s2", "general", "b", [])])],
        answers=[answer("A"), answer("B"), answer("NİHAİ")],
        reviews=["bozuk"] * 3,
    )
    res = run(rt, fake_ollama, s, "İki parçalı bir iş yap")
    assert res.status == "succeeded" and res.answer == "NİHAİ"
    assert any("Gözden geçirme yapılamadı" in w for w in res.warnings)


def test_failed_step_skips_dependents(rt, fake_ollama):
    s = Script(
        planner=[plan_steps([("s1", "general", "a", []), ("s2", "general", "b", ["s1"]), ("s3", "general", "c", [])])],
        answers=["bozuk"] * 3 + [answer("C"), answer("NİHAİ")],
        reviews=[review("ok")],
    )
    res = run(rt, fake_ollama, s, "Üç parçalı iş")
    st = {x.id: x for x in res.steps}
    assert st["s1"].status == "failed" and st["s2"].status == "failed" and "bağımlılık" in st["s2"].error
    assert st["s3"].status == "succeeded"
    assert res.status == "succeeded" and any("adım başarısız" in w for w in res.warnings)


def test_invalid_plan_falls_back_to_general(rt, fake_ollama):
    bad = plan_direct("hacker")
    s = Script(planner=[bad] * 3, answers=[answer("Genel cevap.")])
    res = run(rt, fake_ollama, s, "Bir şey sor")
    assert res.status == "succeeded" and res.answer == "Genel cevap."
    assert any("Plan yapılamadı" in w for w in res.warnings)
    # planlayıcıya hata geri bildirildi
    assert "bilinmeyen" in s.user_messages["RoutePlan"][1]


def test_nothing_succeeds_is_failed_not_success(rt, fake_ollama):
    s = Script(planner=[plan_direct("general")], answers=["bozuk"] * 3)
    res = run(rt, fake_ollama, s, "Bir şey sor")
    assert res.status == "failed" and res.error
    assert rt.store.get(res.job_id).status == TaskStatus.FAILED


# ---------------------------------------------------------------- Claude yönlendirmesi (D15/D16)

def _needs_claude():
    return plan_direct("general", needs_claude=True, reason="karmaşık mimari")


def test_needs_claude_but_off_runs_local_with_warning(rt, fake_ollama):
    s = Script(planner=[_needs_claude()], answers=[answer("Yerel cevap.")])
    res = run(rt, fake_ollama, s, "Büyük bir dağıtık sistem mimarisi tasarla")
    assert res.status == "succeeded" and res.routing.decision == "local_with_warning"
    assert any("Claude ile muhtemelen daha iyi" in w for w in res.warnings)


def test_needs_claude_and_on_goes_to_inbox(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[_needs_claude()], answers=[])
    res = run(rt, fake_ollama, s, "Büyük bir dağıtık sistem mimarisi tasarla")
    assert res.status == "waiting_claude" and res.routing.decision == "claude_inbox"
    assert s.calls["GeneralAnswer"] == 0  # yerelde çalıştırılmadı
    assert rt.store.get(res.job_id).status == TaskStatus.WAITING_CLAUDE
    assert rt.claude.status().waiting_tasks == 1
    events = [e["event"] for e in rt.store.events(res.job_id)]
    assert "routing.decision" in events


def test_claude_on_but_not_needed_stays_local(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("general")], answers=[answer("Yerel.")])
    res = run(rt, fake_ollama, s, "Merhaba")
    assert res.status == "succeeded" and res.routing.decision == "local"


def test_force_local_and_force_claude(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[_needs_claude()], answers=[answer("Yerel.")])
    res = run(rt, fake_ollama, s, "Zor iş", force="local")
    assert res.status == "succeeded" and res.routing.decision == "local_with_warning"
    s2 = Script(planner=[plan_direct("general")], answers=[])
    res2 = run(rt, fake_ollama, s2, "Kolay iş", force="claude")
    assert res2.status == "waiting_claude"


def test_origin_claude_never_goes_to_inbox(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[_needs_claude()], answers=[answer("Yerel.")])
    res = run(rt, fake_ollama, s, "Zor iş", origin="claude")
    assert res.status == "succeeded" and res.routing.decision == "local"


def test_local_failure_escalates_to_inbox_when_claude_on(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("general")], answers=["bozuk"] * 3)
    res = run(rt, fake_ollama, s, "Bir şey")
    assert res.status == "waiting_claude" and "yerel sonuç üretilemedi" in res.routing.why


# ---------------------------------------------------------------- arayüzler

def test_mcp_kayaai_do(rt, fake_ollama):
    s = Script(planner=[plan_direct("general")], answers=[answer("MCP üzerinden cevap.")])
    fake_ollama.chat_replies = [s] * 20

    async def go():
        async with Client(create_server(rt.settings, runtime=rt)) as c:
            return await c.call_tool("kayaai_do", {"request": "Merhaba, nasılsın?"})

    r = asyncio.run(go())
    assert not r.is_error, r.content
    assert r.structured_content["answer"] == "MCP üzerinden cevap."
    assert r.structured_content["routing"]["decision"] == "local"


def test_cli_do_subprocess(fake_ollama, tmp_path: Path):
    import os
    import subprocess
    import sys

    from kayaai.config import PROJECT_ROOT

    s = Script(planner=[plan_direct("general")], answers=[answer("Komut satırından cevap.")])
    fake_ollama.chat_replies = [s] * 10
    env = dict(os.environ, KAYAAI_OLLAMA_URL=fake_ollama.url, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-m", "kayaai", "do", "Merhaba", "dünya"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Komut satırından cevap." in r.stdout and "yönlendirme: local" in r.stdout
