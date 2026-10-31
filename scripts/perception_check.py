"""Adım 12 doğrulaması — GERÇEK modellerle algı: 12a ekranı okuma (OCR + qwen2.5vl:7b) ve taranmış PDF.

Kullanım (proje klasöründe, venv etkin; önce: ollama pull qwen2.5vl:7b):
    python scripts/perception_check.py            # örnek görüntüler + taranmış PDF
    python scripts/perception_check.py --screen   # + gerçek ekranından TEK kare (yalnız bu komutla, kaydedilmez)
Sonuç: data/perception_check.json

AYRI veri klasöründe çalışır (data/checks/perception). Örnek görüntüler sistem yazı tipiyle üretilir (Türkçe karakterli);
OCR doğruluğu (beklenen parçalar bulundu mu), görsel modelin cevabı (beklenen sayılar/kelimeler — KODLA) ve süreler ölçülür.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.config import load_settings  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

INVOICE = ["KAYA KIRTASİYE LTD. ŞTİ.", "Fatura No: KYA-2026-0042", "Tarih: 15.01.2026", "Müşteri: Atlas Yazılım A.Ş.",
           "A4 Defter        10 x 25,00 = 250,00 TL", "Tükenmez Kalem   50 x 5,00  = 250,00 TL",
           "Sırt Çantası      2 x 450,00 = 900,00 TL", "Ara toplam: 1.400,00 TL", "KDV %20: 280,00 TL",
           "GENEL TOPLAM: 1.680,00 TL"]
DIALOG = ["Dosya kaydedilemedi", "Hata kodu: 0x80070005", "Erişim engellendi: C:\\Raporlar\\ocak.xlsx",
          "Yönetici olarak çalıştırmayı deneyin.", "[ Tamam ]      [ İptal ]"]
# (ad, satırlar, soru, beklenen OCR parçaları, beklenen cevap: sayı → sayı olarak, metin → kelime)
CASES = [
    ("fatura", INVOICE, "Bu faturanın genel toplamı ve KDV tutarı ne kadar?",
     ["KYA-2026-0042", "1.680,00", "Çantası"], [1680, 280]),
    ("fatura-no", INVOICE, "Fatura numarası ve müşteri kim?", ["Atlas"], ["KYA-2026-0042", "Atlas"]),
    ("hata", DIALOG, "Bu hata penceresi ne diyor, hangi dosya kaydedilemedi?",
     ["0x80070005", "ocak.xlsx"], ["ocak.xlsx"]),
]


def render(lines: list[str], scale: int = 1) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    from kayaai.business.report import FONT_CANDIDATES

    path = next((r for r, _ in FONT_CANDIDATES if Path(r).is_file()), None)
    font = ImageFont.truetype(path, 26 * scale) if path else ImageFont.load_default()
    img = Image.new("RGB", (1100 * scale, (90 + 44 * len(lines)) * scale), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((40 * scale, (40 + 44 * i) * scale), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def scanned_pdf(png: bytes) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(ImageReader(io.BytesIO(png)), 30, 400, width=535, preserveAspectRatio=True)
    c.showPage()
    c.save()
    return buf.getvalue()


def main() -> int:
    from kayaai.llm.compare import missing_expected
    from kayaai.perception.ocr import OcrUnavailable, available, ocr_image
    from kayaai.perception.vision import VisionError, see

    settings = load_settings()
    report_path = settings.data_dir / "perception_check.json"
    work = settings.data_dir / "checks" / "perception"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    settings.data_dir = work / "data"
    settings.files.home_dir = str(work / "files")
    t_all = time.monotonic()
    ok_ocr, why = available()
    print(f"OCR: {why}")
    rows, ocr_rows = [], []
    with build_runtime(settings) as rt:
        images = {name: render(lines) for name, lines, *_ in CASES}
        for name, lines, question, ocr_expect, answer_expect in CASES:
            row: dict = {"case": name, "question": question}
            data = images[name]
            if ok_ocr:
                t0 = time.monotonic()
                try:
                    text = ocr_image(data).text
                    found = [e for e in ocr_expect if e.lower() in text.lower()]
                    ocr_rows.append({"case": name, "found": f"{len(found)}/{len(ocr_expect)}",
                                     "missing": [e for e in ocr_expect if e not in found],
                                     "seconds": round(time.monotonic() - t0, 2), "text_head": text[:200]})
                except OcrUnavailable as exc:
                    ocr_rows.append({"case": name, "error": str(exc)})
            try:
                res = see(rt, [data], question)
                miss = missing_expected(res.answer, question, answer_expect)
                row.update(ok=not miss and res.verified is not False, missing=miss, verified=res.verified,
                           unverified_numbers=res.unverified_numbers, seconds=res.seconds, answer=res.answer[:400])
            except VisionError as exc:
                row.update(ok=False, error=str(exc))
            rows.append(row)
            print(f"{'OK ' if row.get('ok') else 'X  '} {name}: {row.get('answer', row.get('error', ''))[:140]}")

        pdf_row: dict = {}
        if ok_ocr:
            from kayaai.business.readers import ReadError, read_pdf

            t0 = time.monotonic()
            try:
                doc = read_pdf(scanned_pdf(render(INVOICE, scale=2)), "tarama.pdf")
                txt = doc.text
                pdf_row = {"ok": doc.ocr and "1.680,00" in txt and "KYA-2026-0042" in txt, "ocr": doc.ocr,
                           "seconds": round(time.monotonic() - t0, 2), "text_head": txt[:200]}
            except ReadError as exc:
                pdf_row = {"ok": False, "error": str(exc)}
            print(f"Taranmış PDF: {'OK' if pdf_row.get('ok') else 'X'} {pdf_row.get('error', '')}")

        screen_row: dict = {}
        if "--screen" in sys.argv:
            from kayaai.cli import capture_screen

            print("Gerçek ekrandan tek kare alınıyor (kaydedilmez)…")
            try:
                res = see(rt, [capture_screen(1)], "Bu ekranda ne var? Kısaca anlat.")
                screen_row = {"seconds": res.seconds, "verified": res.verified, "answer": res.answer[:600],
                              "ocr_chars": res.ocr[0].chars if res.ocr else 0}
                print(res.answer[:600])
            except (VisionError, OSError, ValueError) as exc:
                screen_row = {"error": str(exc)}

    summary = {
        "ocr": why, "vision_ok": f"{sum(1 for r in rows if r.get('ok'))}/{len(rows)}",
        "ocr_found": ", ".join(o.get("found", "hata") for o in ocr_rows) or "OCR yok",
        "scanned_pdf_ok": pdf_row.get("ok"), "avg_vision_s": round(sum(r.get("seconds", 0) for r in rows) / max(1, len(rows)), 2),
        "total_s": round(time.monotonic() - t_all, 1),
    }
    report_path.write_text(json.dumps({"summary": summary, "vision": rows, "ocr": ocr_rows, "scanned_pdf": pdf_row,
                                       "screen": screen_row}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
