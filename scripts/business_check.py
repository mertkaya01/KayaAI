"""Adım 10 doğrulaması — GERÇEK modellerle iş modülleri (kabul #6 PDF özeti, #7 Excel analizi, #12 iş raporu).

Kullanım (proje klasöründe, venv etkin):
    python scripts/business_check.py
Sonuç: data/business_check.json ve örnek raporlar: data/checks/business/raporlar/

AYRI bir klasörde çalışır (data/checks/business): örnek satış Excel'i, örnek fatura PDF'i ve 3 sayfalık örnek rapor
PDF'i üretilir; gerçek dosyalarına ve geçmişine dokunulmaz. Ölçülenler: planın doğru işlemleri seçip seçmediği
(beklenen değer sonuç tablolarında mı), yorumdaki doğrulanmamış sayılar, fatura alanları ve tutar denetimi,
özetin kaynak sayfa göstermesi, dört rapor biçiminin üretilip geri okunabilmesi, süreler.
"""

from __future__ import annotations

import io
import json
import random
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.business import from_result, read_pdf, read_table, render, run_mode  # noqa: E402
from kayaai.business.report import _register_font  # noqa: E402
from kayaai.config import load_settings  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

REGIONS = ["Ankara", "İstanbul", "İzmir", "Bursa"]
PRODUCTS = ["Defter", "Kalem", "Çanta"]


def sales_rows() -> list[tuple[str, str, str, int, float]]:
    rnd = random.Random(42)
    rows = []
    d = date(2026, 1, 3)
    for i in range(48):
        rows.append((d.isoformat(), REGIONS[i % 4], PRODUCTS[(i * 7) % 3], rnd.randint(1, 20), round(rnd.uniform(40, 900), 2)))
        d += timedelta(days=7)
    return rows


def make_xlsx(rows) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Satışlar"
    ws.append(["Tarih", "Bölge", "Ürün", "Adet", "Tutar (TL)"])
    for t, b, u, a, tutar in rows:
        ws.append([date.fromisoformat(t), b, u, a, tutar])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pdf(pages: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    font, _ = _register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for page in pages:
        y = 800
        for line in page.split("\n"):
            c.setFont(font, 11)
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


INVOICE = """e-FATURA
Satıcı: Kaya Kırtasiye Ltd. Şti.  VKN: 1234567890
Alıcı: Atlas Yazılım A.Ş.
Fatura No: KYA2026000123
Fatura Tarihi: 15.01.2026     Son Ödeme Tarihi: 14.02.2026
Sıra  Mal/Hizmet         Miktar   Birim Fiyat   Tutar
1     A4 Defter          10       25,00 TL      250,00 TL
2     Tükenmez Kalem     50       5,00 TL       250,00 TL
3     Sırt Çantası       2        450,00 TL     900,00 TL
Mal Hizmet Toplam Tutarı: 1.400,00 TL
Hesaplanan KDV (%20): 280,00 TL
Vergiler Dahil Toplam Tutar: 1.680,00 TL
Ödenecek Tutar: 1.680,00 TL"""

REPORT_PAGES = [
    "Atlas Projesi Çeyrek Raporu\nBu raporda Atlas projesinin ilk çeyrek durumu özetlenmektedir.\n"
    "Proje bütçesi 1,2 milyon TL olarak onaylandı ve şu ana kadar yüzde 35'i harcandı.",
    "Teknik ilerleme\nGiriş ekranına iki adımlı doğrulama eklendi.\nVeritabanı PostgreSQL'e taşındı.\n"
    "Performans testlerinde sayfa açılış süresi 2,1 saniyeden 0,8 saniyeye indi.",
    "Riskler ve sonraki adımlar\nEn büyük risk, ödeme entegrasyonunun gecikmesi.\n"
    "Teslim tarihi 15 Kasım olarak korunuyor. Bir sonraki toplantı 20 Kasım'da yapılacak.",
]


def main() -> int:
    settings = load_settings()
    report_path = settings.data_dir / "business_check.json"
    work = settings.data_dir / "checks" / "business"
    shutil.rmtree(work, ignore_errors=True)
    (work / "raporlar").mkdir(parents=True)
    settings.data_dir = work / "data"
    settings.files.home_dir = str(work / "files")
    settings.files.allowed_dirs = []

    rows = sales_rows()
    xlsx = make_xlsx(rows)
    by_region: dict[str, float] = {}
    by_product: dict[str, float] = {}
    for _, b, u, _, t in rows:
        by_region[b] = round(by_region.get(b, 0) + t, 2)
        by_product[u] = round(by_product.get(u, 0) + t, 2)
    top_product = max(by_product, key=by_product.get)  # type: ignore[arg-type]
    cases = [
        ("Bölgelere göre toplam satış tutarı ve payları neler?", round(by_region["Ankara"], 2)),
        ("Aylara göre toplam satış nasıl değişti?", None),
        ("En çok satış getiren ürün hangisi?", round(by_product[top_product], 2)),
    ]
    out: dict = {"analysis": [], "invoice": None, "pdf_summary": None, "reports": []}
    with build_runtime(settings) as rt:
        tables = read_table(xlsx, "satislar.xlsx")
        first = None
        for q, expected in cases:
            t0 = time.perf_counter()
            res = run_mode(rt, "analyze", xlsx, "satislar.xlsx", q)
            dt = round(time.perf_counter() - t0, 1)
            values = [v for r in res.results for row in r.rows for v in row if isinstance(v, float)]
            found = expected is None or any(abs(v - expected) < 0.01 for v in values)
            row = {"question": q, "ok": bool(res.results) and found, "operations": len(res.results),
                   "titles": [r.title for r in res.results], "expected": expected, "expected_found": found,
                   "unverified_numbers": res.unverified_numbers, "warnings": res.warnings, "seconds": dt,
                   "narrative": res.narrative[:400]}
            out["analysis"].append(row)
            first = first or res
            print(f"[{'OK ' if row['ok'] else '?? '}] {dt:>5} sn  analiz: {q[:50]:<52} işlem: {row['operations']} "
                  f"beklenen bulundu: {found}  uydurma sayı: {len(res.unverified_numbers)}")

        t0 = time.perf_counter()
        inv = run_mode(rt, "invoice", make_pdf([INVOICE]), "fatura.pdf")
        dt = round(time.perf_counter() - t0, 1)
        i = inv.invoice
        inv_ok = i is not None and i.total == 1680 and i.subtotal == 1400 and i.vat == 280 and not inv.warnings
        out["invoice"] = {"ok": inv_ok, "fields": i.model_dump() if i else None, "warnings": inv.warnings, "seconds": dt}
        print(f"[{'OK ' if inv_ok else '?? '}] {dt:>5} sn  fatura: toplam={i.total if i else None} "
              f"kalem={len(i.lines) if i else 0} uyarı={inv.warnings}")

        t0 = time.perf_counter()
        pdf = make_pdf(REPORT_PAGES)
        doc = read_pdf(pdf, "atlas_rapor.pdf")
        summ = run_mode(rt, "summarize", pdf, "atlas_rapor.pdf", "Bu raporu yönetici için özetle.")
        dt = round(time.perf_counter() - t0, 1)
        keys = ["1,2", "35", "PostgreSQL", "15 Kasım"]
        hits = [k for k in keys if k.lower() in summ.summary.lower()]
        s_ok = bool(summ.summary) and "[s." in summ.summary and len(hits) >= 2
        out["pdf_summary"] = {"ok": s_ok, "pages": len(doc.pages), "key_facts_found": hits, "has_page_refs": "[s." in summ.summary,
                          "summary": summ.summary[:800], "warnings": summ.warnings, "seconds": dt}
        print(f"[{'OK ' if s_ok else '?? '}] {dt:>5} sn  PDF özeti: anahtar bilgiler {hits}, sayfa kaynağı: {'[s.' in summ.summary}")

        if first is not None:
            rep = from_result(first.model_dump(mode="json"), title="Satış analizi (kayaAI deneme)")
            for fmt_ in ("md", "xlsx", "docx", "pdf"):
                data = render(rep, fmt_)  # type: ignore[arg-type]
                path = work / "raporlar" / f"satis-analizi.{fmt_}"
                path.write_bytes(data)
                out["reports"].append({"format": fmt_, "bytes": len(data), "path": str(path)})
            print(f"[OK ]  raporlar: {', '.join(r['format'] for r in out['reports'])} → {work / 'raporlar'}")

    summary = {
        "analysis_ok": f"{sum(r['ok'] for r in out['analysis'])}/{len(out['analysis'])}",
        "unverified_numbers": sum(len(r["unverified_numbers"]) for r in out["analysis"]),
        "invoice_ok": out["invoice"]["ok"],
        "pdf_summary_ok": out["pdf_summary"]["ok"],
        "reports": len(out["reports"]),
        "total_s": round(sum(r["seconds"] for r in out["analysis"]) + out["invoice"]["seconds"] + out["pdf_summary"]["seconds"], 1),
    }
    report_path.write_text(json.dumps({"summary": summary, **out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nÖzet: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
