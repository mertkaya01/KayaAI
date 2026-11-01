"""`kayaai bench` (Adım 13b): tek komutla gerçek donanımda ölçüm → `data/bench.json`.

Ölçülenler: genel model (soğuk = ilk yükleme dahil / sıcak), token/sn; embedding; görsel model (OCR dahil); Whisper
(yükleme ayrı, gerçek zaman oranı); süre boyunca VRAM tepe kullanımı. Yalnız kurulu olanlar ölçülür; görev geçmişi
kirlenmesin diye ayrı veri klasöründe (data/checks/bench) çalışır.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import Settings


class _VramSampler:
    def __init__(self) -> None:
        from .llm.vram import free_vram

        self._free = free_vram
        self.peak_used_mb: int | None = None
        self.total_mb: int | None = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True, name="kayaai-bench-vram")

    def _loop(self) -> None:
        while not self._stop.wait(0.5):
            p = self._free()
            if p:
                used = p[1] - p[0]
                self.total_mb = p[1]
                self.peak_used_mb = max(self.peak_used_mb or 0, used)

    def __enter__(self) -> "_VramSampler":
        self._t.start()
        return self

    def __exit__(self, *a: object) -> None:
        self._stop.set()
        self._t.join(2)


def _sample_image() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    from .business.report import FONT_CANDIDATES

    path = next((r for r, _ in FONT_CANDIDATES if Path(r).is_file()), None)
    font = ImageFont.truetype(path, 28) if path else ImageFont.load_default()
    img = Image.new("RGB", (1100, 300), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(["Fatura No: KYA-2026-0042", "Ara toplam: 1.400,00 TL", "KDV %20: 280,00 TL",
                              "GENEL TOPLAM: 1.680,00 TL"]):
        d.text((40, 30 + 60 * i), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_bench(settings: Settings, log: Any = print) -> dict[str, Any]:
    from .runtime import build_runtime

    real = settings.model_copy(deep=True)
    work = settings.data_dir / "checks" / "bench"
    shutil.rmtree(work, ignore_errors=True)
    settings.data_dir = work / "data"
    settings.files.home_dir = str(work / "files")
    out: dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    with build_runtime(settings) as rt, _VramSampler() as vs:
        try:
            installed = {m.get("name") for m in rt.llm.list_models()}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Ollama'ya ulaşılamadı: {exc}"}

        def have(name: str) -> bool:
            return name in installed or f"{name}:latest" in installed

        # 1) genel model: soğuk (boşaltıp) ve sıcak
        gen = rt.registry.model_for_worker("general")
        if have(gen.name):
            try:
                rt.llm.unload_model(gen.name)
            except Exception:  # noqa: BLE001
                pass
            rows = []
            for label in ("soğuk", "sıcak", "sıcak"):
                t0 = time.monotonic()
                t = rt.orchestrator.ask("Kendini tek cümleyle tanıt.", worker="general")
                rows.append({"run": label, "seconds": round(time.monotonic() - t0, 2),
                             "tokens_per_second": (t.metrics or {}).get("tokens_per_second"), "ok": t.status.value == "succeeded"})
            out["chat"] = {"model": gen.name, "runs": rows}
            log(f"Sohbet ({gen.name}): soğuk {rows[0]['seconds']} sn · sıcak {rows[-1]['seconds']} sn · "
                f"{rows[-1]['tokens_per_second']} token/sn")
        # 2) embedding
        emb = rt.registry.models.get(settings.memory.embed_model)
        if emb and have(emb.name):
            texts = [f"Örnek cümle {i}: Atlas projesinin teslim tarihi yaklaşıyor." for i in range(20)]
            rt.llm.embed(emb.name, texts[:1])
            t0 = time.monotonic()
            rt.llm.embed(emb.name, texts)
            ms = round((time.monotonic() - t0) * 1000 / len(texts), 1)
            out["embed"] = {"model": emb.name, "ms_per_text": ms}
            log(f"Embedding ({emb.name}): {ms} ms/metin")
        # 3) görsel model
        vis = rt.registry.models.get("vision-7b")
        if vis and have(vis.name):
            from .perception.vision import VisionError, see

            img = _sample_image()
            runs = []
            for _ in range(2):
                t0 = time.monotonic()
                try:
                    r = see(rt, [img], "Genel toplam ne kadar?")
                    runs.append({"seconds": round(time.monotonic() - t0, 2), "verified": r.verified,
                                 "correct": "1.680" in r.answer})
                except VisionError as exc:
                    runs.append({"error": str(exc)})
            out["vision"] = {"model": vis.name, "runs": runs}
            log(f"Görsel ({vis.name}): soğuk {runs[0].get('seconds')} sn · sıcak {runs[-1].get('seconds')} sn")
        # 4) Whisper
        from .speech.stt import SpeechError, is_installed, release, status, transcribe

        if is_installed(real) and sys.platform == "win32":
            from .speech.tts_win import synth_wav, wer

            release()
            text = "Please schedule a meeting with the design team next Tuesday afternoon."
            wav = work / "bench.wav"
            if synth_wav(text, "en-US", wav):
                rows = []
                for _ in range(2):
                    try:
                        t = transcribe(real, wav.read_bytes(), "en")
                        rows.append({"load_s": t.load_seconds, "seconds": t.seconds, "audio_s": t.audio_seconds,
                                     "rtf": round(t.seconds / max(0.01, t.audio_seconds), 3), "wer": wer(text, t.text),
                                     "device": t.device})
                    except SpeechError as exc:
                        rows.append({"error": str(exc)})
                out["whisper"] = {"model": real.speech.model, "runs": rows, "gpu_error": status(real)["gpu_error"]}
                log(f"Whisper: yükleme {rows[0].get('load_s')} sn · gerçek zaman oranı {rows[-1].get('rtf')} · "
                    f"{rows[-1].get('device')}")
    out["vram"] = {"peak_used_mb": vs.peak_used_mb, "total_mb": vs.total_mb}
    if vs.peak_used_mb:
        log(f"VRAM tepe: {vs.peak_used_mb / 1024:.1f} / {(vs.total_mb or 0) / 1024:.1f} GB")
    path = real.data_dir / "bench.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    out["path"] = str(path)
    return out
