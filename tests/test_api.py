"""Adım 4: yerel API (FastAPI) + süreçler arası olay akışı."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.api import create_app
from kayaai.config import PROJECT_ROOT, load_settings
from kayaai.core.store import TaskStore
from kayaai.core.task import Task, TaskStatus
from kayaai.runtime import build_runtime

from .conductor_helpers import Script, answer, plan_direct


@pytest.fixture
def api(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 1})
    settings = load_settings()
    settings.ollama.max_retries = 0
    rt = build_runtime(settings)
    app = create_app(settings, runtime=rt)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.token}"
        yield client, rt, app
    rt.close()


def wait_terminal(client, task_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = client.get(f"/api/tasks/{task_id}").json()["task"]
        if t["status"] not in ("pending", "running", "awaiting_approval"):
            return t
        time.sleep(0.05)
    raise AssertionError(f"görev bitmedi: {task_id}")


def test_auth_required(api):
    client, _, app = api
    for path in ("/api/health", "/api/agents", "/api/tasks", "/api/system", "/api/claude", "/api/inbox"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer yanlis"}).status_code == 401
    assert client.post("/api/ask", json={"question": "x"}, headers={"Authorization": ""}).status_code == 401


def test_token_persisted_and_strong(tmp_path, monkeypatch):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    from kayaai.api.app import load_or_create_token
    s = load_settings()
    t1, t2 = load_or_create_token(s), load_or_create_token(s)
    assert t1 == t2 and len(t1) >= 32 and (tmp_path / "api_token").exists()


def test_health_agents_models_system(api):
    client, _, _ = api
    h = client.get("/api/health").json()
    assert h["ollama"]["reachable"] and "general" in h["workers"] and h["claude"]["state"] == "off"
    agents = {a["name"]: a for a in client.get("/api/agents").json()}
    assert agents["coder"]["local_model"] == "qwen2.5-coder:7b" and agents["general"]["status"]["state"] == "idle"
    models = client.get("/api/models").json()
    assert models["ollama_reachable"] and any(m["key"] == "coder-7b" and m["agents"] == ["coder"] for m in models["models"])
    sysm = client.get("/api/system").json()
    assert {"cpu_pct", "ram_used_pct", "gpus", "active_tasks"} <= set(sysm)


def test_ask_runs_in_background(api, fake_ollama):
    client, _, _ = api
    fake_ollama.chat_replies = [answer("API üzerinden cevap.")]
    r = client.post("/api/ask", json={"question": "Merhaba"})
    assert r.status_code == 202
    t = wait_terminal(client, r.json()["id"])
    assert t["status"] == "succeeded" and t["result"]["answer"] == "API üzerinden cevap."
    agents = {a["name"]: a["status"] for a in client.get("/api/agents").json()}
    assert agents["general"]["state"] == "completed" and agents["general"]["result_available"]


def test_ask_validation(api):
    client, _, _ = api
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 20_001}).status_code == 422
    assert client.post("/api/ask", json={"question": "x", "worker": "shell"}).status_code == 400


def test_do_job_with_children(api, fake_ollama):
    client, _, _ = api
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general")], answers=[answer("Şef cevabı.")])] * 10
    r = client.post("/api/do", json={"request": "Bir şey yap"})
    assert r.status_code == 202
    job = wait_terminal(client, r.json()["id"])
    assert job["status"] == "succeeded" and job["result"]["answer"] == "Şef cevabı."
    detail = client.get(f"/api/tasks/{job['id']}").json()
    assert {c["worker"] for c in detail["children"]} == {"planner", "general"}
    assert client.get("/api/tasks", params={"parent_id": job["id"]}).json()["tasks"]


def test_claude_toggle_inbox_and_handback(api, fake_ollama):
    client, _, _ = api
    assert client.post("/api/claude", json={"enabled": True}).json()["status"]["enabled"]
    hard = plan_direct("general", needs_claude=True, reason="zor")
    fake_ollama.chat_replies = [Script(planner=[hard], answers=[])] * 5
    job_id = client.post("/api/do", json={"request": "Zor iş"}).json()["id"]
    assert wait_terminal(client, job_id)["status"] == "waiting_claude"
    assert [i["job_id"] for i in client.get("/api/inbox").json()["items"]] == [job_id]
    fake_ollama.chat_replies = [Script(planner=[hard], answers=[answer("Yerelde yapıldı.")])] * 5
    off = client.post("/api/claude", json={"enabled": False}).json()
    assert off["handed_back_to_local"] == [job_id]
    assert wait_terminal(client, job_id)["status"] == "succeeded"
    assert client.get("/api/inbox").json()["items"] == []


def test_inbox_run_and_cancel_and_task_cancel(api, fake_ollama):
    client, rt, _ = api
    rt.claude.enable()
    hard = plan_direct("general", needs_claude=True, reason="zor")
    fake_ollama.chat_replies = [Script(planner=[hard], answers=[])] * 10
    a = client.post("/api/do", json={"request": "A"}).json()["id"]
    b = client.post("/api/do", json={"request": "B"}).json()["id"]
    wait_terminal(client, a), wait_terminal(client, b)
    fake_ollama.chat_replies = [Script(planner=[hard], answers=[answer("A yerelde.")])] * 5
    assert client.post(f"/api/inbox/{a}/run").status_code == 202
    assert wait_terminal(client, a)["status"] == "succeeded"
    assert client.post(f"/api/inbox/{a}/run").status_code == 409
    assert client.post(f"/api/tasks/{b}/cancel").json()["cancelled"]
    assert client.get(f"/api/tasks/{b}").json()["task"]["status"] == "cancelled"
    assert client.get("/api/tasks/yok").status_code == 404


def test_events_websocket_sees_other_process_writes(api):
    """Başka süreç (CLI / MCP sunucusu) aynı veritabanına yazar; API olay akışı bunu görmeli."""
    client, rt, app = api
    other = TaskStore(rt.settings.db_path)  # ayrı bağlantı = ayrı süreç benzetimi
    with client.websocket_connect(f"/api/events?token={app.state.token}") as ws:
        t = Task(worker="general", objective="başka süreçten")
        other.save(t)
        ev = ws.receive_json()
        assert ev["type"] == "task.status" and ev["task_id"] == t.id and ev["data"]["status"] == "pending"
        t.status = TaskStatus.RUNNING
        other.save(t)
        assert ws.receive_json()["data"]["status"] == "running"
        other.emit("claude.mode", {"enabled": True})
        assert ws.receive_json()["type"] == "claude.mode"
    other.close()


def test_events_websocket_rejects_bad_token(api):
    client, _, _ = api
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/events?token=yanlis") as ws:
            ws.receive_json()


def test_events_backlog_with_after(api, fake_ollama):
    client, rt, app = api
    rt.store.emit("test.one", {"n": 1})
    rt.store.emit("test.two", {"n": 2})
    with client.websocket_connect(f"/api/events?token={app.state.token}&after=0") as ws:
        types = [ws.receive_json()["type"], ws.receive_json()["type"]]
    assert types == ["test.one", "test.two"]


def test_events_recent_backlog(api):
    """Arayüz ilk bağlantıda son N olayı ister (backlog); fazlası gelmez, sonra canlı devam eder."""
    client, rt, app = api
    for i in range(5):
        rt.store.emit("test.n", {"n": i})
    with client.websocket_connect(f"/api/events?token={app.state.token}&backlog=2") as ws:
        got = [ws.receive_json()["data"]["n"], ws.receive_json()["data"]["n"]]
        rt.store.emit("test.live", {})
        assert ws.receive_json()["type"] == "test.live"
    assert got == [3, 4]


def test_cli_refuses_non_local_host(tmp_path):
    env = dict(os.environ, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-m", "kayaai", "api", "--host", "0.0.0.0"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 2 and "reddedildi" in r.stdout
    tok = subprocess.run([sys.executable, "-m", "kayaai", "api", "token"], env=env, cwd=str(PROJECT_ROOT),
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert tok.returncode == 0 and len(tok.stdout.splitlines()[0]) >= 32


def test_real_server_shuts_down_after_websocket_client_leaves(tmp_path):
    """Regresyon: kopan WebSocket bağlantısı açık kalıyor, `kayaai api` kapatma sinyalinde kapanmıyordu."""
    import socket

    from websockets.sync.client import connect

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, KAYAAI_DATA_DIR=str(tmp_path), KAYAAI_OLLAMA_URL="http://127.0.0.1:9", PYTHONUTF8="1")
    proc = subprocess.Popen([sys.executable, "-m", "kayaai", "api", "--port", str(port)], env=env, cwd=str(PROJECT_ROOT),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        token_file = tmp_path / "api_token"
        deadline = time.monotonic() + 20
        connected = False
        while time.monotonic() < deadline and not connected:
            try:
                url = f"ws://127.0.0.1:{port}/api/events?token={token_file.read_text().strip()}"
                with connect(url, open_timeout=2):
                    connected = True  # bağlan ve hemen ayrıl
            except (OSError, FileNotFoundError):
                time.sleep(0.2)
        assert connected, "sunucu başlamadı"
        time.sleep(0.5)
        proc.terminate()
        proc.wait(timeout=5)  # önceden burada takılıyordu
    finally:
        if proc.poll() is None:
            proc.kill()
