"""Adım 11b/c: model yönetimi — görünüm, yükle/boşalt (R1), ajan modeli (R2), indirme (R2), karşılaştırma, aktif yapma."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kayaai.agents.lifecycle import create_temporary, overrides_path, sync_agents
from kayaai.api import create_app
from kayaai.config import load_settings
from kayaai.llm import manager as mm
from kayaai.llm.compare import CompareError, list_compares, start_compare
from kayaai.llm.registry import local_registry_path
from kayaai.runtime import build_runtime

from .test_agent_lifecycle import LEGAL

CODER = {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4_700_000_000,
         "details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}}


def _settings(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    r = build_runtime(_settings(fake_ollama, tmp_path, monkeypatch))
    yield r
    r.close()


def _row(ov, key):
    return next(m for m in ov["models"] if m["key"] == key)


def _model_of(rt, agent):
    return rt.workers.get(agent).definition.local_model


def _reply(body) -> str:
    """Sahte model: isteğe göre doğru cevap; 'qwen3:4b' başkent sorusunu yanlış bilir."""
    user = body["messages"][-1]["content"]
    if "başkenti" in user:
        ans, lang = ("İstanbul." if body["model"] == "qwen3:4b" else "Ankara."), "tr"
    elif "API" in user:
        ans, lang = "An API is a contract that lets two programs talk to each other. It defines requests and replies.", "en"
    elif "haftada" in user:
        ans, lang = "Bir haftada 168 saat vardır.", "tr"
    elif "15%" in user:
        ans, lang = "15% of 240 is 36.", "en"
    elif "İngilizceye" in user:
        ans, lang = "I will be late to the meeting tomorrow morning.", "en"
    else:
        ans, lang = "Tamam, bunu senin için hallettim.", "tr"
    return json.dumps({"answer": ans, "language": lang, "task_type": "chat", "confidence": 0.9, "needs_tools": []},
                      ensure_ascii=False)


# ---------------------------------------------------------------- görünüm

def test_overview_lists_registry_installed_loaded_and_agents(rt, fake_ollama):
    fake_ollama.models.append({"name": "phi4:14b", "model": "phi4:14b", "size": 9_100_000_000})
    ov = mm.overview(rt)
    assert ov["ollama_reachable"] is True
    g = _row(ov, "general-8b")
    assert g["installed"] is True and g["size_gb"] == pytest.approx(4.84, abs=0.01) and g["loaded"] is None
    assert {"general", "data", "planner"} <= set(g["agents"])
    assert _row(ov, "coder-7b")["installed"] is False and _row(ov, "coder-7b")["agents"] == ["coder"]
    assert _row(ov, "llama31-8b")["status"] == "candidate"
    assert _row(ov, "embed-m3")["embedding"] and _row(ov, "embed-m3")["agents"] == ["hafıza"]
    extra = next(m for m in ov["models"] if m["name"] == "phi4:14b")
    assert extra["key"] is None and extra["status"] == "unregistered"
    assert next(a for a in ov["agents"] if a["name"] == "coder")["model_name"] == "qwen2.5-coder:7b"


def test_overview_without_ollama(rt, fake_ollama):
    fake_ollama.stop()
    ov = mm.overview(rt)
    assert ov["ollama_reachable"] is False and _row(ov, "general-8b")["installed"] is None


# ---------------------------------------------------------------- yükle / boşalt (R1)

def test_load_and_unload_run_without_approval_and_are_logged(rt, fake_ollama):
    r = mm.request_load(rt, "qwen3:8b")
    assert r.status == "done" and r.risk.value == "R1"
    assert _row(mm.overview(rt), "general-8b")["loaded"]["vram_gb"] == pytest.approx(0.93, abs=0.01)
    gen = [b for (_, p, b) in fake_ollama.requests if p == "/api/generate"]
    assert gen[-1]["keep_alive"] == "30m" and gen[-1]["prompt"] == ""
    assert mm.request_load(rt, "qwen3:8b", unload=True).status == "done"
    assert _row(mm.overview(rt), "general-8b")["loaded"] is None
    assert [b for (_, p, b) in fake_ollama.requests if p == "/api/generate"][-1]["keep_alive"] == 0
    types = [e["type"] for e in rt.store.events_since(0)]
    assert "model.loaded" in types and "model.unloaded" in types and types.count("tool.used") == 2


def test_embedding_model_is_loaded_with_embed_endpoint(rt, fake_ollama):
    assert mm.request_load(rt, "bge-m3").status == "done"
    assert [p for (_, p, _) in fake_ollama.requests][-1] == "/api/embed"


def test_load_unknown_model_refused(rt):
    with pytest.raises(mm.ModelAdminError, match="kurulu değil"):
        mm.request_load(rt, "yok:1b")


# ---------------------------------------------------------------- ajan modeli (R2)

def test_agent_model_needs_owner_approval_and_persists(rt, fake_ollama, tmp_path, monkeypatch):
    fake_ollama.models.append(CODER)
    r = mm.request_agent_model(rt, "data", "coder-7b")
    assert r.status == "awaiting_approval" and r.risk.value == "R2"
    a = rt.permissions.get(r.approval_id)
    assert "qwen3:8b → qwen2.5-coder:7b" in a.action.summary and "4.7 GB" in a.action.preview["new_head"]
    assert _model_of(rt, "data") == "general-8b"  # onaysız hiçbir şey değişmez
    assert not overrides_path(rt).exists()

    done = rt.permissions.approve(r.approval_id, decided_by="owner")
    assert done.status == "approved", done.error
    assert _model_of(rt, "data") == "coder-7b"
    assert yaml.safe_load(overrides_path(rt).read_text(encoding="utf-8")) == {"data": {"local_model": "coder-7b"}}
    assert (Path("config/agents/data.yaml").read_text(encoding="utf-8").count("local_model: general-8b")) == 1
    ov = mm.overview(rt)
    assert next(a for a in ov["agents"] if a["name"] == "data")["overridden"] is True
    assert "data" in _row(ov, "coder-7b")["agents"]

    # başka süreç (ör. MCP sunucusu) aynı atamayı görür
    other = build_runtime(_settings(fake_ollama, tmp_path, monkeypatch))
    try:
        assert _model_of(other, "data") == "coder-7b"
        # dosyadaki modele dönüş → geçersiz kılma kaldırılır
        back = mm.request_agent_model(other, "data", "general-8b")
        assert other.permissions.approve(back.approval_id, decided_by="owner").status == "approved"
        assert yaml.safe_load(overrides_path(rt).read_text(encoding="utf-8")) in ({}, None)
    finally:
        other.close()
    sync_agents(rt)
    assert _model_of(rt, "data") == "general-8b"


@pytest.mark.parametrize("agent,key,err", [
    ("data", "llama31-8b", "aday model"),
    ("data", "coder-7b", "kurulu değil"),
    ("data", "embed-m3", "embedding"),
    ("data", "general-8b", "zaten"),
    ("data", "yok-model", "ne kayaAI'de kayıtlı ne de Ollama'da kurulu"),
    ("yokajan", "general-8b", "Bilinmeyen ajan"),
])
def test_agent_model_refusals(rt, agent, key, err):
    with pytest.raises(mm.ModelAdminError, match=err):
        mm.request_agent_model(rt, agent, key)
    assert rt.permissions.list_approvals() == []


def test_invalid_override_is_ignored_with_warning(rt):
    overrides_path(rt).write_text("data:\n  local_model: llama31-8b\n", encoding="utf-8")
    warnings = sync_agents(rt)
    assert any("llama31-8b" in w for w in warnings) and _model_of(rt, "data") == "general-8b"


def test_user_agent_model_change_edits_its_own_file(rt, fake_ollama, tmp_path):
    fake_ollama.models.append(CODER)
    create_temporary(rt, LEGAL, created_by="owner")
    r = mm.request_agent_model(rt, "legal", "coder-7b")
    assert rt.permissions.approve(r.approval_id, decided_by="owner").status == "approved"
    saved = yaml.safe_load((tmp_path / "agents" / "legal.yaml").read_text(encoding="utf-8"))
    assert saved["local_model"] == "coder-7b" and saved["status"] == "temporary"
    assert _model_of(rt, "legal") == "coder-7b" and not overrides_path(rt).exists()


# ---------------------------------------------------------------- indirme (R2)

@pytest.mark.parametrize("name,err", [("Qwen3 4b; rm -rf", "Geçersiz"), ("../etc", "Geçersiz"), ("", "Geçersiz"),
                                      ("qwen3:8b", "Zaten kurulu")])
def test_pull_refusals(rt, name, err):
    with pytest.raises(mm.ModelAdminError, match=err):
        mm.request_pull(rt, name)


def test_pull_after_approval_adds_candidate_to_local_registry(rt, fake_ollama):
    r = mm.request_pull(rt, "qwen3:4b")
    assert r.status == "awaiting_approval" and r.risk.value == "R2"
    assert not any(p == "/api/pull" for (_, p, _) in fake_ollama.requests)
    done = rt.permissions.approve(r.approval_id, decided_by="owner")
    assert done.status == "approved", done.error
    local = yaml.safe_load(local_registry_path(rt.settings).read_text(encoding="utf-8"))
    entry = local["models"]["qwen3-4b"]
    assert entry["name"] == "qwen3:4b" and entry["status"] == "candidate" and entry["approx_vram_gb"] == pytest.approx(2.33, abs=0.01)
    assert rt.registry.get("qwen3-4b").status == "candidate"
    pulls = [e["data"] for e in rt.store.events_since(0) if e["type"] == "model.pull"]
    assert pulls[-1]["status"] == "tamamlandı" and any(p.get("percent") == 50.0 for p in pulls)
    # aday: ajana atanamaz
    with pytest.raises(mm.ModelAdminError, match="aday"):
        mm.request_agent_model(rt, "general", "qwen3-4b")


def test_pull_failure_marks_approval_failed(rt):
    r = mm.request_pull(rt, "yokboyle:1b")
    done = rt.permissions.approve(r.approval_id, decided_by="owner")
    assert done.status == "failed" and "file does not exist" in done.error
    assert not local_registry_path(rt.settings).exists()


# ---------------------------------------------------------------- karşılaştırma + aktif yapma

def _pulled(rt):
    r = mm.request_pull(rt, "qwen3:4b")
    assert rt.permissions.approve(r.approval_id, decided_by="owner").status == "approved"


def test_compare_then_activate_then_assign(rt, fake_ollama):
    _pulled(rt)
    with pytest.raises(mm.ModelAdminError, match="karşılaştır"):
        mm.request_activate(rt, "qwen3-4b")
    fake_ollama.chat_replies = [_reply] * 40
    rec = start_compare(rt, "general", "qwen3-4b")
    assert rec["status"] == "done", rec.get("error")
    assert rec["summary"]["current"]["ok"] == 5 and rec["summary"]["candidate"]["ok"] == 4
    bad = next(r for r in rec["rows"]["candidate"] if not r["ok"])
    assert bad["missing"] == ["Ankara"]
    assert rec["summary"]["candidate"]["model"] == "qwen3:4b"
    assert list_compares(rt)[0]["id"] == rec["id"]
    assert not list(Path(rt.settings.data_dir / "model_compare").glob("*.db*"))  # geçici veritabanı silindi
    assert rt.store.list_by_worker("general", 10) == []  # gerçek geçmiş kirlenmedi

    r = mm.request_activate(rt, "qwen3-4b")
    a = rt.permissions.get(r.approval_id)
    assert r.risk.value == "R2" and "aday 4/5" in a.action.preview["new_head"]
    assert rt.permissions.approve(r.approval_id, decided_by="owner").status == "approved"
    assert rt.registry.get("qwen3-4b").status == "active"
    assert mm.request_agent_model(rt, "general", "qwen3-4b").status == "awaiting_approval"


@pytest.mark.parametrize("agent,cand,err", [("planner", "llama31-8b", "cevap üreten"), ("general", "general-8b", "aynı"),
                                            ("general", "embed-m3", "Embedding"), ("yok", "general-8b", "Bilinmeyen")])
def test_compare_refusals(rt, agent, cand, err):
    with pytest.raises(CompareError, match=err):
        start_compare(rt, agent, cand)


def test_compare_with_missing_candidate_records_failure(rt, fake_ollama):
    fake_ollama.chat_replies = [_reply] * 40
    rec = start_compare(rt, "general", "llama31-8b")  # kayıtlı ama kurulu değil
    assert rec["status"] == "done"  # görevler başarısız olur, karşılaştırma yine de raporlanır
    assert rec["summary"]["candidate"]["ok"] == 0 and rec["summary"]["current"]["ok"] == 5
    # kilit bırakıldı: yeni karşılaştırma başlatılabilir
    fake_ollama.chat_replies = [_reply] * 40
    assert start_compare(rt, "general", "llama31-8b")["status"] == "done"


# ---------------------------------------------------------------- Windows geri bildirimi (v0.11.1): kayıtsız / bekleyen aday

QWEN4 = {"name": "qwen3:4b", "model": "qwen3:4b", "size": 2_500_000_000}


@pytest.mark.parametrize("ref", ["qwen3:4b", "qwen3-4b"])
def test_compare_accepts_installed_but_unregistered_model(rt, fake_ollama, ref):
    fake_ollama.models.append(dict(QWEN4))  # `ollama pull qwen3:4b` ile kayaAI dışında indirilmiş
    fake_ollama.chat_replies = [_reply] * 40
    rec = start_compare(rt, "general", ref)
    assert rec["status"] == "done" and rec["candidate"] == "qwen3-4b"
    assert rec["summary"]["candidate"]["model"] == "qwen3:4b" and rec["summary"]["candidate"]["ok"] == 4
    local = yaml.safe_load(local_registry_path(rt.settings).read_text(encoding="utf-8"))
    assert local["models"]["qwen3-4b"]["status"] == "candidate"
    assert any(e["type"] == "model.registered" for e in rt.store.events_since(0))
    with pytest.raises(mm.ModelAdminError, match="aday"):  # kayıt aday: ajana atanamaz
        mm.request_agent_model(rt, "general", "qwen3:4b")
    assert mm.request_activate(rt, "qwen3:4b").status == "awaiting_approval"  # Ollama adıyla da


def test_compare_with_pending_pull_says_approve(rt):
    r = mm.request_pull(rt, "qwen3:4b")
    with pytest.raises(CompareError, match=f"kayaai approvals approve {r.approval_id}"):
        start_compare(rt, "data", "qwen3-4b")


def test_compare_not_installed_says_pull(rt):
    with pytest.raises(CompareError, match="kayaai models pull qwen3:4b"):
        start_compare(rt, "data", "qwen3:4b")
    with pytest.raises(CompareError, match="kayaai models pull <ad:etiket>"):
        start_compare(rt, "data", "qwen3-4b")


def test_assign_unregistered_installed_model_points_to_compare(rt, fake_ollama):
    fake_ollama.models.append(dict(QWEN4))
    with pytest.raises(mm.ModelAdminError, match="kayaai models compare <ajan> qwen3:4b"):
        mm.request_agent_model(rt, "data", "qwen3:4b")
    with pytest.raises(mm.ModelAdminError, match="kayaai models compare"):
        mm.request_pull(rt, "qwen3:4b")


def test_compare_warms_up_models_and_frees_candidate_vram(rt, fake_ollama):
    fake_ollama.models.append(dict(QWEN4))
    fake_ollama.chat_replies = [_reply] * 40
    rec = start_compare(rt, "general", "qwen3:4b")
    loads = [b["model"] for (_, p, b) in fake_ollama.requests if p == "/api/generate" and b.get("keep_alive") != 0]
    assert loads[:2] == ["qwen3:8b", "qwen3:4b"] and set(rec["load_seconds"]) == {"current", "candidate"}
    unloads = [b["model"] for (_, p, b) in fake_ollama.requests if p == "/api/generate" and b.get("keep_alive") == 0]
    assert unloads == ["qwen3:4b"]  # önceden yüklü değildi → karşılaştırma sonunda boşaltıldı
    first_gen = next(i for i, (_, p, _) in enumerate(fake_ollama.requests) if p == "/api/generate")
    first_chat = next(i for i, (_, p, _) in enumerate(fake_ollama.requests) if p == "/api/chat")
    assert first_gen < first_chat  # ısınma vakalardan önce


def test_thinking_models_registered_with_think_off(rt, fake_ollama):
    fake_ollama.models.append(dict(QWEN4))
    fake_ollama.chat_replies = [_reply] * 40
    start_compare(rt, "general", "qwen3:4b")
    assert rt.registry.get("qwen3-4b").think is False
    chats = [b for (_, p, b) in fake_ollama.requests if p == "/api/chat" and b["model"] == "qwen3:4b"]
    assert chats and all(b.get("think") is False for b in chats)
    fake_ollama.models.append({"name": "qwen2:7b", "model": "qwen2:7b", "size": 4_400_000_000})
    start_compare(rt, "general", "qwen2:7b")
    assert rt.registry.get("qwen2-7b").think is None  # düşünmeyen model: ayar eklenmez


def test_old_candidate_entry_gets_think_policy(rt, fake_ollama):
    """v0.11.1 öncesi indirilen qwen3:4b kaydında think yoktu (Windows: 161 token/sn ama cevap başına ~6 sn)."""
    fake_ollama.models.append(dict(QWEN4))
    local_registry_path(rt.settings).write_text(
        "models:\n  qwen3-4b:\n    name: qwen3:4b\n    status: candidate\n", encoding="utf-8")
    sync_agents(rt)
    assert rt.registry.get("qwen3-4b").think is None
    fake_ollama.chat_replies = [_reply] * 40
    start_compare(rt, "data", "qwen3-4b")
    assert rt.registry.get("qwen3-4b").think is False


# Windows ölçümü (2026-11-01, v0.11.2): qwen3:4b iki yanlış cevapla 4/5 sayılmıştı.
@pytest.mark.parametrize("answer,request_,expected,missing,echo", [
    ("120 + 80 = 200", "Bir ürünün fiyatı 250 TL'den 300 TL'ye çıktı. Artış yüzde kaç?", [20], ["20"], False),
    ("Fiyatın %20 arttığı hesaplanmıştır.", "Bir ürünün fiyatı 250 TL'den 300 TL'ye çıktı. Artış yüzde kaç?", [20], [], False),
    ("Bir mağaza ocakta 200, şubatta 260 adet sattı. Şubattaki artış yüzde kaç? Mart satışları şubata göre %25 düşerse "
     "mart kaç adet olur?", "Bir mağaza ocakta 200, şubatta 260 adet sattı. Şubattaki artış yüzde kaç? Mart satışları "
     "şubata göre %25 düşerse mart kaç adet olur?", [30, 195], ["30", "195"], True),
    ("Şubattaki artış %30'dur; mart satışları 195 adet olur.", "ocakta 200, şubatta 260 … %25 düşerse", [30, 195], [], False),
    ("Total: 240\nAverage: 60.0", "Compute the total and the average of these expenses: 40, 70, 50, 80.", [240, 60], [], False),
    ("Toplam 1.234,50 TL", "x", [1234.5], [], False),
    ("The final price is 68.00.", "A product costs 80 … 25% discount, then 10% tax", [66], ["66"], False),
    ("Türkiye'nin başkenti Ankara'dır.", "Türkiye'nin başkenti neresi?", ["Ankara"], [], False),
    ("I will translate it.", "çevir", ["late"], ["late"], False),
])
def test_compare_scoring_is_strict(answer, request_, expected, missing, echo):
    from kayaai.llm.compare import is_echo, missing_expected

    assert missing_expected(answer, request_, expected) == missing
    assert is_echo(answer, request_) is echo


def test_warm_up_uses_chat_options_so_model_is_not_reloaded(rt, fake_ollama):
    fake_ollama.models.append(dict(QWEN4))
    fake_ollama.chat_replies = [_reply] * 40
    start_compare(rt, "general", "qwen3:4b")
    warm = next(b for (_, p, b) in fake_ollama.requests if p == "/api/generate" and b["model"] == "qwen3:8b")
    assert warm["options"]["num_ctx"] == rt.registry.get("general-8b").context_length
    mm.request_load(rt, "qwen3:8b")
    last = [b for (_, p, b) in fake_ollama.requests if p == "/api/generate"][-1]
    assert last["options"]["num_ctx"] == rt.registry.get("general-8b").context_length


# ---------------------------------------------------------------- API

def test_api_model_admin_flow(fake_ollama, tmp_path, monkeypatch):
    settings = _settings(fake_ollama, tmp_path, monkeypatch)
    app = create_app(settings, ui_dir=tmp_path / "noui")
    token = (tmp_path / "api_token").read_text(encoding="utf-8").strip()
    h = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as c:
        assert c.get("/api/model-admin").status_code == 401
        ov = c.get("/api/model-admin", headers=h).json()
        assert any(m["key"] == "general-8b" for m in ov["models"])
        assert c.post("/api/models/load", json={"name": "qwen3:8b"}, headers=h).json()["status"] == "done"
        assert c.post("/api/models/unload", json={"name": "qwen3:8b"}, headers=h).json()["status"] == "done"
        assert c.post("/api/models/load", json={"name": "yok:1b"}, headers=h).status_code == 409
        assert c.post("/api/agents/data/model", json={"model_key": "llama31-8b"}, headers=h).status_code == 409
        assert c.post("/api/models/pull", json={"name": "bad name"}, headers=h).status_code == 409

        pr = c.post("/api/models/pull", json={"name": "qwen3:4b"}, headers=h).json()
        assert pr["status"] == "awaiting_approval"
        assert c.post(f"/api/approvals/{pr['approval_id']}/approve", headers=h).json()["status"] == "approved"
        for _ in range(100):  # arka planda iner
            ov = c.get("/api/model-admin", headers=h).json()
            if any(m["key"] == "qwen3-4b" for m in ov["models"]):
                break
            time.sleep(0.05)
        assert _row(ov, "qwen3-4b")["status"] == "candidate" and _row(ov, "qwen3-4b")["installed"] is True
        assert ov["pulls"][0]["name"] == "qwen3:4b"

        fake_ollama.chat_replies = [_reply] * 40
        rec = c.post("/api/model-compare", json={"agent": "general", "candidate": "qwen3-4b"}, headers=h).json()
        assert rec["status"] == "running"
        for _ in range(200):
            got = c.get(f"/api/model-compare/{rec['id']}", headers=h).json()
            if got["status"] != "running":
                break
            time.sleep(0.05)
        assert got["status"] == "done" and got["summary"]["candidate"]["ok"] == 4
        assert c.get("/api/model-compare/yok", headers=h).status_code == 404
        act = c.post("/api/models/qwen3-4b/activate", headers=h).json()
        assert act["status"] == "awaiting_approval"


# ---------------------------------------------------------------- CLI

def test_cli_models(fake_ollama, tmp_path, monkeypatch, capsys):
    from kayaai.cli import main

    _settings(fake_ollama, tmp_path, monkeypatch)
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "general-8b" in out and "ADAY" in out and "kullanan:" in out
    assert main(["models", "load", "qwen3:8b"]) == 0 and "belleğe yüklendi" in capsys.readouterr().out
    assert main(["models", "list"]) == 0 and "YÜKLÜ" in capsys.readouterr().out
    assert main(["models", "assign", "data", "llama31-8b"]) == 1 and "aday" in capsys.readouterr().out
    assert main(["models", "pull", "qwen3:4b"]) == 0 and "kayaai approvals approve" in capsys.readouterr().out
    assert main(["models", "assign"]) == 2
    fake_ollama.models.append(dict(QWEN4))
    fake_ollama.chat_replies = [_reply] * 40
    assert main(["models", "compare", "general", "qwen3:4b"]) == 0
    out = capsys.readouterr().out
    assert "Aday" in out and "4/5 doğru" in out
