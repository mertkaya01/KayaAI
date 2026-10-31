"""kayaAI Faz 1 kabul testleri - GERÇEK Ollama ve GERÇEK model ile.

Kullanım (proje klasöründe, venv etkin):
    python scripts/smoke_ollama.py            # kabul testleri + kısa benchmark
    python scripts/smoke_ollama.py --quick    # sadece kabul testleri

Kabul testleri (MASTER_PROMPT bölüm 20):
    #1  Yerel LLM başarıyla yanıt veriyor
    #2  Python, Ollama ile konuşuyor
    #3  Orkestratör görevi bir worker'a delege ediyor
    #4  Worker doğrulanmış yapılandırılmış çıktı döndürüyor
    #13 Sistem yeniden başlayınca görev geçmişini geri yüklüyor

Sonuç: data/smoke_report.json  (bu dosyayı geliştirme oturumuna yapıştırın)
Çıkış kodu: tüm kabul testleri geçerse 0, aksi halde 1.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai import __version__  # noqa: E402
from kayaai.config import load_settings  # noqa: E402
from kayaai.core.lang import detect_language  # noqa: E402
from kayaai.core.task import TaskStatus  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402
from kayaai.system.audit import gpu_info  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# (beklenen cevap dili, soru). Çeviri sorusunda beklenen dil HEDEF dildir.
BENCH_PROMPTS = [
    ("tr", "Python'da liste ile demet (tuple) arasındaki farkı iki cümleyle açıkla."),
    ("en", "Give three short tips for writing readable Python code."),
    ("en", "Şu cümleyi İngilizceye çevir: 'Yarın sabah toplantıya geç kalacağım.'"),
    ("tr", "Bir freelance yazılımcı için haftalık plan önerisi ver, 3 madde."),
    ("en", "Summarize in one sentence: Local LLMs run on the user's own hardware, keeping data private."),
    ("en", "Explain what an API is in two sentences."),
]


class Report:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kayaai_version": __version__,
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} {platform.version()}",
            "acceptance": {},
            "benchmark": {},
        }

    def check(self, key: str, title: str, fn: Callable[[], dict[str, Any]]) -> bool:
        print(f"\n[{key}] {title} ...", flush=True)
        t0 = time.perf_counter()
        try:
            detail = fn()
            passed = bool(detail.pop("passed", True))
        except Exception as exc:  # noqa: BLE001
            detail = {"exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=3)}
            passed = False
        detail["seconds"] = round(time.perf_counter() - t0, 2)
        self.data["acceptance"][key] = {"title": title, "passed": passed, **detail}
        print(f"    -> {'GEÇTİ' if passed else 'BAŞARISIZ'}  {json.dumps(detail, ensure_ascii=False, default=str)[:400]}")
        return passed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="benchmark'ı atla")
    args = ap.parse_args()

    settings = load_settings()
    report = Report()
    report.data["gpu_before"] = gpu_info()
    rt = build_runtime(settings)
    spec = rt.registry.model_for_worker("general")
    report.data["model"] = spec.model_dump()
    state: dict[str, Any] = {}

    # #2 Python <-> Ollama
    def t2() -> dict[str, Any]:
        version = rt.llm.version()
        installed = [m.get("name") for m in rt.llm.list_models()]
        present = rt.llm.has_model(spec.name)
        hint = None if present else f"Model kurulu değil: ollama pull {spec.name}"
        return {"passed": present, "ollama_version": version, "installed_models": installed, "hint": hint}

    ok2 = report.check("#2", "Python, Ollama ile konuşuyor ve model kurulu", t2)

    # #1 Yerel LLM yanıt veriyor (ham sohbet, ilk çağrı modeli yükler)
    def t1() -> dict[str, Any]:
        res = rt.llm.chat(
            spec.name,
            [{"role": "user", "content": "Türkiye'nin başkenti neresidir? Sadece şehir adını yaz."}],
            options=spec.ollama_options(),
            think=spec.think,
            keep_alive=spec.keep_alive,
        )
        return {
            "passed": "ankara" in res.content.lower(),
            "answer": res.content.strip()[:200],
            "cold_start": True,  # ilk çağrı: model diskten VRAM'e yüklenir + GPU ısınması
            **res.metrics(),
        }

    ok1 = report.check("#1", "Yerel LLM yanıt veriyor (Türkçe doğruluk: Ankara)", t1) if ok2 else False

    # Aynı istek model yüklüyken: soğuk/sıcak başlangıç farkı
    if ok1:
        try:
            warm = rt.llm.chat(
                spec.name,
                [{"role": "user", "content": "Türkiye'nin başkenti neresidir? Sadece şehir adını yaz."}],
                options=spec.ollama_options(), think=spec.think, keep_alive=spec.keep_alive,
            )
            report.data["latency"] = {
                "cold_total_s": report.data["acceptance"]["#1"].get("total_duration_s"),
                "cold_load_s": report.data["acceptance"]["#1"].get("load_duration_s"),
                "warm_total_s": round(warm.total_duration_s, 3),
                "warm_load_s": round(warm.load_duration_s, 3),
            }
        except Exception as exc:  # noqa: BLE001
            report.data["latency"] = {"error": str(exc)}

    # VRAM ölçümü: model şimdi yüklü olmalı
    try:
        report.data["loaded_models"] = [
            {
                "name": m.get("name"),
                "size_gb": round((m.get("size") or 0) / 1024**3, 2),
                "size_vram_gb": round((m.get("size_vram") or 0) / 1024**3, 2),
                "context_length": m.get("context_length"),
            }
            for m in rt.llm.running_models()
        ]
    except Exception as exc:  # noqa: BLE001
        report.data["loaded_models"] = f"okunamadı: {exc}"
    report.data["gpu_after_load"] = gpu_info()

    # #3 + #4 Orkestratör -> worker -> doğrulanmış çıktı
    def t34() -> dict[str, Any]:
        task = rt.orchestrator.ask("Merhaba! Kendini tek cümleyle tanıtır mısın?")
        state["task_id"] = task.id
        return {
            "passed": task.status == TaskStatus.SUCCEEDED and bool(task.validation and task.validation.passed),
            "task_id": task.id,
            "status": task.status.value,
            "error": task.error,
            "result": task.result,
            "validation": task.validation.model_dump() if task.validation else None,
            "metrics": task.metrics,
        }

    ok34 = report.check("#3/#4", "Orkestratör delege ediyor, worker doğrulanmış JSON döndürüyor", t34) if ok1 else False

    # #13 Yeniden başlatma sonrası geçmiş
    def t13() -> dict[str, Any]:
        rt.close()
        rt2 = build_runtime(settings)
        state["rt"] = rt2
        restored = rt2.store.get(state["task_id"])
        return {
            "passed": restored is not None and restored.status == TaskStatus.SUCCEEDED,
            "restored_status": restored.status.value if restored else None,
            "total_tasks_in_history": rt2.store.count(),
        }

    ok13 = report.check("#13", "Yeniden başlatmada görev geçmişi geri yükleniyor", t13) if ok34 else False
    current = state.get("rt", rt)

    # Benchmark (bilgi amaçlı; kabul kriterini etkilemez)
    if ok34 and not args.quick:
        print("\n[bench] JSON güvenilirliği ve hız ölçülüyor ...", flush=True)
        rows = []
        for lang, prompt in BENCH_PROMPTS:
            t = current.orchestrator.ask(prompt)
            answer_text = str((t.result or {}).get("answer", ""))
            rows.append(
                {
                    "lang": lang,
                    "prompt": prompt[:60],
                    "status": t.status.value,
                    "first_try_valid": t.metrics.get("output_attempts") == 1,
                    "validation_retries": t.metrics.get("validation_retries", 0),
                    "corrections": t.metrics.get("corrections", []),
                    "model_language_label": (t.result or {}).get("language"),
                    "detected_language": detect_language(answer_text),
                    "tokens_per_second": t.metrics.get("tokens_per_second"),
                    "seconds": t.duration_s,
                    "answer": str((t.result or {}).get("answer", t.error))[:300],
                }
            )
            print(f"    {lang} {t.status.value:<10} {t.metrics.get('tokens_per_second')} tok/s  {rows[-1]['answer'][:80]!r}")
        tps = [r["tokens_per_second"] for r in rows if r["tokens_per_second"]]
        report.data["benchmark"] = {
            "runs": rows,
            "success_rate": sum(r["status"] == "succeeded" for r in rows) / len(rows),
                        "language_match_rate": sum(r["detected_language"] == r["lang"] for r in rows) / len(rows),
            "first_try_all_checks_rate": sum(r["first_try_valid"] for r in rows) / len(rows),
            "avg_tokens_per_second": round(sum(tps) / len(tps), 1) if tps else None,
        }

        def arithmetic() -> dict[str, Any]:
            res = current.llm.chat(
                spec.name,
                [{"role": "user", "content": "What is 17 * 23? Reply with only the number."}],
                options=spec.ollama_options(), think=spec.think, keep_alive=spec.keep_alive,
            )
            return {"answer": res.content.strip()[:50], "correct": "391" in res.content}

        try:
            report.data["benchmark"]["arithmetic"] = arithmetic()
        except Exception as exc:  # noqa: BLE001
            report.data["benchmark"]["arithmetic"] = {"error": str(exc)}

    current.close()
    all_ok = ok1 and ok2 and ok34 and ok13
    report.data["all_acceptance_passed"] = all_ok
    out = settings.data_dir / "smoke_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print("\n================================================")
    print("SONUÇ:", "TÜM KABUL TESTLERİ GEÇTİ" if all_ok else "BAZI KABUL TESTLERİ BAŞARISIZ")
    if report.data["benchmark"]:
        b = report.data["benchmark"]
        print(f"Benchmark: başarı {b['success_rate']:.0%}, ilk denemede tüm kontroller {b['first_try_all_checks_rate']:.0%}, "
              f"dil eşleşmesi {b['language_match_rate']:.0%}, ort. {b['avg_tokens_per_second']} token/sn")
    print(f"Rapor: {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
