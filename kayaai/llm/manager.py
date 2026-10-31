"""Model yönetimi (Adım 11; sahip kararı: yalnız Ollama — görüntüle, yükle/boşalt, ajan modeli değiştir, indir, karşılaştır).

Tüm değişiklikler izin motorundan geçer:
- yükle / boşalt: R1 (otomatik, kayda geçer) — yalnızca VRAM'i etkiler.
- ajanın modelini değiştir, model indir, adayı aktif yap: **R2 sahip onayı** (onay merkezinde önizlemeli).
Repo dosyaları değişmez: indirilen/aktif yapılan modeller `data/models.local.yaml`, repo ajanlarının model atamaları
`data/agent_overrides.yaml`, kullanıcı ajanlarınınki kendi `data/agents/<ad>.yaml` dosyasında.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..core.permissions import Risk, SubmitResult, ToolAction
from .ollama_client import OllamaError
from .registry import local_registry_path

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}(/[a-z0-9][a-z0-9._-]{0,60})?(:[a-z0-9][a-z0-9._-]{0,40})?$")
_PULLS: dict[str, dict[str, Any]] = {}
_PULLS_LOCK = threading.Lock()


class ModelAdminError(ValueError):
    pass


def _gb(b: Any) -> float | None:
    return round(float(b) / 1024**3, 2) if b else None


def _match(name: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for m in items:
        n = m.get("name") or m.get("model") or ""
        if n == name or n == f"{name}:latest" or f"{n}:latest" == name:
            return m
    return None


def model_key_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "model"


# ---------------------------------------------------------------------------- görünüm


def overview(rt: "Runtime") -> dict[str, Any]:
    from ..agents.lifecycle import read_overrides, sync_agents

    sync_agents(rt)
    try:
        installed, loaded, ok = rt.llm.list_models(), rt.llm.running_models(), True
    except OllamaError:
        installed, loaded, ok = [], [], False
    users: dict[str, list[str]] = {}
    for w in rt.workers.all():
        try:
            users.setdefault(w.model_spec(rt.registry).key, []).append(w.name)
        except KeyError:
            continue
    embed_key = rt.settings.memory.embed_model
    users.setdefault(embed_key, []).append("hafıza")
    rows, seen = [], set()
    for key, spec in rt.registry.models.items():
        inst = _match(spec.name, installed)
        load = _match(spec.name, loaded)
        if inst:
            seen.add(inst.get("name"))
        det = (inst or {}).get("details") or {}
        rows.append({
            "key": key, "name": spec.name, "status": spec.status, "purpose": spec.purpose, "license": spec.license,
            "approx_vram_gb": spec.approx_vram_gb, "installed": bool(inst) if ok else None, "size_gb": _gb((inst or {}).get("size")),
            "family": det.get("family"), "parameters": det.get("parameter_size"), "quantization": det.get("quantization_level"),
            "loaded": {"vram_gb": _gb(load.get("size_vram")), "expires_at": load.get("expires_at")} if load else None,
            "agents": users.get(key, []), "embedding": key == embed_key,
        })
    for m in installed:
        if m.get("name") in seen:
            continue
        det = m.get("details") or {}
        load = _match(m.get("name", ""), loaded)
        rows.append({"key": None, "name": m.get("name"), "status": "unregistered", "purpose": "", "license": None,
                     "approx_vram_gb": None, "installed": True, "size_gb": _gb(m.get("size")), "family": det.get("family"),
                     "parameters": det.get("parameter_size"), "quantization": det.get("quantization_level"),
                     "loaded": {"vram_gb": _gb(load.get("size_vram")), "expires_at": load.get("expires_at")} if load else None,
                     "agents": [], "embedding": False})
    overrides = read_overrides(rt)
    agents = []
    for w in rt.workers.all():
        d = getattr(w, "definition", None)
        if d is None:
            continue
        agents.append({"name": w.name, "model_key": d.local_model, "model_name": rt.registry.get(d.local_model).name,
                       "overridden": w.name in overrides, "user_agent": w.name in rt.workers.user_names,
                       "description": w.description, "output": d.output})
    from .compare import list_compares

    with _PULLS_LOCK:
        pulls = [dict(v, name=k) for k, v in _PULLS.items()]
    return {"ollama_reachable": ok, "models": rows, "agents": agents, "pulls": pulls,
            "compares": list_compares(rt)[:10]}


# ---------------------------------------------------------------------------- yerel kayıt dosyaları


def _read_yaml(p: Path) -> dict[str, Any]:
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _write_yaml(p: Path, data: dict[str, Any], header: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(p)


LOCAL_HEADER = "# kayaAI yerel model kaydı (Adım 11): indirilen / aktif yapılan modeller. config/models.yaml üzerine eklenir.\n"
OVERRIDE_HEADER = "# kayaAI ajan model atamaları (Adım 11, sahip onayıyla). Repo ajanlarının config/agents/*.yaml dosyası değişmez.\n"


# ---------------------------------------------------------------------------- talepler (izin motoru)


def _submit(rt: "Runtime", action: ToolAction) -> SubmitResult:
    assert rt.permissions is not None
    return rt.permissions.submit(action)


def _installed_names(rt: "Runtime") -> list[dict[str, Any]]:
    try:
        return rt.llm.list_models()
    except OllamaError as exc:
        raise ModelAdminError(f"Ollama'ya ulaşılamadı: {exc}") from exc


def find_key(rt: "Runtime", ref: str) -> str | None:
    """Kayıt anahtarı ya da Ollama adı ('qwen3-4b' ≡ 'qwen3:4b') → kayıt anahtarı (yoksa None)."""
    ref = (ref or "").strip()
    if ref in rt.registry.models:
        return ref
    return rt.registry.key_for_name(ref.lower())


def _slug(name: str) -> str:
    return model_key_slug(name.removesuffix(":latest"))


def _pending_pull(rt: "Runtime", ref: str) -> str | None:
    assert rt.permissions is not None
    for a in rt.permissions.list_approvals("pending"):
        if a.action.tool == "model.pull" and _slug(a.action.params.get("name", "")) == _slug(ref):
            return a.id
    return None


def _not_found(rt: "Runtime", ref: str) -> ModelAdminError:
    pending = _pending_pull(rt, ref)
    if pending:
        return ModelAdminError(f"'{ref}' henüz inmedi: indirme sahip onayı bekliyor → kayaai approvals approve {pending}")
    example = ref if ":" in ref else "<ad:etiket> (ör. qwen3:4b)"
    return ModelAdminError(f"'{ref}' ne kayaAI'de kayıtlı ne de Ollama'da kurulu. Önce indir: kayaai models pull {example} "
                           f"(sahip onayı gerekir) ya da Modeller → Yeni model indir")


def _think_policy(rt: "Runtime", name: str) -> dict[str, Any]:
    """Düşünen modellerde (Ollama yeteneği 'thinking', ör. qwen3) gizli düşünme kapalı: genel modelle aynı politika
    (config/models.yaml general-8b `think: false`); yoksa karşılaştırmada süreler adil olmaz."""
    try:
        caps = rt.llm.show(name).get("capabilities") or []
    except OllamaError:
        return {}
    return {"think": False} if "thinking" in caps else {}


def ensure_think_policy(rt: "Runtime", key: str) -> None:
    """Yerel kayıttaki (sonradan eklenen) bir modelde düşünme ayarı yoksa ekler (v0.11.1 öncesi kayıtlar için)."""
    data = _read_yaml(local_registry_path(rt.settings))
    entry = (data.get("models") or {}).get(key)
    if not entry or "think" in entry or key not in rt.registry.models:
        return
    policy = _think_policy(rt, rt.registry.get(key).name)
    if policy:
        _add_local_model(rt, key, policy)


def resolve_candidate(rt: "Runtime", ref: str) -> str:
    """Karşılaştırma adayı: kayıtlıysa anahtarı; Ollama'da kurulu ama kayıtsızsa (ör. `ollama pull` ile indirilmiş)
    yerel kayda **aday** olarak ekler (indirme yok, ajana atanamaz); hiçbiri değilse ne yapılacağını söyleyen hata."""
    key = find_key(rt, ref)
    if key:
        return key
    inst = next((m for m in _installed_names(rt)
                 if m.get("name") and (_match(ref.strip().lower(), [m]) or _slug(m["name"]) == _slug(ref))), None)
    if inst is None:
        raise _not_found(rt, ref)
    name = inst["name"]
    key = _slug(name)
    while key in rt.registry.models:  # başka bir modelin anahtarıyla çakışmasın
        key += "-x"
    _add_local_model(rt, key, {"name": name, "purpose": "Ollama'da kuruluydu; karşılaştırma için aday olarak eklendi",
                               "keep_alive": "10m", "approx_vram_gb": _gb(inst.get("size")), "license": "kontrol et",
                               "status": "candidate", **_think_policy(rt, name)})
    rt.store.emit("model.registered", {"key": key, "name": name, "status": "candidate"})
    return key


def _known_key(rt: "Runtime", ref: str) -> str:
    key = find_key(rt, ref)
    if key:
        return key
    try:
        installed = _match(ref.strip().lower(), _installed_names(rt))
    except ModelAdminError:
        installed = None
    if installed:
        raise ModelAdminError(f"'{ref}' Ollama'da kurulu ama kayaAI'de kayıtlı değil; önce karşılaştır: "
                              f"kayaai models compare <ajan> {installed['name']}")
    raise _not_found(rt, ref)


def request_load(rt: "Runtime", name: str, unload: bool = False, requested_by: str = "user") -> SubmitResult:
    if not _match(name, _installed_names(rt)):
        raise ModelAdminError(f"Model kurulu değil: {name}")
    key = rt.registry.key_for_name(name)
    embedding = key == rt.settings.memory.embed_model or "embed" in name or "bge" in name
    verb = "Bellekten çıkar" if unload else "Belleğe yükle"
    return _submit(rt, ToolAction(tool="model.unload" if unload else "model.load", params={"name": name, "embedding": embedding},
                                  risk=Risk.R1, summary=f"{verb}: {name}", requested_by=requested_by,
                                  undo="Tersini yapmak yeterli (yükle / boşalt)."))


def request_agent_model(rt: "Runtime", agent: str, key: str, requested_by: str = "user") -> SubmitResult:
    from ..agents.lifecycle import sync_agents

    sync_agents(rt)
    if agent not in rt.workers.names():
        raise ModelAdminError(f"Bilinmeyen ajan: {agent}")
    d = getattr(rt.workers.get(agent), "definition", None)
    if d is None:
        raise ModelAdminError(f"{agent} tanımlı bir ajan değil")
    key = _known_key(rt, key)
    spec = rt.registry.get(key)
    if spec.status != "active":
        raise ModelAdminError(f"'{key}' aday model; önce karşılaştırıp aktif yap (Modeller → Karşılaştır)")
    if key == rt.settings.memory.embed_model:
        raise ModelAdminError("Hafıza (embedding) modeli bir ajana atanamaz")
    if not _match(spec.name, _installed_names(rt)):
        raise ModelAdminError(f"Model kurulu değil: {spec.name} — önce indir")
    if d.local_model == key:
        raise ModelAdminError(f"{agent} zaten {spec.name} kullanıyor")
    old = rt.registry.get(d.local_model)
    return _submit(rt, ToolAction(
        tool="agent.model", params={"agent": agent, "model_key": key}, risk=Risk.R2,
        summary=f"{agent} ajanının modelini değiştir: {old.name} → {spec.name}",
        reason="Ajanın cevap kalitesi ve hızı değişir; GPU belleği kullanımı değişebilir.",
        preview={"old_head": f"{old.name}  (~{old.approx_vram_gb} GB VRAM, {old.license})",
                 "new_head": f"{spec.name}  (~{spec.approx_vram_gb} GB VRAM, {spec.license})"},
        undo="Modeller sayfasından eski modeli yeniden seç (ya da data/agent_overrides.yaml satırını sil).",
        requested_by=requested_by))


def request_pull(rt: "Runtime", name: str, requested_by: str = "user") -> SubmitResult:
    name = (name or "").strip().lower()
    if not MODEL_NAME.match(name):
        raise ModelAdminError("Geçersiz model adı (ör. qwen3:4b, llama3.2:3b)")
    if _match(name, _installed_names(rt)):
        raise ModelAdminError(f"Zaten kurulu: {name} — karşılaştırmak için: kayaai models compare <ajan> {name}")
    return _submit(rt, ToolAction(
        tool="model.pull", params={"name": name}, risk=Risk.R2,
        summary=f"Yeni model indir: {name} (Ollama kütüphanesinden)",
        reason="İnternetten birkaç GB indirilir ve diske yazılır; lisansını indirmeden önce kontrol et.",
        preview={"new_head": f"ollama pull {name}\nİnen model 'aday' olarak eklenir; ajana atamadan önce karşılaştırılmalı."},
        undo=f"ollama rm {name}", requested_by=requested_by))


def request_activate(rt: "Runtime", key: str, requested_by: str = "user") -> SubmitResult:
    from .compare import list_compares

    key = _known_key(rt, key)
    spec = rt.registry.get(key)
    if spec.status == "active":
        raise ModelAdminError(f"'{key}' zaten aktif")
    done = [c for c in list_compares(rt) if c.get("candidate") == key and c.get("status") == "done"]
    if not done:
        raise ModelAdminError("Önce bu modeli bir ajanın görevlerinde karşılaştır (doğrulayıcı kapısı)")
    last = done[0]
    return _submit(rt, ToolAction(
        tool="model.activate", params={"key": key}, risk=Risk.R2,
        summary=f"Aday modeli aktif yap: {spec.name}",
        reason="Aktif model ajanlara atanabilir.",
        preview={"new_head": f"Son karşılaştırma ({last.get('agent')}): aday {last['summary']['candidate']['ok']}/"
                             f"{last['summary']['candidate']['cases']} — mevcut {last['summary']['current']['ok']}/"
                             f"{last['summary']['current']['cases']}"},
        undo=f"data/models.local.yaml içinde {key} için status: candidate yap", requested_by=requested_by))


# ---------------------------------------------------------------------------- yürütücüler (onaylanınca çalışır)


def _exec_load(rt: "Runtime", params: dict[str, Any], unload: bool) -> dict[str, Any]:
    if unload:
        rt.llm.unload_model(params["name"], embedding=params.get("embedding", False))
    else:
        rt.llm.load_model(params["name"], embedding=params.get("embedding", False))
    rt.store.emit("model.unloaded" if unload else "model.loaded", {"name": params["name"]})
    return {"name": params["name"], "loaded": not unload}


def _exec_agent_model(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    from ..agents.lifecycle import overrides_path, read_overrides, sync_agents, user_agents_dir

    agent, key = params["agent"], params["model_key"]
    if agent in rt.workers.user_names:
        p = user_agents_dir(rt) / f"{agent}.yaml"
        raw = p.read_text(encoding="utf-8")
        head = "".join(line + "\n" for line in raw.splitlines() if line.startswith("#"))
        data = yaml.safe_load(raw) or {}
        data["local_model"] = key
        _write_yaml(p, data, head)
    else:
        ov = read_overrides(rt)
        original = rt.workers.base_definitions.get(agent)
        if original is not None and original.local_model == key:
            ov.pop(agent, None)  # dosyadaki modele dönüş: geçersiz kılma gereksiz
        else:
            ov[agent] = {"local_model": key}
        _write_yaml(overrides_path(rt), ov, OVERRIDE_HEADER)
    sync_agents(rt)
    rt.store.emit("agent.model_changed", {"name": agent, "model_key": key})
    return {"agent": agent, "model_key": key}


def _add_local_model(rt: "Runtime", key: str, entry: dict[str, Any]) -> None:
    p = local_registry_path(rt.settings)
    data = _read_yaml(p)
    models = data.setdefault("models", {})
    models[key] = {**models.get(key, {}), **entry}
    _write_yaml(p, data, LOCAL_HEADER)
    from ..agents.lifecycle import sync_agents

    sync_agents(rt)


def _run_pull(rt: "Runtime", name: str) -> dict[str, Any]:
    state = {"status": "başlıyor", "completed": 0, "total": 0, "error": None, "started": time.time()}
    with _PULLS_LOCK:
        _PULLS[name] = state
    last_pct = -10.0

    def progress(ev: dict[str, Any]) -> None:
        nonlocal last_pct
        state["status"] = ev.get("status", state["status"])
        if ev.get("total"):
            state["total"], state["completed"] = ev["total"], ev.get("completed", 0)
            pct = 100 * state["completed"] / state["total"]
            if pct - last_pct >= 5:
                last_pct = pct
                rt.store.emit("model.pull", {"name": name, "status": state["status"], "percent": round(pct, 1)})

    try:
        rt.llm.pull_model(name, progress)
    except OllamaError as exc:
        state["status"], state["error"] = "hata", str(exc)
        rt.store.emit("model.pull", {"name": name, "status": "hata", "error": str(exc)[:200]})
        return {"name": name, "error": str(exc)}
    inst = _match(name, rt.llm.list_models()) or {}
    key = rt.registry.key_for_name(name) or model_key_slug(name)
    if key not in rt.registry.models:
        _add_local_model(rt, key, {"name": name, "purpose": "Sonradan indirildi (aday — karşılaştırma bekliyor)",
                                   "keep_alive": "10m", "approx_vram_gb": _gb(inst.get("size")), "license": "kontrol et",
                                   "status": "candidate", **_think_policy(rt, name)})
    state["status"] = "tamamlandı"
    rt.store.emit("model.pull", {"name": name, "status": "tamamlandı", "percent": 100, "key": key})
    return {"name": name, "key": key}


def _exec_pull(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    name = params["name"]
    if getattr(rt, "background_ok", False):  # API: onay isteği beklemesin, indirme arka planda sürsün
        threading.Thread(target=_run_pull, args=(rt, name), name=f"kayaai-pull-{name}", daemon=True).start()
        return {"name": name, "started": True}
    out = _run_pull(rt, name)  # CLI: süreç bitmeden tamamlansın
    if out.get("error"):
        raise ModelAdminError(f"İndirilemedi: {out['error']}")
    return out


def _exec_activate(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    key = params["key"]
    spec = rt.registry.get(key)
    _add_local_model(rt, key, {"name": spec.name, "status": "active"})
    rt.store.emit("model.activated", {"key": key, "name": spec.name})
    return {"key": key, "status": "active"}


def executors(rt: "Runtime") -> dict[str, Any]:
    return {
        "model.load": lambda p: _exec_load(rt, p, unload=False),
        "model.unload": lambda p: _exec_load(rt, p, unload=True),
        "agent.model": lambda p: _exec_agent_model(rt, p),
        "model.pull": lambda p: _exec_pull(rt, p),
        "model.activate": lambda p: _exec_activate(rt, p),
    }


def pull_states() -> list[dict[str, Any]]:
    with _PULLS_LOCK:
        return [dict(v, name=k) for k, v in _PULLS.items()]
