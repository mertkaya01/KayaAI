"""Adım 7a/7b: üretici → gözden geçirici akışı, deterministik kontroller, revizyon ve anlaşmazlık yükseltmesi."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kayaai.agents.definitions import AgentDefinitionError, build_workers
from kayaai.conductor import Conductor
from kayaai.conductor.checks import run_checks
from kayaai.conductor.inbox import ClaudeInbox
from kayaai.config import load_settings
from kayaai.core.disputes import DisputeError
from kayaai.core.task import Task
from kayaai.llm.registry import ModelRegistry
from kayaai.runtime import build_runtime
from kayaai.workers.step_review import Revision, RevisionWorker, evidence_in

from .conductor_helpers import Script, answer, plan_direct, revision, step_review

GOOD_CODE = "Fonksiyon şöyle çalışır:\n\n```python\ndef topla(a, b):\n    return a + b\n```\n\nİki sayıyı toplar."
BAD_CODE = "Fonksiyon şöyle çalışır:\n\n```python\ndef topla(a, b:\n    return a + b\n```\n\nİki sayıyı toplar."
REQUEST = "Python'da iki sayıyı toplayan bir fonksiyon yaz ve kısaca açıkla."


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


def run(rt, fake_ollama, script: Script, request: str = REQUEST, **kw):
    fake_ollama.chat_replies = [script] * 50
    return Conductor(rt).run(request, **kw)


# ---------------------------------------------------------------- deterministik kontroller

def test_run_checks_parses_but_never_executes():
    text = ("```python\nimport os\nos.remove('x')\n```\n```json\n{\"a\": 1,}\n```\n"
            "```yaml\na: [1, 2\n```\n```javascript\nconst x = ;\n```\n```python\n>>> 1 +\n```")
    rep = run_checks(text, ["code_syntax"])
    assert rep.checked_blocks == 3 and rep.skipped_blocks == 2 and rep.skipped_languages == ["javascript", "python"]
    assert [f.language for f in rep.failures] == ["json", "yaml"]  # geçerli Python çalıştırılmadan geçti
    assert run_checks(BAD_CODE, ["code_syntax"]).failures[0].message.startswith("1. kod bloğu: Python sözdizimi hatası")
    assert run_checks(BAD_CODE, []).failures == []


def test_evidence_matching_is_whitespace_and_case_insensitive():
    assert evidence_in("def  TOPLA(a, b:", BAD_CODE)
    assert evidence_in("“return a + b”", BAD_CODE)
    assert not evidence_in("return a - b", BAD_CODE)
    assert not evidence_in("a", BAD_CODE)  # çok kısa alıntı kanıt sayılmaz


def test_revision_validation_requires_every_issue_and_no_fact_disputes():
    w = RevisionWorker()
    task = Task(worker="coder.revise", objective="Fonksiyonu düzelt.",
                input={"issues": [{"id": "c1"}, {"id": "i1"}]})
    ok = Revision(answer="Düzeltilmiş fonksiyon şöyle çalışır.", language="tr", accepted=["c1"],
                  disputed=[{"id": "i1", "reason": "Gözden geçirici yanılıyor."}])
    assert w.validate(task, ok).passed
    bad = Revision(answer="Düzeltilmiş fonksiyon şöyle.", language="tr", accepted=["i1"],
                   disputed=[{"id": "c1", "reason": "hata yok"}])
    errors = " ".join(w.validate(task, bad).errors)
    assert "itiraz edilemez" in errors
    missing = Revision(answer="Düzeltilmiş fonksiyon şöyle.", language="tr", accepted=["c1", "x9"])
    errors = " ".join(w.validate(task, missing).errors)
    assert "bilinmeyen" in errors and "i1" in errors


# ---------------------------------------------------------------- tanımlar

def test_internal_workers_are_hidden(rt):
    names = rt.workers.names()
    assert {"coder", "data", "document", "reviewer"} <= set(names)
    assert not any("." in n for n in names)
    assert {"coder.revise", "data.revise", "document.revise", "reviewer.check"} <= set(rt.workers.internal_names())
    assert "coder.revise" in rt.workers  # orkestratör yine de çalıştırabilir


def test_review_link_must_point_to_review_agent(tmp_path):
    reg = ModelRegistry.load(load_settings().models_file)
    d = tmp_path / "agents"
    d.mkdir()
    (d / "yazar.yaml").write_text(yaml.safe_dump({
        "name": "yazar", "description": "x", "local_model": "general-8b",
        "review": {"required": True, "reviewer": "yok"}}), encoding="utf-8")
    with pytest.raises(AgentDefinitionError, match="gözden geçirici 'yok'"):
        build_workers(d, reg)


# ---------------------------------------------------------------- akışlar

def test_approved_answer_is_not_revised(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)], step_reviews=[step_review()])
    res = run(rt, fake_ollama, s)
    st = res.steps[0]
    assert res.status == "succeeded" and res.answer == GOOD_CODE
    assert st.review and st.review.verdict == "approve" and st.review.checks.checked_blocks == 1
    assert not st.review.revised and s.calls["Revision"] == 0 and s.calls["StepReview"] == 1


def test_general_agent_is_not_reviewed(rt, fake_ollama):
    s = Script(planner=[plan_direct("general")], answers=[answer("Merhaba!")])
    res = run(rt, fake_ollama, s, "Merhaba nasılsın?")
    assert res.steps[0].review is None and s.calls["StepReview"] == 0


def test_syntax_error_is_fixed_by_producer(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)],
               step_reviews=[step_review()], revisions=[revision(GOOD_CODE, accepted=["c1"])])
    res = run(rt, fake_ollama, s)
    st = res.steps[0]
    assert res.status == "succeeded" and res.answer == GOOD_CODE
    assert st.review.revised and st.review.accepted == ["c1"] and st.review.unresolved_checks == []
    assert len(st.review.checks.failures) == 1
    # revizyon girdisinde kontrol hatası kanıt olarak gitti ve coder modeliyle çalıştı
    assert "Python sözdizimi hatası" in s.user_messages["Revision"][0]
    assert "qwen2.5-coder:7b" in s.models_used


def test_unfixed_syntax_error_is_reported(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)],
               revisions=[revision(BAD_CODE, accepted=["c1"])])
    res = run(rt, fake_ollama, s)
    assert res.steps[0].review.unresolved_checks
    assert any("doğrulanamadı" in w for w in res.warnings)


def test_issue_without_evidence_is_dropped(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("blocker", "Sonsuz döngü var", "while True: pass")])])
    res = run(rt, fake_ollama, s)
    st = res.steps[0]
    assert st.review.dropped_issues == 1 and st.review.verdict == "approve" and st.review.issues == []
    assert s.calls["Revision"] == 0 and res.answer == GOOD_CODE


def test_minor_issue_does_not_trigger_revision(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("minor", "Tip ipucu eklenebilir", "def topla(a, b)")])])
    res = run(rt, fake_ollama, s)
    assert s.calls["Revision"] == 0 and res.steps[0].review.issues == ["minor: Tip ipucu eklenebilir"]


def test_dispute_with_claude_off_goes_to_owner(rt, fake_ollama):
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Toplama yerine çıkarma yapıyor", "return a + b")])],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Kod a + b döndürüyor, bu toplamadır.")])])
    res = run(rt, fake_ollama, s)
    assert res.status == "succeeded" and res.answer == GOOD_CODE
    assert any("kayaai disputes" in w for w in res.warnings)
    [d] = rt.disputes.list(status="open")
    assert d.job_id == res.job_id and d.producer == "coder" and d.reviewer == "reviewer"
    assert d.escalated_to == "owner" and "çıkarma" in d.issue and "toplamadır" in d.producer_position
    assert res.steps[0].review.disputes == [d.id]
    types = [e["type"] for e in rt.store.events_since(0, 500)]
    assert "dispute.opened" in types and "decision.summary" in types
    # sahip karar verir; ikinci karar reddedilir
    r = rt.disputes.resolve(d.id, "producer", "cli", "coder haklı")
    assert r.status == "resolved" and r.resolution == "producer" and r.note == "coder haklı"
    with pytest.raises(DisputeError):
        rt.disputes.resolve(d.id, "reviewer", "cli")


def test_dispute_with_claude_on_goes_to_inbox(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Toplama yerine çıkarma yapıyor", "return a + b")])],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Kod toplama yapıyor.")])])
    res = run(rt, fake_ollama, s)
    assert res.status == "waiting_claude" and res.routing.decision == "claude_inbox"
    inbox = ClaudeInbox(rt)
    [item] = inbox.items()
    assert item.job_id == res.job_id and item.local_draft == GOOD_CODE
    assert item.disputes[0]["producer_position"] == "Kod toplama yapıyor."
    done = inbox.complete(res.job_id, "Claude kararı: kod doğru.", "coder haklı")
    assert done.status == "succeeded"
    [d] = rt.disputes.list()
    assert d.status == "resolved" and d.resolution == "claude" and d.escalated_to == "claude"


def test_dispute_owner_policy_ignores_claude(rt, fake_ollama):
    rt.claude.enable()
    rt.settings.conductor.disputes = "owner"
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Hatalı", "return a + b")])],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Hata yok.")])])
    res = run(rt, fake_ollama, s)
    assert res.status == "succeeded" and rt.disputes.list()[0].escalated_to == "owner"


def test_dispute_from_claude_origin_returns_to_caller(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Hatalı", "return a + b")])],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Hata yok.")])])
    res = run(rt, fake_ollama, s, origin="claude")
    assert res.status == "succeeded"
    assert any("karar senin" in w for w in res.warnings)
    assert rt.disputes.list()[0].escalated_to == "claude"


def test_release_supersedes_old_disputes(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("coder"), plan_direct("coder")], answers=[answer(GOOD_CODE), answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Hatalı", "return a + b")]), step_review()],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Hata yok.")])])
    res = run(rt, fake_ollama, s)
    assert res.status == "waiting_claude"
    again = ClaudeInbox(rt).release(res.job_id)
    assert again.status == "succeeded"
    [d] = rt.disputes.list()
    assert d.resolution == "superseded"


def test_disputing_a_check_failure_is_rejected(rt, fake_ollama):
    bad_rev = revision(BAD_CODE, disputed=[("c1", "Sözdizimi doğru.")])
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)], revisions=[bad_rev] * 3)
    res = run(rt, fake_ollama, s)
    assert rt.disputes.list() == []
    assert any("düzeltilemedi" in w for w in res.warnings)


def test_time_budget_skips_review(rt, fake_ollama, monkeypatch):
    from kayaai.conductor import conductor as mod
    monkeypatch.setattr(mod._Run, "over_budget", lambda self: True)
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)])
    res = run(rt, fake_ollama, s)
    assert res.steps[0].review.skipped == "zaman bütçesi doldu" and s.calls["StepReview"] == 0


def test_review_never_disables_step_reviews(rt, fake_ollama):
    rt.settings.conductor.review = "never"
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)])
    res = run(rt, fake_ollama, s)
    assert res.steps[0].review is None and s.calls["StepReview"] == 0


def test_agent_status_counts_internal_tasks(rt, fake_ollama):
    from kayaai.core.agent_status import agent_statuses
    s = Script(planner=[plan_direct("coder")], answers=[answer(BAD_CODE)],
               revisions=[revision(GOOD_CODE, accepted=["c1"])])
    run(rt, fake_ollama, s)
    st = {a.name: a for a in agent_statuses(rt.store, rt.workers.names())}
    assert st["coder"].state == "completed" and st["coder"].current_task.startswith(REQUEST[:20])
    assert st["reviewer"].state == "completed"
