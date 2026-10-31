"""v0.7.1: Windows'ta (gerçek modelle) görülen kusurların düzeltmeleri."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from kayaai.conductor.coverage import is_instruction_topic, missing_topics
from kayaai.config import load_settings
from kayaai.core.lang import foreign_script, strip_code
from kayaai.core.task import Task
from kayaai.runtime import build_runtime
from kayaai.workers.step_review import Revision, RevisionWorker, contradicts_answer

from .conftest import good_answer

LEAK = "Toplantımız ertelenmiştir. Bu değişiklikten dolayı造成的 rahatsızlık için özür dileriz."
CLEAN = "Toplantımız ertelenmiştir. Bu değişiklikten dolayı yaşanan rahatsızlık için özür dileriz."


def test_foreign_script_detection():
    assert foreign_script(LEAK, "Kısa bir e-posta yaz.") == "造成的"
    assert foreign_script(CLEAN, "Kısa bir e-posta yaz.") == ""
    assert foreign_script("你好 = merhaba", "Şunu Türkçeye çevir: 你好") == ""  # istekte var
    assert foreign_script("你好", "Çince merhaba nasıl denir?") == ""  # o dil istendi


def test_general_worker_retries_until_clean(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    settings = load_settings()
    settings.ollama.max_retries = 0
    fake_ollama.chat_replies = [good_answer(LEAK), good_answer(CLEAN)]
    with build_runtime(settings) as rt:
        task = rt.orchestrator.ask("Müşteriye toplantının ertelendiğini bildiren kısa bir e-posta yaz.", worker="document")
    assert task.status.value == "succeeded" and task.result["answer"] == CLEAN
    assert task.metrics["output_attempts"] == 2
    feedback = fake_ollama.requests[-1][2]["messages"][-1]["content"]
    assert "造成的" in feedback and "Çince" in feedback


def test_revision_rejects_foreign_script():
    w = RevisionWorker()
    task = Task(worker="document.revise", objective="Kısa bir e-posta yaz.",
                input={"current_answer": LEAK, "issues": [{"id": "i1"}]})
    assert any("Çince" in e for e in w.validate(task, Revision(answer=LEAK, language="tr", accepted=["i1"])).errors)
    assert w.validate(task, Revision(answer=CLEAN, language="tr", accepted=["i1"])).passed


def test_contradictory_missing_part_is_dropped():
    answer = "Yarınki toplantı ertelendi. Yeni tarih için size kısa sürede bilgi vereceğiz."
    assert contradicts_answer("E-postada 'yeni tarih için size kısa sürede bilgi vereceğiz' ifadesi eksik.", answer)
    assert not contradicts_answer("Yeni tarih belirtilmemiş.", answer)
    assert not contradicts_answer("'özür dileme cümlesi' eksik", answer)


def test_step_review_drops_contradictions(fake_ollama, tmp_path: Path, monkeypatch):
    from .conductor_helpers import Script, answer, plan_direct, step_review
    from kayaai.conductor import Conductor

    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    settings = load_settings()
    settings.ollama.max_retries = 0
    text = "Sayın ilgili, yarınki toplantı ertelendi. Yeni tarih için size kısa sürede bilgi vereceğiz."
    s = Script(planner=[plan_direct("document")], answers=[answer(text)],
               step_reviews=[step_review(missing=["'yeni tarih için size kısa sürede bilgi vereceğiz' ifadesi eksik"])])
    fake_ollama.chat_replies = [s] * 20
    with build_runtime(settings) as rt:
        res = Conductor(rt).run("Toplantı ertelemesi için kısa ve resmi bir e-posta yaz.")
    rv = res.steps[0].review
    assert rv.verdict == "approve" and rv.dropped_issues == 1 and not rv.revised and s.calls["Revision"] == 0


@pytest.mark.parametrize("topic,expected", [
    ("e-posta yazma / email writing", True),
    ("resmi mektup", True),
    ("Kısa özet / short summary", True),
    ("veri izolasyonu / data isolation", False),
    ("toplantı ertelemesi / meeting postponement", False),
    ("e-posta pazarlaması / email marketing", False),
])
def test_instruction_topics(topic, expected):
    assert is_instruction_topic(topic) is expected


def test_instruction_topic_not_reported_missing():
    answer = "Konu: Toplantı Ertelemesi\n\nSayın ilgili,\n\n" + "Yarınki toplantımız gelecek haftaya ertelenmiştir. " * 5
    assert missing_topics(["e-posta yazma / email writing", "toplantı ertelemesi"], answer) == []


def test_strip_code_for_language_measurement():
    assert strip_code("```python\nprint('x')\n```").strip() == ""


def test_api_open_opens_browser_when_ready(monkeypatch):
    from kayaai import cli

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sessiz
            pass

        def do_GET(self):  # noqa: N802
            ok = self.headers.get("Authorization") == "Bearer tok"
            self.send_response(200 if ok else 401)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    opened: list[str] = []
    done = threading.Event()
    monkeypatch.setattr("webbrowser.open", lambda url: (opened.append(url), done.set()))
    port = srv.server_address[1]
    cli._open_when_ready("127.0.0.1", port, "tok", timeout_s=5)
    assert done.wait(5)
    srv.shutdown()
    assert opened == [f"http://127.0.0.1:{port}/#token=tok"]
