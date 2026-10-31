"""Görüntüden yazı okuma (OCR) — Adım 12a.

Windows: yerleşik **Windows.Media.Ocr** motoru (pywinrt paketleri, MIT). Ek model/indirme yok, hızlı ve deterministik;
Türkçe tanıma dil paketi yüklüyse Türkçe, değilse kullanıcı profilinin dili. Başka sistemlerde OCR yoktur: görsel model
yazıyı okur ve cevap "doğrulanmadı" olarak işaretlenir (bkz. perception/vision.py).

Testler `set_engine()` ile sahte motor takar (Linux'ta Windows motoru yoktur).
"""

from __future__ import annotations

import asyncio
import io
import sys
import threading
from collections.abc import Callable

from pydantic import BaseModel, Field

MAX_PIXELS = 40_000_000  # 8000x5000 üstü reddedilir (bellek)


class OcrResult(BaseModel):
    text: str
    lines: list[str] = Field(default_factory=list)
    engine: str
    language: str | None = None


class OcrUnavailable(RuntimeError):
    pass


EngineFn = Callable[[bytes], OcrResult]
_ENGINE: EngineFn | None = None


def set_engine(fn: EngineFn | None) -> None:
    """Testler / başka motorlar için (None: varsayılana dön)."""
    global _ENGINE
    _ENGINE = fn


def normalize_image(data: bytes, max_side: int | None = None) -> tuple[bytes, int, int]:
    """Görüntüyü doğrular ve PNG'ye çevirir (isteğe bağlı küçültme). Bozuk/dev görüntüde ValueError."""
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise ValueError(f"Görüntü çok büyük ({img.width}x{img.height})")
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Görüntü okunamadı (PNG/JPEG/WebP/BMP olmalı)") from exc
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), img.width, img.height


# ---------------------------------------------------------------------------- Windows motoru


def _windows_engine(data: bytes) -> OcrResult:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError as exc:
        raise OcrUnavailable("Windows OCR paketleri kurulu değil (setup.ps1 yeniden çalıştırılmalı)") from exc

    limit = int(OcrEngine.max_image_dimension or 2600)
    png, _, _ = normalize_image(data, max_side=limit)

    async def run() -> OcrResult:
        engine = None
        if OcrEngine.is_language_supported(Language("tr")):
            engine = OcrEngine.try_create_from_language(Language("tr"))
        engine = engine or OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("Windows'ta OCR dili yok (Ayarlar → Saat ve dil → Dil: Türkçe/İngilizce dil paketi)")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        lines = [ln.text for ln in result.lines]
        return OcrResult(text="\n".join(lines), lines=lines, engine="windows",
                         language=engine.recognizer_language.language_tag)

    box: dict[str, object] = {}

    def worker() -> None:  # kendi olay döngüsü (API iş parçacığında da güvenli)
        try:
            box["r"] = asyncio.run(run())
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    t = threading.Thread(target=worker, name="kayaai-ocr", daemon=True)
    t.start()
    t.join(60)
    if "e" in box:
        e = box["e"]
        if isinstance(e, OcrUnavailable):
            raise e
        raise OcrUnavailable(f"Windows OCR hatası: {type(e).__name__}: {e}") from e  # type: ignore[arg-type]
    if "r" not in box:
        raise OcrUnavailable("Windows OCR 60 sn içinde bitmedi")
    return box["r"]  # type: ignore[return-value]


def available() -> tuple[bool, str]:
    """(kullanılabilir mi, açıklama)."""
    if _ENGINE is not None:
        return True, "test/özel motor"
    if sys.platform != "win32":
        return False, "OCR yalnızca Windows'ta (yerleşik Windows.Media.Ocr); görsel model okur, doğrulanmaz"
    try:
        from winrt.windows.media.ocr import OcrEngine

        langs = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    except ImportError:
        return False, "Windows OCR paketleri kurulu değil"
    except Exception as exc:  # noqa: BLE001
        return False, f"Windows OCR başlatılamadı: {exc}"
    if not langs:
        return False, "Windows'ta OCR dili yok"
    return True, "Windows OCR · diller: " + ", ".join(langs)


def ocr_image(data: bytes) -> OcrResult:
    """Görüntüdeki yazı. Motor yoksa OcrUnavailable."""
    if _ENGINE is not None:
        return _ENGINE(data)
    if sys.platform != "win32":
        raise OcrUnavailable("OCR yalnızca Windows'ta")
    return _windows_engine(data)


def ocr_pdf(data: bytes, max_pages: int = 50, scale: float = 2.0) -> list[str]:
    """Taranmış (metinsiz) PDF: sayfaları görüntüye çevirip (pypdfium2) OCR'dan geçirir. Sayfa metinleri döner."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        if len(pdf) > max_pages:
            raise ValueError(f"Taranmış PDF çok uzun ({len(pdf)} sayfa > {max_pages}); bir kısmını ayır")
        pages = []
        for i in range(len(pdf)):
            img = pdf[i].render(scale=scale).to_pil()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            pages.append(ocr_image(buf.getvalue()).text.strip())
        return pages
    finally:
        pdf.close()
