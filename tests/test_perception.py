"""Adım 12a: ekranı okuma — OCR arayüzü, görsel ajan, sayı denetimi, sohbet görüntü eki, taranmış PDF, CLI/API."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.assistant.chat import ChatBook, ChatError
from kayaai.config import load_settings
from kayaai.perception import ocr
from kayaai.perception.ocr import OcrResult, OcrUnavailable
from kayaai.perception.vision import VisionError, see
from kayaai.runtime import build_runtime

from .conftest import good_answer
from .test_business import make_pdf

VL = {"name": "qwen2.5vl:7b", "model": "qwen2.5vl:7b", "size": 6_000_000_000}
INVOICE_OCR = "Fatura No: KYA-2026-0042\nTarih: 15.01.2026\nAra toplam: 1.400,00 TL\nKDV %20: 280,00 TL\nToplam: 1.680,00 TL"


def png(w: int = 320, h: int = 120, text: str = "Toplam: 1.680,00 TL") -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(img).text((10, 40), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_ocr():
    calls: list[int] = []

    def engine(data: bytes) -> OcrResult:
        calls.append(len(data))
        return OcrResult(text=INVOICE_OCR, lines=INVOICE_OCR.splitlines(), engine="fake", language="tr")

    ocr.set_engine(engine)
    yield calls
    ocr.set_engine(None)


@pytest.fixture
def no_ocr():
    def engine(data: bytes) -> OcrResult:
        raise OcrUnavailable("test: OCR yok")

    ocr.set_engine(engine)
    yield
    ocr.set_engine(None)


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    fake_ollama.models.append(dict(VL))
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def rt(env):
    r = build_runtime(env)
    yield r
    r.close()


def _vision_chats(fake_ollama):
    return [b for (_, p, b) in fake_ollama.requests if p == "/api/chat" and b["model"] == "qwen2.5vl:7b"]


# ---------------------------------------------------------------- görsel ajan

def test_see_sends_image_and_ocr_text_and_verifies_numbers(rt, fake_ollama, fake_ocr):
    fake_ollama.chat_replies = [good_answer("Bu bir fatura; toplam tutar 1.680,00 TL ve KDV 280,00 TL.")]
    res = see(rt, [png()], "Bu faturanın toplamı ne kadar?")
    assert res.verified is True and res.unverified_numbers == [] and res.model == "qwen2.5vl:7b"
    body = _vision_chats(fake_ollama)[-1]
    user = body["messages"][-1]
    assert len(user["images"]) == 1 and base64.b64decode(user["images"][0])[:4] == b"\x89PNG"
    assert "Toplam: 1.680,00 TL" in user["content"] and "_images" not in user["content"]
    assert body["keep_alive"] == "2m"  # görsel model iş bitince boşalır
    assert not list((rt.settings.data_dir / "perception" / "tmp").glob("*"))  # geçici kopyalar silindi
    task = rt.store.get(res.task_id)
    assert task.worker == "vision" and all(str(p).endswith(".png") for p in task.input["_images"])
    assert "doğrulandı" in res.markdown()


def test_see_flags_numbers_not_on_screen(rt, fake_ollama, fake_ocr):
    fake_ollama.chat_replies = [good_answer("Toplam tutar 1.860,00 TL görünüyor.")]
    res = see(rt, [png()], "Toplam ne?")
    assert res.verified is False and res.unverified_numbers == [1860.0]
    assert any("1.860" in w for w in res.warnings) and "dikkat" in res.markdown()


def test_see_without_ocr_is_marked_unverified(rt, fake_ollama, no_ocr):
    fake_ollama.chat_replies = [good_answer("Ekranda bir fatura var, toplam 1.680 TL.")]
    res = see(rt, [png()], "")
    assert res.verified is None and res.question.startswith("Bu ekran görüntüsünde ne var")
    assert any("doğrulanmadı" in w for w in res.warnings) and "ocr_text" not in _vision_chats(fake_ollama)[-1]["messages"][-1]["content"]


def test_see_missing_model_explains_how_to_install(rt, fake_ollama, fake_ocr):
    fake_ollama.models = [m for m in fake_ollama.models if m["name"] != "qwen2.5vl:7b"]
    with pytest.raises(VisionError, match="ollama pull qwen2.5vl:7b"):
        see(rt, [png()], "ne var?")


@pytest.mark.parametrize("bad", [b"bu bir resim degil", b"\x89PNG\r\n\x1a\nbozuk"])
def test_see_rejects_broken_images(rt, fake_ocr, bad):
    with pytest.raises(VisionError):
        see(rt, [bad], "ne var?")


def test_too_many_images(rt):
    with pytest.raises(VisionError, match="En fazla 3"):
        see(rt, [png()] * 4, "x")


def test_large_image_is_downscaled_for_model(rt, fake_ollama, fake_ocr):
    from PIL import Image

    fake_ollama.chat_replies = [good_answer("Büyük bir ekran.")]
    see(rt, [png(3840, 2160)], "ne var?")
    img = Image.open(io.BytesIO(base64.b64decode(_vision_chats(fake_ollama)[-1]["messages"][-1]["images"][0])))
    assert max(img.size) == 1600


def test_vision_agent_is_not_offered_to_planner(rt):
    from kayaai.conductor import Conductor

    names = {a["name"] for a in Conductor(rt)._agents_for_planner()}
    assert "vision" not in names and "general" in names
    assert rt.workers.get("vision").definition.claude_tier == "none"


# ---------------------------------------------------------------- sohbet

def _send(book: ChatBook, conv_id: str, text: str, **kw):
    user, reply, runner = book.send(conv_id, text, **kw)
    runner()
    return user, book.view(conv_id).messages[-1]


def test_chat_image_attachment_goes_to_vision_and_follow_up_reuses_image(rt, fake_ollama, fake_ocr):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload_binary("ekran-20261101.png", base64.b64encode(png()).decode())
    assert a.kind == "image" and a.chars == len(INVOICE_OCR)
    fake_ollama.chat_replies = [good_answer("Fatura toplamı 1.680,00 TL."), good_answer("Fatura numarası KYA-2026-0042.")]
    _, reply = _send(book, conv.id, "Toplam ne kadar?", attachment_ids=[a.id])
    assert reply.status == "done" and reply.agent == "vision" and "1.680,00 TL" in reply.content
    assert reply.meta["vision"]["verified"] is True and reply.meta["vision"]["ocr"][0]["engine"] == "önceden"
    assert len(fake_ocr) == 1  # OCR yalnız yüklemede bir kez
    _, follow = _send(book, conv.id, "Fatura numarası ne?")
    assert follow.agent == "vision" and "KYA-2026-0042" in follow.content
    assert len(_vision_chats(fake_ollama)) == 2 and "images" in _vision_chats(fake_ollama)[-1]["messages"][-1]


def test_chat_text_after_vision_with_other_agent_goes_normal_route(rt, fake_ollama, fake_ocr):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload_binary("e.png", base64.b64encode(png()).decode())
    fake_ollama.chat_replies = [good_answer("Bir fatura.")]
    _send(book, conv.id, "ne var?", attachment_ids=[a.id])
    fake_ollama.chat_replies = [good_answer("Merhaba!")]
    _, r = _send(book, conv.id, "Selam", agent="general")
    assert r.agent != "vision"


def test_chat_rejects_broken_image(rt):
    with pytest.raises(ChatError, match="okunamadı"):
        ChatBook(rt).upload_binary("x.png", base64.b64encode(b"degil").decode())


def test_handoff_never_sends_screenshots_to_claude(rt, fake_ollama, fake_ocr):
    book = ChatBook(rt)
    conv = book.create()
    a = book.upload_binary("e.png", base64.b64encode(png()).decode())
    fake_ollama.chat_replies = [good_answer("Bir fatura.")]
    user, _ = _send(book, conv.id, "ne var?", attachment_ids=[a.id])
    rt.claude.enable()
    reply, runner = book.handoff(conv.id, user.id)
    runner()
    task = rt.store.get(book.view(conv.id).messages[-1].job_id)
    blob = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
    assert "KYA-2026-0042" not in blob and "Claude'a gönderilmez" in " ".join(reply.warnings)


# ---------------------------------------------------------------- taranmış PDF

def test_scanned_pdf_is_read_with_ocr(fake_ocr):
    from kayaai.business.readers import read_pdf

    doc = read_pdf(make_pdf(["x", "y"], text=False), "tarama.pdf")
    assert doc.ocr and len(doc.pages) == 2 and "1.680,00" in doc.pages[0] and len(fake_ocr) == 2


def test_scanned_pdf_summary_warns_about_ocr(rt, fake_ollama, fake_ocr):
    from kayaai.business import run_mode

    fake_ollama.chat_replies = [good_answer("- Fatura toplamı 1.680,00 TL [s.1]")] * 4
    res = run_mode(rt, "summarize", make_pdf(["x"], text=False), "tarama.pdf", "")
    assert res.warnings[0].startswith("Taranmış PDF")


def test_scanned_pdf_ocr_finds_nothing():
    """Windows'ta gerçek OCR boş sayfada yazı bulamaz (sahibin kurulumunda görüldü): anlaşılır hata."""
    from kayaai.business.readers import ReadError, read_pdf

    ocr.set_engine(lambda b: OcrResult(text="", engine="fake"))
    try:
        with pytest.raises(ReadError, match="metin içermiyor.*okunabilir yazı bulamadı"):
            read_pdf(make_pdf(["x"], text=False), "tarama.pdf")
    finally:
        ocr.set_engine(None)


def test_scanned_pdf_without_ocr_explains(no_ocr):
    from kayaai.business.readers import ReadError, read_pdf

    with pytest.raises(ReadError, match="OCR çalışmadı"):
        read_pdf(make_pdf(["x"], text=False), "tarama.pdf")


# ---------------------------------------------------------------- CLI / API

def test_cli_screen_with_file(env, fake_ollama, fake_ocr, tmp_path, capsys):
    from kayaai.cli import main

    f = tmp_path / "ekran.png"
    f.write_bytes(png())
    fake_ollama.chat_replies = [good_answer("Toplam 1.680,00 TL.")]
    assert main(["screen", "Toplam", "ne?", "--file", str(f)]) == 0
    out = capsys.readouterr().out
    assert "1.680,00 TL" in out and "doğrulandı" in out and "OCR: test/özel motor" in out


def test_api_perception(env, fake_ollama, fake_ocr, tmp_path):
    from kayaai.api import create_app

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        st = c.get("/api/perception/status", headers=h).json()
        assert st["ocr"]["available"] and st["vision_model"] == "qwen2.5vl:7b"
        fake_ollama.chat_replies = [good_answer("Toplam 1.680,00 TL.")]
        r = c.post("/api/perception/image", json={"data_b64": base64.b64encode(png()).decode(), "question": "Toplam?"},
                   headers=h)
        assert r.status_code == 200 and r.json()["result"]["verified"] is True
        assert c.post("/api/perception/image", json={"data_b64": base64.b64encode(b"degil-resim").decode()},
                      headers=h).status_code == 400


def test_ocr_comma_misread_still_verifies(rt, fake_ollama):
    """Windows bench (2026-11-01): OCR virgülü '1' okudu (1.680,00 → 1.680100); model doğru okudu → doğrulanmalı."""
    from kayaai.perception.vision import ocr_comma_variants

    bench_ocr = "Fatura No: KYA-2026-0042\nAra toplam: 1.400100 TL\nKDV %20: 280100 TL\nGENEL TOPLAM: 1.680100 TL"
    assert ocr_comma_variants(bench_ocr) == [1400.0, 280.0, 1680.0]
    assert ocr_comma_variants("Telefon 5551001, 280100 adet") == []
    ocr.set_engine(lambda b: OcrResult(text=bench_ocr, engine="fake"))
    try:
        fake_ollama.chat_replies = [good_answer("Genel toplam 1.680,00 TL, KDV 280,00 TL.")]
        res = see(rt, [png()], "Genel toplam ne kadar?")
        assert res.verified is True and res.unverified_numbers == []
        fake_ollama.chat_replies = [good_answer("Genel toplam 1.860,00 TL.")]  # gerçekten yanlış sayı yine yakalanır
        assert see(rt, [png()], "Genel toplam?").unverified_numbers == [1860.0]
    finally:
        ocr.set_engine(None)
