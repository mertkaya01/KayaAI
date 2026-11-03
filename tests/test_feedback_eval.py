"""Adım 22: 👍/👎 geri bildirim, kendi test seti (kayaai degerlendir) ve tek komut kontrol (kayaai kontrol)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai import evalset
from kayaai.api import create_app
from kayaai.assistant import ChatBook, ChatError
from kayaai.cli import main
from kayaai.config import load_settings
from kayaai.runtime import build_runtime

from .conductor_helpers import Script, answer, plan_direct


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 1})
    settings = load_settings()
    settings.ollama.max_retries = 0
    return settings


@pytest.fixture
def rt(env):
    r = build_runtime(env)
    yield r
    r.close()


def _reply(rt, fake_ollama, question: str, text: str):
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer(text)])] * 10
    _, _, runner = book.send(conv.id, question)
    runner()
    return book, conv.id, book.view(conv.id).messages[-1]


# ---------------------------------------------------------------- 👍/👎

def test_feedback_set_clear_and_items(rt, fake_ollama):
    book, cid, msg = _reply(rt, fake_ollama, "Başkent neresi?", "İzmir.")
    m = book.feedback(cid, msg.id, "down", "  yanlış, Ankara olmalı  ")
    assert m.meta["feedback"]["value"] == "down" and m.meta["feedback"]["note"] == "yanlış, Ankara olmalı"
    items = book.feedback_items("down")
    assert len(items) == 1 and items[0]["question"] == "Başkent neresi?" and items[0]["answer"] == "İzmir."
    assert book.feedback_items("up") == []
    assert any(e["type"] == "chat.feedback" for e in rt.store.events_since(0, 500))
    book.feedback(cid, msg.id, None)
    assert "feedback" not in book.view(cid).messages[-1].meta and book.feedback_items("down") == []


def test_feedback_rejects_user_message_and_bad_value(rt, fake_ollama):
    book, cid, msg = _reply(rt, fake_ollama, "Merhaba", "Selam!")
    user = book.view(cid).messages[0]
    with pytest.raises(ChatError, match="tamamlanmış"):
        book.feedback(cid, user.id, "up")
    with pytest.raises(ChatError, match="up, down"):
        book.feedback(cid, msg.id, "meh")
    with pytest.raises(ChatError, match="bulunamadı"):
        book.feedback("baska", msg.id, "up")


def test_feedback_api(env, fake_ollama):
    r = build_runtime(env)
    app = create_app(env, runtime=r)
    try:
        with TestClient(app) as c:
            c.headers["Authorization"] = f"Bearer {app.state.token}"
            _, cid, msg = _reply(r, fake_ollama, "2+2?", "4")
            res = c.post(f"/api/chat/{cid}/messages/{msg.id}/feedback", json={"value": "up", "note": ""})
            assert res.status_code == 200
            assert c.get(f"/api/chat/{cid}").json()["messages"][-1]["meta"]["feedback"]["value"] == "up"
            assert c.post(f"/api/chat/{cid}/messages/{msg.id}/feedback", json={"value": "bad"}).status_code == 422
            assert c.post(f"/api/chat/{cid}/messages/yok/feedback", json={"value": "up"}).status_code in (400, 404)
    finally:
        r.close()


# ---------------------------------------------------------------- test seti

def test_check_is_case_and_turkish_i_insensitive():
    q = {"olmali": ["İstanbul", "ANKARA"], "olmamali": ["bilmiyorum"]}
    assert evalset.check("istanbul ve ankara", q)["passed"]
    r = evalset.check("Ankara. Bilmiyorum.", q)
    assert not r["passed"] and r["missing"] == ["İstanbul"] and r["forbidden"] == ["bilmiyorum"]
    assert evalset.check("x", {"olmali": [], "olmamali": []}) == {"passed": False, "scored": False, "missing": [], "forbidden": []}


def test_seed_file_created_and_feedback_imported_once(rt, fake_ollama):
    qs = evalset.load(rt)
    assert evalset.questions_path(rt).is_file() and len(qs) == len(evalset.SEED)
    assert evalset.questions_path(rt).read_text(encoding="utf-8").startswith("# kayaAI test seti")
    book, cid, msg = _reply(rt, fake_ollama, "Fatura nasıl kesilir?", "Bilmiyorum.")
    book.feedback(cid, msg.id, "down", "boş cevap")
    assert evalset.import_feedback(rt) == 1
    assert evalset.import_feedback(rt) == 0  # aynı soru iki kez eklenmez
    last = evalset.load(rt)[-1]
    assert last["soru"] == "Fatura nasıl kesilir?" and last["olmali"] == [] and "boş cevap" in last["not"]


def test_run_scores_saves_and_compares(rt, fake_ollama):
    evalset.save(rt, [{"soru": "Başkent?", "olmali": ["Ankara"], "olmamali": []},
                      {"soru": "Renk?", "olmali": ["mavi"], "olmamali": []},
                      {"soru": "Serbest", "olmali": [], "olmamali": []}])
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Ankara.")])] * 50
    lines: list[str] = []
    s1 = evalset.run(rt, log=lines.append)
    assert (s1["total"], s1["scored"], s1["passed"]) == (3, 2, 1) and s1["previous"] is None
    assert Path(s1["path"]).is_file() and len(lines) == 3 and "eksik: ['mavi']" in lines[1]
    s2 = evalset.run(rt, agent="general", log=lines.append)
    assert s2["previous"]["passed"] == 1 and s2["agent"] == "general"
    assert evalset.last_result(rt)["agent"] == "general"


def test_run_never_uses_external_provider(rt, fake_ollama):
    sentinel = object()
    rt.orchestrator.outbound = sentinel
    seen = []
    orig = rt.orchestrator.run

    def spy(task_id):
        seen.append(rt.orchestrator.outbound)
        return orig(task_id)

    rt.orchestrator.run = spy
    evalset.save(rt, [{"soru": "Başkent?", "olmali": ["Ankara"], "olmamali": []}])
    fake_ollama.chat_replies = [Script(planner=[], answers=[answer("Ankara.")])] * 10
    evalset.run(rt, agent="general", log=lambda _: None)
    assert seen and all(o is None for o in seen)
    assert rt.orchestrator.outbound is sentinel  # sonra geri konur


# ---------------------------------------------------------------- CLI

def test_cli_degerlendir_and_kontrol(env, capsys):
    assert main(["degerlendir"]) == 0
    assert "Test seti:" in capsys.readouterr().out
    code = main(["kontrol"])
    out = capsys.readouterr().out
    assert "tam kontrol" in out and "Rapor:" in out and "Arayüz derlemesi" in out
    assert "[ATLA ] Qdrant" in out  # SQLite kullanılıyorsa Qdrant atlanır
    reports = list((env.data_dir / "kontrol").glob("kontrol-*.md"))
    assert len(reports) == 1 and "| Modül | Durum |" in reports[0].read_text(encoding="utf-8")
    assert code in (0, 1)
