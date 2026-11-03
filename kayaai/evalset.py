"""Sahibin test seti (Adım 22): "daha iyi oldu mu" tahmin değil ölçüm olsun.

`data/eval/sorular.yaml`: her soru için cevapta OLMASI gereken ifadeler (`olmali`) ve olmaması gerekenler (`olmamali`).
Kontrol kodla yapılır (büyük/küçük harf ve Türkçe i/ı duyarsız). Sohbette 👎 verilen cevaplar `aktar` ile buraya eklenir
(ifadeleri sahip yazar). `calistir` hepsini yerel ekiple (şef) çalıştırır, sonucu `data/eval/sonuc-<zaman>.json`'a yazar
ve bir önceki çalıştırmayla karşılaştırır.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

if TYPE_CHECKING:
    from .runtime import Runtime

HEADER = """# kayaAI test seti — her değişiklikten sonra: kayaai degerlendir calistir
# soru: sorulacak metin · olmali: cevapta MUTLAKA geçmesi gereken ifadeler · olmamali: geçmemesi gerekenler
# Kontrol büyük/küçük harf duyarsız. Sohbette 👎 verdiğin cevaplar: kayaai degerlendir aktar
"""

SEED: list[dict[str, Any]] = [
    {"soru": "Türkiye'nin başkenti neresidir? Tek cümleyle cevap ver.", "olmali": ["Ankara"], "olmamali": ["İstanbul'dur"]},
    {"soru": "17 ile 23'ün çarpımı kaçtır?", "olmali": ["391"]},
    {"soru": "Şu cümleyi İngilizceye çevir: 'Yarın sabah toplantıya geç kalacağım.'", "olmali": ["late", "meeting", "tomorrow"]},
    {"soru": "Neler yapabildiğinizi tek tek açıklar mısın?", "olmali": ["Excel", "belge", "kod"], "olmamali": ["bilmiyorum"]},
    {"soru": "Python'da bir listenin elemanlarını toplayan kısa bir fonksiyon yaz.", "olmali": ["def ", "return"]},
    {"soru": "Müşteriye teslim tarihinin bir hafta gecikeceğini bildiren kısa ve kibar bir e-posta yaz.", "olmali": ["hafta"],
     "olmamali": ["[İsim]"]},
]


def folder(rt: "Runtime") -> Path:
    return rt.settings.data_dir / "eval"


def questions_path(rt: "Runtime") -> Path:
    return folder(rt) / "sorular.yaml"


def _norm(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def load(rt: "Runtime") -> list[dict[str, Any]]:
    p = questions_path(rt)
    if not p.is_file():
        save(rt, SEED)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for q in data.get("sorular") or []:
        if isinstance(q, dict) and str(q.get("soru", "")).strip():
            out.append({"soru": str(q["soru"]).strip(), "olmali": [str(x) for x in q.get("olmali") or []],
                        "olmamali": [str(x) for x in q.get("olmamali") or []], "not": str(q.get("not") or "")})
    return out


def save(rt: "Runtime", items: list[dict[str, Any]]) -> Path:
    p = questions_path(rt)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"sorular": items}, allow_unicode=True, sort_keys=False, width=110)
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def import_feedback(rt: "Runtime") -> int:
    """👎 verilen cevapların sorularını sete ekler (zaten varsa atlar). İfadeleri sahip doldurur."""
    from .assistant.chat import ChatBook

    items = load(rt)
    have = {_norm(q["soru"]) for q in items}
    added = 0
    for fb in ChatBook(rt).feedback_items("down"):
        q = fb["question"].strip()
        if not q or _norm(q) in have:
            continue
        items.append({"soru": q, "olmali": [], "olmamali": [], "not": f"👎 {fb['note']}".strip()})
        have.add(_norm(q))
        added += 1
    if added:
        save(rt, items)
    return added


def check(answer: str, q: dict[str, Any]) -> dict[str, Any]:
    a = _norm(answer)
    missing = [x for x in q["olmali"] if _norm(x) not in a]
    forbidden = [x for x in q["olmamali"] if _norm(x) in a]
    scored = bool(q["olmali"] or q["olmamali"])
    return {"passed": scored and not missing and not forbidden, "scored": scored, "missing": missing, "forbidden": forbidden}


def run(rt: "Runtime", *, agent: str | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Seti çalıştırır: agent None → şef (otomatik), yoksa o ajan. Dış sağlayıcı kullanılmaz (yerel ölçüm)."""
    items = load(rt)
    results = []
    saved_outbound, rt.orchestrator.outbound = rt.orchestrator.outbound, None  # ölçüm yerel ekibin
    try:
        _run_items(rt, items, agent, results, log)
    finally:
        rt.orchestrator.outbound = saved_outbound
    scored = [r for r in results if r["scored"]]
    summary = {"at": datetime.now().isoformat(timespec="seconds"), "agent": agent or "şef", "total": len(results),
               "scored": len(scored), "passed": sum(r["passed"] for r in scored), "results": results}
    prev = last_result(rt)
    out = folder(rt) / f"sonuc-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["path"] = str(out)
    summary["previous"] = {"passed": prev["passed"], "scored": prev["scored"], "at": prev["at"]} if prev else None
    return summary


def _run_items(rt: "Runtime", items: list[dict[str, Any]], agent: str | None, results: list[dict[str, Any]],
               log: Callable[[str], None]) -> None:
    from .conductor import Conductor

    for i, q in enumerate(items, 1):
        t0 = time.perf_counter()
        try:
            if agent:
                task = rt.orchestrator.ask(q["soru"], worker=agent)
                res_d = task.result or {}
                answer = str(res_d.get("answer") or json.dumps(res_d, ensure_ascii=False)) if res_d else ""
                error, models = task.error, [task.model] if task.model else []
            else:
                res = Conductor(rt).run(q["soru"], force="local")
                answer, error = res.answer, res.error
                models = sorted({c.model for c in rt.store.list_children(res.job_id) if c.model})
        except Exception as exc:  # noqa: BLE001 - bir sorunun hatası seti durdurmaz
            answer, error, models = "", f"{type(exc).__name__}: {exc}", []
        c = check(answer, q)
        r = {"soru": q["soru"], **c, "seconds": round(time.perf_counter() - t0, 1), "error": error, "models": models,
             "answer": answer[:2000]}
        results.append(r)
        mark = "✓" if c["passed"] else ("·" if not c["scored"] else "✗")
        why = "" if c["passed"] or not c["scored"] else f"  eksik: {c['missing']}" + (f" yasak: {c['forbidden']}" if c["forbidden"] else "")
        log(f"  {mark} {i:>2}/{len(items)} {q['soru'][:60]}{why}{f'  HATA: {error}' if error else ''}")


def last_result(rt: "Runtime") -> dict[str, Any] | None:
    files = sorted(folder(rt).glob("sonuc-*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
