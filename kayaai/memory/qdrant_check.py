"""Qdrant'ı bu bilgisayarda başlat / durdur / denetle (Adım 19b doğrulaması, `kayaai qdrant ...`).

- `start`: Docker'da `kayaai-qdrant` konteynerini başlatır; YALNIZ 127.0.0.1'e açılır (ağdaki başka cihazlar
  erişemez), veriler `kayaai-qdrant` Docker biriminde kalır. İlk seferde imaj internetten indirilir; sonra gerekmez.
- `test`: gerçek Qdrant ile ekleme, arama, süzgeç, SQLite ile aynı sonuç, silme → `data/qdrant_check.json`.
  Gerçek hafızana ve belgelerine dokunmaz (deneme vektörleri "check" türüyle yazılır ve silinir). Hata olursa sebebi
  ve konteyner durumu da rapora yazılır.
"""

from __future__ import annotations

import json
import math
import time
import traceback
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from ..sandbox import runner
from .db import MemoryDB
from .qdrant import QdrantError, QdrantStore

CONTAINER = "kayaai-qdrant"
VOLUME = "kayaai-qdrant"
IMAGE = "qdrant/qdrant:v1.12.4"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}

TEXTS = [
    "Atlas projesinin teslim tarihi 15 Kasım.",
    "Raporları her zaman PDF olarak isterim.",
    "Ankara bölgesinde satışlar yüzde 18 arttı.",
    "Kahvemi şekersiz içerim.",
    "Sözleşme 12 ay sürüyor, yenileme otomatik.",
]
QUERY = "Atlas ne zaman teslim edilecek?"

Log = Callable[[str], None]


def _local_port(url: str) -> int | None:
    u = urlparse(url)
    return (u.port or 6333) if u.hostname in LOCAL_HOSTS else None


def run_cmd(port: int, docker: str = "docker") -> list[str]:
    return [docker, "run", "-d", "--name", CONTAINER, "-p", f"127.0.0.1:{port}:6333",
            "-v", f"{VOLUME}:/qdrant/storage", IMAGE]


def container_state(exec_fn: runner.ExecFn | None = None, docker: str = "docker") -> str:
    """'running' | 'exited' | 'created' … | 'yok' (konteyner yok) | 'docker: …' (Docker'a ulaşılamadı)."""
    exec_fn = exec_fn or runner.execute
    code, out, err = exec_fn([docker, "inspect", "-f", "{{.State.Status}}", CONTAINER], 20)
    if code == 0:
        return out.strip() or "?"
    low = err.lower()
    if code == 127 or "daemon" in low or "pipe" in low or "connect" in low:
        return "docker: " + (err.strip()[:200] or "bulunamadı")
    return "yok"


def wait_healthy(url: str, seconds: float = 30, transport: Any = None) -> dict[str, Any]:
    q = QdrantStore(url, transport=transport, timeout=5)
    try:
        deadline = time.monotonic() + seconds
        h = q.health()
        while not h.get("ok") and time.monotonic() < deadline:
            time.sleep(1)
            h = q.health()
        return h
    finally:
        q.close()


def start(url: str, exec_fn: runner.ExecFn | None = None, docker: str = "docker", log: Log = print,
          wait_s: float = 30, transport: Any = None) -> bool:
    exec_fn = exec_fn or runner.execute
    port = _local_port(url)
    if port is None:
        log(f"[HATA] Ayardaki adres ({url}) bu bilgisayar değil; burada başlatılmaz (sunucuda Docker Compose kullanılır).")
        return False
    state = container_state(exec_fn, docker)
    if state.startswith("docker:"):
        log(f"[HATA] Docker'a ulaşılamadı — Docker Desktop açık mı? ({state[8:]})")
        return False
    if state == "running":
        log(f"Qdrant zaten çalışıyor ({CONTAINER}).")
    elif state == "yok":
        log(f"Qdrant başlatılıyor: {IMAGE} → yalnız 127.0.0.1:{port} (ilk seferde imaj indirilir, ~60 MB)…")
        code, out, err = exec_fn(run_cmd(port, docker), 600)
        if code != 0:
            log(f"[HATA] docker run başarısız ({code}): {(err or out).strip()[:400]}")
            if "port is already allocated" in err or "address already in use" in err.lower():
                log(f"  {port} portunu başka bir program kullanıyor. Başka port için ayar: memory.qdrant_url")
            return False
    else:
        log(f"Qdrant konteyneri duruyordu ({state}); başlatılıyor…")
        code, out, err = exec_fn([docker, "start", CONTAINER], 60)
        if code != 0:
            log(f"[HATA] docker start başarısız ({code}): {(err or out).strip()[:400]}")
            return False
    h = wait_healthy(url, wait_s, transport)
    if not h.get("ok"):
        log(f"[HATA] Qdrant başladı ama {url} cevap vermiyor: {h.get('error', '?')}")
        log(f"  Kayıt için: docker logs --tail 30 {CONTAINER}")
        return False
    log(f"[OK] Qdrant hazır: {url} (sürüm {h.get('version')}, {h.get('points', 0)} nokta)")
    return True


def stop(exec_fn: runner.ExecFn | None = None, docker: str = "docker", log: Log = print) -> bool:
    exec_fn = exec_fn or runner.execute
    code, out, err = exec_fn([docker, "stop", CONTAINER], 60)
    if code != 0:
        log(f"[HATA] docker stop: {(err or out).strip()[:300]}")
        return False
    log("Qdrant durduruldu (veriler duruyor; tekrar: kayaai qdrant start).")
    return True


def _vectors(settings: Any, log: Log) -> tuple[list[list[float]], list[float], str]:
    try:
        from ..llm.ollama_client import OllamaClient
        from ..llm.registry import ModelRegistry

        name = ModelRegistry.load_for(settings).get(settings.memory.embed_model).name
        vs = OllamaClient(settings.ollama).embed(name, TEXTS + [QUERY])
        return vs[:-1], vs[-1], name
    except Exception as exc:  # noqa: BLE001 - bge-m3 yoksa sabit vektörlerle devam
        log(f"[bilgi] bge-m3 kullanılamadı ({exc}); sabit deneme vektörleri")

        def v(i: int) -> list[float]:
            return [math.sin(i * 7 + j) for j in range(64)]
        return [v(i) for i in range(len(TEXTS))], [x + 0.01 for x in v(0)], "check-vec"


def run_check(settings: Any, *, exec_fn: runner.ExecFn | None = None, transport: Any = None, log: Log = print,
              vectors: Callable[[Any, Log], tuple[list[list[float]], list[float], str]] | None = None) -> dict[str, Any]:
    url = settings.memory.qdrant_url
    report: dict[str, Any] = {"url": url, "ok": False, "steps": {}}
    q = QdrantStore(url, transport=transport)
    try:
        h = q.health()
        report["health"] = h
        log(f"Qdrant: {url} → {h}")
        if not h.get("ok"):
            state = container_state(exec_fn)
            report["container"] = state
            if state == "yok":
                report["error"] = "Qdrant konteyneri yok — önce: kayaai qdrant start"
            elif state.startswith("docker:"):
                report["error"] = f"Docker'a ulaşılamadı (Docker Desktop açık mı?): {state[8:]}"
            elif state != "running":
                report["error"] = f"Qdrant konteyneri çalışmıyor ({state}) — kayaai qdrant start"
            else:
                report["error"] = f"Konteyner çalışıyor ama {url} cevap vermiyor: {h.get('error', '?')}"
                code, out, err = (exec_fn or runner.execute)(["docker", "logs", "--tail", "20", CONTAINER], 20)
                report["container_logs"] = (out + err)[-2000:]
            return report
        vecs, qv, model = (vectors or _vectors)(settings, log)
        report["model"] = model
        ids = [f"check-{i}" for i in range(len(TEXTS))]
        steps = report["steps"]
        t0 = time.perf_counter()
        q.upsert("check", [(i, model, v) for i, v in zip(ids, vecs)])
        steps["upsert_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        t0 = time.perf_counter()
        got = q.search("check", model, qv, 3)
        steps["search_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        steps["top"] = [[i, round(sc, 4)] for i, sc in got]
        steps["top_is_atlas"] = bool(got) and got[0][0] == "check-0"
        steps["filter_other_kind_empty"] = q.search("memory-yok", model, qv, 3) == []
        tmp = settings.data_dir / "checks" / "qdrant_check.db"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        for p in (tmp, Path(f"{tmp}-wal"), Path(f"{tmp}-shm")):
            p.unlink(missing_ok=True)
        db = MemoryDB(tmp)
        try:
            with db.tx() as c:
                for i, v in zip(ids, vecs):
                    db.put_vector(c, "check", i, model, v)
            ref = db.nearest("check", model, qv, 3)
        finally:
            db.close()
        steps["sqlite_top"] = [[i, round(sc, 4)] for i, sc in ref]
        steps["same_as_sqlite"] = [i for i, _ in ref] == [i for i, _ in got] and all(
            abs(a[1] - b[1]) < 1e-3 for a, b in zip(ref, got))
        q.delete("check", ids)
        steps["deleted"] = q.search("check", model, qv, 3) == []
        report["ok"] = all(steps[k] for k in ("top_is_atlas", "filter_other_kind_empty", "same_as_sqlite", "deleted"))
    except QdrantError as exc:
        report["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - beklenmeyen hata da rapora yazılsın
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-3000:]
    finally:
        q.close()
    return report


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
