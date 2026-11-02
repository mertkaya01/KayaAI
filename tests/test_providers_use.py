"""Adım 20b: dış sağlayıcı kullanımı — mesaj başına ☁, ajan ataması (onaylı), veri kapısı, gizli bilgi, yerel yedek."""

from __future__ import annotations

import json

import pytest

from kayaai.assistant.chat import ChatBook
from kayaai.conductor import Conductor
from kayaai.llm import providers as prov

from .conductor_helpers import Script, answer, plan_steps
from .conftest import good_answer
from .test_providers import KEY, FakeAPI, approve_last, fake, rt  # noqa: F401  (fixture)


def ready(rt, fake, pid="groq"):
    prov.add_provider(rt, "groq")
    prov.save_key(rt, pid, KEY)
    prov.test_connection(rt, pid)
    prov.request_enable(rt, pid)
    approve_last(rt)
    fake.calls.clear()


def chats(fake):
    return [b for m, p, b in fake.calls if p.endswith("/chat/completions")]


def test_message_cloud_goes_out_without_private_data(rt, fake, fake_ollama):
    ready(rt, fake)
    rt.memory.add("Kahvemi şekersiz içerim.", category="preference", sensitivity="personal", source="test", approved=True) \
        if hasattr(rt.memory, "add") else None
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [good_answer("yerel")] * 5
    _, reply, run = book.send(conv.id, "Bilgisayarım için kısa bir öneri ver", agent="general",
                              cloud={"provider": "groq", "model": "qwen/qwen3-32b"})
    run()
    [body] = chats(fake)
    sent = json.dumps(body, ensure_ascii=False)
    assert body["model"] == "qwen/qwen3-32b" and body["response_format"] == {"type": "json_object"}
    assert "this_computer" not in sent and "_cloud" not in sent and '"memory"' not in sent
    msg = book.view(conv.id).messages[-1]
    assert msg.status == "done" and msg.content == "Buluttan cevap."
    assert msg.meta["model"] == "☁ Groq/qwen/qwen3-32b" and msg.meta["cloud_requested"] == "groq/qwen/qwen3-32b"
    assert not [r for r in fake_ollama.requests if r[1] == "/api/chat"]  # yerel model hiç çağrılmadı
    ev = [e for e in rt.store.events_since(0, 500) if e["type"] == "provider.call"]
    assert ev[-1]["data"]["ok"] and ev[-1]["data"]["agent"] == "general" and "Bilgisayar" not in json.dumps(ev[-1]["data"])
    assert prov.used_today(rt, "groq") == 1


def test_secret_in_message_never_leaves_and_local_answers(rt, fake, fake_ollama):
    ready(rt, fake)
    book = ChatBook(rt)
    conv = book.create()
    fake_ollama.chat_replies = [good_answer("Yerel cevap.")] * 3
    _, reply, run = book.send(conv.id, "Şu şifreyi kontrol et: password=Hunter2!xyz ve kart 4111 1111 1111 1111",
                              agent="general", cloud={"provider": "groq"})
    run()
    assert chats(fake) == []
    msg = book.view(conv.id).messages[-1]
    assert msg.content == "Yerel cevap." and any("yerel model cevapladı" in w for w in msg.warnings)
    assert [e["type"] for e in rt.store.events_since(0, 500)].count("provider.blocked") == 1


@pytest.mark.parametrize("status,needle", [(429, "kota"), (401, "anahtar")])
def test_provider_errors_fall_back_to_local(rt, fake, fake_ollama, status, needle):
    ready(rt, fake)
    if status == 401:
        prov.save_key(rt, "groq", "bozuk-anahtar")
    else:
        fake.status = 429
    fake_ollama.chat_replies = [good_answer("Yerel yedek.")] * 3
    t = rt.orchestrator.ask("Merhaba", worker="general", input={"_cloud": {"provider": "groq", "model": "x"}})
    assert t.status.value == "succeeded" and t.result["answer"] == "Yerel yedek."
    assert t.metrics["cloud"].startswith("yerel modele düşüldü") and needle in t.metrics["cloud"]


def test_json_mode_unsupported_retries_without_it(rt, fake):
    ready(rt, fake)
    fake.json_mode_ok = False
    t = rt.orchestrator.ask("Merhaba", worker="general", input={"_cloud": {"provider": "groq", "model": "m"}})
    assert t.status.value == "succeeded" and t.model.startswith("☁")
    a, b = chats(fake)
    assert "response_format" in a and "response_format" not in b


def test_disabled_limit_and_vision_stay_local(rt, fake, fake_ollama):
    ready(rt, fake)
    fake_ollama.chat_replies = [good_answer("yerel")] * 10
    prov.update_provider(rt, "groq", daily_limit=1)
    t1 = rt.orchestrator.ask("bir", worker="general", input={"_cloud": {"provider": "groq"}})
    t2 = rt.orchestrator.ask("iki", worker="general", input={"_cloud": {"provider": "groq"}})
    assert t1.model.startswith("☁") and t2.model == "qwen3:8b" and "günlük sınırı" in t2.metrics["cloud"]
    prov.request_disable(rt, "groq")
    t3 = rt.orchestrator.ask("üç", worker="general", input={"_cloud": {"provider": "groq"}})
    assert "kapalı" in t3.metrics["cloud"] and len(chats(fake)) == 1


def test_conductor_passes_cloud_to_every_step(rt, fake, fake_ollama):
    ready(rt, fake)
    fake.reply = None
    plan = plan_steps([("s1", "general", "Birinci bölüm", []), ("s2", "general", "İkinci bölüm", ["s1"])])

    def reply_for(body):
        # planlayıcı RoutePlan şeması istiyor; diğerleri cevap
        sys = body["messages"][0]["content"]
        return plan if "planner of kayaAI" in sys else answer("Dış cevap.")
    real = fake.__call__

    def routed(req):
        b = json.loads(req.content) if req.content else {}
        if req.url.path.endswith("/chat/completions"):
            fake.reply = reply_for(b)
        return real(req)
    fake.__class__ = type("Routed", (FakeAPI,), {"__call__": lambda self, req: routed(req)})
    rt.settings.conductor.review = "never"
    res = Conductor(rt).run("İki parçalı bir iş", context={"_cloud": {"provider": "groq", "model": "llama-3.3-70b-versatile"}})
    assert res.status == "succeeded"
    assert res.cloud_models == ["☁ Groq/llama-3.3-70b-versatile"]
    assert len(chats(fake)) == 3  # plan + 2 adım
    assert not [r for r in fake_ollama.requests if r[1] == "/api/chat"]


def test_agent_assignment_needs_approval_and_routes_all_its_tasks(rt, fake, fake_ollama):
    ready(rt, fake)
    with pytest.raises(prov.ProviderError, match="Görsel"):
        prov.request_assign(rt, "vision", "groq")
    res = prov.request_assign(rt, "general", "groq", "llama-3.3-70b-versatile")
    assert res.status == "awaiting_approval" and res.risk == "R2"
    assert "BÜTÜN işleri" in rt.permissions.get(res.approval_id).action.reason
    assert prov.status(rt)["pending_assign"] == {"general": res.approval_id}
    fake_ollama.chat_replies = [good_answer("yerel")] * 5
    before = rt.orchestrator.ask("Merhaba", worker="general")
    assert before.model == "qwen3:8b"  # onay yokken yerel
    approve_last(rt)
    assert prov.assignments(rt) == {"general": {"provider": "groq", "model": "llama-3.3-70b-versatile"}}
    after = rt.orchestrator.ask("Merhaba", worker="general")
    assert after.model == "☁ Groq/llama-3.3-70b-versatile"
    coder = rt.orchestrator.ask("Bir fonksiyon yaz", worker="general", input={"_images": []})
    assert coder.model.startswith("☁")  # boş görüntü listesi engel değil
    off = prov.request_unassign(rt, "general")
    assert off.status == "done" and prov.assignments(rt) == {}
    prov.request_assign(rt, "general", "groq")
    approve_last(rt)
    prov.remove_provider(rt, "groq")
    assert prov.assignments(rt) == {}  # silinen sağlayıcının atamaları düşer


def test_api_chat_with_cloud_and_assign(rt, fake, fake_ollama):
    from fastapi.testclient import TestClient

    from kayaai.api import create_app

    ready(rt, fake)
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        conv = c.post("/api/chat", json={}).json()
        bad = c.post(f"/api/chat/{conv['id']}/messages", json={"text": "selam", "agent": "general", "cloud": {"provider": "yok"}})
        assert bad.status_code in (400, 404, 409, 422)
        ok = c.post(f"/api/chat/{conv['id']}/messages", json={"text": "selam", "agent": "general", "cloud": {"provider": "groq"}})
        assert ok.status_code == 202
        r = c.post("/api/providers/assign", json={"agent": "coder", "provider": "groq"}).json()
        assert r["status"] == "awaiting_approval"
        assert c.post("/api/providers/assign", json={"agent": "coder"}).json()["status"] == "done"
