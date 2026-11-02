"""Adım 19b: Qdrant vektör deposu — sahte Qdrant (REST), hafıza/belge araması, işlem sonrası toplu gönderim,
geri alma, silme, taşıma, Qdrant kapalıyken kelime araması."""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
import pytest

from kayaai import memory as memmod
from kayaai.config import load_settings
from kayaai.memory.db import MemoryDB
from kayaai.memory.qdrant import QdrantError, QdrantStore, point_id
from kayaai.runtime import build_runtime


class FakeQdrant:
    """Qdrant REST'inin kullandığımız kısmı (bellekte, kosinüs)."""

    def __init__(self):
        self.cols: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.down = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("bağlantı reddedildi")
        p, m = req.url.path, req.method
        self.calls.append((m, p))
        body = json.loads(req.content) if req.content else {}
        ok = lambda result: httpx.Response(200, json={"result": result, "status": "ok"})  # noqa: E731
        if p == "/":
            return httpx.Response(200, json={"title": "qdrant", "version": "1.12.0"})
        if p == "/collections":
            return ok({"collections": [{"name": n} for n in self.cols]})
        parts = p.strip("/").split("/")
        name = parts[1]
        if len(parts) == 2 and m == "PUT":
            self.cols[name] = {"size": body["vectors"]["size"], "points": {}}
            return ok(True)
        col = self.cols.get(name)
        if col is None:
            return httpx.Response(404, json={"status": {"error": "not found"}})
        if parts[2] == "index":
            return ok({})
        if parts[2:] == ["points"] and m == "PUT":
            for pt in body["points"]:
                assert len(pt["vector"]) == col["size"]
                col["points"][pt["id"]] = pt
            return ok({"status": "completed"})
        if parts[2:] == ["points", "delete"]:
            for pid in body["points"]:
                col["points"].pop(pid, None)
            return ok({"status": "completed"})
        if parts[2:] == ["points", "count"]:
            pts = col["points"].values()
            if "filter" in body:
                kind = body["filter"]["must"][0]["match"]["value"]
                pts = [x for x in pts if x["payload"]["kind"] == kind]
            return ok({"count": len(list(pts))})
        if parts[2:] == ["points", "search"]:
            must = {c["key"]: c["match"]["value"] for c in body["filter"]["must"]}
            q = body["vector"]
            nq = math.sqrt(sum(x * x for x in q)) or 1
            res = []
            for pt in col["points"].values():
                if any(pt["payload"][k] != v for k, v in must.items()):
                    continue
                v = pt["vector"]
                nv = math.sqrt(sum(x * x for x in v)) or 1
                res.append({"id": pt["id"], "score": sum(a * b for a, b in zip(q, v)) / nq / nv, "payload": pt["payload"]})
            res.sort(key=lambda r: -r["score"])
            return ok(res[: body["limit"]])
        return httpx.Response(400, json={"status": {"error": f"bilinmeyen {m} {p}"}})


@pytest.fixture
def fq():
    return FakeQdrant()


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    return tmp_path


@pytest.fixture
def qrt(env, fq, monkeypatch):
    monkeypatch.setenv("KAYAAI_VECTOR_BACKEND", "qdrant")
    monkeypatch.setattr(memmod, "make_vector_store",
                        lambda s: QdrantStore(s.memory.qdrant_url, transport=httpx.MockTransport(fq)))
    r = build_runtime(load_settings())
    yield r
    r.close()


def test_settings_from_env(env, monkeypatch):
    monkeypatch.setenv("KAYAAI_VECTOR_BACKEND", "qdrant")
    monkeypatch.setenv("KAYAAI_QDRANT_URL", "http://qdrant:6333")
    s = load_settings()
    assert s.memory.vector_backend == "qdrant" and s.memory.qdrant_url == "http://qdrant:6333"


def test_memory_and_documents_use_qdrant(qrt, fq):
    item, _ = qrt.memory.book.add("Atlas projesinin teslim tarihi 15 Kasım", category="project")
    files = Path(qrt.settings.files.home_dir)
    files.mkdir(parents=True, exist_ok=True)
    (files / "notlar.md").write_text("# Atlas\n\nAtlas toplantısı: bütçe 2 milyon TL, teslim 15 Kasım.\n", encoding="utf-8")
    qrt.memory.docs.index()
    assert qrt.memory.db.query("SELECT COUNT(*) AS n FROM vectors")[0]["n"] == 0  # vektörler SQLite'ta değil
    col = fq.cols["kayaai_" + str(len(next(iter(next(iter(fq.cols.values()))["points"].values()))["vector"]))]
    kinds = sorted(p["payload"]["kind"] for p in col["points"].values())
    assert kinds == ["chunk", "memory"] and point_id("memory", item.id) in col["points"]
    rec = qrt.memory.recall("Atlas teslim tarihi ne zaman?")
    assert rec.memories and rec.memories[0]["id"] == item.id
    assert rec.documents and rec.documents[0]["name"] == "notlar.md"
    upserts = [c for c in fq.calls if c[0] == "PUT" and c[1].endswith("/points")]
    assert len(upserts) == 2  # her işlem tek toplu gönderim (öğe + belge)
    qrt.memory.book.delete(item.id)
    assert point_id("memory", item.id) not in col["points"]


def test_rollback_sends_nothing(env, fq):
    db = MemoryDB(env / "x.db", vectors=QdrantStore("http://127.0.0.1:6333", transport=httpx.MockTransport(fq)))
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            db.put_vector(c, "memory", "m1", "bge-m3", [1.0, 0.0, 0.0])
            raise RuntimeError("iptal")
    assert not any(c[1].endswith("/points") for c in fq.calls)
    with db.tx() as c:
        db.put_vector(c, "memory", "m1", "bge-m3", [1.0, 0.0, 0.0])
    assert db.nearest("memory", "bge-m3", [0.9, 0.1, 0.0], 3)[0][0] == "m1"
    assert db.nearest("memory", "baska-model", [0.9, 0.1, 0.0], 3) == []  # model süzgeci
    db.close()


def test_qdrant_down_keyword_search_still_works(qrt, fq):
    qrt.memory.book.add("Kahvemi şekersiz içerim", category="preference")
    fq.down = True
    assert qrt.memory.db.nearest("memory", "bge-m3", [0.1] * 1024, 5) == []
    assert "ulaşılamadı" in (qrt.memory.db.last_vector_error or "")
    rec = qrt.memory.recall("kahvemi nasıl içerim şekersiz")
    assert any("şekersiz" in m["text"] for m in rec.memories)  # FTS kelime araması
    with pytest.raises(QdrantError):
        qrt.memory.book.add("Yeni not ekleme Qdrant kapalıyken hata verir")


def test_migrate_from_sqlite(env, fq, monkeypatch, capsys):
    import kayaai.memory.qdrant as qmod
    from kayaai.cli import main

    rt = build_runtime(load_settings())  # önce SQLite'ta (masaüstü varsayılanı)
    rt.memory.book.add("Raporları PDF olarak isterim", category="preference")
    rt.memory.book.add("Atlas teslim tarihi 15 Kasım", category="project")
    model = rt.memory.book.embedder.model
    qv = rt.memory.book.embedder.embed(["Atlas teslim"])[0]
    want = rt.memory.db.nearest("memory", model, qv, 2)
    rt.close()

    real = qmod.QdrantStore
    monkeypatch.setattr(qmod, "QdrantStore", lambda url, api_key=None: real(url, api_key, transport=httpx.MockTransport(fq)))
    assert main(["memory", "migrate"]) == 0
    out = capsys.readouterr().out
    assert "{'memory': 2}" in out and "vector_backend: qdrant" in out
    store = real("http://127.0.0.1:6333", transport=httpx.MockTransport(fq))
    got = store.search("memory", model, qv, 2)
    assert [i for i, _ in got] == [i for i, _ in want]  # aynı sonuçlar, aynı sıra
    assert [round(x, 4) for _, x in got] == [round(x, 4) for _, x in want]


# ---------------------------------------------------------------- kayaai qdrant start|status|test (sahip denetimi)

def _fixed(settings, log):
    def v(i):
        return [math.sin(i * 7 + j) for j in range(64)]
    return [v(i) for i in range(5)], [x + 0.01 for x in v(0)], "check-vec"


class FakeDockerCLI:
    def __init__(self, state="yok", run_rc=0, run_err=""):
        self.state, self.run_rc, self.run_err = state, run_rc, run_err
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        if args[1] == "inspect":
            if self.state == "docker-yok":
                return 1, "", "error during connect: open //./pipe/dockerDesktopLinuxEngine"
            return (0, self.state + "\n", "") if self.state != "yok" else (1, "", "Error: No such object: kayaai-qdrant")
        if args[1] == "run":
            return self.run_rc, "abc123" if self.run_rc == 0 else "", self.run_err
        if args[1] == "logs":
            return 0, "panic: depolama kilitli", ""
        return 0, "", ""


@pytest.fixture
def qsettings(tmp_path, monkeypatch):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    return load_settings()


def test_check_passes_with_qdrant(qsettings):
    from kayaai.memory import qdrant_check as qc

    fq = FakeQdrant()
    rep = qc.run_check(qsettings, transport=httpx.MockTransport(fq), vectors=_fixed, log=lambda m: None)
    assert rep["ok"], rep
    assert all(rep["steps"][k] for k in ("top_is_atlas", "filter_other_kind_empty", "same_as_sqlite", "deleted"))
    assert rep["steps"]["top"][0][0] == "check-0" and rep["health"]["version"] == "1.12.0"
    assert not any(fq.cols[c]["points"] for c in fq.cols)  # deneme vektörleri silindi


@pytest.mark.parametrize("state,expect", [
    ("yok", "kayaai qdrant start"), ("docker-yok", "Docker Desktop açık mı"), ("exited", "çalışmıyor (exited)"),
    ("running", "cevap vermiyor"),
])
def test_check_explains_why_qdrant_is_unreachable(qsettings, state, expect):
    from kayaai.memory import qdrant_check as qc

    fq = FakeQdrant()
    fq.down = True
    rep = qc.run_check(qsettings, transport=httpx.MockTransport(fq), exec_fn=FakeDockerCLI(state), log=lambda m: None)
    assert not rep["ok"] and expect in rep["error"]
    if state == "running":
        assert "depolama kilitli" in rep["container_logs"]


def test_check_records_unexpected_errors(qsettings):
    from kayaai.memory import qdrant_check as qc

    def broken(settings, log):
        raise ValueError("vektör boyutu bozuk")
    rep = qc.run_check(qsettings, transport=httpx.MockTransport(FakeQdrant()), vectors=broken, log=lambda m: None)
    assert not rep["ok"] and "ValueError: vektör boyutu bozuk" in rep["error"] and "Traceback" in rep["traceback"]


def test_start_binds_only_localhost_and_reuses_container():
    from kayaai.memory import qdrant_check as qc

    t = httpx.MockTransport(FakeQdrant())
    logs: list[str] = []
    d = FakeDockerCLI("yok")
    assert qc.start("http://127.0.0.1:6333", exec_fn=d, log=logs.append, wait_s=0, transport=t)
    run = next(c for c in d.calls if c[1] == "run")
    assert run[run.index("-p") + 1] == "127.0.0.1:6333:6333" and "kayaai-qdrant:/qdrant/storage" in run
    assert run[-1] == qc.IMAGE and "--network" not in run and "[OK] Qdrant hazır" in logs[-1]
    d = FakeDockerCLI("exited")
    assert qc.start("http://localhost:6400", exec_fn=d, log=logs.append, wait_s=0, transport=t)
    assert ["docker", "start", "kayaai-qdrant"] in d.calls and not any(c[1] == "run" for c in d.calls)
    d = FakeDockerCLI("running")
    assert qc.start("http://127.0.0.1:6333", exec_fn=d, log=logs.append, wait_s=0, transport=t)
    assert [c[1] for c in d.calls] == ["inspect"]


def test_start_refuses_or_explains():
    from kayaai.memory import qdrant_check as qc

    logs: list[str] = []
    d = FakeDockerCLI("yok")
    assert not qc.start("http://qdrant:6333", exec_fn=d, log=logs.append, wait_s=0)
    assert "bu bilgisayar değil" in logs[-1] and d.calls == []
    assert not qc.start("http://127.0.0.1:6333", exec_fn=FakeDockerCLI("docker-yok"), log=logs.append, wait_s=0)
    assert "Docker Desktop açık mı" in logs[-1]
    busy = FakeDockerCLI("yok", run_rc=125, run_err="Bind for 127.0.0.1:6333 failed: port is already allocated")
    assert not qc.start("http://127.0.0.1:6333", exec_fn=busy, log=logs.append, wait_s=0)
    assert "portunu başka bir program" in logs[-1]


def test_cli_qdrant_test_writes_report(qsettings, monkeypatch, capsys):
    from kayaai import cli
    from kayaai.memory import qdrant_check as qc

    fq = FakeQdrant()
    real = qc.QdrantStore
    monkeypatch.setattr(qc, "QdrantStore", lambda url, **kw: real(url, transport=httpx.MockTransport(fq)))
    monkeypatch.setattr(qc, "_vectors", _fixed)
    assert cli.main(["qdrant", "test"]) == 0
    out = capsys.readouterr().out
    assert "✓ same_as_sqlite: True" in out and "[OK] Qdrant denetimi geçti" in out
    rep = json.loads((qsettings.data_dir / "qdrant_check.json").read_text(encoding="utf-8"))
    assert rep["ok"] and rep["model"] == "check-vec"
    fq.down = True
    monkeypatch.setattr(qc.runner, "execute", FakeDockerCLI("yok"))
    assert cli.main(["qdrant", "test"]) == 1
    assert "kayaai qdrant start" in capsys.readouterr().out
    assert "kayaai qdrant start" in json.loads((qsettings.data_dir / "qdrant_check.json").read_text(encoding="utf-8"))["error"]
