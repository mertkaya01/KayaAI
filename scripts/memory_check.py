"""Adım 9 doğrulaması — GERÇEK bge-m3 ile hafıza ve belge araması kalitesi + benzerlik eşiği ölçümü.

Kullanım (proje klasöründe, venv etkin; önce: ollama pull bge-m3):
    python scripts/memory_check.py
Sonuç: data/memory_check.json

AYRI bir veri ve dosya klasöründe çalışır (data/checks/memory): gerçek hafızan ve belgelerin kullanılmaz/değişmez.
Her soru için doğru öğenin bulunup bulunmadığı ve puanlar ölçülür; ilgili/ilgisiz puan dağılımından
`memory.min_score` için bir eşik ÖNERİLİR (ayar otomatik değiştirilmez).
"""

from __future__ import annotations

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

MEMORIES = [
    ("Kahvemi şekersiz ve sütlü içerim.", "preference"),
    ("Atlas projesinin teslim tarihi 15 Kasım; müşteri Kaya Ltd.", "project"),
    ("Raporları her zaman PDF olarak isterim.", "instruction"),
    ("Haftalık ekip toplantısı salı günleri saat 10:00'da.", "note"),
    ("We decided to use PostgreSQL instead of MySQL for the billing service.", "decision"),
    ("Annemin doğum günü 3 Mart.", "note"),
]
DOCS = {
    "atlas_toplanti.md": "# Atlas toplantı notu\n\nMüşteri, giriş ekranında iki adımlı doğrulama istedi.\n"
                         "Bütçe onaylandı: 120.000 TL. Sonraki toplantı 20 Kasım.\n",
    "kurulum.md": "# Sunucu kurulumu\n\nUygulama Docker ile çalışır. Ortam değişkenleri .env dosyasında tutulur.\n"
                  "Yedekler her gece 02:00'de alınır.\n",
    "satislar.csv": "ay,satis\nOcak,120\nŞubat,80\nMart,100\n",
}
# (soru, beklenen hafıza metni parçası | None, beklenen belge adı | None)
QUERIES = [
    ("Kahvemi nasıl içiyorum?", "şekersiz", None),
    ("Atlas ne zaman teslim edilecek?", "15 Kasım", None),
    ("Rapor hangi formatta olmalı?", "PDF", None),
    ("Toplantı hangi gün?", "salı", None),
    ("Which database did we choose for billing?", "PostgreSQL", None),
    ("Müşteri giriş ekranı için ne istedi?", None, "atlas_toplanti.md"),
    ("Yedekler saat kaçta alınıyor?", None, "kurulum.md"),
    ("Şubat ayı satışları ne kadar?", None, "satislar.csv"),
    ("Hava durumu yarın nasıl olacak?", None, None),  # ilgisiz: hiçbir şey dönmemeli
    ("En sevdiğin film hangisi?", None, None),
]


def main() -> int:
    settings = load_settings()
    report_path = settings.data_dir / "memory_check.json"
    work = settings.data_dir / "checks" / "memory"
    shutil.rmtree(work, ignore_errors=True)
    (work / "files").mkdir(parents=True)
    for name, text in DOCS.items():
        (work / "files" / name).write_text(text, encoding="utf-8")
    settings.data_dir = work / "data"
    settings.files.home_dir = str(work / "files")
    settings.files.allowed_dirs = []
    settings.memory.min_score = 0.0  # ham puanları görmek için; eşik aşağıda önerilir
    rows, relevant, irrelevant = [], [], []
    with build_runtime(settings) as rt:
        mem = rt.memory
        assert mem is not None
        t0 = time.perf_counter()
        for text, cat in MEMORIES:
            item, warnings = mem.book.add(text, category=cat)
            if warnings:
                print("[UYARI]", warnings[0])
                print("bge-m3 kurulu mu? ollama pull bge-m3")
                return 1
        rep = mem.docs.index()
        print(f"{len(MEMORIES)} hafıza öğesi + {rep.indexed} belge ({rep.chunks_total} parça) {time.perf_counter() - t0:.1f} sn\n")
        for q, exp_mem, exp_doc in QUERIES:
            t1 = time.perf_counter()
            res = mem.recall(q)
            dt = round((time.perf_counter() - t1) * 1000)
            top_m = res.memories[0] if res.memories else None
            top_d = res.documents[0] if res.documents else None
            mem_ok = exp_mem is None or (top_m is not None and exp_mem.lower() in top_m["text"].lower())
            doc_ok = exp_doc is None or (top_d is not None and top_d["name"] == exp_doc)
            for m in res.memories:
                (relevant if exp_mem and exp_mem.lower() in m["text"].lower() else irrelevant).append(m["score"])
            for d in res.documents:
                (relevant if exp_doc and d["name"] == exp_doc else irrelevant).append(d["score"])
            rows.append({"query": q, "memory_ok": mem_ok, "document_ok": doc_ok, "ms": dt,
                         "top_memory": top_m and {"text": top_m["text"], "score": top_m["score"]},
                         "top_document": top_d and {"name": top_d["name"], "score": top_d["score"]}})
            flag = "OK " if mem_ok and doc_ok else "?? "
            tm = f"{top_m['score']:.2f} {top_m['text'][:40]}" if top_m else "-"
            td = f"{top_d['score']:.2f} {top_d['name']}" if top_d else "-"
            print(f"[{flag}] {dt:>4} ms  {q[:42]:<44} hafıza: {tm:<50} belge: {td}")
    best_irrelevant = max(irrelevant, default=0.0)
    worst_relevant = min(relevant, default=1.0)
    suggested = round((best_irrelevant + worst_relevant) / 2, 2) if worst_relevant > best_irrelevant else round(best_irrelevant + 0.02, 2)
    summary = {
        "queries": len(rows),
        "memory_ok": sum(r["memory_ok"] for r in rows),
        "document_ok": sum(r["document_ok"] for r in rows),
        "relevant_min_score": round(worst_relevant, 3),
        "irrelevant_max_score": round(best_irrelevant, 3),
        "suggested_min_score": suggested,
        "current_min_score": load_settings().memory.min_score,
        "avg_ms": round(sum(r["ms"] for r in rows) / len(rows)),
    }
    report_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nÖzet: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
