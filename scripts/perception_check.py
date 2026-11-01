"""Adım 12 doğrulaması — GERÇEK modellerle algı: 12a ekranı okuma (OCR + qwen2.5vl:7b), taranmış PDF, 12b ses tanıma.

Kullanım (proje klasöründe, venv etkin; önce: ollama pull qwen2.5vl:7b ve kayaai speech download):
    python scripts/perception_check.py            # örnek görüntüler + taranmış PDF + ses tanıma
    python scripts/perception_check.py --screen   # + gerçek ekranından TEK kare (yalnız bu komutla, kaydedilmez)
Ses: konuşma örnekleri Windows'un kendi sesleriyle (System.Speech, çevrim dışı) WAV'a sentezlenir → whisper → kelime hata
oranı (WER). Türkçe ses yüklü değilse yalnız İngilizce ölçülür.
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


SPEECH = [
    ("tr", "Yarın sabah saat onda Atlas projesi için müşteriyle toplantımız var."),
    ("tr", "Lütfen geçen ayın satış raporunu Excel olarak hazırla ve bana gönder."),
    ("en", "Please schedule a meeting with the design team next Tuesday afternoon."),
]


def synth_wav(text: str, culture: str, out: Path) -> str | None:
    """Windows System.Speech ile WAV (çevrim dışı). Ses yoksa None."""
    import subprocess

    ps = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq '{culture}' -and $_.Enabled }} | "
        "Select-Object -First 1; if (-not $v) { exit 3 }; $s.SelectVoice($v.VoiceInfo.Name); "
        f"$s.SetOutputToWaveFile('{out}'); $s.Speak($env:KAYA_TTS_TEXT); $s.Dispose(); Write-Output $v.VoiceInfo.Name"
    )
    import os

    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       env={**os.environ, "KAYA_TTS_TEXT": text}, timeout=60)
    return r.stdout.strip() if r.returncode == 0 and out.is_file() else None


def wer(ref: str, hyp: str) -> float:
    import re

    norm = lambda t: re.findall(r"\w+", t.lower().replace("İ", "i").replace("I", "ı"))  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return round(d[len(h)] / max(1, len(r)), 3)


def check_speech(settings, work: Path, work_settings) -> tuple[list[dict], dict]:
    from kayaai.speech.stt import SpeechError, is_installed, status, transcribe

    if not is_installed(settings):
        return [], {"error": "ses modeli kurulu değil: kayaai speech download"}
    if sys.platform != "win32":
        return [], {"error": "örnek ses sentezi yalnız Windows'ta (System.Speech)"}
    rows = []
    for i, (lang, text) in enumerate(SPEECH):
        f = work / f"ses{i}.wav"
        voice = synth_wav(text, "tr-TR" if lang == "tr" else "en-US", f)
        if not voice:
            rows.append({"lang": lang, "skipped": f"Windows'ta {lang} sesi yok"})
            continue
        try:
            t = transcribe(settings, f.read_bytes(), lang)
            rows.append({"lang": lang, "voice": voice, "wer": wer(text, t.text), "text": t.text,
                         "audio_s": t.audio_seconds, "seconds": t.seconds, "device": t.device})
        except SpeechError as exc:
            rows.append({"lang": lang, "error": str(exc)})
        print(f"Ses [{lang}]: {rows[-1].get('text', rows[-1].get('error', rows[-1].get('skipped')))}")
    st = status(settings)
    info = {"device": st["device"], "gpu_error": st["gpu_error"]}
    # 12c: aynı cümleler arka arkaya (aralarında 1,5 sn sessizlik) canlı altyazı motorundan geçer → gecikme + çeviri
    wavs = [work / f"ses{i}.wav" for i in range(len(SPEECH)) if (work / f"ses{i}.wav").is_file()]
    if wavs:
        import numpy as np

        from kayaai.runtime import build_runtime
        from kayaai.speech.live import LiveSession
        from kayaai.speech.stt import decode

        gap = np.zeros(int(1.5 * 16000), dtype=np.float32)
        audio = np.concatenate([x for w in wavs for x in (decode(w.read_bytes()), gap)])
        msgs: list[dict] = []
        with build_runtime(work_settings) as rt:  # ayrı veri klasörü; ses modeli asıl yerinden
            live = LiveSession(rt, msgs.append, "auto", "en", partials=False, settings=settings)
            for i in range(0, len(audio), 1600):  # gerçek zamanlı akış gibi 100 ms parçalar
                live.feed(audio[i:i + 1600])
                time.sleep(0.1)
            live.stop()
        finals = [m for m in msgs if m["type"] == "final"]
        info["live"] = {"lines": len(finals), "expected": len(wavs),
                        "avg_latency_s": round(sum(f["latency_s"] for f in finals) / max(1, len(finals)), 2),
                        "translated": sum(1 for f in finals if f.get("translation")),
                        "samples": [{"text": f["text"], "translation": f.get("translation")} for f in finals[:4]]}
        print(f"Canlı altyazı: {len(finals)} satır, ort. gecikme {info['live']['avg_latency_s']} sn")
    return rows, info


def main() -> int:
    from kayaai.llm.compare import missing_expected
    from kayaai.perception.ocr import OcrUnavailable, available, ocr_image
    from kayaai.perception.vision import VisionError, see

    settings = load_settings()
    report_path = settings.data_dir / "perception_check.json"
    work = settings.data_dir / "checks" / "perception"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    real = settings.model_copy(deep=True)  # ses modeli asıl data/models altında (indirilmiş olanı kullan)
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

    sp_rows, sp_info = check_speech(real, work, settings)
    measured = [r for r in sp_rows if "wer" in r]
    summary_speech = {"live_subtitles": {k: v for k, v in (sp_info.get("live") or {}).items() if k != "samples"} or None,
                      "speech_device": sp_info.get("device"), "speech_gpu_error": sp_info.get("gpu_error"),
                      "speech_error": sp_info.get("error"),
                      "speech_wer": {r["lang"]: r["wer"] for r in measured} or None,
                      "speech_rtf": round(sum(r["seconds"] for r in measured) / max(0.01, sum(r["audio_s"] for r in measured)), 3)
                      if measured else None}
    summary = {
        **summary_speech,
        "ocr": why, "vision_ok": f"{sum(1 for r in rows if r.get('ok'))}/{len(rows)}",
        "ocr_found": ", ".join(o.get("found", "hata") for o in ocr_rows) or "OCR yok",
        "scanned_pdf_ok": pdf_row.get("ok"), "avg_vision_s": round(sum(r.get("seconds", 0) for r in rows) / max(1, len(rows)), 2),
        "total_s": round(time.monotonic() - t_all, 1),
    }
    report_path.write_text(json.dumps({"summary": summary, "vision": rows, "ocr": ocr_rows, "scanned_pdf": pdf_row,
                                       "screen": screen_row, "speech": sp_rows,
                                       "live": sp_info.get("live")}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
