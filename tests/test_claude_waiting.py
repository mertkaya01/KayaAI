"""Claude kutusunda takılı kalma (sahip, 2026-11-02): Claude modu açık ama Claude Code oturumu bağlı değilken iş
kutuya bırakılmaz; kutuda süre aşan iş yerel ekibe verilir; Ofis'ten işi başlatan sohbete dönülür."""

from __future__ import annotations

from datetime import timedelta

from kayaai.conductor import ClaudeInbox, Conductor
from kayaai.conductor.graph import list_jobs
from kayaai.core.claude_mode import KEY_LAST_CONTACT
from kayaai.core.task import TaskStatus, utcnow

from .conductor_helpers import Script, answer, connect_claude, plan_direct, revision, step_review
from .test_api import api, wait_terminal  # noqa: F401  (fixture)
from .test_conductor import rt, run  # noqa: F401  (fixture)

HARD = plan_direct("general", needs_claude=True, reason="karmaşık mimari")
GOOD_CODE = "```python\ndef topla(a, b):\n    return a + b\n```"


def _stale(rt, hours: float = 2) -> None:
    rt.store.set_meta(KEY_LAST_CONTACT, (utcnow() - timedelta(hours=hours)).isoformat())


def test_claude_on_but_no_session_does_it_locally(rt, fake_ollama):
    rt.claude.enable()  # hiç temas yok
    res = run(rt, fake_ollama, Script(planner=[HARD], answers=[answer("Yerelde yapıldı.")]), "Zor mimari iş")
    assert res.status == "succeeded" and res.routing.decision == "local_with_warning"
    assert "bağlı değil" in res.routing.why
    assert any("Claude Code oturumu bağlı olmadığı" in w for w in res.warnings)
    assert not any("Claude modu kapalı" in w for w in res.warnings)
    assert rt.claude.status().waiting_tasks == 0


def test_stale_session_also_local_but_explicit_handoff_still_goes(rt, fake_ollama):
    rt.claude.enable()
    _stale(rt)
    res = run(rt, fake_ollama, Script(planner=[HARD], answers=[answer("Yerel.")]), "Zor iş")
    assert res.status == "succeeded" and res.routing.decision == "local_with_warning"
    res2 = run(rt, fake_ollama, Script(planner=[plan_direct("general")], answers=[]), "Bunu Claude yapsın", force="claude")
    assert res2.status == "waiting_claude"  # sahip açıkça devretti: Claude Code'u kendisi açacak


def test_dispute_goes_to_owner_when_no_session(rt, fake_ollama):
    rt.claude.enable()
    s = Script(planner=[plan_direct("coder")], answers=[answer(GOOD_CODE)],
               step_reviews=[step_review([("major", "Toplama yerine çıkarma yapıyor", "return a + b")])],
               revisions=[revision(GOOD_CODE, disputed=[("i1", "Kod toplama yapıyor.")])])
    res = run(rt, fake_ollama, s, "Toplama fonksiyonu yaz")
    assert res.status == "succeeded"
    assert rt.disputes.list()[0].escalated_to == "owner"
    assert any("karar sana bırakıldı" in w for w in res.warnings)


def test_local_failure_fails_instead_of_waiting_when_no_session(rt, fake_ollama):
    rt.claude.enable()
    res = run(rt, fake_ollama, Script(planner=[plan_direct("general")], answers=["bozuk"] * 3), "Bir şey")
    assert res.status == "failed" and rt.claude.status().waiting_tasks == 0


def test_overdue_only_when_session_gone_and_time_passed(rt, fake_ollama):
    connect_claude(rt)
    job = run(rt, fake_ollama, Script(planner=[HARD], answers=[]), "Zor iş").job_id
    inbox = ClaudeInbox(rt)
    later = utcnow() + timedelta(minutes=31)
    assert inbox.overdue() == []                    # yeni bırakıldı
    _stale(rt, hours=0.1)                          # son temas 6 dk önce → 31 dk sonra "bağlı değil"
    assert inbox.overdue(later) == [job]
    assert inbox.overdue(utcnow() + timedelta(minutes=10)) == []  # süre dolmadı
    rt.claude.record_contact()                     # Claude Code üzerinde çalışıyor olabilir: dokunma
    assert inbox.overdue(utcnow() + timedelta(minutes=5)) == []
    rt.settings.claude.inbox_timeout_min = 0       # kapalı
    _stale(rt)
    assert inbox.overdue(later) == []
    assert rt.claude.status().inbox_timeout_min == 0


def test_api_sweep_hands_overdue_job_to_local_team(api, fake_ollama):
    client, rt, app = api
    connect_claude(rt)
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[])] * 5
    job_id = client.post("/api/do", json={"request": "Zor iş"}).json()["id"]
    assert wait_terminal(client, job_id)["status"] == "waiting_claude"
    _stale(rt)
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("Yerel ekip yaptı.")])] * 5
    later = utcnow() + timedelta(minutes=31)
    assert app.state.inbox_sweep(later) == [job_id]
    assert app.state.inbox_sweep(later) == []      # aynı iş iki kez verilmez
    done = wait_terminal(client, job_id)
    assert done["status"] == "succeeded" and done["result"]["answer"] == "Yerel ekip yaptı."
    warns = " ".join(done["result"]["warnings"])
    assert "Claude Code oturumu bağlı olmadığı" in warns and "Claude modu kapalı" not in warns
    assert "claude.timeout" in [e["event"] for e in rt.store.events(job_id)]
    assert client.get("/api/claude").json()["inbox_timeout_min"] == 30


def test_jobs_list_knows_the_conversation(rt, fake_ollama):
    from kayaai.assistant.chat import ChatBook

    book = ChatBook(rt)
    conv = book.create()
    _, reply, _ = book.send(conv.id, "Zor bir mimari iş")  # otomatik → şef işi (çalıştırılmadan)
    other = Conductor(rt).create_job("Sohbetsiz iş")
    rows = {j["id"]: j for j in list_jobs(rt.store)}
    assert rows[reply.job_id]["conv_id"] == conv.id
    assert rows[other.id]["conv_id"] is None
    assert rt.store.get(reply.job_id).status == TaskStatus.PENDING


def test_manual_release_while_connected_says_local_team_did_it(rt, fake_ollama):
    connect_claude(rt)
    job = run(rt, fake_ollama, Script(planner=[HARD], answers=[]), "Zor iş").job_id
    fake_ollama.chat_replies = [Script(planner=[HARD], answers=[answer("Yerel.")])] * 5
    res = ClaudeInbox(rt).release(job)
    assert res.status == "succeeded"
    w = " ".join(res.warnings)
    assert "yerel ekip yaptı" in w and "Claude modu kapalı" not in w and w.count("muhtemelen daha iyi") == 1
