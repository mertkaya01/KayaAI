"""Adım 12c: canlı altyazı — bölütleyici, oturum + çeviri, WebSocket, döküm kaydı."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.speech import stt
from kayaai.speech.live import LiveSession, Segmenter, to_srt, to_txt
from kayaai.speech.stt import Segment

R = 16000


def tone(sec: float, amp: float = 0.2, f: float = 300) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * f * np.arange(int(sec * R)) / R)).astype(np.float32)


def quiet(sec: float, amp: float = 0.002, seed: int = 0) -> np.ndarray:
    return (amp * np.random.default_rng(seed).standard_normal(int(sec * R))).astype(np.float32)


def run(seg: Segmenter, audio: np.ndarray, chunk: float = 0.1):
    out = []
    step = int(chunk * R)
    for i in range(0, len(audio), step):
        out += seg.feed(audio[i:i + step])
    return out + seg.flush()


# ---------------------------------------------------------------- bölütleyici

def test_segmenter_splits_on_silence():
    audio = np.concatenate([quiet(1), tone(1.2), quiet(1, seed=1), tone(2.2), quiet(1, seed=2)])
    ev = run(Segmenter(), audio)
    finals = [e for e in ev if e[0] == "final"]
    assert len(finals) == 2
    (_, a1, s1, e1), (_, a2, s2, e2) = finals
    assert s1 == pytest.approx(0.7, abs=0.15) and e1 == pytest.approx(2.8, abs=0.15)  # ön tampon 0,3 sn + 0,6 sn sessizlik
    assert s2 == pytest.approx(2.9, abs=0.2) and len(a2) / R == pytest.approx(3.1, abs=0.3)
    assert any(e[0] == "partial" for e in ev)  # uzun ifadede ara sonuç


def test_segmenter_forces_split_on_long_speech():
    """Duraksamadan konuşma (hece aralarında 0,2 sn düşüş, 0,6 sn sessizlik yok) 8 sn'de bölünür."""
    syllables = np.concatenate([np.concatenate([tone(0.4), quiet(0.2, seed=i)]) for i in range(34)])  # ~20 sn
    finals = [e for e in run(Segmenter(), np.concatenate([quiet(0.5), syllables])) if e[0] == "final"]
    assert len(finals) >= 2 and all(len(a) / R <= 8.1 for _, a, _, _ in finals)
    assert sum(len(a) for _, a, _, _ in finals) / R > 18  # konuşmanın tamamı kapsandı


def test_segmenter_ignores_silence_and_short_clicks():
    assert run(Segmenter(), quiet(5)) == []
    assert [e for e in run(Segmenter(), np.concatenate([quiet(1), tone(0.1), quiet(1, seed=3)])) if e[0] == "final"] == []


def test_segmenter_adapts_to_background_noise():
    noisy = lambda s, seed: quiet(s, amp=0.03, seed=seed)  # noqa: E731
    finals = [e for e in run(Segmenter(), np.concatenate([noisy(3, 1), tone(1.5, amp=0.3), noisy(2, 2)])) if e[0] == "final"]
    assert len(finals) == 1 and len(finals[0][1]) / R < 3


# ---------------------------------------------------------------- oturum

@pytest.fixture
def settings(tmp_path: Path, monkeypatch, fake_ollama):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def heard():
    calls: list[float] = []

    def model(samples, language):
        calls.append(len(samples) / R)
        return f"Yarın toplantı var {len(calls)}", "tr", [Segment(start=0, end=1, text="x")]

    stt.set_model(model)
    yield calls
    stt.set_model(None)


def speech_audio() -> np.ndarray:
    return np.concatenate([quiet(0.6), tone(1.2), quiet(1, seed=1), tone(1.0), quiet(1, seed=2)])


def test_session_transcribes_and_translates(settings, fake_ollama, heard):
    fake_ollama.chat_replies = ["There is a meeting tomorrow 1", '"There is a meeting tomorrow 2"']
    msgs: list[dict] = []
    with build_runtime(settings) as rt:
        s = LiveSession(rt, msgs.append, "auto", "en", partials=False)
        a = speech_audio()
        s.feed_pcm16((a * 32767).astype("<i2").tobytes())
        s.stop()
    finals = [m for m in msgs if m["type"] == "final"]
    assert [f["text"] for f in finals] == ["Yarın toplantı var 1", "Yarın toplantı var 2"]
    assert [f["translation"] for f in finals] == ["There is a meeting tomorrow 1", "There is a meeting tomorrow 2"]
    assert finals[0]["lang"] == "tr" and finals[0]["start"] < finals[0]["end"] <= finals[1]["start"]
    chat = [b for (_, p, b) in fake_ollama.requests if p == "/api/chat"]
    assert "into English" in chat[0]["messages"][0]["content"] and "Previous subtitles" in chat[1]["messages"][0]["content"]


@pytest.mark.parametrize("target", ["tr", "none"])
def test_session_skips_translation_when_not_needed(settings, fake_ollama, heard, target):
    msgs: list[dict] = []
    with build_runtime(settings) as rt:
        s = LiveSession(rt, msgs.append, "auto", target, partials=False)
        s.feed(speech_audio())
        s.stop()
    finals = [m for m in msgs if m["type"] == "final"]
    assert finals and all(f["translation"] is None for f in finals)
    assert not [p for (_, p, _) in fake_ollama.requests if p == "/api/chat"]


def test_bad_translation_is_dropped(settings, fake_ollama, heard):
    fake_ollama.chat_replies = ["会议明天", "There is a meeting"]
    msgs: list[dict] = []
    with build_runtime(settings) as rt:
        s = LiveSession(rt, msgs.append, "auto", "en", partials=False)
        s.feed(speech_audio())
        s.stop()
    assert [m["translation"] for m in msgs if m["type"] == "final"] == [None, "There is a meeting"]


def test_transcript_formats():
    lines = [{"start": 0.5, "end": 2.25, "text": "Merhaba", "translation": "Hello"},
             {"start": 3661.0, "end": 3662.5, "text": "Nasılsın", "translation": None}]
    assert to_srt(lines) == "1\n00:00:00,500 --> 00:00:02,250\nHello\n\n2\n01:01:01,000 --> 01:01:02,500\nNasılsın\n"
    assert to_txt(lines) == "Merhaba\n  → Hello\nNasılsın\n"


# ---------------------------------------------------------------- WebSocket + API

def test_websocket_live_subtitles(settings, fake_ollama, heard, tmp_path):
    from kayaai.api import create_app

    fake_ollama.chat_replies = ["There is a meeting tomorrow"] * 5
    app = create_app(settings, ui_dir=tmp_path / "noui")
    tok = app.state.token
    with TestClient(app) as c:
        with c.websocket_connect(f"/api/speech/live?token={tok}") as ws:
            ws.send_json({"type": "start", "source_lang": "auto", "target": "en", "source": "mic"})
            assert ws.receive_json()["status"] == "listening"
            pcm = (speech_audio() * 32767).astype("<i2").tobytes()
            for i in range(0, len(pcm), 3200):
                ws.send_bytes(pcm[i:i + 3200])
            ws.send_text(json.dumps({"type": "stop"}))
            msgs = []
            while True:
                m = ws.receive_json()
                msgs.append(m)
                if m["type"] == "status" and m["status"] == "stopped":
                    break
        finals = [m for m in msgs if m["type"] == "final"]
        assert len(finals) == 2 and finals[0]["translation"] == "There is a meeting tomorrow"
        ev = [e["data"] for e in app.state.runtime.store.events_since(0) if e["type"] == "speech.live"]
        assert ev[0]["status"] == "started" and ev[-1]["lines"] == 2 and "toplantı" not in json.dumps(ev)

        h = {"Authorization": f"Bearer {tok}"}
        r = c.post("/api/speech/transcript", json={"format": "srt", "lines": [
            {"start": f["start"], "end": f["end"], "text": f["text"], "translation": f["translation"]} for f in finals]},
            headers=h).json()
        assert r["status"] == "done"
        saved = Path(r["result"]["path"])
        assert saved.parent.name == "altyazilar" and "There is a meeting tomorrow" in saved.read_text(encoding="utf-8")


def test_websocket_rejects_bad_token_and_missing_model(settings, tmp_path):
    from starlette.websockets import WebSocketDisconnect

    from kayaai.api import create_app

    app = create_app(settings, ui_dir=tmp_path / "noui")
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/speech/live?token=yanlis") as ws:
                ws.receive_json()
        with c.websocket_connect(f"/api/speech/live?token={app.state.token}") as ws:
            ws.send_json({"type": "start"})
            m = ws.receive_json()
            assert m["type"] == "error" and m["fatal"] and "kurulu değil" in m["message"]
