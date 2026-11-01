"""Ses tanıma (Adım 12b) — faster-whisper (MIT) + large-v3-turbo (MIT), tamamen yerel.

- GPU (CUDA float16) denenir; cuBLAS/cuDNN yoksa ya da kart desteklenmiyorsa işlemciye (int8) düşülür ve nedeni raporlanır.
- Ses diske yazılmaz: bayt → bellekte çözülür (PyAV) → model.
- Model ilk kullanımdan önce **sahip onayıyla** indirilir (`speech.download`, R2; ~1,6 GB, huggingface.co).
- Model süreçte bir kez yüklenir; `idle_unload_s` boyunca kullanılmazsa bellekten (VRAM) çıkarılır.
Testler `set_model()` ile sahte model takar (çözme gerçek kalır).
"""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
APPROX_MB = {"large-v3-turbo": 1620, "large-v3": 3100, "medium": 1530, "small": 485, "base": 145, "tiny": 75}


class SpeechError(ValueError):
    pass


class SpeechUnavailable(SpeechError):
    pass


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    text: str
    language: str | None = None
    audio_seconds: float = 0.0
    seconds: float = 0.0          # tanıma süresi (model yükleme hariç)
    load_seconds: float = 0.0     # bu çağrıda model belleğe yüklendiyse süresi
    device: str | None = None     # cuda | cpu | test
    segments: list[Segment] = Field(default_factory=list)


# (örnekler, dil) → (metin, algılanan dil, bölümler)
ModelFn = Callable[[Any, str | None], tuple[str, str | None, list[Segment]]]
_FAKE: ModelFn | None = None
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"model": None, "key": None, "device": None, "gpu_error": None, "last_used": 0.0, "timer": None}


def set_model(fn: ModelFn | None) -> None:
    """Testler için sahte model (None: gerçek modele dön)."""
    global _FAKE
    _FAKE = fn


def model_dir(settings: "Settings", name: str | None = None) -> Path:
    return settings.data_dir / "models" / "whisper" / (name or settings.speech.model)


def is_installed(settings: "Settings", name: str | None = None) -> bool:
    return _FAKE is not None or (model_dir(settings, name) / "model.bin").is_file()


def status(settings: "Settings") -> dict[str, Any]:
    d = model_dir(settings)
    return {"model": settings.speech.model, "installed": is_installed(settings), "dir": str(d),
            "approx_mb": APPROX_MB.get(settings.speech.model), "loaded": _STATE["model"] is not None,
            "device": _STATE["device"], "gpu_error": _STATE["gpu_error"], "max_seconds": settings.speech.max_seconds}


# ---------------------------------------------------------------------------- GPU kütüphaneleri (Windows)


def _add_nvidia_dll_dirs() -> None:
    """pip'le kurulan nvidia-cublas-cu12 / nvidia-cudnn-cu12 DLL klasörlerini arama yoluna ekler (Windows)."""
    if sys.platform != "win32":
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            mod = __import__(pkg, fromlist=["__path__"])
        except ImportError:
            continue
        for base in getattr(mod, "__path__", []):
            b = Path(base) / "bin"
            if b.is_dir():
                os.add_dll_directory(str(b))  # type: ignore[attr-defined]
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------- model


def _load(settings: "Settings", force_cpu: bool = False) -> Any:
    from faster_whisper import WhisperModel

    d = model_dir(settings)
    if not (d / "model.bin").is_file():
        raise SpeechUnavailable(f"Ses tanıma modeli kurulu değil ({settings.speech.model}). İndir: kayaai speech download "
                                "(ya da arayüzde mikrofon → İndir; sahip onayı gerekir)")
    want = "cpu" if force_cpu else settings.speech.device
    if want in ("auto", "cuda"):
        _add_nvidia_dll_dirs()
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                m = WhisperModel(str(d), device="cuda", compute_type="float16")
                _STATE.update(device="cuda", gpu_error=None)
                return m
            _STATE["gpu_error"] = "CUDA aygıtı bulunamadı"
        except Exception as exc:  # noqa: BLE001 - eksik DLL, desteklenmeyen kart…
            _STATE["gpu_error"] = f"{type(exc).__name__}: {exc}"[:300]
        if want == "cuda":
            raise SpeechUnavailable(f"GPU'da ses tanıma başlatılamadı: {_STATE['gpu_error']}")
    m = WhisperModel(str(d), device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) // 2))
    _STATE["device"] = "cpu"
    return m


def _schedule_unload(settings: "Settings") -> None:
    t = _STATE.get("timer")
    if t is not None:
        t.cancel()
    t = threading.Timer(settings.speech.idle_unload_s, release)
    t.daemon = True
    t.start()
    _STATE["timer"] = t


def release() -> None:
    """Modeli bellekten (VRAM) çıkarır."""
    with _LOCK:
        _STATE.update(model=None, key=None)


def _is_gpu_runtime_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("cublas", "cudnn", "cuda", ".dll", "library", "no kernel image"))


def decode(audio: bytes) -> Any:
    """Ses baytları (webm/opus, wav, mp3, m4a…) → 16 kHz mono float32 dizi. Diske yazılmaz."""
    from faster_whisper import decode_audio

    if not audio:
        raise SpeechError("Ses boş")
    try:
        return decode_audio(io.BytesIO(audio), sampling_rate=SAMPLE_RATE)
    except Exception as exc:  # noqa: BLE001 - PyAV çözme hataları çeşitli
        raise SpeechError(f"Ses çözülemedi (desteklenmeyen biçim ya da bozuk kayıt): {type(exc).__name__}") from exc


def transcribe_samples(settings: "Settings", samples: Any, language: str | None = None) -> Transcript:
    lang = None if (language or settings.speech.language) == "auto" else (language or settings.speech.language)
    audio_s = round(len(samples) / SAMPLE_RATE, 2)
    if audio_s > settings.speech.max_seconds + 1:
        raise SpeechError(f"Kayıt çok uzun ({audio_s:.0f} sn > {settings.speech.max_seconds} sn)")
    t0 = time.monotonic()
    if _FAKE is not None:
        text, detected, segs = _FAKE(samples, lang)
        return Transcript(text=text.strip(), language=detected, audio_seconds=audio_s,
                          seconds=round(time.monotonic() - t0, 2), device="test", segments=segs)
    if audio_s < 0.3:
        return Transcript(text="", language=lang, audio_seconds=audio_s, device=_STATE["device"])
    load_s = 0.0
    with _LOCK:
        key = (str(model_dir(settings)), settings.speech.device)
        if _STATE["model"] is None or _STATE["key"] != key:
            _STATE.update(model=_load(settings), key=key)
            load_s = time.monotonic() - t0
            t0 = time.monotonic()  # tanıma süresi yüklemeden ayrı (Windows ölçümü: ilk çağrı 23 sn görünüyordu)

        def run(model: Any) -> tuple[str, str | None, list[Segment]]:
            segments, info = model.transcribe(samples, language=lang, beam_size=settings.speech.beam_size,
                                              vad_filter=True, condition_on_previous_text=False)
            segs = [Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segments]
            return " ".join(s.text for s in segs).strip(), info.language, segs

        try:
            text, detected, segs = run(_STATE["model"])
        except Exception as exc:  # noqa: BLE001
            if _STATE["device"] != "cuda" or not _is_gpu_runtime_error(exc):
                raise SpeechError(f"Ses tanıma hatası: {exc}") from exc
            log.warning("GPU ses tanıma çalışmadı, işlemciye geçiliyor: %s", exc)
            _STATE["gpu_error"] = f"{type(exc).__name__}: {exc}"[:300]
            _STATE["model"] = _load(settings, force_cpu=True)
            text, detected, segs = run(_STATE["model"])
        _STATE["last_used"] = time.monotonic()
    _schedule_unload(settings)
    return Transcript(text=text, language=detected, audio_seconds=audio_s, seconds=round(time.monotonic() - t0, 2),
                      load_seconds=round(load_s, 2), device=_STATE["device"], segments=segs)


def transcribe(settings: "Settings", audio: bytes, language: str | None = None) -> Transcript:
    """Ses kaydını yazıya çevirir (bas-konuş). Kayıt saklanmaz."""
    if _FAKE is None and not is_installed(settings):
        _load(settings)  # anlaşılır "kurulu değil" hatası
    return transcribe_samples(settings, decode(audio), language)


# ---------------------------------------------------------------------------- indirme (sahip onayıyla)

_DL: dict[str, Any] = {}


def download_state() -> dict[str, Any]:
    return dict(_DL)


def _dir_mb(d: Path) -> float:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6 if d.is_dir() else 0.0


def download(settings: "Settings", emit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Modeli Hugging Face'ten indirir (faster-whisper'ın kendi indiricisi). İlerleme klasör boyutundan izlenir."""
    from faster_whisper import download_model

    name = settings.speech.model
    d = model_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    total = APPROX_MB.get(name)
    _DL.clear()
    _DL.update(model=name, status="indiriliyor", percent=0.0, error=None)
    stop = threading.Event()

    def watch() -> None:
        last = -5.0
        while not stop.wait(2):
            if total:
                pct = min(99.0, 100 * _dir_mb(d) / total)
                _DL["percent"] = round(pct, 1)
                if emit and pct - last >= 5:
                    last = pct
                    emit({"model": name, "status": "indiriliyor", "percent": round(pct, 1)})

    w = threading.Thread(target=watch, daemon=True, name="kayaai-whisper-dl")
    w.start()
    try:
        download_model(name, output_dir=str(d))
    except Exception as exc:  # noqa: BLE001 - ağ/hub hataları
        _DL.update(status="hata", error=f"{type(exc).__name__}: {exc}"[:300])
        if emit:
            emit({"model": name, "status": "hata", "error": _DL["error"]})
        raise SpeechError(f"Ses modeli indirilemedi: {_DL['error']}") from exc
    finally:
        stop.set()
    _DL.update(status="tamamlandı", percent=100.0)
    if emit:
        emit({"model": name, "status": "tamamlandı", "percent": 100})
    return {"model": name, "dir": str(d), "mb": round(_dir_mb(d))}
