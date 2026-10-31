"""Model karşılaştırma (Adım 11, doğrulayıcı kapısı): bir ajanın görev setinde mevcut model ile aday model yarışır.

- Ayrı görev veritabanında çalışır (gerçek geçmiş kirlenmez); ajan doğrudan çağrılır (planlayıcı değişkenliği yok).
- Doğruluk KODLA ölçülür: şema/anlamsal doğrulama, beklenen değerler, dil, yabancı yazı, kod sözdizimi.
- Aynı anda tek karşılaştırma (tek GPU). Sonuç `data/model_compare/<id>.json`, ilerleme `model.compare` olaylarıyla.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .ollama_client import OllamaError

if TYPE_CHECKING:
    from ..runtime import Runtime

_LOCK = threading.Lock()

# (istek, beklenen, kod bekleniyor mu). Beklenen: sayı → cevapta o SAYI (20 ≠ 200; istekte geçen sayılar sayılmaz);
# metin → kelime olarak (büyük/küçük harf duyarsız). Beklenen sayılar istekteki sayılarla çakışmayacak şekilde seçildi.
Expected = list[str | int | float]
CASES: dict[str, list[tuple[str, Expected, bool]]] = {
    "coder": [
        ("Python'da bir listedeki çift sayıları döndüren bir fonksiyon yaz ve kısaca açıkla.", [], True),
        ("Write a Python function that checks whether a string is a palindrome, with one usage example.", [], True),
        ("Python'da bir sözlüğü değerlerine göre büyükten küçüğe sıralayan kısa bir fonksiyon yaz.", [], True),
    ],
    "data": [
        ("Şu aylık satışların toplamını ve aylık ortalamasını hesapla: Ocak 140, Şubat 90, Mart 100.", [330, 110], False),
        ("Compute the total and the average of these expenses: 40, 70, 50, 80.", [240, 60], False),
        ("Bir ürünün fiyatı 250 TL'den 300 TL'ye çıktı. Artış yüzde kaç?", [20], False),
        ("Bir mağaza ocakta 200, şubatta 260 adet sattı. Şubattaki artış yüzde kaç? Mart satışları şubata göre %25 "
         "düşerse mart kaç adet olur?", [30, 195], False),
        ("A product costs 80. It gets a 25% discount, then 10% tax is added to the discounted price. "
         "What is the final price?", [66], False),
    ],
    "document": [
        ("Bir müşteriye, yarınki toplantının gelecek haftaya ertelendiğini bildiren kısa ve resmi bir e-posta yaz.", [], False),
        ("Şu metni daha resmi ve düzgün bir Türkçeyle yeniden yaz: 'abi rapor yarın gelir sıkıntı yok merak etme'", [], False),
    ],
    "general": [
        ("Türkiye'nin başkenti neresi?", ["Ankara"], False),
        ("Explain in two sentences what an API is.", [], False),
        ("Şu cümleyi İngilizceye çevir: 'Yarın sabah toplantıya geç kalacağım.'", ["late"], False),
        ("Bir haftada toplam kaç saat vardır?", [168], False),
        ("What is 15% of 240? Answer in one sentence.", [36], False),
    ],
}

_NUM = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)*")


def numbers(text: str) -> list[float]:
    """Metindeki sayılar; Türkçe ve İngilizce biçimler: 1.234,56 · 1,234.56 · 0,20 · 60.0 · %25 · 25%'dır."""
    out = []
    for raw in _NUM.findall(text):
        t = raw
        if "." in t and "," in t:  # sonuncu ayraç ondalık
            t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
        elif "," in t:  # 1,234 / 1,234,567 → binlik (İngilizce); 0,20 / 2,5 → ondalık (Türkçe)
            parts = t.split(",")
            t = t.replace(",", "") if all(len(x) == 3 for x in parts[1:]) and parts[0].lstrip("-") != "0" else t.replace(",", ".")
        elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[1]) == 3 and t.lstrip("-")[0] != "0"):
            t = t.replace(".", "")  # 3.000 / 1.234.567 → binlik (Türkçe); 60.0 / 68.00 → ondalık
        try:
            out.append(float(t))
        except ValueError:
            continue
    return out


def missing_expected(answer: str, request: str, expected: Expected) -> list[str]:
    """Cevapta bulunmayan beklentiler. Sayı: cevapta, istekte geçtiğinden FAZLA kez geçmeli (soruyu tekrarlamak sayılmaz)."""
    ans_nums, req_nums = numbers(answer), numbers(request)
    out: list[str] = []
    for e in expected:
        if isinstance(e, (int, float)):
            hits = sum(abs(n - e) < 1e-6 for n in ans_nums) - sum(abs(n - e) < 1e-6 for n in req_nums)
            if hits <= 0:
                out.append(f"{e:g}")
        elif not re.search(rf"(?<!\w){re.escape(e)}(?!\w)", answer, re.IGNORECASE):
            out.append(e)
    return out


def is_echo(answer: str, request: str) -> bool:
    """Cevap isteğin kendisi mi (model soruyu geri yazdı)?"""
    a, r = " ".join(answer.lower().split()), " ".join(request.lower().split())
    return len(a) > 20 and SequenceMatcher(None, a, r).ratio() > 0.8


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


def _score(task: Any, request: str, expected: Expected, code: bool) -> dict[str, Any]:
    from ..conductor.checks import run_checks
    from ..core.lang import detect_language, foreign_script, strip_code

    ans = str((task.result or {}).get("answer", "")) if task.result else ""
    ok_task = task.status.value == "succeeded"
    missing = missing_expected(ans, request, expected)
    echo = is_echo(ans, request)
    prose = strip_code(ans)
    lang_ok = True
    if len(prose.split()) >= 4 and "çevir" not in request.lower():
        lang_ok = detect_language(prose) in ("other", detect_language(request))
    checks = run_checks(ans, ["code_syntax"])
    code_ok = (not code) or (checks.checked_blocks > 0 and not checks.failures)
    clean = not foreign_script(ans, request)
    return {
        "request": request[:90], "ok": ok_task and not missing and not echo and lang_ok and code_ok and clean,
        "succeeded": ok_task, "missing": missing, "echo": echo, "language_ok": lang_ok, "code_ok": code_ok, "foreign_script": not clean,
        "seconds": round(task.duration_s or 0, 2), "tokens_per_second": (task.metrics or {}).get("tokens_per_second"),
        "attempts": (task.metrics or {}).get("output_attempts"), "answer_head": ans[:300],
    }


def _loaded_names(rt: "Runtime") -> set[str]:
    try:
        return {m.get("name", "") for m in rt.llm.running_models()}
    except OllamaError:
        return set()


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
    rec.setdefault("load_seconds", {})
    try:
        was_loaded = _loaded_names(rt)
        for side, key in (("current", rec["current"]), ("candidate", rec["candidate"])):
            # Isınma: modeli önce belleğe yükle; yükleme süresi vakalara karışmasın (ayrı raporlanır).
            t0 = time.monotonic()
            try:
                spec = rt.registry.get(key)
                rt.llm.load_model(spec.name, options=spec.ollama_options())  # sohbetle aynı num_ctx → yeniden yükleme yok
            except OllamaError:
                pass  # kurulu değilse vakalar zaten başarısız olur ve raporlanır
            rec["load_seconds"][side] = round(time.monotonic() - t0, 2)
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
        cand_name = rt.registry.get(rec["candidate"]).name
        if cand_name not in was_loaded:  # karşılaştırmadan önce bellekte değildiyse VRAM'i geri ver
            try:
                rt.llm.unload_model(cand_name)
            except OllamaError:
                pass
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
    from .manager import ModelAdminError, ensure_think_policy, resolve_candidate

    try:
        candidate_key = resolve_candidate(rt, candidate_key)  # anahtar ya da Ollama adı; kurulu+kayıtsız → aday
    except ModelAdminError as exc:
        raise CompareError(str(exc)) from exc
    ensure_think_policy(rt, candidate_key)
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
