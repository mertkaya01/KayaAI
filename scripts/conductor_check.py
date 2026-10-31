"""Yerel şef (kayaai do) doğrulaması - GERÇEK modellerle.

Kullanım (proje klasöründe, venv etkin):
    python scripts/conductor_check.py
Sonuç: data/conductor_check.json

Her istek için beklenen davranış yazılıdır; script sonucu karşılaştırır ama "beklenen" bir hedeftir,
model kararları kesin değildir. Asıl amaç: plan kalitesini, süreyi ve uyarıları ölçmek.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.conductor import Conductor  # noqa: E402
from kayaai.config import load_settings  # noqa: E402
from kayaai.core.lang import detect_language  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# (istek, beklenen mod, beklenen ajanlardan biri, Claude gerekli mi beklentisi)
CASES = [
    ("Türkiye'nin en kalabalık üç şehrini say.", "direct", "general", False),
    ("Explain in two sentences what a REST API is.", "direct", "general", False),
    ("Python'da bir listedeki tekrar eden elemanları sırayı bozmadan silen bir fonksiyon yaz.", "direct", "coder", False),
    ("Write a JavaScript function that debounces another function, with a short usage example.", "direct", "coder", False),
    ("Bir CSV dosyasındaki satışları aylara göre toplayan bir Python fonksiyonu yaz, sonra bu kodu programcı "
     "olmayan bir yöneticiye 3 maddede Türkçe açıkla ve en sonunda İngilizce kısa bir commit mesajı öner.",
     "plan", "coder", False),
    ("Çok kiracılı (multi-tenant) bir SaaS için mikroservis mimarisini; veri izolasyonu, kimlik doğrulama, "
     "ölçekleme ve maliyet ödünleşimleriyle birlikte ayrıntılı tasarla.", "any", "general", True),
]


def main() -> int:
    settings = load_settings()
    rows = []
    with build_runtime(settings) as rt:
        print(f"Claude modu: {rt.claude.status().label if rt.claude else '?'}\n")
        conductor = Conductor(rt)
        for request, exp_mode, exp_agent, exp_claude in CASES:
            t0 = time.perf_counter()
            res = conductor.run(request)
            agents = [s.agent for s in res.steps]
            row = {
                "request": request[:90],
                "status": res.status,
                "mode": res.mode,
                "agents": agents,
                "steps": [s.model_dump() for s in res.steps],
                "needs_claude": res.routing.needs_claude,
                "routing": res.routing.decision,
                "review": res.review.model_dump(),
                "uncovered_topics": res.review.uncovered_topics,
                "warnings": res.warnings,
                "seconds": round(time.perf_counter() - t0, 2),
                "answer_language": detect_language(res.answer),
                "request_language": detect_language(request),
                "answer": res.answer[:600],
                "expected": {"mode": exp_mode, "agent": exp_agent, "needs_claude": exp_claude},
                "matches": {
                    "mode": exp_mode == "any" or res.mode == exp_mode,
                    "agent": exp_agent in agents,
                    "needs_claude": res.routing.needs_claude == exp_claude,
                },
                "job_id": res.job_id,
            }
            rows.append(row)
            m = row["matches"]
            print(f"[{res.status:<9}] {res.mode:<6} {' → '.join(agents):<28} {row['seconds']:>6} sn  "
                  f"claude:{'E' if res.routing.needs_claude else 'H'}  beklenti mod/ajan/claude: "
                  f"{'✓' if m['mode'] else '✗'}{'✓' if m['agent'] else '✗'}{'✓' if m['needs_claude'] else '✗'}")
            print(f"            {request[:80]}")
            for w in res.warnings:
                print(f"            uyarı: {w}")

    ok = [r for r in rows if r["status"] == "succeeded"]
    summary = {
        "success_rate": f"{len(ok)}/{len(rows)}",
        "mode_match": f"{sum(r['matches']['mode'] for r in rows)}/{len(rows)}",
        "agent_match": f"{sum(r['matches']['agent'] for r in rows)}/{len(rows)}",
        "needs_claude_match": f"{sum(r['matches']['needs_claude'] for r in rows)}/{len(rows)}",
        "language_match": f"{sum(r['answer_language'] in (r['request_language'], 'other') for r in ok)}/{len(ok)}",
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
    }
    out = settings.data_dir / "conductor_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nÖZET:", json.dumps(summary, ensure_ascii=False))
    print(f"Rapor: {out}")
    return 0 if len(ok) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
