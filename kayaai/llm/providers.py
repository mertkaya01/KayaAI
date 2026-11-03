"""Dış LLM sağlayıcıları (Adım 20; ilke değişikliği, sahip kararı 2026-11-02 — Adım 17'deki bulut köprüsünün
genişletilmiş hâli).

Sahip kararları:
1. **Ne gider:** yalnız mesaj, sohbet geçmişi ve o mesajda eklenen dosya metni. Hafıza, belge arama sonuçları, ekran
   görüntüleri, bilgisayar ölçümü ASLA (veri kapısı `outbound_input`). Gizli bilgi (parola, anahtar, kart, IBAN…)
   görülen istek gönderilmez, yerelde yapılır.
2. **Ne zaman:** yalnız sahip seçince — mesaj başına ☁ ya da bir ajanı dış modele atayınca (Adım 20b). "Yerel
   başaramazsa otomatik dışarı" YOK.
3. **Anahtar:** Windows Kimlik Bilgisi Yöneticisi (`secretstore`); bir kez girilir, bir daha gösterilmez.
4. **İnternet sağlayıcıları (Groq gibi) olur**, ama her sağlayıcı ayrı ayrı sahip onayıyla açılır (R2, önizlemede
   neyin gidip neyin gitmediği); kapatmak R1. Adresi değişen sağlayıcı kendiliğinden kapanır (yeniden onay gerekir).

Hepsi OpenAI uyumlu (`/v1/models`, `/v1/chat/completions`). Bağlantı testi yalnız model listesini ister; senin
verin gitmez. Her çağrı `provider.call` olayına METİNSİZ yazılır; günlük sınır; hata/kota/sınırda yerel model.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from ..config import LOCAL_HOSTS
from ..core.permissions import Risk, SubmitResult, ToolAction
from .ollama_client import ChatResult
from .secretstore import ID_RE, SecretStore, SecretStoreError

if TYPE_CHECKING:
    from ..runtime import Runtime

META_KEY = "providers"
# Dışarı ASLA gitmeyen girdi alanları (iç içe 'context' dahil her düzeyde çıkarılır)
PRIVATE_INPUT_KEYS = ("memory", "documents", "_images", "images", "recall", "this_computer")

PRESETS: dict[str, dict[str, str]] = {
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1",
             "note": "Hızlı, ücretsiz katmanı var (dakika/gün sınırlı). Anahtar: console.groq.com → API Keys"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "note": "Birçok sağlayıcının modeli tek anahtarla; bazı modeller ücretsiz. Anahtar: openrouter.ai → Keys"},
    "omniroute": {"label": "OmniRoute", "base_url": "http://127.0.0.1:20128/v1",
                  "note": "Bu bilgisayarda çalışan ağ geçidi; sağlayıcı anahtarları onda kalır"},
    "custom": {"label": "Özel (OpenAI uyumlu)", "base_url": "",
               "note": "OpenAI uyumlu herhangi bir adres (internet adresi https olmalı)"},
}


class ProviderError(RuntimeError):
    pass


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


class Provider(BaseModel):
    id: str
    preset: str = "custom"
    label: str
    base_url: str
    enabled: bool = False
    default_model: str = ""
    models: list[str] = Field(default_factory=list)   # son bağlantı testinden
    daily_limit: int = Field(200, ge=1, le=100_000)
    timeout_s: float = Field(90, ge=5, le=600)
    json_mode: bool = True                              # response_format=json_object (desteklemiyorsa bir kez onsuz)
    tested_at: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("kimlik küçük harf, rakam, - ya da _ olmalı (en çok 32)")
        return v

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 60:
            raise ValueError("ad gerekli (en çok 60 karakter)")
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        u = urlparse(v)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("adres http(s)://… biçiminde olmalı")
        if u.scheme == "http" and u.hostname not in LOCAL_HOSTS:
            raise ValueError("internet adresi https olmalı (http yalnız bu bilgisayar için: 127.0.0.1 / localhost)")
        if u.username or u.password:
            raise ValueError("adreste kullanıcı adı/parola olamaz; anahtarı ayrıca gir")
        return v

    @field_validator("default_model")
    @classmethod
    def _model(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 160:
            raise ValueError("model adı çok uzun")
        return v

    @property
    def internet(self) -> bool:
        return not is_local(self.base_url)


# ---------------------------------------------------------------- kayıt (SQLite meta)

_lock = threading.Lock()


def _load(rt: "Runtime") -> dict[str, Provider]:
    raw = rt.store.get_meta(META_KEY)
    out: dict[str, Provider] = {}
    for item in (json.loads(raw) if raw else []):
        try:
            p = Provider.model_validate(item)
            out[p.id] = p
        except ValueError:
            continue  # bozuk kayıt atlanır (asla açık sayılmaz)
    return out


def _save(rt: "Runtime", items: dict[str, Provider]) -> None:
    rt.store.set_meta(META_KEY, json.dumps([p.model_dump() for p in items.values()], ensure_ascii=False))


def list_providers(rt: "Runtime") -> list[Provider]:
    return list(_load(rt).values())


def get_provider(rt: "Runtime", provider_id: str) -> Provider:
    p = _load(rt).get(provider_id)
    if p is None:
        raise ProviderError(f"Sağlayıcı yok: {provider_id}")
    return p


def add_provider(rt: "Runtime", preset: str, *, label: str | None = None, base_url: str | None = None,
                 daily_limit: int | None = None, provider_id: str | None = None) -> Provider:
    if preset not in PRESETS:
        raise ProviderError(f"Bilinmeyen hazır ayar: {preset}")
    with _lock:
        items = _load(rt)
        pid = provider_id or (preset if preset != "custom" else _slug(label or "ozel"))
        base = pid
        n = 2
        while pid in items:
            pid = f"{base}-{n}"
            n += 1
        p = Provider(id=pid, preset=preset, label=label or PRESETS[preset]["label"],
                     base_url=base_url or PRESETS[preset]["base_url"],
                     **({"daily_limit": daily_limit} if daily_limit else {}))
        items[p.id] = p
        _save(rt, items)
    rt.store.emit("provider.added", {"id": p.id, "label": p.label, "internet": p.internet})
    return p


def update_provider(rt: "Runtime", provider_id: str, **changes: Any) -> Provider:
    allowed = {"label", "base_url", "daily_limit", "default_model", "timeout_s", "json_mode"}
    bad = set(changes) - allowed
    if bad:
        raise ProviderError(f"Değiştirilemez alan: {', '.join(sorted(bad))}")
    with _lock:
        items = _load(rt)
        old = items.get(provider_id)
        if old is None:
            raise ProviderError(f"Sağlayıcı yok: {provider_id}")
        new = Provider.model_validate({**old.model_dump(), **{k: v for k, v in changes.items() if v is not None}})
        moved = new.base_url != old.base_url
        if moved:  # onay o adres içindi: yeni adres yeniden onay ister
            new.enabled, new.models, new.tested_at = False, [], None
        items[provider_id] = new
        _save(rt, items)
    if moved and old.enabled:
        rt.store.emit("provider.disabled", {"id": provider_id, "reason": "adres değişti"})
    return new


def remove_provider(rt: "Runtime", provider_id: str) -> None:
    with _lock:
        items = _load(rt)
        if items.pop(provider_id, None) is None:
            raise ProviderError(f"Sağlayıcı yok: {provider_id}")
        _save(rt, items)
    try:
        secrets(rt).delete(provider_id)
    except SecretStoreError:
        pass
    with _lock:  # bu sağlayıcıya atanmış ajanlar yerele döner
        data = assignments(rt)
        kept = {k: v for k, v in data.items() if v.get("provider") != provider_id}
        if kept != data:
            _save_assignments(rt, kept)
    rt.store.emit("provider.removed", {"id": provider_id})


def _slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = re.sub(r"[^a-z0-9]+", "-", text.translate(tr).lower()).strip("-")[:32]
    return s or "ozel"


# ---------------------------------------------------------------- anahtarlar

def secrets(rt: "Runtime") -> SecretStore:
    if rt.secret_store is None:
        rt.secret_store = SecretStore(rt.settings.data_dir)
    return rt.secret_store


def save_key(rt: "Runtime", provider_id: str, key: str) -> None:
    get_provider(rt, provider_id)
    secrets(rt).set(provider_id, key)
    rt.store.emit("provider.key_saved", {"id": provider_id})  # anahtarın kendisi ASLA olaya yazılmaz


def delete_key(rt: "Runtime", provider_id: str) -> None:
    get_provider(rt, provider_id)
    secrets(rt).delete(provider_id)
    rt.store.emit("provider.key_deleted", {"id": provider_id})


# ---------------------------------------------------------------- kullanım sayacı

_count_lock = threading.Lock()


def used_today(rt: "Runtime", provider_id: str, today: date | None = None) -> int:
    return int(rt.store.get_meta(f"provider_count:{provider_id}:{(today or date.today()).isoformat()}") or 0)


def _count(rt: "Runtime", provider_id: str) -> int:
    with _count_lock:
        k = f"provider_count:{provider_id}:{date.today().isoformat()}"
        n = int(rt.store.get_meta(k) or 0) + 1
        rt.store.set_meta(k, str(n))
        return n


def status(rt: "Runtime") -> dict[str, Any]:
    st = secrets(rt)
    rows = []
    for p in list_providers(rt):
        try:
            source = st.source(p.id)
        except SecretStoreError as exc:
            source = f"okunamadı: {exc}"
        rows.append({**p.model_dump(), "internet": p.internet, "has_key": source in ("env", "store"),
                     "key_source": source, "used_today": used_today(rt, p.id),
                     "pending_approval": _pending(rt, p.id)})
    return {"providers": rows, "presets": [{"preset": k, **v} for k, v in PRESETS.items()],
            "key_backend": st.backend_name, "assignments": assignments(rt), "pending_assign": _pending_assign(rt)}


def _pending_assign(rt: "Runtime") -> dict[str, str]:
    assert rt.permissions is not None
    return {str(a.action.params.get("agent")): a.id for a in rt.permissions.list_approvals("pending")
            if a.action.tool == "provider.assign"}


def _pending(rt: "Runtime", provider_id: str) -> str | None:
    assert rt.permissions is not None
    for a in rt.permissions.list_approvals("pending"):
        if a.action.tool == "provider.enable" and a.action.params.get("id") == provider_id:
            return a.id
    return None


# ---------------------------------------------------------------- aç (R2) / kapat (R1)

WHAT_GOES = "Gider: yazdığın mesaj, sohbet geçmişi, o mesajda eklediğin dosya metni."
NEVER_GOES = ("Asla gitmez: hafızan, belge arama sonuçları, ekran görüntüleri, bilgisayar ölçümü; gizli bilgi "
              "(parola, anahtar, kart, IBAN…) görülen istek gönderilmez, yerelde yapılır.")


def request_enable(rt: "Runtime", provider_id: str, requested_by: str = "user") -> SubmitResult:
    p = get_provider(rt, provider_id)
    if p.enabled:
        raise ProviderError("Sağlayıcı zaten açık")
    if not secrets(rt).get(p.id) and p.internet:
        raise ProviderError("Önce anahtarı gir (Anahtar)")
    where = "İNTERNET üzerinden, başka bir şirketin sunucusuna" if p.internet else "bu bilgisayardaki ağ geçidine"
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="provider.enable", params={"id": p.id, "base_url": p.base_url}, risk=Risk.R2,
        summary=f"Dış sağlayıcıyı aç: {p.label} ({p.base_url})",
        reason=f"Açarsan, yalnız senin seçtiğin isteklerde metin {where} gider.",
        preview={"new_head": (
            f"Sağlayıcı: {p.label}\nAdres: {p.base_url} ({'internet' if p.internet else 'yalnız bu bilgisayar'})\n"
            f"Günlük sınır: {p.daily_limit} çağrı\n\n"
            "Yalnız sen bir mesajda ☁ ile bu sağlayıcıyı seçersen ya da bir ajanı ona atarsan (ayrı onay) kullanılır.\n"
            f"{WHAT_GOES}\n{NEVER_GOES}\nHata, kota ya da sınırda iş yerel modelle yapılır.")},
        undo=f"kayaai providers disable {p.id}", requested_by=requested_by))


def request_disable(rt: "Runtime", provider_id: str, requested_by: str = "user") -> SubmitResult:
    p = get_provider(rt, provider_id)
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(tool="provider.disable", params={"id": p.id}, risk=Risk.R1,
                                            summary=f"Dış sağlayıcıyı kapat: {p.label}", requested_by=requested_by))


def executors(rt: "Runtime") -> dict[str, Any]:
    def enable(params: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            items = _load(rt)
            p = items.get(str(params.get("id")))
            if p is None:
                raise ProviderError("sağlayıcı silinmiş")
            if p.base_url != params.get("base_url"):
                raise ProviderError("onaydan sonra adres değişmiş; yeniden aç")
            p.enabled = True
            _save(rt, items)
        rt.store.emit("provider.enabled", {"id": p.id, "label": p.label, "internet": p.internet})
        return {"enabled": True, "id": p.id}

    def disable(params: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            items = _load(rt)
            p = items.get(str(params.get("id")))
            if p is None:
                return {"enabled": False}
            p.enabled = False
            _save(rt, items)
        rt.store.emit("provider.disabled", {"id": p.id})
        return {"enabled": False, "id": p.id}

    return {"provider.enable": enable, "provider.disable": disable, **_assign_executors(rt)}


# ---------------------------------------------------------------- istemci (OpenAI uyumlu)


def _client(p: Provider, key: str | None, timeout: float, transport: httpx.BaseTransport | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if p.preset == "openrouter":
        headers.update({"HTTP-Referer": "https://kayaai.local", "X-Title": "kayaAI"})
    return httpx.Client(base_url=p.base_url, timeout=timeout, transport=transport, headers=headers,
                        follow_redirects=False)


def _http_error(p: Provider, r: httpx.Response) -> ProviderError:
    msg = r.text[:200]
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or msg
    except ValueError:
        pass
    hint = {401: " (anahtar yanlış ya da süresi dolmuş)", 403: " (yetki yok)", 404: " (adres ya da model yanlış)",
            429: " (kota/sınır doldu, biraz sonra dene)"}.get(r.status_code, "")
    return ProviderError(f"{p.label} HTTP {r.status_code}{hint}: {str(msg)[:200]}")


NOT_CHAT = ("whisper", "tts", "guard", "embed", "playai", "distil", "moderation", "audio", "transcribe", "image", "vision-")
PREFERRED = ("llama-3.3-70b", "gpt-oss-120b", "qwen3-32b", "kimi-k2", "gpt-oss", "qwen3", "llama-4", "llama-3.1-70b",
             "mistral", "gemma", "llama", "qwen", "auto")


def pick_default_model(models: list[str]) -> str:
    """Bağlantı testinden sonra varsayılan: sohbet modeli (ses/koruma/gömme modelleri değil), bilinen iyi modeller önce."""
    chat = [m for m in models if not any(k in m.lower() for k in NOT_CHAT)] or models
    for pref in PREFERRED:
        for m in chat:
            if pref in m.lower():
                return m
    return chat[0]


def test_connection(rt: "Runtime", provider_id: str, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Model listesini ister (GET /models). Senin hiçbir verin gitmez; yalnız anahtar doğrulanır."""
    p = get_provider(rt, provider_id)
    key = secrets(rt).get(p.id)
    if p.internet and not key:
        return {"ok": False, "error": "anahtar yok"}
    t0 = time.monotonic()
    try:
        with _client(p, key, 20, transport) as c:
            r = c.get("/models")
            if r.status_code >= 400:
                raise _http_error(p, r)
            data = r.json()
        models = sorted({str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")})
    except (httpx.HTTPError, ValueError, ProviderError) as exc:
        rt.store.emit("provider.test", {"id": p.id, "ok": False, "error": str(exc)[:200]})
        return {"ok": False, "error": str(exc)[:300], "ms": int((time.monotonic() - t0) * 1000)}
    with _lock:
        items = _load(rt)
        if p.id in items:
            items[p.id].models = models[:500]
            items[p.id].tested_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            if not items[p.id].default_model and models:
                items[p.id].default_model = pick_default_model(models)
            _save(rt, items)
    ms = int((time.monotonic() - t0) * 1000)
    rt.store.emit("provider.test", {"id": p.id, "ok": True, "models": len(models), "ms": ms})
    return {"ok": True, "models": models, "ms": ms}


# ---------------------------------------------------------------- veri kapısı


def outbound_input(data: dict[str, Any] | None) -> dict[str, Any]:
    """Dışarı gidecek görev girdisi: hafıza, belge parçaları, görüntüler, bilgisayar ölçümü çıkarılır (her düzeyde)."""
    def clean(d: Any) -> Any:
        if isinstance(d, dict):
            return {k: clean(v) for k, v in d.items() if k not in PRIVATE_INPUT_KEYS}
        if isinstance(d, list):
            return [clean(x) for x in d]
        return d
    return clean(dict(data or {}))


def secret_findings(messages: list[dict[str, Any]]) -> list[str]:
    from ..memory.secrets import detect_secrets

    return detect_secrets("\n".join(str(m.get("content", "")) for m in messages))


def call(rt: "Runtime", provider_id: str, model: str, messages: list[dict[str, Any]], *, agent: str,
         timeout: float | None = None, transport: httpx.BaseTransport | None = None) -> ChatResult:
    """Tek sohbet çağrısı (JSON çıktı). Kurallar burada da denetlenir: açık mı, sınır, gizli bilgi. Hata → ProviderError
    (çağıran yerel modele düşer). Olay METİNSİZ: sağlayıcı, model, ajan, karakter sayıları, süre."""
    p = get_provider(rt, provider_id)
    if not p.enabled:
        raise ProviderError(f"{p.label} kapalı")
    if used_today(rt, p.id) >= p.daily_limit:
        raise ProviderError(f"{p.label} günlük sınırı doldu ({p.daily_limit})")
    found = secret_findings(messages)
    if found:
        rt.store.emit("provider.blocked", {"id": p.id, "agent": agent, "reason": f"gizli bilgi: {', '.join(found)}"})
        raise ProviderError(f"gizli bilgi görüldü ({', '.join(found)}); istek dışarı gönderilmedi")
    key = secrets(rt).get(p.id)
    if p.internet and not key:
        raise ProviderError(f"{p.label} anahtarı yok")
    model = (model or p.default_model).strip()
    if not model:
        raise ProviderError(f"{p.label} için model seçilmedi (Bağlantıyı dene → model)")
    body: dict[str, Any] = {"model": model, "stream": False,
                            "messages": [{"role": m["role"], "content": m.get("content", "")} for m in messages]}
    if p.json_mode:
        body["response_format"] = {"type": "json_object"}
    chars_out = sum(len(str(m.get("content", ""))) for m in messages)
    t0 = time.monotonic()
    _count(rt, p.id)
    try:
        with _client(p, key, timeout or p.timeout_s, transport) as c:
            r = c.post("/chat/completions", json=body)
            if r.status_code == 400 and "response_format" in body and "response_format" in r.text:
                body.pop("response_format")  # bu model JSON kipini desteklemiyor: şema talimatı yine mesajda
                r = c.post("/chat/completions", json=body)
            if r.status_code >= 400:
                raise _http_error(p, r)
            data = r.json()
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            raise ProviderError(f"{p.label} boş cevap döndürdü")
    except (httpx.HTTPError, ValueError, ProviderError) as exc:
        rt.store.emit("provider.call", {"id": p.id, "model": model, "agent": agent, "ok": False, "chars_out": chars_out,
                                        "ms": int((time.monotonic() - t0) * 1000), "error": str(exc)[:200]})
        raise exc if isinstance(exc, ProviderError) else ProviderError(f"{p.label}: {exc}") from exc
    ms = int((time.monotonic() - t0) * 1000)
    usage = data.get("usage") or {}
    rt.store.emit("provider.call", {"id": p.id, "model": model, "agent": agent, "ok": True, "chars_out": chars_out,
                                    "chars_in": len(content), "ms": ms})
    return ChatResult(content=content, model=f"☁ {p.label}/{model}", done_reason=choice.get("finish_reason"),
                      prompt_tokens=int(usage.get("prompt_tokens") or 0),
                      output_tokens=int(usage.get("completion_tokens") or 0),
                      total_duration_s=ms / 1000, eval_duration_s=ms / 1000, raw={})


# ---------------------------------------------------------------- ajan ataması (Adım 20b; atamak R2, kaldırmak R1)

ASSIGN_KEY = "provider_agents"
NEVER_OUT_AGENTS = {"vision"}  # görüntülerle çalışır: hiçbir zaman dışarı gitmez


def assignments(rt: "Runtime") -> dict[str, dict[str, str]]:
    raw = rt.store.get_meta(ASSIGN_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("provider")}


def _save_assignments(rt: "Runtime", data: dict[str, dict[str, str]]) -> None:
    rt.store.set_meta(ASSIGN_KEY, json.dumps(data, ensure_ascii=False))


def request_assign(rt: "Runtime", agent: str, provider_id: str, model: str = "", requested_by: str = "user") -> SubmitResult:
    if agent not in rt.workers.names() or "." in agent:
        raise ProviderError(f"Bilinmeyen ajan: {agent}")
    if agent in NEVER_OUT_AGENTS:
        raise ProviderError("Görsel ajan dış sağlayıcıya verilemez (ekran görüntüleri bilgisayardan çıkmaz)")
    p = get_provider(rt, provider_id)
    if not p.enabled:
        raise ProviderError(f"{p.label} kapalı; önce Bağlantılar → Dış sağlayıcılar'dan aç")
    model = (model or p.default_model).strip()
    if not model:
        raise ProviderError(f"{p.label} için model yok (Bağlantıyı dene)")
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="provider.assign", params={"agent": agent, "provider": p.id, "model": model, "base_url": p.base_url},
        risk=Risk.R2, summary=f"{agent} ajanını dış modele ata: {p.label}/{model}",
        reason=(f"Bundan sonra {agent} ajanının BÜTÜN işleri (zamanlanmış görevler dahil) "
                f"{'internet üzerinden ' if p.internet else ''}{p.label} sağlayıcısına gider."),
        preview={"new_head": (
            f"Ajan: {agent}\nSağlayıcı: {p.label} ({p.base_url})\nModel: {model}\n\n"
            f"{WHAT_GOES}\n{NEVER_GOES}\nHata, kota ya da günlük sınırda yerel model yapar. Geri almak: Modeller → Yerel.")},
        undo=f"Modeller → {agent} → Yerel", requested_by=requested_by))


def request_unassign(rt: "Runtime", agent: str, requested_by: str = "user") -> SubmitResult:
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(tool="provider.unassign", params={"agent": agent}, risk=Risk.R1,
                                            summary=f"{agent} ajanını yerel modele geri al", requested_by=requested_by))


def _assign_executors(rt: "Runtime") -> dict[str, Any]:
    def assign(params: dict[str, Any]) -> dict[str, Any]:
        p = get_provider(rt, str(params["provider"]))
        if not p.enabled or p.base_url != params.get("base_url"):
            raise ProviderError("sağlayıcı kapanmış ya da adresi değişmiş; yeniden ata")
        with _lock:
            data = assignments(rt)
            data[str(params["agent"])] = {"provider": p.id, "model": str(params["model"])}
            _save_assignments(rt, data)
        rt.store.emit("provider.assigned", {"agent": params["agent"], "id": p.id, "model": params["model"]})
        return {"agent": params["agent"], "provider": p.id, "model": params["model"]}

    def unassign(params: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            data = assignments(rt)
            data.pop(str(params["agent"]), None)
            _save_assignments(rt, data)
        rt.store.emit("provider.unassigned", {"agent": params["agent"]})
        return {"agent": params["agent"], "provider": None}

    return {"provider.assign": assign, "provider.unassign": unassign}


# ---------------------------------------------------------------- yönlendirme: bu iş dışarı mı gidecek?


class Outbound:
    """İşçilere verilen yardımcı. Karar sırası: mesajdaki ☁ seçimi (`_cloud`) > ajan ataması > yerel.
    Her çağrıda ayarlar yeniden okunur (başka süreç değiştirmiş olabilir)."""

    def __init__(self, rt: "Runtime", transport: httpx.BaseTransport | None = None):
        self.rt = rt
        self.transport = transport

    def route(self, agent: str, task: Any) -> tuple[dict[str, str] | None, str | None]:
        """(yol, neden): yol None ise yerel; neden doluysa dışarı istenmişti ama gitmeyecek (kullanıcıya söylenir)."""
        data = task.input or {}
        base = agent.split(".")[0]
        choice, source = data.get("_cloud"), "message"
        if not isinstance(choice, dict) or not choice.get("provider"):
            choice, source = assignments(self.rt).get(base), "agent"
            if not choice:
                return None, None
        if base in NEVER_OUT_AGENTS or data.get("_images"):
            return None, "görüntü içeren iş dışarı gitmez"
        try:
            p = get_provider(self.rt, str(choice["provider"]))
        except ProviderError:
            return None, "sağlayıcı silinmiş"
        if not p.enabled:
            return None, f"{p.label} kapalı"
        if used_today(self.rt, p.id) >= p.daily_limit:
            return None, f"{p.label} günlük sınırı doldu ({p.daily_limit})"
        if p.internet and not secrets(self.rt).get(p.id):
            return None, f"{p.label} anahtarı yok"
        model = str(choice.get("model") or p.default_model)
        if not model:
            return None, f"{p.label} için model seçilmedi"
        return {"provider": p.id, "label": p.label, "model": model, "source": source}, None

    def chat(self, agent: str, route: dict[str, str], messages: list[dict[str, Any]], *,
             timeout: float | None = None) -> ChatResult:
        return call(self.rt, route["provider"], route["model"], messages, agent=agent, timeout=timeout,
                    transport=self.transport)
