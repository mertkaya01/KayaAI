"""Görüntüyü anlama (Adım 12a): OCR (kodla, deterministik) + yerel görsel model (qwen2.5vl:7b, vision ajanı).

Akış: görüntü(ler) → OCR (Windows) → vision ajanı (görüntü + OCR metni + soru) → cevaptaki sayılar OCR metnine karşı
KODLA denetlenir (Adım 10'daki sayı denetimi). OCR yoksa cevap "doğrulanmadı" olarak işaretlenir.
Ekran içeriği yereldir: Claude'a gitmez (vision ajanının Claude karşılığı yok, MCP aracı yok).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .ocr import OcrUnavailable, normalize_image, ocr_image

if TYPE_CHECKING:
    from ..runtime import Runtime

MAX_IMAGES = 3
MODEL_SIDE = 1600       # görsel modele giden görüntünün uzun kenarı (token/VRAM sınırı)
OCR_CHARS = 6000        # görüntü başına modele verilen OCR metni
DEFAULT_QUESTION = "Bu ekran görüntüsünde ne var? Önemli bilgileri ve yazıları kısaca özetle."


class VisionError(ValueError):
    pass


class OcrInfo(BaseModel):
    engine: str | None = None
    language: str | None = None
    chars: int = 0
    error: str | None = None


class SeeResult(BaseModel):
    question: str
    answer: str = ""
    model: str | None = None
    ocr: list[OcrInfo] = Field(default_factory=list)
    ocr_text: str = ""                 # ilk görüntünün OCR metni (kısaltılmış; arayüzde "okunan yazı")
    verified: bool | None = None       # True: sayılar OCR ile doğrulandı · False: doğrulanamayan sayı var · None: OCR yok
    unverified_numbers: list[float] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    seconds: float = 0.0
    task_id: str | None = None

    def markdown(self) -> str:
        if self.verified is None:
            note = "yazılar/sayılar doğrulanamadı (bu sistemde OCR yok)"
        elif self.verified:
            note = "yazılar ve sayılar OCR ile doğrulandı"
        else:
            note = "bazı sayılar ekranda okunan yazıda yok — dikkat"
        return f"{self.answer}\n\n*Görüntü yerel görsel modelle yorumlandı ({self.model or 'vision'}); {note}.*"


def run_ocr(data: bytes) -> tuple[str, OcrInfo]:
    try:
        r = ocr_image(data)
    except OcrUnavailable as exc:
        return "", OcrInfo(error=str(exc))
    except ValueError as exc:
        raise VisionError(str(exc)) from exc
    return r.text, OcrInfo(engine=r.engine, language=r.language, chars=len(r.text))


def see(rt: "Runtime", images: list[bytes], question: str = "", *, ocr_texts: list[str] | None = None,
        conversation: list[dict[str, Any]] | None = None, parent_id: str | None = None) -> SeeResult:
    """Görüntü(ler) hakkında soruyu yerel görsel modelle cevaplar. `ocr_texts` verilirse (ek yüklenirken okunmuş) yeniden okunmaz."""
    from ..business.analysis import unverified_numbers
    from ..business.numbers import fmt, numbers_in_text

    if not images:
        raise VisionError("Görüntü yok")
    if len(images) > MAX_IMAGES:
        raise VisionError(f"En fazla {MAX_IMAGES} görüntü")
    if "vision" not in rt.workers:
        raise VisionError("vision ajanı tanımlı değil (config/agents/vision.yaml)")
    question = question.strip() or DEFAULT_QUESTION
    t0 = time.monotonic()
    res = SeeResult(question=question)

    texts: list[str] = []
    for i, data in enumerate(images):
        if ocr_texts is not None and i < len(ocr_texts):
            texts.append(ocr_texts[i])
            res.ocr.append(OcrInfo(engine="önceden", chars=len(ocr_texts[i])))
        else:
            text, info = run_ocr(data)
            texts.append(text)
            res.ocr.append(info)
    has_ocr = any(o.engine for o in res.ocr)
    res.ocr_text = texts[0][:OCR_CHARS] if texts else ""

    tmp = rt.settings.data_dir / "perception" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        for data in images:
            try:
                png, _, _ = normalize_image(data, max_side=MODEL_SIDE)
            except ValueError as exc:
                raise VisionError(str(exc)) from exc
            p = tmp / f"{uuid.uuid4().hex[:12]}.png"
            p.write_bytes(png)
            paths.append(str(p))
        task_input: dict[str, Any] = {"_images": paths}
        if has_ocr:
            task_input["ocr_text"] = [t[:OCR_CHARS] for t in texts]
        if conversation:
            task_input["conversation"] = conversation[-4:]
        from ..llm.vram import ensure_vram, model_loaded

        spec = rt.registry.get(rt.workers.get("vision").definition.local_model)  # type: ignore[attr-defined]
        if not model_loaded(rt, spec.name):  # Adım 13b: yüklemeden önce GPU'da yer aç
            vr = ensure_vram(rt, spec.approx_vram_gb or 6.0, "görsel model", keep={spec.name})
            if vr.unloaded:
                res.warnings.append("GPU'da yer açmak için bellekten çıkarıldı: " + ", ".join(vr.unloaded)
                                    + " (gerekince kendiliğinden yeniden yüklenir)")
            if vr.warning:
                res.warnings.append(vr.warning)
        task = rt.orchestrator.ask(question, worker="vision", input=task_input, parent_id=parent_id)
    finally:
        for p in paths:  # geçici kopyalar silinir (özgün ek, sohbet ekiyse ek klasöründe kalır)
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass

    res.task_id, res.model = task.id, task.model
    res.seconds = round(time.monotonic() - t0, 2)
    if task.status.value != "succeeded":
        err = task.error or task.status.value
        spec = rt.registry.get(rt.workers.get("vision").definition.local_model)  # type: ignore[attr-defined]
        if "not found" in err:
            raise VisionError(f"Görsel model kurulu değil: {spec.name}. Kur: ollama pull {spec.name} "
                              f"(ya da Modeller → Yeni model indir)")
        raise VisionError(f"Görsel model cevap veremedi: {err}")
    res.answer = str((task.result or {}).get("answer", "")).strip()
    if has_ocr:
        allowed = [v for t in texts for v in numbers_in_text(t)] + numbers_in_text(question)
        res.unverified_numbers = unverified_numbers(res.answer, allowed)
        res.verified = not res.unverified_numbers
        if res.unverified_numbers:
            res.warnings.append("Cevapta ekranda okunan yazıda olmayan sayı(lar) var: "
                                + ", ".join(fmt(v) for v in res.unverified_numbers[:6]))
    else:
        reason = next((o.error for o in res.ocr if o.error), None)
        if reason:
            res.warnings.append(f"OCR yok ({reason}); yazılar ve sayılar görsel modelin okumasıdır, doğrulanmadı")
    return res
