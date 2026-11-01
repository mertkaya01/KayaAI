"""`kayaai quality`: yerel ajanların çıktı kalitesi — fine-tuning gerekip gerekmediğine KANITLA karar vermek için.

Kaynak yalnız bu bilgisayardaki görev kayıtlarıdır (`tasks` tablosu); hiçbir şey dışarı gönderilmez, model çağrılmaz.
Her ajan × model için: görev sayısı, başarı, **ilk denemede geçerli çıktı** oranı (şema + doğrulama), şema/doğrulama
hataları, geçersiz çıktı (3 denemede de olmadı), zaman aşımı, kesilen cevap (`done_reason=length`), hız.

Karar kuralı (docs/FINETUNING.md): en az 30 görevi olan bir grupta ilk-deneme oranı %85'in altındaysa ya da geçersiz
çıktı %5'in üstündeyse o ajan "aday"dır — önce istem/model değişikliği denenir, düzelmezse dar kapsamlı LoRA düşünülür.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MIN_TASKS = 30
FIRST_TRY_TARGET = 0.85
INVALID_LIMIT = 0.05
_IGNORED = {"pending", "running", "awaiting_approval", "waiting_claude", "cancelled", "rejected"}


def _classify(t: dict[str, Any]) -> str:
    st = t.get("status")
    if st == "succeeded":
        return "succeeded"
    if st == "timed_out":
        return "timed_out"
    v = t.get("validation") or {}
    if st == "failed" and v and not v.get("passed", True):
        return "invalid"  # şema ya da doğrulama: 3 denemede de geçerli çıktı yok
    return "error"        # Ollama hatası vb. — model kalitesi değil


def _pct(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    speeds: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in rows:
        if t.get("status") in _IGNORED:
            continue
        m = t.get("metrics") or {}
        key = (t.get("worker") or "?", t.get("model") or m.get("model") or "?")
        g = groups[key]
        kind = _classify(t)
        g["tasks"] += 1
        g[kind] += 1
        attempts = int(m.get("output_attempts") or 0)
        vret = int(m.get("validation_retries") or 0)
        if kind == "succeeded" and attempts <= 1:
            g["first_try"] += 1
        # Başarısız deneme sayıları: son deneme de başarısızsa (geçersiz) hangi kontrolde düştüğü validator adından
        last_failed = kind == "invalid"
        last_schema = last_failed and (t.get("validation") or {}).get("validator") == "schema"
        g["validation_failures"] += vret + (1 if last_failed and not last_schema else 0)
        g["schema_failures"] += max(0, attempts - 1 - vret) + (1 if last_schema else 0)
        if m.get("done_reason") == "length":
            g["truncated"] += 1
        if m.get("tokens_per_second"):
            speeds[key].append(float(m["tokens_per_second"]))

    agents = []
    for (worker, model), g in sorted(groups.items()):
        judged = g["tasks"] - g["error"]  # altyapı hataları modelin suçu değil
        first = _pct(g["first_try"], judged)
        invalid = _pct(g["invalid"], judged)
        if judged < MIN_TASKS:
            verdict = "yetersiz veri"
        elif (first is not None and first < FIRST_TRY_TARGET) or (invalid is not None and invalid > INVALID_LIMIT):
            verdict = "aday"
        else:
            verdict = "gerek yok"
        sp = speeds[(worker, model)]
        agents.append({
            "agent": worker, "model": model, "tasks": g["tasks"], "judged": judged,
            "succeeded": g["succeeded"], "first_try": g["first_try"], "first_try_rate": first,
            "invalid": g["invalid"], "invalid_rate": invalid, "timed_out": g["timed_out"], "errors": g["error"],
            "schema_failures": g["schema_failures"], "validation_failures": g["validation_failures"],
            "truncated": g["truncated"], "tokens_per_second": round(sum(sp) / len(sp), 1) if sp else None,
            "verdict": verdict,
        })
    cands = [a for a in agents if a["verdict"] == "aday"]
    if cands:
        summary = ("Aday: " + ", ".join(f"{a['agent']} ({a['model']})" for a in cands)
                   + " — önce istem/model değişikliği, düzelmezse dar kapsamlı LoRA (docs/FINETUNING.md)")
    elif any(a["verdict"] == "gerek yok" for a in agents):
        summary = "Fine-tuning gerekmiyor: yeterli verisi olan ajanların hepsi hedefte"
    else:
        summary = f"Yetersiz veri: karar için ajan başına en az {MIN_TASKS} görev gerekli"
    return {"agents": agents, "summary": summary,
            "rules": {"min_tasks": MIN_TASKS, "first_try_target": FIRST_TRY_TARGET, "invalid_limit": INVALID_LIMIT}}


def run(store: Any, data_dir: Path, days: int | None = None) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else None
    out = report(store.iter_task_rows(since))
    out.update({"generated": datetime.now().isoformat(timespec="seconds"), "days": days})
    path = data_dir / "quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    out["path"] = str(path)
    return out


def format_table(out: dict[str, Any]) -> list[str]:
    def pc(v: float | None) -> str:
        return "-" if v is None else f"%{v * 100:.0f}"

    lines = [f"{'ajan':<14}{'model':<22}{'görev':>6}{'ilk deneme':>12}{'geçersiz':>10}{'zaman aşımı':>13}"
             f"{'kesik':>7}{'tok/sn':>8}  karar"]
    for a in out["agents"]:
        lines.append(f"{a['agent'][:13]:<14}{a['model'][:21]:<22}{a['tasks']:>6}{pc(a['first_try_rate']):>12}"
                     f"{pc(a['invalid_rate']):>10}{a['timed_out']:>13}{a['truncated']:>7}"
                     f"{(a['tokens_per_second'] or 0):>8.0f}  {a['verdict']}")
    if not out["agents"]:
        lines.append("(henüz biten görev yok)")
    lines.append(out["summary"])
    return lines
