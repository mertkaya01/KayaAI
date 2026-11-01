"""Adım 15a: canlı ilerleme — akışlı Ollama, okunur kuyruk, seyrek task.progress olayları, bitince silinir."""

from __future__ import annotations

import json
import threading

import pytest

from kayaai.config import OrchestratorSettings
from kayaai.core.progress import ProgressSink, readable_tail
from kayaai.core.task import TaskStatus
from kayaai.llm.ollama_client import OllamaCancelled, OllamaError

from .conftest import NDJSON, good_answer


@pytest.mark.parametrize("partial,field,tail", [
    ('{"answer": "Ankara bölgesinde sat', "answer", "Ankara bölgesinde sat"),
    ('{"answer": "Bitti.", "language": "t', "language", "t"),
    ('{"answer": "satır1\\nsatır2 \\"tırnak\\"", "x": 1', "answer", 'satır1 satır2 "tırnak"'),
    ('{"answer": "yarım kaçış \\', "answer", "yarım kaçış"),
    ('{"steps": [{"agent": "data", "objective": "Excel', "objective", "Excel"),
    ("{", None, ""),
    ("düz metin cevap", None, "düz metin cevap"),
])
def test_readable_tail(partial, field, tail):
    assert readable_tail(partial) == (field, tail)


def test_tail_is_clipped():
    f, t = readable_tail('{"answer": "' + "a" * 500)
    assert f == "answer" and len(t) == 140 and t.startswith("…")


def test_sink_throttles():
    now = [0.0]
    sent = []
    s = ProgressSink(sent.append, interval_s=1.0, clock=lambda: now[0])
    for i in range(10):
        s.feed('{"answer": "x' if i == 0 else "y")
        now[0] += 0.25
    assert [x["chars"] for x in sent] == [13, 17, 21]  # 0, 1.0, 2.0 sn'de birer olay
    s.flush()
    assert sent[-1]["chars"] == 22 and sent[-1]["tail"] == "x" + "y" * 9
    s.reset(2)
    assert sent[-1] == {"chars": 0, "field": None, "tail": "", "attempt": 2}


def test_client_stream_joins_chunks(client, fake_ollama):
    fake_ollama.chat_replies = [good_answer("Akış çalışıyor")]
    chunks: list[str] = []
    r = client.chat("qwen3:8b", [{"role": "user", "content": "x"}], on_token=chunks.append)
    assert len(chunks) >= 3 and "".join(chunks) == r.content
    assert json.loads(r.content)["answer"] == "Akış çalışıyor"
    assert r.output_tokens == 40 and r.done_reason == "stop"
    assert fake_ollama.chat_paths()[-1]["stream"] is True


def test_client_stream_errors(client, fake_ollama):
    fake_ollama.chat_replies = [(200, NDJSON([{"error": "model kapasitesi aşıldı"}]))]
    with pytest.raises(OllamaError, match="kapasitesi"):
        client.chat("qwen3:8b", [], on_token=lambda c: None)
    fake_ollama.chat_replies = [(200, NDJSON([{"message": {"content": "{"}, "done": False}]))]
    with pytest.raises(OllamaError, match="tamamlanmadan"):
        client.chat("qwen3:8b", [], on_token=lambda c: None)
    fake_ollama.chat_replies = [(400, {"error": "bozuk istek"})]
    with pytest.raises(OllamaError, match="400"):
        client.chat("qwen3:8b", [], on_token=lambda c: None)


def test_client_stream_cancel(client, fake_ollama):
    ev = threading.Event()
    fake_ollama.chat_replies = [good_answer("uzun cevap " * 20)]

    def tok(_c):
        ev.set()

    with pytest.raises(OllamaCancelled):
        client.chat("qwen3:8b", [], on_token=tok, cancel_event=ev)


def test_orchestrator_emits_progress_then_cleans_up(make_orchestrator, fake_ollama, store):
    fake_ollama.chat_replies = [good_answer("Canlı ofis için ilerleme")]
    seen: list[dict] = []
    orig = store.emit

    def spy(type_, data=None, task_id=None):
        if type_ == "task.progress":
            seen.append({"task_id": task_id, **(data or {})})
        orig(type_, data, task_id)

    store.emit = spy  # type: ignore[method-assign]
    orch = make_orchestrator(settings=OrchestratorSettings(default_timeout_s=10, progress_interval_s=0.05))
    task = orch.ask("Merhaba")
    assert task.status == TaskStatus.SUCCEEDED
    assert seen and seen[-1]["task_id"] == task.id and seen[-1]["worker"] == "general"
    assert seen[-1]["chars"] == len(good_answer("Canlı ofis için ilerleme"))
    assert any("Canlı ofis" in s["tail"] for s in seen)
    assert not [e for e in store.events_since(0, 500) if e["type"] == "task.progress"]  # bitince silindi


def test_retry_resets_progress(make_orchestrator, fake_ollama, store):
    fake_ollama.chat_replies = ["bozuk", good_answer()]
    attempts = []
    orig = store.emit
    store.emit = lambda t, d=None, task_id=None: (attempts.append(d["attempt"]) if t == "task.progress" else None,  # type: ignore[method-assign]
                                                 orig(t, d, task_id))
    task = make_orchestrator().ask("Merhaba")
    assert task.status == TaskStatus.SUCCEEDED and task.metrics["output_attempts"] == 2
    assert 1 in attempts and 2 in attempts


def test_progress_can_be_turned_off(make_orchestrator, fake_ollama):
    fake_ollama.chat_replies = [good_answer()]
    task = make_orchestrator(settings=OrchestratorSettings(default_timeout_s=10, live_progress=False)).ask("Merhaba")
    assert task.status == TaskStatus.SUCCEEDED and fake_ollama.chat_paths()[-1]["stream"] is False
