"""Adım 9 doğrulaması — GERÇEK bge-m3 ile hafıza ve belge araması kalitesi + benzerlik eşiği ölçümü.

Kullanım (proje klasöründe, venv etkin; önce: ollama pull bge-m3):
    python scripts/memory_check.py
Sonuç: data/memory_check.json

AYRI bir veri ve dosya klasöründe çalışır (data/checks/memory): gerçek hafızan ve belgelerin kullanılmaz/değişmez.
Her soru için doğru öğenin bulunup bulunmadığı ve puanlar ölçülür; ilgili/ilgisiz puan dağılımından
`memory.min_score_memory` / `memory.min_score_docs` için tür başına eşik ÖNERİLİR (ayar otomatik değiştirilmez).
Süre embedding (Ollama) ve arama (numpy + FTS5) olarak ayrı ölçülür.
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
    settings.memory.min_score_memory = settings.memory.min_score_docs = 0.0  # ham puanlar; eşik aşağıda önerilir
    rows: list[dict] = []
    scores: dict[str, dict[str, list[float]]] = {"memory": {"rel": [], "irr": []}, "docs": {"rel": [], "irr": []}}
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
            [qvec] = mem.book.embedder.embed([q])
            t2 = time.perf_counter()
            mems = mem.book.search(q, k=5, query_vec=qvec, min_score=0.0)
            docs = mem.docs.search(q, k=4, query_vec=qvec, min_score=0.0)
            t3 = time.perf_counter()
            embed_ms, search_ms = round((t2 - t1) * 1000), round((t3 - t2) * 1000)
            unrelated = exp_mem is None and exp_doc is None
            # Etiketleme (v0.9.1 düzeltmesi): yalnızca beklenen öğe "ilgili"; beklenmeyen tür ancak kesin ilgisizse sayılır.
            for m, sc in mems:
                if exp_mem and exp_mem.lower() in m.text.lower():
                    scores["memory"]["rel"].append(sc)
                elif unrelated or exp_mem or exp_doc:  # belge sorusunda hafıza cevabı yoktur
                    scores["memory"]["irr"].append(sc)
            for ch, sc in docs:
                name = Path(ch.path).name
                if exp_doc and name == exp_doc:
                    scores["docs"]["rel"].append(sc)
                elif unrelated or exp_doc:  # hafıza sorusunda belge parçası da ilgili olabilir: sayılmaz
                    scores["docs"]["irr"].append(sc)
            top_m, top_d = (mems[0] if mems else None), (docs[0] if docs else None)
            mem_ok = exp_mem is None or (top_m is not None and exp_mem.lower() in top_m[0].text.lower())
            doc_ok = exp_doc is None or (top_d is not None and Path(top_d[0].path).name == exp_doc)
            rows.append({"query": q, "memory_ok": mem_ok, "document_ok": doc_ok, "embed_ms": embed_ms,
                         "search_ms": search_ms,
                         "top_memory": top_m and {"text": top_m[0].text, "score": top_m[1]},
                         "top_document": top_d and {"name": Path(top_d[0].path).name, "score": top_d[1]}})
            flag = "OK " if mem_ok and doc_ok else "?? "
            tm = f"{top_m[1]:.2f} {top_m[0].text[:38]}" if top_m else "-"
            td = f"{top_d[1]:.2f} {Path(top_d[0].path).name}" if top_d else "-"
            print(f"[{flag}] embed {embed_ms:>4} ms + ara {search_ms:>3} ms  {q[:40]:<42} hafıza: {tm:<46} belge: {td}")

    def suggest(kind: str) -> dict:
        rel, irr = scores[kind]["rel"], scores[kind]["irr"]
        lo, hi = min(rel, default=1.0), max(irr, default=0.0)
        value = round((lo + hi) / 2, 2) if lo > hi else round(hi + 0.02, 2)
        return {"relevant_min": round(lo, 3), "irrelevant_max": round(hi, 3), "separable": lo > hi, "suggested": value}

    current = load_settings().memory
    summary = {
        "queries": len(rows),
        "memory_ok": sum(r["memory_ok"] for r in rows),
        "document_ok": sum(r["document_ok"] for r in rows),
        "memory_threshold": {**suggest("memory"), "current": current.min_score_memory},
        "docs_threshold": {**suggest("docs"), "current": current.min_score_docs},
        "avg_embed_ms": round(sum(r["embed_ms"] for r in rows) / len(rows)),
        "max_embed_ms": max(r["embed_ms"] for r in rows),
        "avg_search_ms": round(sum(r["search_ms"] for r in rows) / len(rows)),
    }
    report_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nÖzet: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
