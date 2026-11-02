"""Adım 20a: dış sağlayıcılar — kayıt, anahtar (asla geri dönmez), adres kuralları, onaylı açma, bağlantı testi."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from kayaai.api import create_app
from kayaai.config import load_settings
from kayaai.llm import providers as prov
from kayaai.llm.secretstore import FileStore, MemoryStore, SecretStore, SecretStoreError, clean_key, env_name
from kayaai.runtime import build_runtime

KEY = "gsk_test_ABCdef1234567890xyz"


class FakeAPI:
    """OpenAI uyumlu sağlayıcının kullandığımız kısmı."""

    def __init__(self, key: str = KEY):
        self.key = key
        self.calls: list[tuple[str, str, dict]] = []
        self.reply = '{"answer": "Buluttan cevap.", "language": "tr", "task_type": "chat", "confidence": 0.9, "needs_tools": []}'
        self.status = 200
        self.json_mode_ok = True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        self.calls.append((req.method, req.url.path, body))
        if req.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "qwen/qwen3-32b"}]})
        if req.url.path.endswith("/chat/completions"):
            if self.status != 200:
                return httpx.Response(self.status, json={"error": {"message": "rate limit"}})
            if "response_format" in body and not self.json_mode_ok:
                return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
            return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": self.reply},
                                             "finish_reason": "stop"}], "usage": {"prompt_tokens": 50, "completion_tokens": 20}})
        return httpx.Response(404)


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    r = build_runtime(load_settings())
    r.secret_store = SecretStore(r.settings.data_dir, backend=MemoryStore())
    yield r
    r.close()


@pytest.fixture
def fake(monkeypatch):
    api = FakeAPI()
    real = prov._client
    monkeypatch.setattr(prov, "_client", lambda p, key, timeout, transport: real(p, key, timeout, httpx.MockTransport(api)))
    return api


def approve_last(rt):
    [a] = rt.permissions.list_approvals("pending")
    return rt.permissions.approve(a.id, decided_by="test")


# ---------------------------------------------------------------- kayıt ve adres kuralları

def test_add_presets_and_address_rules(rt):
    g = prov.add_provider(rt, "groq")
    assert g.id == "groq" and g.internet and not g.enabled and g.base_url == "https://api.groq.com/openai/v1"
    o = prov.add_provider(rt, "omniroute")
    assert not o.internet
    g2 = prov.add_provider(rt, "groq")
    assert g2.id == "groq-2"
    c = prov.add_provider(rt, "custom", label="Şirket Sunucusu", base_url="https://llm.ornek.com/v1/")
    assert c.id == "sirket-sunucusu" and c.base_url == "https://llm.ornek.com/v1"
    for bad in ["http://llm.ornek.com/v1", "ftp://x/v1", "https://user:pw@llm.ornek.com/v1", "llm.ornek.com"]:
        with pytest.raises(ValueError):
            prov.add_provider(rt, "custom", label="kötü", base_url=bad)
    with pytest.raises(prov.ProviderError):
        prov.add_provider(rt, "bilinmeyen")


def test_key_is_never_returned_or_logged(rt):
    prov.add_provider(rt, "groq")
    prov.save_key(rt, "groq", f"  {KEY}  ")
    assert rt.secret_store.backend.data["groq"] == KEY
    st = prov.status(rt)
    [row] = st["providers"]
    assert row["has_key"] and row["key_source"] == "store"
    assert KEY not in json.dumps(st)
    assert KEY not in json.dumps(rt.store.events_since(0, 500))
    assert KEY not in (rt.store.get_meta("providers") or "")
    prov.delete_key(rt, "groq")
    assert not prov.status(rt)["providers"][0]["has_key"]


def test_enable_needs_key_and_owner_approval(rt):
    prov.add_provider(rt, "groq")
    with pytest.raises(prov.ProviderError, match="anahtar"):
        prov.request_enable(rt, "groq")
    prov.save_key(rt, "groq", KEY)
    res = prov.request_enable(rt, "groq")
    assert res.status == "awaiting_approval" and res.risk == "R2"
    a = rt.permissions.get(res.approval_id)
    assert "İNTERNET" in a.action.reason and "Asla gitmez" in a.action.preview["new_head"]
    assert prov.status(rt)["providers"][0]["pending_approval"] == res.approval_id
    assert not prov.get_provider(rt, "groq").enabled
    approve_last(rt)
    assert prov.get_provider(rt, "groq").enabled
    off = prov.request_disable(rt, "groq")
    assert off.status == "done" and not prov.get_provider(rt, "groq").enabled  # kapatmak R1, onaysız


def test_address_change_disables_and_stale_approval_fails(rt):
    prov.add_provider(rt, "groq")
    prov.save_key(rt, "groq", KEY)
    prov.request_enable(rt, "groq")
    approve_last(rt)
    p = prov.update_provider(rt, "groq", base_url="https://baska.ornek.com/v1")
    assert not p.enabled  # onay eski adres içindi
    prov.update_provider(rt, "groq", base_url="https://api.groq.com/openai/v1")
    res = prov.request_enable(rt, "groq")
    prov.update_provider(rt, "groq", base_url="https://baska.ornek.com/v1")  # onay beklerken adres değişti
    out = rt.permissions.approve(res.approval_id, decided_by="test")
    assert out.status == "failed" and not prov.get_provider(rt, "groq").enabled
    with pytest.raises(prov.ProviderError):
        prov.update_provider(rt, "groq", enabled=True)  # açma yalnız onayla


def test_connection_test_sends_no_user_data(rt, fake):
    prov.add_provider(rt, "groq")
    assert prov.test_connection(rt, "groq") == {"ok": False, "error": "anahtar yok"}
    prov.save_key(rt, "groq", "yanlis-anahtar")
    r = prov.test_connection(rt, "groq")
    assert not r["ok"] and "401" in r["error"] and "anahtar yanlış" in r["error"]
    prov.save_key(rt, "groq", KEY)
    r = prov.test_connection(rt, "groq")
    assert r["ok"] and r["models"] == ["llama-3.3-70b-versatile", "qwen/qwen3-32b"]
    p = prov.get_provider(rt, "groq")
    assert p.models == r["models"] and p.default_model == "llama-3.3-70b-versatile" and p.tested_at
    assert [(m, path) for m, path, _ in fake.calls] == [("GET", "/openai/v1/models")] * 2


def test_remove_deletes_key(rt):
    prov.add_provider(rt, "groq")
    prov.save_key(rt, "groq", KEY)
    prov.remove_provider(rt, "groq")
    assert "groq" not in rt.secret_store.backend.data and prov.list_providers(rt) == []


# ---------------------------------------------------------------- anahtar deposu

def test_secret_store_rules(tmp_path, monkeypatch):
    st = SecretStore(tmp_path, backend=FileStore(tmp_path / "secrets"))
    st.set("groq", KEY)
    f = tmp_path / "secrets" / "groq.key"
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE((tmp_path / "secrets").stat().st_mode) == 0o700
    assert st.get("groq") == KEY and st.source("groq") == "store"
    monkeypatch.setenv(env_name("groq"), "env-anahtar")
    assert st.get("groq") == "env-anahtar" and st.source("groq") == "env"
    st.delete("groq")
    assert not f.exists()
    for bad in ["", "a b", "x" * 1001, "ab\x00c"]:
        with pytest.raises(SecretStoreError):
            clean_key(bad)
    with pytest.raises(SecretStoreError):
        st.set("../kaç", KEY)


# ---------------------------------------------------------------- API ve CLI

def test_api_flow(rt, fake):
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {app.state.token}"
        assert c.get("/api/providers").json()["providers"] == []
        assert c.post("/api/providers", json={"preset": "groq"}).status_code == 200
        bad = c.post("/api/providers", json={"preset": "custom", "label": "x", "base_url": "http://uzak.com/v1"})
        assert bad.status_code == 422 and "https" in bad.json()["detail"]
        assert c.post("/api/providers/groq/enable").status_code == 409
        r = c.put("/api/providers/groq/key", json={"key": KEY})
        assert r.json() == {"id": "groq", "has_key": True} and KEY not in r.text
        t = c.post("/api/providers/groq/test").json()
        assert t["ok"] and len(t["models"]) == 2
        en = c.post("/api/providers/groq/enable").json()
        assert en["status"] == "awaiting_approval"
        c.post(f"/api/approvals/{en['approval_id']}/approve")
        st = c.get("/api/providers").json()
        assert st["providers"][0]["enabled"] and KEY not in json.dumps(st)
        c.post("/api/providers/groq/settings", json={"default_model": "qwen/qwen3-32b", "daily_limit": 50})
        assert c.get("/api/providers").json()["providers"][0]["daily_limit"] == 50
        assert c.delete("/api/providers/groq").json() == {"removed": "groq"}


def test_cli_list_add_keytest(rt, monkeypatch, capsys):
    from kayaai.cli import main

    assert main(["providers", "add", "openrouter"]) == 0
    assert main(["providers", "list"]) == 0
    out = capsys.readouterr().out
    assert "openrouter" in out and "anahtar YOK" in out and "kapalı" in out
    assert main(["providers", "keytest"]) == 0
    assert "yaz/oku ✓ · sil ✓" in capsys.readouterr().out
    assert main(["providers", "test"]) == 2
