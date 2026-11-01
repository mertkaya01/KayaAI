"""Adım 17: bulut köprüsü — kapalı varsayılan, R2 ile açılır, yalnız yerel ağ geçidi, istek başına izin, veri kapısı
(hafıza/belge/görüntü gitmez, gizli bilgi engeller), sınır, kayıt (metinsiz), hata → yerel."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from kayaai.config import load_settings
from kayaai.llm import cloud as cl
from kayaai.runtime import build_runtime

from .conftest import good_answer


class Gateway:
    def __init__(self):
        self.calls: list[dict] = []
        self.replies: list = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1" and request.headers["authorization"] == "Bearer gizli-anahtar"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "auto"}, {"id": "groq/llama-3.3-70b"}]})
        body = json.loads(request.content)
        self.calls.append(body)
        r = self.replies.pop(0) if self.replies else good_answer("Buluttan selam")
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(200, json={"model": "groq/llama-3.3-70b", "choices": [{"message": {"content": r}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 50, "completion_tokens": 20}})


@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("KAYAAI_CLOUD_KEY", "gizli-anahtar")
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def gw():
    return Gateway()


@pytest.fixture
def rt(env, gw):
    r = build_runtime(env)
    r.orchestrator.cloud = cl.CloudBridge(r, transport=httpx.MockTransport(gw))
    yield r
    r.close()


def enable(rt, **kw):
    res = cl.request_enable(rt, cl.CloudSettings(**kw))
    assert res.status == "awaiting_approval" and res.risk.value == "R2"
    assert rt.permissions.approve(res.approval_id, decided_by="owner").status == "approved"


def ask(rt, text, agent="general", cloud=True):
    from kayaai.assistant.chat import ChatBook

    book = ChatBook(rt)
    conv = book.create()
    user, reply, run = book.send(conv.id, text, agent=agent, cloud=cloud)
    run()
    msg = book.view(conv.id).messages[-1]
    return msg, rt.store.get(reply.job_id)


def test_only_local_gateway():
    with pytest.raises(ValueError, match="yalnız bu bilgisayardaki"):
        cl.CloudSettings(base_url="https://api.openrouter.ai/v1")
    assert cl.CloudSettings(base_url="http://localhost:20128/v1/").base_url == "http://localhost:20128/v1"


def test_off_by_default_nothing_leaves(rt, gw, fake_ollama):
    fake_ollama.chat_replies = [good_answer("Yerelden")]
    msg, task = ask(rt, "Merhaba")
    assert gw.calls == [] and msg.content == "Yerelden"
    assert task.metrics["cloud"] == "yerel (bulut köprüsü kapalı)"


def test_enable_needs_approval_and_refuses_vision(rt):
    with pytest.raises(cl.CloudError, match="Görsel"):
        cl.request_enable(rt, cl.CloudSettings(agents=["general", "vision"]))
    with pytest.raises(cl.CloudError, match="Bilinmeyen"):
        cl.request_enable(rt, cl.CloudSettings(agents=["yok"]))
    res = cl.request_enable(rt, cl.CloudSettings(model="auto/fast"))
    preview = rt.permissions.get(res.approval_id).action.preview["new_head"]
    assert "Asla gitmez: hafıza" in preview and "127.0.0.1:20128" in preview
    assert not cl.get_settings(rt).enabled
    rt.permissions.approve(res.approval_id, decided_by="owner")
    assert cl.get_settings(rt).enabled and cl.get_settings(rt).model == "auto/fast"
    assert cl.request_disable(rt).status == "done" and not cl.get_settings(rt).enabled


def test_cloud_answer_without_memory_and_logged_without_text(rt, gw, fake_ollama):
    enable(rt)
    rt.memory.book.add("Müşteri Atlas'ın bütçesi 2 milyon TL", category="project")
    before = len(fake_ollama.chat_paths())
    msg, task = ask(rt, "Atlas projesinin bütçesi ne kadar, kısa bir e-posta taslağı yaz")
    assert msg.content == "Buluttan selam" and len(fake_ollama.chat_paths()) == before  # yerel model çağrılmadı
    sent = json.dumps(gw.calls[0], ensure_ascii=False)
    assert "2 milyon" not in sent and "memory" not in sent and "_cloud" not in sent
    assert gw.calls[0]["response_format"] == {"type": "json_object"} and gw.calls[0]["model"] == "auto"
    assert task.model == "☁ groq/llama-3.3-70b" and task.metrics["cloud"] == "bulut"
    assert any("hafıza ve belge araması kullanılmadı" in w for w in msg.warnings)
    ev = [e["data"] for e in rt.store.events_since(0, 500) if e["type"] == "cloud.call"]
    assert ev[0]["ok"] and ev[0]["chars_out"] > 0 and "content" not in ev[0] and "Atlas" not in json.dumps(ev)
    assert cl.usage_today(rt) == 1


def test_without_request_permission_stays_local_even_if_enabled(rt, gw, fake_ollama):
    enable(rt)
    rt.memory.book.add("Kahvemi şekersiz içerim", category="preference")
    fake_ollama.chat_replies = [good_answer("Yerel cevap")]
    msg, task = ask(rt, "Kahvemi nasıl içerim?", cloud=False)
    assert gw.calls == [] and "cloud" not in task.metrics
    assert "şekersiz" in json.dumps(fake_ollama.chat_paths()[-1], ensure_ascii=False)  # yerelde hafıza kullanılır


def test_secret_blocks_and_falls_back_local(rt, gw, fake_ollama):
    enable(rt)
    fake_ollama.chat_replies = [good_answer("Yerelde yapıldı")]
    token = "hf_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z"
    msg, task = ask(rt, f"Bu anahtarla model indirme komutu yaz: {token}")
    assert gw.calls == [] and msg.content == "Yerelde yapıldı"
    assert task.metrics["cloud"].startswith("yerel'e düşüldü (gizli bilgi")
    assert [e["type"] for e in rt.store.events_since(0, 500) if e["type"].startswith("cloud.")][-1] == "cloud.blocked"


def test_gateway_error_falls_back_local(rt, gw, fake_ollama):
    enable(rt)
    gw.replies = [httpx.Response(503, text="kota doldu")]
    fake_ollama.chat_replies = [good_answer("Yerel yedek")]
    msg, task = ask(rt, "Merhaba")
    assert msg.content == "Yerel yedek" and "HTTP 503" in task.metrics["cloud"]
    assert [e["data"]["ok"] for e in rt.store.events_since(0, 500) if e["type"] == "cloud.call"] == [False]


def test_invalid_json_retried_in_cloud(rt, gw):
    enable(rt)
    gw.replies = ["bu json değil", good_answer("İkinci denemede")]
    msg, task = ask(rt, "Merhaba")
    assert msg.content == "İkinci denemede" and len(gw.calls) == 2 and task.metrics["output_attempts"] == 2
    assert gw.calls[1]["messages"][-1]["content"].startswith("Your output did not match")


def test_agent_not_allowed_and_daily_limit(rt, gw, fake_ollama):
    enable(rt, agents=["general"], daily_limit=1)
    fake_ollama.chat_replies = [good_answer("Yerel kod")] * 3
    _, t1 = ask(rt, "Python ile dosya listele", agent="coder")
    assert t1.metrics["cloud"] == "yerel (coder ajanı buluta izinli değil)" and gw.calls == []
    ask(rt, "Merhaba")
    _, t3 = ask(rt, "Tekrar merhaba")
    assert len(gw.calls) == 1 and t3.metrics["cloud"] == "yerel (günlük bulut sınırı doldu (1))"


def test_no_key_stays_local(rt, gw, fake_ollama, monkeypatch):
    enable(rt)
    monkeypatch.delenv("KAYAAI_CLOUD_KEY")
    fake_ollama.chat_replies = [good_answer("Yerel")]
    _, t = ask(rt, "Merhaba")
    assert gw.calls == [] and "anahtarı yok" in t.metrics["cloud"]


def test_cloud_input_strips_private_keys():
    data = {"conversation": "x", "memory": [1], "documents": [2], "_images": ["a.png"],
            "context": {"memory": [3], "documents": [4], "exchange_rates": {"USD": 41}}, "steps": [{"recall": 1, "a": 2}]}
    assert cl.cloud_input(data) == {"conversation": "x", "context": {"exchange_rates": {"USD": 41}}, "steps": [{"a": 2}]}


def test_conductor_passes_permission_to_every_step(rt, gw):
    from kayaai.conductor import Conductor

    from .conductor_helpers import plan_steps

    enable(rt)
    gw.replies = [plan_steps([("s1", "general", "Kısa bir selam yaz", [])]), good_answer("Selam!"),
                  json.dumps({"verdict": "approve", "missing_parts": [], "issues": []})] + [good_answer("ek")] * 5
    res = Conductor(rt).run("Bana kısa bir selam yaz", force="local", context={"_cloud": True})
    assert res.status == "succeeded"
    kids = rt.store.list_children(res.job_id)
    assert kids and all(k.input.get("_cloud") for k in kids)
    assert any((k.model or "").startswith("☁") for k in kids)


def test_schedule_cloud_only_for_free_tasks():
    from kayaai.schedule import Cadence, Schedule

    with pytest.raises(ValueError, match="yalnız serbest"):
        Schedule(name="x", kind="reindex", cadence=Cadence(), cloud=True)
    s = Schedule(name="Haber özeti", kind="free", params={"request": "Bugünün genel teknoloji haberlerini özetle"},
                 cadence=Cadence(), cloud=True)
    assert "buluta izinli" in s.summary()


def test_api(env, tmp_path, monkeypatch):
    from kayaai.api import create_app

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        st = c.get("/api/cloud", headers=h).json()
        assert st["enabled"] is False and st["has_key"] is True and "gizli-anahtar" not in json.dumps(st)
        assert c.post("/api/cloud/enable", headers=h, json={"base_url": "https://evil.example/v1"}).status_code == 422
        r = c.post("/api/cloud/enable", headers=h, json={"model": "auto/fast"}).json()
        assert r["status"] == "awaiting_approval"
        assert c.post(f"/api/approvals/{r['approval_id']}/approve", headers=h).json()["status"] == "approved"
        assert c.get("/api/cloud", headers=h).json()["enabled"] is True
        monkeypatch.setattr(cl.CloudBridge, "models", lambda self: ["auto"])
        assert c.post("/api/cloud/test", headers=h).json() == {"ok": True, "models": ["auto"]}
        assert c.post("/api/cloud/disable", headers=h).json()["status"] == "done"
