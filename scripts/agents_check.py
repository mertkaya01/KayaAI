"""Adım 7 doğrulaması — GERÇEK modellerle üretici → gözden geçirici akışı.

Kullanım (proje klasöründe, venv etkin):
    python scripts/agents_check.py
Sonuç: data/agents_check.json

Ölçüm AYRI bir veri klasöründe yapılır (data/checks/agents): gerçek görev geçmişin, onayların ve
anlaşmazlık listen bu denemelerle kirlenmez. Claude kutusuna iş bırakılmaz (force=local).

Her senaryo için ölçülenler: hangi ajan çalıştı, gözden geçirme yapıldı mı, kod kontrolü (kaç blok, kaç hata),
gözden geçiricinin kanıtsız (uydurma) notlarından kaçı elendi, revizyon oldu mu, anlaşmazlık çıktı mı, süre.
Hesap senaryolarında doğru sonucun cevapta geçip geçmediği KODLA kontrol edilir.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.conductor import Conductor  # noqa: E402
from kayaai.conductor.checks import run_checks  # noqa: E402
from kayaai.config import load_settings  # noqa: E402
from kayaai.core.lang import detect_language  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# (istek, beklenen ajan, cevapta geçmesi gereken ifadeler — hepsi)
CASES: list[tuple[str, str, list[str]]] = [
    ("Python'da bir listedeki çift sayıları döndüren bir fonksiyon yaz ve kısaca açıkla.", "coder", []),
    ("Write a Python function that checks whether a string is a palindrome, with one usage example.", "coder", []),
    ("Şu aylık satışların toplamını ve aylık ortalamasını hesapla: Ocak 120, Şubat 80, Mart 100.", "data",
     ["300", "100"]),
    ("Compute the total and the average of these expenses: 40, 60, 50, 90.", "data", ["240", "60"]),
    ("Bir müşteriye, yarınki toplantının gelecek haftaya ertelendiğini bildiren kısa ve resmi bir e-posta yaz.",
     "document", []),
    ("Şu metni daha resmi ve düzgün bir Türkçeyle yeniden yaz: 'abi rapor yarın gelir sıkıntı yok merak etme'",
     "document", []),
]


def main() -> int:
    settings = load_settings()
    check_dir = settings.data_dir / "checks" / "agents"
    shutil.rmtree(check_dir, ignore_errors=True)
    report_path = settings.data_dir / "agents_check.json"
    settings.data_dir = check_dir  # ayrı veritabanı: gerçek geçmiş kirlenmez
    rows = []
    with build_runtime(settings) as rt:
        print("Ölçüm yerel ekiple yapılıyor (force=local), ayrı veri klasörü: " + str(check_dir) + "\n")
        conductor = Conductor(rt)
        for request, exp_agent, must in CASES:
            t0 = time.perf_counter()
            res = conductor.run(request, force="local")
            dt = round(time.perf_counter() - t0, 1)
            agents = [s.agent for s in res.steps]
            reviews = [s.review for s in res.steps if s.review]
            rv = reviews[0] if reviews else None
            final_checks = run_checks(res.answer, ["code_syntax"])
            missing = [m for m in must if m not in res.answer]
            row = {
                "request": request[:90],
                "status": res.status,
                "agents": agents,
                "expected_agent": exp_agent,
                "agent_ok": exp_agent in agents,
                "language_ok": detect_language(res.answer) == detect_language(request),
                "reviewed": rv is not None and rv.skipped is None,
                "review_verdict": rv.verdict if rv else None,
                "review_issues": rv.issues if rv else [],
                "review_missing_parts": rv.missing_parts if rv else [],
                "dropped_unproven_issues": rv.dropped_issues if rv else 0,
                "code_blocks_checked": rv.checks.checked_blocks if rv and rv.checks else 0,
                "code_check_failures": [f.message for f in rv.checks.failures] if rv and rv.checks else [],
                "revised": bool(rv and rv.revised),
                "disputes": len(rv.disputes) if rv else 0,
                "final_answer_syntax_ok": not final_checks.failures,
                "expected_values_missing": missing,
                "warnings": res.warnings,
                "duration_s": dt,
                "answer_head": res.answer[:400],
            }
            rows.append(row)
            flag = "OK " if res.status == "succeeded" and row["agent_ok"] and not missing and row["reviewed"] else "?? "
            print(f"[{flag}] {dt:>6} sn  {','.join(agents):<10} gözden geçirme: {row['review_verdict'] or '-':<15} "
                  f"elenen: {row['dropped_unproven_issues']}  düzeltme: {'evet' if row['revised'] else 'hayır'}  "
                  f"anlaşmazlık: {row['disputes']}  {request[:50]}")
            if missing:
                print(f"       beklenen değer(ler) cevapta yok: {missing}")
            for w in res.warnings:
                print(f"       [uyarı] {w[:160]}")
    summary = {
        "cases": len(rows),
        "succeeded": sum(r["status"] == "succeeded" for r in rows),
        "agent_ok": sum(r["agent_ok"] for r in rows),
        "reviewed": sum(r["reviewed"] for r in rows),
        "values_ok": sum(not r["expected_values_missing"] for r in rows),
        "language_ok": sum(r["language_ok"] for r in rows),
        "revised": sum(r["revised"] for r in rows),
        "disputes": sum(r["disputes"] for r in rows),
        "dropped_unproven_issues": sum(r["dropped_unproven_issues"] for r in rows),
        "total_s": round(sum(r["duration_s"] for r in rows), 1),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("\nÖzet: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    print(f"Rapor: {report_path}")
    return 0 if summary["succeeded"] == summary["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
