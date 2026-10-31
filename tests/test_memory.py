"""Adım 9: hafıza — gizli bilgi, kişisel hafıza, belge dizini (RAG), sohbet entegrasyonu, API/MCP/CLI."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from kayaai import cli
from kayaai.api import create_app
from kayaai.assistant import ChatBook
from kayaai.config import load_settings
from kayaai.mcp_server import create_server
from kayaai.memory import SecretRefused, remember
from kayaai.memory.documents import chunk_text
from kayaai.memory.secrets import detect_secrets
from kayaai.runtime import build_runtime

from .conftest import good_answer
from .conductor_helpers import plan_direct

COFFEE = "Kahvemi şekersiz ve sütlü içerim."
ATLAS = "Atlas projesinin teslim tarihi 15 Kasım."


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    (tmp_path / "files").mkdir()
    s = load_settings()
    s.ollama.max_retries = 0
    s.memory.min_score = 0.2  # sahte embedding kaba; gerçek eşik scripts/memory_check.py ile ayarlanır
    return s


@pytest.fixture
def rt(env):
    r = build_runtime(env)
    yield r
    r.close()


def note(text: str, category: str = "preference", sensitivity: str = "personal") -> str:
    return json.dumps({"text": text, "category": category, "sensitivity": sensitivity}, ensure_ascii=False)


# ---------------------------------------------------------------- yardımcılar

@pytest.mark.parametrize("text,kind", [
    ("Wi-Fi şifrem: kaya1234", "parola"),
    ("my password is Hunter2!", "parola"),
    ("anahtar sk-ant-abcdefghijklmnopqrstu", "API anahtarı"),
    ("-----BEGIN RSA PRIVATE KEY-----", "özel anahtar"),
    ("IBAN: TR12 0006 2000 0000 0006 2959 11", "IBAN"),
    ("kart 4111 1111 1111 1111", "kart numarası"),
    ("api_key = abcdef1234567890", "erişim anahtarı"),
])
def test_secret_patterns(text, kind):
    assert kind in detect_secrets(text)


@pytest.mark.parametrize("text", [COFFEE, ATLAS, "Şifreleme için AES kullanılır.", "Telefonumu 3 kez aradım."])
def test_no_false_secret(text):
    assert detect_secrets(text) == []


def test_chunking_keeps_lines_and_overlap():
    text = "\n".join(f"satır {i} " + "x" * 40 for i in range(1, 41))
    chunks = chunk_text(text, size=300, overlap=60)
    assert chunks[0][0] == 1 and len(chunks) > 3
    assert all(len(c) <= 300 for _, c in chunks)
    first_last_line = chunks[0][1].splitlines()[-1]
    assert first_last_line in chunks[1][1]  # örtüşme
    long = chunk_text("a" * 1000, size=300, overlap=50)
    assert len(long) >= 4 and all(len(c) <= 300 for _, c in long)


# ---------------------------------------------------------------- kişisel hafıza

def test_add_search_and_privacy(rt):
    book = rt.memory.book
    coffee, _ = book.add(COFFEE, category="preference")
    atlas, _ = book.add(ATLAS, category="project", sensitivity="private")
    assert coffee.embedded and atlas.embedded
    res = rt.memory.recall("Kahve nasıl içiyorum?")
    assert [m["text"] for m in res.memories][0] == COFFEE
    assert all(m["text"] != ATLAS for m in res.memories)  # ilgisiz
    local = rt.memory.recall("Atlas projesinin teslim tarihi ne?")
    assert local.memories[0]["text"] == ATLAS
    claude = rt.memory.recall("Atlas projesinin teslim tarihi ne?", for_claude=True)
    assert claude.memories == []  # özel öğe Claude'a gitmez


def test_secret_requires_explicit_permission_and_never_recalled(rt):
    book = rt.memory.book
    with pytest.raises(SecretRefused):
        book.add("Wi-Fi şifrem: kaya1234")
    with pytest.raises(SecretRefused):
        book.add("Banka bilgim", sensitivity="secret")
    item, _ = book.add("Wi-Fi şifrem: kaya1234", allow_secret=True)
    assert item.sensitivity == "secret" and item.secret_kinds == ["parola"]
    assert rt.memory.recall("Wi-Fi şifrem neydi?").memories == []
    with pytest.raises(SecretRefused):
        book.propose("Kullanıcının şifresi: kaya1234")


def test_proposals_need_approval(rt):
    book = rt.memory.book
    item, _ = book.propose(COFFEE, category="preference")
    assert item.status == "proposed" and rt.memory.recall("kahve nasıl içiyorum").memories == []
    book.approve(item.id)
    assert rt.memory.recall("kahve nasıl içiyorum").memories[0]["id"] == item.id


def test_update_and_delete(rt):
    book = rt.memory.book
    item, _ = book.add(COFFEE)
    book.update(item.id, text="Çayı demli severim.")
    assert rt.memory.recall("kahve nasıl içiyorum").memories == []
    assert rt.memory.recall("çayı nasıl severim").memories[0]["id"] == item.id
    with pytest.raises(SecretRefused):
        book.update(item.id, text="şifrem: abc12345")
    book.delete(item.id)
    assert book.list() == [] and rt.memory.recall("çayı nasıl severim").memories == []
    assert [e["type"] for e in rt.store.events_since(0)].count("memory.deleted") == 1


def test_works_without_embedding_model(rt, fake_ollama):
    fake_ollama.models = [m for m in fake_ollama.models if m["name"] != "bge-m3"]
    item, warnings = rt.memory.book.add(COFFEE)
    assert not item.embedded and "ollama pull bge-m3" in warnings[0]
    res = rt.memory.recall("kahvemi nasıl içerim")
    assert res.memories and res.memories[0]["id"] == item.id  # kelime araması
    assert "kelime aramasıyla" in res.warnings[0]
    fake_ollama.models.append({"name": "bge-m3", "model": "bge-m3", "size": 1})
    assert rt.memory.book.reindex() == 1 and rt.memory.book.get(item.id).embedded


# ---------------------------------------------------------------- belge dizini

def test_document_index_incremental_and_safe(rt, tmp_path):
    files = tmp_path / "files"
    (files / "notlar.md").write_text("# Atlas\n\nAtlas projesinin teslim tarihi 15 Kasım. Müşteri: Kaya Ltd.\n",
                                     encoding="utf-8")
    (files / "satis.csv").write_text("ay,satis\nOcak,120\nŞubat,80\n", encoding="utf-8")
    (files / ".env").write_text("API_KEY=gizli1234567890", encoding="utf-8")
    (files / "ayar.txt").write_text("db password: hunter2xyz\n", encoding="utf-8")
    (files / "ikili.txt").write_bytes(b"ab\x00cd")
    (files / "node_modules").mkdir()
    (files / "node_modules" / "paket.md").write_text("Atlas", encoding="utf-8")
    (files / "resim.png").write_bytes(b"\x89PNG")
    outside = tmp_path / "disari.md"
    outside.write_text("Atlas gizli dış dosya", encoding="utf-8")
    try:
        os.symlink(outside, files / "kacis.md")
    except OSError:
        pass
    rep = rt.memory.docs.index()
    paths = {Path(d.path).name for d in rt.memory.docs.documents()}
    assert paths == {"notlar.md", "satis.csv", "ayar.txt"}
    assert rep.secret_chunks_skipped == 1 and rep.skipped["gizli bilgi taşıyabilir (dosya adı)"] == 1
    assert rep.skipped["ikili içerik"] == 1
    hits = rt.memory.recall("Atlas projesinin teslim tarihi ne zaman?").documents
    assert hits[0]["name"] == "notlar.md" and hits[0]["line"] == 1
    assert all("hunter2" not in h["text"] and "dış dosya" not in h["text"] for h in hits)
    again = rt.memory.docs.index()
    assert again.indexed == 0 and again.unchanged == 3
    (files / "satis.csv").write_text("ay,satis\nOcak,150\n", encoding="utf-8")
    (files / "notlar.md").unlink()
    third = rt.memory.docs.index()
    assert third.indexed == 1 and third.removed == 1
    assert rt.memory.recall("Atlas teslim tarihi").documents == []
    assert any(e["type"] == "memory.indexed" for e in rt.store.events_since(0, 500))


# ---------------------------------------------------------------- hatırla + sohbet

def test_remember_classifies_and_refuses_secrets(rt, fake_ollama):
    fake_ollama.chat_replies = [note("Kahvesini şekersiz ve sütlü içer.")]
    item, msg, _ = remember(rt, "kahvemi şekersiz ve sütlü içerim")
    assert item.text == "Kahvesini şekersiz ve sütlü içer." and item.category == "preference"
    assert "Hafızaya kaydettim" in msg and "tercih" in msg
    calls = len(fake_ollama.requests)
    item2, msg2, _ = remember(rt, "Wi-Fi şifrem: kaya1234")
    assert item2 is None and "gizli bilgi" in msg2 and len(fake_ollama.requests) == calls  # modele bile gitmedi


def test_remember_falls_back_when_model_fails(rt, fake_ollama):
    fake_ollama.chat_replies = ["{}", "{}", "{}"]
    item, _, warnings = remember(rt, "Toplantılar salı günleri saat 10'da.")
    assert item.text == "Toplantılar salı günleri saat 10'da." and item.category == "note" and warnings


def test_chat_remember_then_recall(rt, fake_ollama):
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [note(COFFEE)]
    _, reply, run = book.send(conv.id, "hatırla: kahvemi şekersiz ve sütlü içerim")
    run()
    saved = book.view(conv.id).messages[-1]
    assert saved.status == "done" and "Hafızaya kaydettim" in saved.content and saved.agent == "memory"

    (rt.settings.data_dir.parent / "files" / "menu.md").write_text("Ofis menüsü: kahve, çay, ayran.", encoding="utf-8")
    rt.memory.docs.index()
    seen: list[str] = []

    def reply(body):
        title = (body.get("format") or {}).get("title")
        seen.append(body["messages"][-1]["content"])
        if title == "RoutePlan":
            return plan_direct("general")
        return good_answer("Şekersiz ve sütlü içiyorsun.")
    fake_ollama.chat_replies = [reply] * 10
    _, r2, run2 = book.send(conv.id, "Kahvemi nasıl içiyorum, ofiste kahve var mı?")
    run2()
    ans = book.view(conv.id).messages[-1]
    assert ans.content == "Şekersiz ve sütlü içiyorsun."
    assert ans.recall["memories"][0]["text"] == COFFEE
    assert ans.recall["sources"][0]["name"] == "menu.md"
    general_input = [s for s in seen if "<input_data>" in s and '"memory"' in s][-1]
    assert COFFEE in general_input and "menu.md:1" in general_input


def test_handoff_recall_excludes_private_and_documents(rt, fake_ollama):
    rt.memory.book.add(ATLAS, category="project", sensitivity="private")
    rt.memory.book.add(COFFEE, category="preference", sensitivity="personal")
    (rt.settings.data_dir.parent / "files" / "atlas.md").write_text("Atlas bütçesi 2 milyon.", encoding="utf-8")
    rt.memory.docs.index()
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [lambda b: plan_direct("general") if (b.get("format") or {}).get("title") == "RoutePlan"
                                else good_answer("Yerel cevap.")] * 20
    _, local, run = book.send(conv.id, "Atlas teslim tarihi ve kahve tercihim nedir?")
    run()
    rt.claude.enable()
    handed, run2 = book.handoff(conv.id, book.view(conv.id).messages[-1].id)
    run2()
    from kayaai.conductor.inbox import ClaudeInbox
    [item] = ClaudeInbox(rt).items()
    ctx = item.context
    assert "documents" not in ctx
    assert [m["text"] for m in ctx.get("memory", [])] == [COFFEE]


# ---------------------------------------------------------------- API / MCP / CLI

def test_api_memory(env, fake_ollama):
    rt = build_runtime(env)
    app = create_app(env, runtime=rt)
    with TestClient(app) as c:
        assert c.get("/api/memory").status_code == 401
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        r = c.post("/api/memory", json={"text": COFFEE, "category": "preference"})
        assert r.status_code == 201 and r.json()["item"]["embedded"]
        mid = r.json()["item"]["id"]
        assert c.post("/api/memory", json={"text": "şifrem: kaya12345"}).status_code == 422
        sec = c.post("/api/memory", json={"text": "şifrem: kaya12345", "allow_secret": True})
        assert sec.status_code == 201
        listed = {m["id"]: m for m in c.get("/api/memory").json()}
        sid = sec.json()["item"]["id"]
        assert listed[sid]["text"] == "" and listed[sid]["masked"] and "kaya12345" not in c.get("/api/memory").text
        assert c.get(f"/api/memory/{sid}/reveal").json()["text"] == "şifrem: kaya12345"
        assert c.patch(f"/api/memory/{mid}", json={"category": "note"}).json()["item"]["category"] == "note"
        assert c.get("/api/memory-search", params={"q": "kahve nasıl içiyorum"}).json()["memories"][0]["id"] == mid
        assert len(c.get("/api/memory-export").json()["items"]) == 2
        fake_ollama.chat_replies = [note("Toplantılar salı günü.", "note")]
        assert c.post("/api/memory/from-text", json={"text": "toplantılar salı"}).json()["item"]["text"] == "Toplantılar salı günü."
        (env.data_dir.parent / "files" / "a.md").write_text("Atlas notu", encoding="utf-8")
        assert c.post("/api/documents/index").status_code == 202
        import time
        for _ in range(100):
            if c.get("/api/documents").json()["status"]["documents"] == 1:
                break
            time.sleep(0.05)
        assert c.get("/api/documents").json()["documents"][0]["path"].endswith("a.md")
        assert c.delete(f"/api/memory/{mid}").status_code == 200
        assert c.delete(f"/api/memory/{mid}").status_code == 404
    rt.close()


def test_mcp_memory_tools(env):
    rt = build_runtime(env)
    rt.memory.book.add(COFFEE, sensitivity="personal")
    rt.memory.book.add(ATLAS, sensitivity="private")
    rt.close()

    async def go():
        async with Client(create_server(env)) as c:
            s1 = await c.call_tool("kayaai_memory_search", {"query": "Atlas teslim tarihi ve kahve"})
            p = await c.call_tool("kayaai_memory_propose", {"text": "Kullanıcı raporları PDF ister.", "category": "preference"})
            bad = await c.call_tool("kayaai_memory_propose", {"text": "şifresi: kaya12345"})
            return s1, p, bad

    s1, p, bad = asyncio.run(go())
    texts = [m["text"] for m in s1.structured_content["memories"]]
    assert COFFEE in texts and ATLAS not in texts
    assert p.structured_content["status"] == "proposed" and bad.is_error


def test_cli_memory(env, fake_ollama, capsys):
    assert cli.main(["memory"]) == 0 and "Hafıza boş" in capsys.readouterr().out
    assert cli.main(["memory", "add", COFFEE, "--category", "preference"]) == 0
    assert cli.main(["memory", "add", "şifrem:", "kaya12345"]) == 1
    assert cli.main(["memory", "add", "şifrem:", "kaya12345", "--secret"]) == 0
    capsys.readouterr()
    assert cli.main(["memory", "list"]) == 0
    out = capsys.readouterr().out
    assert COFFEE in out and "•••• (gizli)" in out and "kaya12345" not in out
    assert cli.main(["memory", "search", "kahvemi", "şekersiz", "sütlü"]) == 0 and COFFEE in capsys.readouterr().out
    (env.data_dir.parent / "files" / "n.md").write_text("Atlas notu", encoding="utf-8")
    assert cli.main(["memory", "index"]) == 0 and "işlenen 1" in capsys.readouterr().out
    assert cli.main(["memory", "export"]) == 0
    assert len(json.loads((env.data_dir / "memory_export.json").read_text(encoding="utf-8"))["items"]) == 2
