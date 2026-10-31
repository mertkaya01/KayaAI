"""Adım 5: izin motoru v2 (R0–R3, kalıcı onay kuyruğu) + izinli klasörlerle sınırlı dosya araçları."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from kayaai.api import create_app
from kayaai.config import AllowedDir, load_settings
from kayaai.core.permissions import ApprovalError, PermissionEngine, Risk, ToolAction
from kayaai.core.task import utcnow
from kayaai.mcp_server import create_server
from kayaai.runtime import build_runtime
from kayaai.tools.files import PathNotAllowed


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    home = tmp_path / "kayaAI-files"
    ro = tmp_path / "Faturalar"
    rw = tmp_path / "Projeler"
    for d in (ro, rw):
        d.mkdir()
    (ro / "fatura.txt").write_text("Fatura no: 42", encoding="utf-8")
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(home))
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", "http://127.0.0.1:9")
    settings = load_settings()
    settings.files.allowed_dirs = [AllowedDir(path=str(ro), access="read"), AllowedDir(path=str(rw), access="read_write")]
    rt = build_runtime(settings)
    yield rt, home, ro, rw, tmp_path
    rt.close()


def events(rt) -> list[str]:
    return [e["type"] for e in rt.store.events_since(0)]


# ---------------------------------------------------------------- yol güvenliği

@pytest.mark.parametrize("bad", ["../gizli.txt", "../../etc/passwd", "/etc/passwd", "alt/../../../dışarı.txt"])
def test_paths_outside_roots_rejected(env, bad):
    rt, *_ = env
    with pytest.raises(PathNotAllowed):
        rt.files.read(bad)
    with pytest.raises(PathNotAllowed):
        rt.files.write(bad, "x")
    assert rt.permissions.list_approvals() == []  # reddedilen yol için onay talebi bile oluşmaz


@pytest.mark.skipif(os.name == "nt", reason="sembolik bağlantı oluşturmak Windows'ta yetki ister")
def test_symlink_escape_rejected(env):
    rt, home, *_rest, tmp = env
    secret = tmp / "gizli"
    secret.mkdir()
    (secret / "sifre.txt").write_text("123", encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    (home / "kisayol").symlink_to(secret, target_is_directory=True)
    with pytest.raises(PathNotAllowed):
        rt.files.read("kisayol/sifre.txt")


def test_read_only_dir_can_be_read_not_written(env):
    rt, home, ro, rw, _ = env
    assert rt.files.read(str(ro / "fatura.txt")).result["content"] == "Fatura no: 42"
    with pytest.raises(PathNotAllowed, match="yalnızca okunabilir"):
        rt.files.write(str(ro / "yeni.txt"), "x")
    with pytest.raises(PathNotAllowed, match="yalnızca okunabilir"):
        rt.files.write(str(ro / "fatura.txt"), "değişti")  # onay istemeden reddedilir
    assert (ro / "fatura.txt").read_text(encoding="utf-8") == "Fatura no: 42"
    assert rt.permissions.list_approvals() == []


def test_read_write_extra_dir(env):
    rt, home, ro, rw, _ = env
    res = rt.files.write(str(rw / "not.md"), "merhaba")
    assert res.status == "done" and res.risk == Risk.R1


def test_unsupported_type_and_size_limits(env):
    rt, home, *_ = env
    home.mkdir(parents=True, exist_ok=True)
    (home / "belge.pdf").write_bytes(b"%PDF-1.7")
    res = rt.files.read("belge.pdf")
    assert res.status == "failed" and "Adım 9" in res.error
    rt.settings.files.max_write_mb = 0.0001
    with pytest.raises(ValueError, match="çok büyük"):
        rt.files.write("buyuk.txt", "x" * 1000)


# ---------------------------------------------------------------- risk + onay akışı

def test_new_file_is_r1_and_logged(env):
    rt, home, *_ = env
    res = rt.files.write("notlar/ilk.md", "merhaba")
    assert res.status == "done" and res.risk == Risk.R1
    assert (home / "notlar/ilk.md").read_text(encoding="utf-8") == "merhaba"
    assert "tool.used" in events(rt) and rt.permissions.list_approvals() == []
    listing = rt.files.list_dir("notlar")
    assert listing.risk == Risk.R0 and listing.result["entries"][0]["name"] == "ilk.md"


def test_overwrite_waits_for_owner_then_backs_up(env):
    rt, home, *_rest, tmp = env
    rt.files.write("rapor.md", "ESKİ")
    res = rt.files.write("rapor.md", "YENİ", requested_by="agent:coder")
    assert res.status == "awaiting_approval" and res.risk == Risk.R2
    assert (home / "rapor.md").read_text(encoding="utf-8") == "ESKİ"  # onaysız değişmez
    a = rt.permissions.get(res.approval_id)
    assert a.status == "pending" and a.action.requested_by == "agent:coder"
    assert a.action.preview["old_head"] == "ESKİ" and a.action.preview["new_head"] == "YENİ"
    assert "approval.requested" in events(rt)
    done = rt.permissions.approve(res.approval_id, decided_by="cli")
    assert done.status == "approved" and done.result["overwritten"]
    assert (home / "rapor.md").read_text(encoding="utf-8") == "YENİ"
    assert Path(done.result["backup"]).read_text(encoding="utf-8") == "ESKİ"
    assert "approval.decided" in events(rt)
    with pytest.raises(ApprovalError, match="beklemede değil"):
        rt.permissions.approve(res.approval_id, decided_by="cli")
    with pytest.raises(ApprovalError):
        rt.permissions.reject(res.approval_id, decided_by="cli")


def test_reject_leaves_file_untouched(env):
    rt, home, *_ = env
    rt.files.write("a.txt", "1")
    res = rt.files.write("a.txt", "2")
    a = rt.permissions.reject(res.approval_id, decided_by="api", note="istemiyorum")
    assert a.status == "rejected" and a.decision_note == "istemiyorum"
    assert (home / "a.txt").read_text(encoding="utf-8") == "1"


def test_pending_approval_survives_restart(env):
    rt, home, *_ = env
    rt.files.write("b.txt", "eski")
    approval_id = rt.files.write("b.txt", "yeni").approval_id
    settings = rt.settings
    rt.close()
    rt2 = build_runtime(settings)
    try:
        assert [a.id for a in rt2.permissions.list_approvals("pending")] == [approval_id]
        rt2.permissions.approve(approval_id, decided_by="cli")
        assert (home / "b.txt").read_text(encoding="utf-8") == "yeni"
    finally:
        rt2.close()


def test_expired_approval_cannot_be_approved(env):
    rt, *_ = env
    rt.files.write("c.txt", "1")
    approval_id = rt.files.write("c.txt", "2").approval_id
    rt.permissions.expire_after = timedelta(seconds=-1)
    a = rt.permissions.get(approval_id)
    assert a.status == "expired" and a.decided_by == "system"
    with pytest.raises(ApprovalError, match="expired"):
        rt.permissions.approve(approval_id, decided_by="cli")


def test_r3_actions_need_approval_each_time(tmp_path):
    from kayaai.core.store import TaskStore

    store = TaskStore(tmp_path / "k.db")
    sent: list[str] = []
    eng = PermissionEngine(store, {"message.send": lambda p: sent.append(p["to"]) or {"sent": True}})
    ids = [eng.submit(ToolAction(tool="message.send", params={"to": f"kisi{i}"}, risk=Risk.R3,
                                 summary=f"kisi{i}'e mesaj gönder")).approval_id for i in range(2)]
    assert sent == []
    eng.approve(ids[0], decided_by="cli")
    assert sent == ["kisi0"] and eng.get(ids[1]).status == "pending"  # biri onaylanınca diğeri onaylanmaz
    with pytest.raises(ApprovalError):
        eng.submit(ToolAction(tool="yok", params={}, risk=Risk.R0, summary="x"))
    store.close()


def test_failed_execution_after_approval_is_recorded(tmp_path):
    from kayaai.core.store import TaskStore

    store = TaskStore(tmp_path / "k.db")

    def boom(_: dict) -> dict:
        raise OSError("disk dolu")

    eng = PermissionEngine(store, {"file.write": boom})
    aid = eng.submit(ToolAction(tool="file.write", params={}, risk=Risk.R2, summary="yaz")).approval_id
    a = eng.approve(aid, decided_by="cli")
    assert a.status == "failed" and "disk dolu" in a.error
    store.close()


# ---------------------------------------------------------------- API ve MCP

def test_api_files_and_approvals(env):
    rt, home, ro, *_ = env
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        assert c.get("/api/files/roots").json()[1]["access"] == "read"
        assert c.post("/api/files/write", json={"path": "x.md", "content": "1"}).json()["status"] == "done"
        r = c.post("/api/files/write", json={"path": "x.md", "content": "2"}).json()
        assert r["status"] == "awaiting_approval"
        pending = c.get("/api/approvals").json()
        assert [p["id"] for p in pending] == [r["approval_id"]]
        assert c.post(f"/api/approvals/{r['approval_id']}/approve", json={"note": "tamam"}).json()["status"] == "approved"
        assert c.get("/api/files/read", params={"path": "x.md"}).json()["result"]["content"] == "2"
        assert c.post(f"/api/approvals/{r['approval_id']}/approve").status_code == 409
        assert c.get("/api/files/read", params={"path": "/etc/passwd"}).status_code == 403
        assert c.post("/api/files/write", json={"path": str(ro / "y.txt"), "content": "z"}).status_code == 403
        assert c.get("/api/approvals", headers={"Authorization": ""}).status_code == 401
        assert len(c.get("/api/approvals", params={"status": "all"}).json()) == 1


def test_mcp_has_no_approve_tool_and_write_waits(env):
    rt, home, *_ = env

    async def go():
        async with Client(create_server(rt.settings, runtime=rt)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            first = await c.call_tool("kayaai_files_write", {"path": "m.md", "content": "1"})
            second = await c.call_tool("kayaai_files_write", {"path": "m.md", "content": "2"})
            pending = await c.call_tool("kayaai_approvals_pending", {})
            outside = await c.call_tool("kayaai_files_read", {"path": "../../etc/passwd"})
            return names, first, second, pending, outside

    names, first, second, pending, outside = asyncio.run(go())
    assert not any("approve" in n or "reject" in n for n in names)  # ajan kendi isteğini onaylayamaz
    assert first.structured_content["status"] == "done"
    assert second.structured_content["status"] == "awaiting_approval"
    assert pending.structured_content["pending"][0]["requested_by"] == "mcp"
    assert outside.is_error
    assert (home / "m.md").read_text(encoding="utf-8") == "1"
