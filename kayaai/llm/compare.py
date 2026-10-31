"""Model karşılaştırma (Adım 11, doğrulayıcı kapısı): bir ajanın görev setinde mevcut model ile aday model yarışır.

- Ayrı görev veritabanında çalışır (gerçek geçmiş kirlenmez); ajan doğrudan çağrılır (planlayıcı değişkenliği yok).
- Doğruluk KODLA ölçülür: şema/anlamsal doğrulama, beklenen değerler, dil, yabancı yazı, kod sözdizimi.
- Aynı anda tek karşılaştırma (tek GPU). Sonuç `data/model_compare/<id>.json`, ilerleme `model.compare` olaylarıyla.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime

_LOCK = threading.Lock()

# (istek, beklenen ifadeler, kod bekleniyor mu)
CASES: dict[str, list[tuple[str, list[str], bool]]] = {
    "coder": [
        ("Python'da bir listedeki çift sayıları döndüren bir fonksiyon yaz ve kısaca açıkla.", [], True),
        ("Write a Python function that checks whether a string is a palindrome, with one usage example.", [], True),
        ("Python'da bir sözlüğü değerlerine göre büyükten küçüğe sıralayan kısa bir fonksiyon yaz.", [], True),
    ],
    "data": [
        ("Şu aylık satışların toplamını ve aylık ortalamasını hesapla: Ocak 120, Şubat 80, Mart 100.", ["300", "100"], False),
        ("Compute the total and the average of these expenses: 40, 60, 50, 90.", ["240", "60"], False),
        ("Bir ürünün fiyatı 250 TL'den 300 TL'ye çıktı. Artış yüzde kaç?", ["20"], False),
    ],
    "document": [
        ("Bir müşteriye, yarınki toplantının gelecek haftaya ertelendiğini bildiren kısa ve resmi bir e-posta yaz.", [], False),
        ("Şu metni daha resmi ve düzgün bir Türkçeyle yeniden yaz: 'abi rapor yarın gelir sıkıntı yok merak etme'", [], False),
    ],
    "general": [
        ("Türkiye'nin başkenti neresi?", ["Ankara"], False),
        ("Explain in two sentences what an API is.", [], False),
        ("Şu cümleyi İngilizceye çevir: 'Yarın sabah toplantıya geç kalacağım.'", ["late"], False),
    ],
}


class CompareError(ValueError):
    pass


def compare_dir(rt: "Runtime") -> Path:
    return rt.settings.data_dir / "model_compare"


def list_compares(rt: "Runtime") -> list[dict[str, Any]]:
    d = compare_dir(rt)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def get_compare(rt: "Runtime", cid: str) -> dict[str, Any]:
    p = compare_dir(rt) / f"{cid}.json"
    if not p.is_file() or not cid.isalnum():
        raise CompareError(f"Karşılaştırma bulunamadı: {cid}")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(rt: "Runtime", rec: dict[str, Any]) -> None:
    d = compare_dir(rt)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{rec['id']}.json.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / f"{rec['id']}.json")


def _score(task: Any, request: str, expected: list[str], code: bool) -> dict[str, Any]:
    from ..conductor.checks import run_checks
    from ..core.lang import detect_language, foreign_script, strip_code

    ans = str((task.result or {}).get("answer", "")) if task.result else ""
    ok_task = task.status.value == "succeeded"
    missing = [e for e in expected if e.lower() not in ans.lower()]
    prose = strip_code(ans)
    lang_ok = True
    if len(prose.split()) >= 4 and "çevir" not in request.lower():
        lang_ok = detect_language(prose) in ("other", detect_language(request))
    checks = run_checks(ans, ["code_syntax"])
    code_ok = (not code) or (checks.checked_blocks > 0 and not checks.failures)
    clean = not foreign_script(ans, request)
    return {
        "request": request[:90], "ok": ok_task and not missing and lang_ok and code_ok and clean,
        "succeeded": ok_task, "missing": missing, "language_ok": lang_ok, "code_ok": code_ok, "foreign_script": not clean,
        "seconds": round(task.duration_s or 0, 2), "tokens_per_second": (task.metrics or {}).get("tokens_per_second"),
        "attempts": (task.metrics or {}).get("output_attempts"), "answer_head": ans[:300],
    }


def _run(rt: "Runtime", rec: dict[str, Any]) -> dict[str, Any]:
    from ..agents.definitions import make_worker
    from ..core.orchestrator import Orchestrator
    from ..core.store import TaskStore
    from ..workers import WorkerRegistry

    agent = rec["agent"]
    base = rt.workers.get(agent).definition  # type: ignore[attr-defined]
    cases = CASES.get(agent) or CASES.get(base.base or "", None) or CASES["general"]
    work = compare_dir(rt) / f"{rec['id']}.db"
    store = TaskStore(work)
    total = len(cases) * 2
    done = 0
    try:
        for side, key in (("current", rec["current"]), ("candidate", rec["candidate"])):
            workers = WorkerRegistry()
            workers.register(make_worker(base.model_copy(update={"local_model": key})))
            orch = Orchestrator(store, workers, rt.llm, rt.registry, rt.settings.orchestrator, rt.settings.permissions)
            rows = []
            for request, expected, code in cases:
                task = orch.ask(request, worker=agent)
                rows.append(_score(task, request, expected, code))
                done += 1
                rt.store.emit("model.compare", {"id": rec["id"], "done": done, "total": total, "side": side})
            rec["rows"][side] = rows
        for side in ("current", "candidate"):
            rows = rec["rows"][side]
            speeds = [r["tokens_per_second"] for r in rows if r["tokens_per_second"]]
            rec["summary"][side] = {
                "model": rt.registry.get(rec[side]).name, "cases": len(rows), "ok": sum(r["ok"] for r in rows),
                "avg_seconds": round(sum(r["seconds"] for r in rows) / max(1, len(rows)), 2),
                "avg_tokens_per_second": round(sum(speeds) / len(speeds), 1) if speeds else None,
            }
        rec["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - sonuç kaydı her durumda yazılmalı
        rec["status"], rec["error"] = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        store.close()
        try:
            work.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                work.with_name(work.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass
        rec["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _save(rt, rec)
        rt.store.emit("model.compare", {"id": rec["id"], "status": rec["status"], "done": done, "total": total})
        _LOCK.release()
    return rec


def start_compare(rt: "Runtime", agent: str, candidate_key: str) -> dict[str, Any]:
    """Karşılaştırmayı başlatır. API'de arka planda; CLI'da bitene kadar çalışır. Kaydı döner."""
    from ..agents.lifecycle import sync_agents

    sync_agents(rt)
    if agent not in rt.workers.names() or getattr(rt.workers.get(agent), "definition", None) is None:
        raise CompareError(f"Bilinmeyen ajan: {agent}")
    d = rt.workers.get(agent).definition  # type: ignore[attr-defined]
    if d.output != "answer":
        raise CompareError("Yalnızca cevap üreten ajanlar karşılaştırılabilir (planlayıcı/gözden geçirici değil)")
    if candidate_key not in rt.registry.models:
        raise CompareError(f"Kayıtlı model değil: {candidate_key}")
    if candidate_key == d.local_model:
        raise CompareError("Aday, ajanın şu anki modeliyle aynı")
    if candidate_key == rt.settings.memory.embed_model:
        raise CompareError("Embedding modeli sohbet modeli değildir")
    if not _LOCK.acquire(blocking=False):
        raise CompareError("Zaten bir karşılaştırma sürüyor (tek GPU); bitmesini bekle")
    rec = {"id": uuid.uuid4().hex[:10], "agent": agent, "current": d.local_model, "candidate": candidate_key,
           "status": "running", "started_at": datetime.now().isoformat(timespec="seconds"), "rows": {}, "summary": {},
           "started": time.time()}
    try:
        _save(rt, rec)
        rt.store.emit("model.compare", {"id": rec["id"], "status": "running", "done": 0})
        if getattr(rt, "background_ok", False):
            threading.Thread(target=_run, args=(rt, rec), name=f"kayaai-compare-{rec['id']}", daemon=True).start()
            return rec
    except BaseException:
        _LOCK.release()
        raise
    return _run(rt, rec)
