"""Adım 8: asistan çalışma alanı — kalıcı sohbet, bağlam, ekler, ajana yönlendirme, Claude'a devretme."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.api import create_app
from kayaai.assistant import ChatBook, ChatError
from kayaai.conductor.inbox import ClaudeInbox
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


def _send(book: ChatBook, conv_id: str, text: str, **kw):
    user, reply, runner = book.send(conv_id, text, **kw)
    runner()  # API'de arka plan kuyruğu yapar; burada doğrudan
    return user, book.view(conv_id).messages[-1]


# ---------------------------------------------------------------- temel akış

def test_auto_message_goes_through_conductor_and_titles_conversation(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    s = Script(planner=[plan_direct("general")], answers=[answer("Ankara, Türkiye'nin başkentidir.")])
    fake_ollama.chat_replies = [s] * 10
    user, reply = _send(book, conv.id, "Türkiye'nin başkenti neresi?")
    assert reply.status == "done" and reply.content == "Ankara, Türkiye'nin başkentidir."
    assert reply.reply_to == user.id and reply.job_kind == "conductor" and reply.meta["agents"] == ["general"]
    assert book.get(conv.id).title == "Türkiye'nin başkenti neresi?"
    types = [e["type"] for e in rt.store.events_since(0, 500)]
    assert types.count("chat.message") >= 2


def test_specific_agent_skips_planner(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    s = Script(planner=[], answers=[answer("Toplam 300.")])
    fake_ollama.chat_replies = [s] * 10
    _, reply = _send(book, conv.id, "120 + 80 + 100 kaç eder?", agent="data")
    assert reply.status == "done" and reply.agent == "data" and reply.job_kind == "task"
    assert s.calls["RoutePlan"] == 0


def test_rejects_bad_agent_and_empty(rt):
    book = ChatBook(rt)
    conv = book.create()
    with pytest.raises(ChatError, match="Bilinmeyen ajan"):
        book.send(conv.id, "x", agent="hacker")
    with pytest.raises(ChatError, match="iç ajanı"):
        book.send(conv.id, "x", agent="planner")
    with pytest.raises(ChatError, match="boş"):
        book.send(conv.id, "   ")
    with pytest.raises(ChatError, match="bulunamadı"):
        book.send("yok", "merhaba")


def test_history_is_passed_as_context_and_limited(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    s = Script(planner=[plan_direct("general")] * 12, answers=[answer(f"Cevap {i} burada.") for i in range(12)])
    fake_ollama.chat_replies = [s] * 100
    for i in range(10):
        _send(book, conv.id, f"Soru numarası {i} nedir?")
    last_general = s.user_messages["GeneralAnswer"][-1]
    data = json.loads(last_general.split("<input_data>")[1].split("</input_data>")[0])
    assert len(data["conversation"]) == 8  # son 8 mesaj
    assert data["conversation"][-1] == {"role": "assistant", "content": "Cevap 8 burada."}
    planner_msg = s.user_messages["RoutePlan"][-1]
    assert '"conversation"' in planner_msg  # planlayıcı devam mesajlarını anlayabilsin


def test_history_survives_restart(env, fake_ollama):
    rt1 = build_runtime(env)
    book = ChatBook(rt1)
    conv = book.create()
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Merhaba, nasılsın?")])] * 10
    _send(book, conv.id, "Merhaba!")
    rt1.close()
    rt2 = build_runtime(env)
    view = ChatBook(rt2).view(conv.id)
    assert [m.role for m in view.messages] == ["user", "assistant"]
    assert view.messages[1].content == "Merhaba, nasılsın?" and view.conversation.title == "Merhaba!"
    rt2.close()


def test_rename_and_delete(rt):
    book = ChatBook(rt)
    conv = book.create()
    assert book.rename(conv.id, "  Proje notları ").title == "Proje notları"
    with pytest.raises(ChatError):
        book.rename(conv.id, "   ")
    book.delete(conv.id)
    assert book.list() == []
    with pytest.raises(ChatError, match="bulunamadı"):
        book.view(conv.id)


# ---------------------------------------------------------------- ekler

def test_upload_attachment_reaches_agent(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload("satislar.csv", "ay,satis\nOcak,120\nŞubat,80\n")
    s = Script(planner=[], answers=[answer("Toplam 200.")])
    fake_ollama.chat_replies = [s] * 10
    user, reply = _send(book, conv.id, "Bu dosyadaki satışların toplamı nedir?", agent="data", attachment_ids=[a.id])
    assert reply.content == "Toplam 200." and user.attachments[0].name == "satislar.csv"
    sent = s.user_messages["GeneralAnswer"][0]
    assert "Ocak,120" in sent and "<input_data>" in sent  # güvenilmez veri olarak çitlendi


@pytest.mark.parametrize("name,text,err", [
    ("resim.png", "x", "türü"),
    ("ikili.txt", "a\x00b", "ikili"),
    ("büyük.txt", "x" * (2 * 1024 * 1024 + 1), "çok büyük"),
])
def test_upload_rejections(rt, name, text, err):
    with pytest.raises(ChatError, match=err):
        ChatBook(rt).upload(name, text)


def test_upload_name_is_sanitized(rt):
    a = ChatBook(rt).upload("..\\..\\gizli/../not.md", "# not")
    assert a.name == "not.md"
    assert (rt.settings.data_dir / "attachments" / f"{a.id}.txt").read_text(encoding="utf-8") == "# not"


def test_long_attachment_is_truncated_with_warning(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload("uzun.txt", "a" * 20_000)
    fake_ollama.chat_replies = [Script(planner=[], answers=[answer("Tamam, okudum.")])] * 5
    _, reply = _send(book, conv.id, "Bu metni özetle.", agent="general", attachment_ids=[a.id])
    assert any("ilk 12000 karakteri" in w for w in reply.warnings)


def test_attach_from_allowed_folder_only(rt, tmp_path):
    files = tmp_path / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / "rapor.md").write_text("# Rapor\nSatışlar arttı.", encoding="utf-8")
    book = ChatBook(rt)
    a = book.attach_path("rapor.md")
    assert a.source == "path" and a.name == "rapor.md" and a.path.endswith("rapor.md")
    from kayaai.tools.files import PathNotAllowed
    with pytest.raises(PathNotAllowed):
        book.attach_path(str(tmp_path / "data" / "api_token"))


# ---------------------------------------------------------------- Claude'a devretme

def test_handoff_requires_claude_mode(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Yerel cevap burada.")])] * 5
    user, reply = _send(book, conv.id, "Bir mimari öner.")
    with pytest.raises(ChatError, match="Claude modu kapalı"):
        book.handoff(conv.id, reply.id)


def test_handoff_goes_to_inbox_and_claude_answer_lands_in_chat(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload("notlar.md", "Gereksinim: çok kiracılı yapı.")
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")] * 2, answers=[answer("Yerel taslak cevap.")])] * 10
    user, local = _send(book, conv.id, "Bu notlara göre bir mimari öner.", attachment_ids=[a.id])
    rt.claude.enable()
    reply, runner = book.handoff(conv.id, local.id)  # cevaptan devret → aynı soru
    runner()
    view = book.view(conv.id)
    handed = view.messages[-1]
    assert handed.handoff and handed.status == "waiting_claude" and handed.reply_to == user.id
    [item] = ClaudeInbox(rt).items()
    assert item.request == "Bu notlara göre bir mimari öner."
    assert item.context["attachments"][0]["content"] == "Gereksinim: çok kiracılı yapı."
    assert item.context["conversation"][-1]["content"] == "Yerel taslak cevap."
    ClaudeInbox(rt).complete(item.job_id, "Claude'un ayrıntılı mimari önerisi.", "tamam")
    done = book.view(conv.id).messages[-1]  # başka süreçte tamamlanmış gibi: görüntülerken güncellenir
    assert done.status == "done" and done.content == "Claude'un ayrıntılı mimari önerisi." and done.agent == "claude"
    assert done.meta["agents"] == [] and not any("Claude kutusuna" in w for w in done.warnings)


# ---------------------------------------------------------------- API

def test_api_chat_flow(env, fake_ollama):
    rt = build_runtime(env)
    app = create_app(env, runtime=rt)
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")] * 3,
                                       answers=[answer("API üzerinden merhaba!")] * 3)] * 20
    with TestClient(app) as c:
        assert c.get("/api/chat").status_code == 401
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        conv = c.post("/api/chat", json={}).json()
        att = c.post("/api/attachments", json={"name": "a.txt", "text": "veri"}).json()
        assert c.post("/api/attachments", json={"name": "a.exe", "text": "x"}).status_code == 400
        r = c.post(f"/api/chat/{conv['id']}/messages", json={"text": "Merhaba", "attachments": [att["id"]]})
        assert r.status_code == 202 and r.json()["reply"]["status"] == "pending"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msgs = c.get(f"/api/chat/{conv['id']}").json()["messages"]
            if msgs[-1]["status"] == "done":
                break
            time.sleep(0.05)
        assert msgs[-1]["content"] == "API üzerinden merhaba!"
        assert c.get("/api/chat").json()[0]["title"] == "Merhaba"
        assert c.post(f"/api/chat/{conv['id']}/messages/{msgs[-1]['id']}/handoff").status_code == 409
        assert c.post(f"/api/chat/{conv['id']}/messages", json={"text": "x", "agent": "yok"}).status_code == 400
        assert c.patch(f"/api/chat/{conv['id']}", json={"title": "Deneme"}).json()["title"] == "Deneme"
        assert c.post("/api/attachments/from-path", json={"path": "/etc/passwd"}).status_code == 403
        assert c.delete(f"/api/chat/{conv['id']}").status_code == 200
        assert c.get(f"/api/chat/{conv['id']}").status_code == 404
    rt.close()
