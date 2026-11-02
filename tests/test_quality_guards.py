"""Sahip videosu (2026-11-02): tekrar döngüsü 120 sn'de düşüyordu, planlayıcı 5 adımı reddetti ve eski uzun cevaba
takıldı, "neler yapabilirsiniz" cevabı uyduruluyordu, bilgisayar analizi verisizdi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kayaai.about import wants_about
from kayaai.config import load_settings
from kayaai.conductor import ClaudeInbox, Conductor
from kayaai.runtime import build_runtime
from kayaai.system.snapshot import wants_computer_info
from kayaai.workers.base import LOOP_NOTE
from kayaai.workers.loopguard import LoopGuard, ModelLooping, find_loop
from kayaai.workers.planner import RoutePlan, validate_plan

from .conductor_helpers import Script, answer, connect_claude, plan_direct, plan_steps
from .conftest import good_answer

PHRASE = "eksik bilgilerin belirtilmesi istenen rapor kapsamında "


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    settings = load_settings()
    settings.ollama.max_retries = 0
    r = build_runtime(settings)
    yield r
    r.close()


def chats(fake_ollama) -> list[dict]:
    return [b for (m, p, b) in fake_ollama.requests if p == "/api/chat"]


# ---------------------------------------------------------------- döngü yakalayıcı

def test_find_loop_catches_the_video_phrase_but_not_normal_text():
    found = find_loop("Diğer ajanların sonuçları: " + PHRASE * 5)
    assert found is not None and len(found) == len(PHRASE)
    normal = [
        "| Ay | Tutar |\n|---|---|\n" + "".join(f"| {m} | {i * 10} |\n" for i, m in enumerate(["Ocak", "Şubat", "Mart"])),
        "=" * 80 + "\n" + "Başlık\n" + "=" * 80,
        "```python\n" + "print('-' * 40)\n" * 3 + "```",
        "Toplam satış 300 TL. Ocak 120 TL, Şubat 180 TL. Artış yüzde 50.",
        "- madde\n" * 12,  # kısa tekrar (dönem < 12)
    ]
    for t in normal:
        assert find_loop(t) is None, t


def test_guard_stops_stream_early():
    seen: list[str] = []
    g = LoopGuard(seen.append)
    with pytest.raises(ModelLooping) as e:
        for _ in range(200):
            g.feed(PHRASE[:20])
            g.feed(PHRASE[20:])
    assert e.value.chars < 1000 and "tekrar" in str(e.value)
    assert seen  # canlı ofis akışı da beslenmeye devam etti


def test_worker_retries_after_loop_with_stricter_options(rt, fake_ollama):
    loop = '{"answer": "' + PHRASE * 60 + '"}'
    fake_ollama.chat_replies = [loop, good_answer("Kısa ve net cevap.")]
    task = rt.orchestrator.ask("Ne yapabilirsin?", worker="general")
    assert task.status.value == "succeeded" and task.result["answer"] == "Kısa ve net cevap."
    assert task.metrics["loops"] == 1 and task.metrics["output_attempts"] == 2
    first, second = chats(fake_ollama)[-2:]
    assert first["stream"] is True
    assert second["options"]["repeat_penalty"] == 1.3 and second["options"]["temperature"] >= 0.7
    assert second["messages"][-1]["content"] == LOOP_NOTE


def test_three_loops_fail_fast_instead_of_timeout(rt, fake_ollama):
    loop = '{"answer": "' + PHRASE * 60 + '"}'
    fake_ollama.chat_replies = [loop] * 3
    task = rt.orchestrator.ask("Ne yapabilirsin?", worker="general")
    assert task.status.value == "failed" and "tekrar" in (task.error or "")
    assert sum(1 for b in chats(fake_ollama) if b["messages"][-1]["content"] == LOOP_NOTE) == 2  # not bir kez eklenir


# ---------------------------------------------------------------- planlayıcı

def test_planner_has_output_cap_and_five_steps_allowed(rt, fake_ollama):
    assert rt.settings.conductor.max_steps == 5
    steps = [(f"s{i}", "general", f"bölüm {i}", []) for i in range(1, 6)]
    plan = RoutePlan.model_validate_json(plan_steps(steps))
    assert validate_plan(plan, {"general"}, 5) == []
    s = Script(planner=[plan_direct("general")], answers=[answer("Tamam.")])
    fake_ollama.chat_replies = [s] * 10
    Conductor(rt).run("Merhaba")
    planner_req = next(b for b in chats(fake_ollama) if b["format"].get("title") == "RoutePlan")
    answer_req = next(b for b in chats(fake_ollama) if b["format"].get("title") == "GeneralAnswer")
    assert planner_req["options"]["num_predict"] == 1500
    assert "num_predict" not in answer_req["options"]


def test_planner_sees_short_history_only(rt, fake_ollama):
    long_answer = "Uzun cevap. " + PHRASE * 40
    s = Script(planner=[plan_direct("general")], answers=[answer("Tamam.")])
    fake_ollama.chat_replies = [s] * 10
    ctx = {"conversation": [{"role": "user", "content": "rapor çıkar"}, {"role": "assistant", "content": long_answer}]}
    Conductor(rt).run("güzel, tek tek neler yapabildiğinizi açıklar mısın", context=ctx)
    planner_req = next(b for b in chats(fake_ollama) if b["format"].get("title") == "RoutePlan")
    data = planner_req["messages"][-1]["content"]
    assert "Uzun cevap." in data and data.count(PHRASE) <= 8


# ---------------------------------------------------------------- kendini tanıma + bilgisayar verisi

@pytest.mark.parametrize("text,yes", [
    ("güzel tek tek neler yapabildiğinizi açıklayabilir misin", True), ("Sen kimsin?", True),
    ("What can you do?", True), ("Ekibinde hangi ajanlar var", True), ("Satış raporunu özetle", False),
])
def test_wants_about(text, yes):
    assert wants_about(text) is yes


@pytest.mark.parametrize("text,yes", [
    ("Bilgisayarım için performans ve optimizasyon analizi hazırla", True), ("GPU kullanımım neden yüksek", True),
    ("Ekran kartım yeterli mi", True), ("Ankara satış performansını analiz et", False), ("RAMazan bayramı ne zaman", False),
])
def test_wants_computer_info(text, yes):
    assert wants_computer_info(text) is yes


def test_chat_gives_real_team_and_computer_snapshot(rt, fake_ollama):
    from kayaai.assistant.chat import ChatBook

    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [good_answer("Ben kayaAI.")] * 3
    _, reply, run = book.send(conv.id, "Neler yapabilirsin?", agent="general")
    run()
    req = chats(fake_ollama)[-1]
    data = req["messages"][-1]["content"]
    assert '"about_kayaai"' in data and '"Veri"' in data and "Tablo analizi" in data and "Kum havuzu" not in data
    assert "TRUE description of you (kayaAI)" in req["messages"][0]["content"]
    assert '"this_computer"' not in data

    fake_ollama.chat_replies = [good_answer("Analiz.")] * 3
    _, reply2, run2 = book.send(conv.id, "Bilgisayarım için performans analizi yap", agent="general")
    run2()
    req2 = chats(fake_ollama)[-1]
    inp = req2["messages"][-1]["content"].split("<input_data>")[1].split("</input_data>")[0]
    comp = json.loads(inp)["this_computer"]
    assert comp["ram"]["total_gb"] and comp["cpu"]["logical_cores"] and "Sıcaklık" in comp["note"]
    assert "REAL, read-only snapshot" in req2["messages"][0]["content"]


def test_computer_snapshot_never_goes_to_claude_inbox(rt, fake_ollama):
    from kayaai.assistant.chat import ChatBook

    connect_claude(rt)
    hard = plan_direct("general", needs_claude=True, reason="zor")
    fake_ollama.chat_replies = [Script(planner=[hard], answers=[])] * 5
    book = ChatBook(rt)
    conv = book.create()
    _, reply, run = book.send(conv.id, "Bilgisayarımı derinlemesine analiz et ve optimizasyon planı yap")
    run()
    assert "this_computer" in rt.store.get(reply.job_id).input["context"]
    [item] = ClaudeInbox(rt).items()
    assert "this_computer" not in item.context
