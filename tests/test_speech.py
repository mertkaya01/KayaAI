"""Adım 12b: ses tanıma — çözme (gerçek PyAV), sahte model, uzunluk sınırı, GPU → işlemci geri düşüş, indirme (R2), API, CLI."""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.speech import SpeechError, request_download, stt
from kayaai.speech.stt import Segment, SpeechUnavailable, transcribe


def wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        t = np.arange(int(seconds * rate))
        w.writeframes((np.sin(2 * np.pi * 440 * t / rate) * 8000).astype("<i2").tobytes())
    return b.getvalue()


def webm(seconds: float = 2.0) -> bytes:
    """Tarayıcı MediaRecorder biçimi (webm/opus), PyAV ile üretilir."""
    import av

    buf = io.BytesIO()
    out = av.open(buf, mode="w", format="webm")
    try:
        st = out.add_stream("libopus", rate=48000)
    except Exception as exc:  # noqa: BLE001 - kodlayıcısız PyAV derlemesi
        pytest.skip(f"PyAV'da opus kodlayıcı yok: {exc}")
    st.layout = "mono"
    s = (0.3 * np.sin(2 * np.pi * 440 * np.arange(int(48000 * seconds)) / 48000)).astype(np.float32)
    for i in range(0, len(s), 960):
        chunk = s[i:i + 960]
        if len(chunk) < 960:
            chunk = np.pad(chunk, (0, 960 - len(chunk)))
        f = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="flt", layout="mono")
        f.sample_rate = 48000
        for p in st.encode(f):
            out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch, fake_ollama):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def fake_model():
    calls: list[tuple[float, str | None]] = []

    def model(samples, language):
        calls.append((len(samples) / 16000, language))
        return "Yarın sabah toplantı var.", language or "tr", [Segment(start=0, end=1.5, text="Yarın sabah toplantı var.")]

    stt.set_model(model)
    yield calls
    stt.set_model(None)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    stt.release()
    stt._STATE.update(device=None, gpu_error=None)


# ---------------------------------------------------------------- çözme + tanıma

@pytest.mark.parametrize("make,secs", [(wav, 2.0), (webm, 2.0)])
def test_transcribe_decodes_real_audio_formats(settings, fake_model, make, secs):
    t = transcribe(settings, make(secs), "tr")
    assert t.text == "Yarın sabah toplantı var." and t.language == "tr" and t.device == "test"
    assert t.audio_seconds == pytest.approx(secs, abs=0.1) and fake_model[0][1] == "tr"


def test_auto_language_passes_none(settings, fake_model):
    transcribe(settings, wav(1), "auto")
    assert fake_model[-1][1] is None


def test_too_long_recording_is_refused(settings, fake_model):
    settings.speech.max_seconds = 5
    with pytest.raises(SpeechError, match="çok uzun"):
        transcribe(settings, wav(8))


@pytest.mark.parametrize("bad", [b"", b"bu ses degil", b"RIFF\x00\x00\x00\x00WAVEbozuk"])
def test_broken_audio(settings, fake_model, bad):
    with pytest.raises(SpeechError):
        transcribe(settings, bad)


def test_not_installed_explains_download(settings):
    with pytest.raises(SpeechUnavailable, match="kayaai speech download"):
        transcribe(settings, wav(1))


# ---------------------------------------------------------------- GPU → işlemci

class _FakeWM:
    instances: list["_FakeWM"] = []

    def __init__(self, path, device, compute_type, **kw):
        self.device, self.compute_type = device, compute_type
        _FakeWM.instances.append(self)

    def transcribe(self, samples, **kw):
        if self.device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

        class Info:
            language = "tr"

        class S:
            start, end, text = 0.0, 1.0, " Merhaba dünya "

        return iter([S()]), Info()


def test_gpu_failure_falls_back_to_cpu_and_reports_reason(settings, monkeypatch):
    import ctranslate2
    import faster_whisper

    d = stt.model_dir(settings)
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    _FakeWM.instances.clear()
    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeWM)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    t = transcribe(settings, wav(1))
    assert t.text == "Merhaba dünya" and t.device == "cpu"
    assert [(i.device, i.compute_type) for i in _FakeWM.instances] == [("cuda", "float16"), ("cpu", "int8")]
    st = stt.status(settings)
    assert st["installed"] and st["loaded"] and "cublas64_12.dll" in st["gpu_error"]
    t2 = transcribe(settings, wav(1))  # model önbellekte: yeniden yüklenmez
    assert t2.device == "cpu" and len(_FakeWM.instances) == 2
    stt.release()
    assert not stt.status(settings)["loaded"]


def test_no_cuda_device_uses_cpu_directly(settings, monkeypatch):
    import ctranslate2
    import faster_whisper

    d = stt.model_dir(settings)
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    _FakeWM.instances.clear()
    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeWM)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    assert transcribe(settings, wav(1)).device == "cpu"
    assert [i.device for i in _FakeWM.instances] == ["cpu"] and stt.status(settings)["gpu_error"] == "CUDA aygıtı bulunamadı"


# ---------------------------------------------------------------- indirme (R2)

def test_download_needs_owner_approval(settings, monkeypatch):
    import faster_whisper

    def fake_download(name, output_dir):
        (Path(output_dir) / "model.bin").write_bytes(b"0" * 1000)
        return output_dir

    monkeypatch.setattr(faster_whisper, "download_model", fake_download)
    with build_runtime(settings) as rt:
        r = request_download(rt)
        assert r.status == "awaiting_approval" and r.risk.value == "R2"
        assert "huggingface.co" in rt.permissions.get(r.approval_id).action.summary
        assert not stt.is_installed(settings)
        done = rt.permissions.approve(r.approval_id, decided_by="owner")
        assert done.status == "approved", done.error
        assert stt.is_installed(settings)
        events = [e["data"] for e in rt.store.events_since(0) if e["type"] == "speech.download"]
        assert events[-1]["status"] == "tamamlandı"
        with pytest.raises(SpeechError, match="zaten kurulu"):
            request_download(rt)


def test_download_failure_marks_approval_failed(settings, monkeypatch):
    import faster_whisper

    def boom(name, output_dir):
        raise OSError("ağ yok")

    monkeypatch.setattr(faster_whisper, "download_model", boom)
    with build_runtime(settings) as rt:
        r = request_download(rt)
        done = rt.permissions.approve(r.approval_id, decided_by="owner")
        assert done.status == "failed" and "ağ yok" in done.error


# ---------------------------------------------------------------- API / CLI

def test_api_speech(settings, fake_model, tmp_path):
    from kayaai.api import create_app

    app = create_app(settings, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.post("/api/speech/transcribe", json={"data_b64": "eA=="}).status_code == 401
        st = c.get("/api/speech/status", headers=h).json()
        assert st["model"] == "large-v3-turbo" and st["installed"] is True and st["max_seconds"] == 120
        r = c.post("/api/speech/transcribe", json={"data_b64": base64.b64encode(webm(1.5)).decode(), "language": "tr"},
                   headers=h)
        assert r.status_code == 200 and r.json()["text"] == "Yarın sabah toplantı var."
        assert c.post("/api/speech/transcribe", json={"data_b64": base64.b64encode(b"bozuk").decode()},
                      headers=h).status_code == 400
        ev = [e for e in app.state.runtime.store.events_since(0) if e["type"] == "speech.transcribed"]
        assert ev and "toplantı" not in str(ev[-1]["data"])  # metin olay kaydına yazılmaz


def test_api_speech_not_installed_409(settings, tmp_path):
    from kayaai.api import create_app

    app = create_app(settings, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        r = c.post("/api/speech/transcribe", json={"data_b64": base64.b64encode(wav(1)).decode()}, headers=h)
        assert r.status_code == 409 and "kurulu değil" in r.json()["detail"]
        assert c.post("/api/speech/download", headers=h).json()["status"] == "awaiting_approval"


def test_cli_speech(settings, fake_model, tmp_path, capsys):
    from kayaai.cli import main

    f = tmp_path / "not.wav"
    f.write_bytes(wav(1))
    assert main(["speech", "transcribe", str(f), "--lang", "tr"]) == 0
    out = capsys.readouterr().out
    assert "Yarın sabah toplantı var." in out and "dil: tr" in out
    stt.set_model(None)
    assert main(["speech", "status"]) == 0 and "KURULU DEĞİL" in capsys.readouterr().out
