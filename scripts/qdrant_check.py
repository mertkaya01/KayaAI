"""Adım 19b doğrulaması — GERÇEK Qdrant ile vektör deposu (ekleme, arama, süzgeç, silme, SQLite ile aynı sonuç).

Önce Qdrant'ı yalnız bu bilgisayardan erişilecek şekilde başlat (Docker):
    docker run -d --name kayaai-qdrant -p 127.0.0.1:6333:6333 -v kayaai-qdrant:/qdrant/storage qdrant/qdrant:v1.12.4
Sonra (proje klasöründe, venv etkin):
    python scripts/qdrant_check.py
Sonuç: data/qdrant_check.json

Gerçek hafızana ve belgelerine dokunmaz: deneme vektörleri "check" türüyle yazılır ve sonunda silinir.
bge-m3 (Ollama) kuruluysa gerçek vektörlerle, değilse sabit deneme vektörleriyle çalışır.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.config import load_settings  # noqa: E402
from kayaai.memory.db import MemoryDB  # noqa: E402
from kayaai.memory.qdrant import QdrantError, QdrantStore  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

TEXTS = [
    "Atlas projesinin teslim tarihi 15 Kasım.",
    "Raporları her zaman PDF olarak isterim.",
    "Ankara bölgesinde satışlar yüzde 18 arttı.",
    "Kahvemi şekersiz içerim.",
    "Sözleşme 12 ay sürüyor, yenileme otomatik.",
]
QUERY = "Atlas ne zaman teslim edilecek?"


def vectors(settings) -> tuple[list[list[float]], list[float], str]:
    try:
        from kayaai.llm.ollama_client import OllamaClient
        from kayaai.llm.registry import ModelRegistry

        name = ModelRegistry.load_for(settings).get(settings.memory.embed_model).name
        c = OllamaClient(settings.ollama)
        vs = c.embed(name, TEXTS + [QUERY])
        return vs[:-1], vs[-1], name
    except Exception as exc:  # noqa: BLE001 - bge-m3 yoksa sabit vektörlerle devam
        print(f"[bilgi] bge-m3 kullanılamadı ({exc}); sabit deneme vektörleri")
        import math

        def v(i: int) -> list[float]:
            return [math.sin(i * 7 + j) for j in range(64)]
        return [v(i) for i in range(len(TEXTS))], [x + 0.01 for x in v(0)], "check-vec"


def main() -> int:
    s = load_settings()
    report: dict = {"url": s.memory.qdrant_url, "ok": False, "steps": {}}
    out = s.data_dir / "qdrant_check.json"
    q = QdrantStore(s.memory.qdrant_url)
    try:
        h = q.health()
        report["health"] = h
        print(f"Qdrant: {s.memory.qdrant_url} → {h}")
        if not h.get("ok"):
            print("[HATA] Qdrant'a ulaşılamadı. Docker komutu bu dosyanın başında.")
            return 1
        vecs, qv, model = vectors(s)
        ids = [f"check-{i}" for i in range(len(TEXTS))]
        t0 = time.perf_counter()
        q.upsert("check", [(i, model, v) for i, v in zip(ids, vecs)])
        report["steps"]["upsert_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        t0 = time.perf_counter()
        got = q.search("check", model, qv, 3)
        report["steps"]["search_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        report["steps"]["top"] = [(i, round(sc, 4)) for i, sc in got]
        report["steps"]["top_is_atlas"] = bool(got) and got[0][0] == "check-0"
        report["steps"]["filter_other_kind_empty"] = q.search("memory-yok", model, qv, 3) == []
        # SQLite (numpy) ile aynı sonuç mu?
        tmp = s.data_dir / "checks" / "qdrant_check.db"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        db = MemoryDB(tmp)
        with db.tx() as c:
            for i, v in zip(ids, vecs):
                db.put_vector(c, "check", i, model, v)
        ref = db.nearest("check", model, qv, 3)
        db.close()
        report["steps"]["same_as_sqlite"] = [i for i, _ in ref] == [i for i, _ in got] and all(
            abs(a[1] - b[1]) < 1e-3 for a, b in zip(ref, got))
        q.delete("check", ids)
        report["steps"]["deleted"] = q.search("check", model, qv, 3) == []
        report["ok"] = all(report["steps"][k] for k in ("top_is_atlas", "filter_other_kind_empty", "same_as_sqlite", "deleted"))
    except QdrantError as exc:
        report["error"] = str(exc)
        print(f"[HATA] {exc}")
    finally:
        q.close()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in report["steps"].items():
        print(f"  {k}: {v}")
    print(("[OK]" if report["ok"] else "[HATA]") + f" Sonuç: {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
