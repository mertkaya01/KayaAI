"""Canlı çeviri altyazı (Adım 12c, kabul #9–#10).

Tarayıcı sesi (sistem sesi `getDisplayMedia` ya da mikrofon) 16 kHz mono PCM parçaları olarak WebSocket'ten gelir →
`Segmenter` enerjiye dayalı konuşma algılamayla cümle/ifade sınırlarını bulur → Whisper (speech/stt) yazıya çevirir →
gerekirse yerel genel model (qwen3:8b) çevirir → altyazı mesajları geri gönderilir.

Ses ve altyazı metni saklanmaz (olay kaydına yalnız oturum başlangıç/bitiş ve sayılar yazılır); döküm yalnızca sahip
"Kaydet" derse `~/kayaAI-files/altyazilar` altına yazılır.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from .stt import SAMPLE_RATE, SpeechError, transcribe_samples

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)
MAX_SESSION_S = 2 * 3600
LANG_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
              "ru": "Russian", "ar": "Arabic", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "nl": "Dutch",
              "pt": "Portuguese"}


class Segmenter:
    """Enerji tabanlı konuşma bölütleyici: ifade bitince (sessizlik) ya da çok uzayınca 'final', arada 'partial' üretir.

    Gürültü tabanı son ~10 sn'deki çerçeve enerjilerinin 10. yüzdeliğinden kestirilir (konuşmadaki doğal duraklar tabanı
    taşır); eşik = max(taban×3, en_az). İlk ~0,3 sn yalnız öğrenilir (gürültü konuşma sanılmasın).
    """

    def __init__(self, rate: int = SAMPLE_RATE, frame_ms: int = 30, silence_end_s: float = 0.6,
                 max_utt_s: float = 8.0, min_speech_s: float = 0.3, partial_every_s: float = 1.5,
                 preroll_s: float = 0.3, min_rms: float = 0.006):
        self.rate, self.frame = rate, int(rate * frame_ms / 1000)
        self.silence_end = int(silence_end_s * 1000 / frame_ms)
        self.max_frames = int(max_utt_s * 1000 / frame_ms)
        self.min_speech = int(min_speech_s * 1000 / frame_ms)
        self.partial_every = int(partial_every_s * 1000 / frame_ms)
        self.min_rms = min_rms
        self._pending = np.zeros(0, dtype=np.float32)
        self._history: deque[float] = deque(maxlen=int(10_000 / frame_ms))
        self._warmup = max(1, int(300 / frame_ms))
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, int(preroll_s * 1000 / frame_ms)))
        self._utt: list[np.ndarray] = []
        self._speech_frames = 0
        self._silence = 0
        self._since_partial = 0
        self.t = 0.0                      # işlenen ses süresi (sn)
        self._utt_start = 0.0

    def threshold(self) -> float:
        floor = float(np.percentile(np.fromiter(self._history, dtype=np.float32), 10)) if self._history else 0.0
        return max(self.min_rms, floor * 3)

    def _final(self) -> tuple[str, np.ndarray, float, float] | None:
        audio = np.concatenate(self._utt) if self._utt else np.zeros(0, dtype=np.float32)
        ok = self._speech_frames >= self.min_speech
        start = self._utt_start
        self._utt, self._speech_frames, self._silence, self._since_partial = [], 0, 0, 0
        return ("final", audio, start, self.t) if ok else None

    def feed(self, samples: np.ndarray) -> list[tuple[str, np.ndarray, float, float]]:
        """Yeni ses → [(tür, ses, başlangıç_sn, bitiş_sn)] (tür: 'partial' | 'final')."""
        out: list[tuple[str, np.ndarray, float, float]] = []
        buf = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        n = len(buf) // self.frame
        self._pending = buf[n * self.frame:]
        for i in range(n):
            fr = buf[i * self.frame:(i + 1) * self.frame]
            rms = float(np.sqrt(np.mean(fr * fr)))
            self._history.append(rms)
            speech = len(self._history) > self._warmup and rms > self.threshold()
            self.t += self.frame / self.rate
            if not self._utt:
                if speech:
                    self._utt = list(self._preroll) + [fr]
                    self._utt_start = max(0.0, self.t - len(self._utt) * self.frame / self.rate)
                    self._speech_frames, self._silence, self._since_partial = 1, 0, 0
                else:
                    self._preroll.append(fr)
                continue
            self._utt.append(fr)
            self._since_partial += 1
            if speech:
                self._speech_frames += 1
                self._silence = 0
            else:
                self._silence += 1
            if self._silence >= self.silence_end or len(self._utt) >= self.max_frames:
                ev = self._final()
                if ev:
                    out.append(ev)
                self._preroll.clear()
            elif self._since_partial >= self.partial_every and self._speech_frames >= self.min_speech:
                self._since_partial = 0
                out.append(("partial", np.concatenate(self._utt), self._utt_start, self.t))
        return out

    def flush(self) -> list[tuple[str, np.ndarray, float, float]]:
        ev = self._final() if self._utt else None
        return [ev] if ev else []


Target = Literal["tr", "en", "none"]


class LiveSession:
    """Bir altyazı oturumu: ses parçaları kuyruğa, işleme ayrı iş parçacığında (WebSocket döngüsü beklemez)."""

    def __init__(self, rt: "Runtime", send: Callable[[dict[str, Any]], None], source_lang: str = "auto",
                 target: Target = "tr", partials: bool = True, settings: Any = None):
        self.rt, self.send = rt, send
        self.settings = settings or rt.settings  # ses modeli yeri (kontrol betiği ayrı veri klasörüyle çalışır)
        self.source_lang = None if source_lang == "auto" else source_lang
        self.target = target
        self.partials = partials
        self.seg = Segmenter()
        self._q: queue.Queue[tuple[str, Any] | None] = queue.Queue()
        self.lines: list[dict[str, Any]] = []
        self.started = time.monotonic()
        self._context: deque[str] = deque(maxlen=2)
        self._slow = False
        self._thread = threading.Thread(target=self._loop, name="kayaai-subtitles", daemon=True)
        self._thread.start()

    # -------------------------------------------------------------- giriş

    def feed_pcm16(self, data: bytes) -> None:
        if len(data) % 2:
            data = data[:-1]
        self.feed(np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0)

    def feed(self, samples: np.ndarray) -> None:
        for kind, audio, start, end in self.seg.feed(samples):
            if kind == "partial" and (not self.partials or self._slow or self._q.qsize() > 0):
                continue  # geride kalındıysa ara sonuçları atla, yalnız kesin altyazılar
            self._q.put((kind, (audio, start, end, time.monotonic())))

    def stop(self, flush: bool = True) -> None:
        if flush:
            for _, audio, start, end in self.seg.flush():
                self._q.put(("final", (audio, start, end, time.monotonic())))
        self._q.put(None)
        self._thread.join(timeout=120)

    # -------------------------------------------------------------- işleme

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            kind, (audio, start, end, wall) = item
            try:
                t = transcribe_samples(self.settings, audio, self.source_lang)
            except SpeechError as exc:
                self.send({"type": "error", "message": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 - oturum düşmesin
                log.exception("altyazı tanıma hatası")
                self.send({"type": "error", "message": f"Ses tanıma hatası: {exc}"})
                continue
            self._slow = t.seconds > 0.8 * max(0.5, t.audio_seconds)  # gerçek zamandan yavaşsa ara sonuç yok
            text = t.text.strip()
            if kind == "partial":
                if text:
                    self.send({"type": "partial", "text": text})
                continue
            if not text:
                self.send({"type": "partial", "text": ""})
                continue
            lang = (t.language or self.source_lang or "").lower()[:2] or None
            translation = None
            if self.target != "none" and lang != self.target:
                translation = self._translate(text, lang)
            line = {"type": "final", "id": len(self.lines) + 1, "text": text, "lang": lang, "translation": translation,
                    "start": round(start, 2), "end": round(end, 2), "device": t.device,
                    "latency_s": round(time.monotonic() - wall, 2)}  # ifade bitişinden altyazıya
            self.lines.append(line)
            self._context.append(translation or text)
            self.send(line)

    def _translate(self, text: str, lang: str | None) -> str | None:
        from ..core.lang import foreign_script

        src = LANG_NAMES.get(lang or "", "the source language")
        tgt = LANG_NAMES[self.target]
        spec = self.rt.registry.model_for_worker("general")
        ctx = "\n".join(self._context)
        system = (f"You translate live subtitles from {src} into {tgt}. Output ONLY the {tgt} translation of the user's "
                  "line: one line, no quotes, no notes, no explanations. Keep names and numbers unchanged."
                  + (f"\nPrevious subtitles (context only, do not translate again):\n{ctx}" if ctx else ""))
        try:
            r = self.rt.llm.chat(spec.name, [{"role": "system", "content": system}, {"role": "user", "content": text}],
                                 options={**spec.ollama_options(), "temperature": 0.1}, think=spec.think,
                                 keep_alive=spec.keep_alive, timeout=30)
        except Exception as exc:  # noqa: BLE001 - çeviri olmazsa özgün metin gösterilir
            log.warning("altyazı çevirisi başarısız: %s", exc)
            return None
        out = " ".join(r.content.strip().strip('"“”').split())
        if not out or foreign_script(out, text):
            return None
        return out


def to_srt(lines: list[dict[str, Any]], use_translation: bool = True) -> str:
    def ts(s: float) -> str:
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    out = []
    for i, ln in enumerate(lines, 1):
        text = (ln.get("translation") if use_translation else None) or ln.get("text", "")
        out.append(f"{i}\n{ts(float(ln.get('start', 0)))} --> {ts(float(ln.get('end', 0)))}\n{text}\n")
    return "\n".join(out)


def to_txt(lines: list[dict[str, Any]]) -> str:
    out = []
    for ln in lines:
        out.append(ln.get("text", ""))
        if ln.get("translation"):
            out.append(f"  → {ln['translation']}")
    return "\n".join(out) + "\n"
