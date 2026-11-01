"""Bulut köprüsü (Adım 17): OmniRoute ya da OpenAI uyumlu başka bir YEREL ağ geçidi üzerinden bulut modelleri.

İlke değişikliği (sahip kararı, 2026-11-01): "Claude dışında bulut" yalnız şu kurallarla:
- **Varsayılan kapalı.** Açmak R2 sahip onayı (önizlemede adres, model, izinli ajanlar, günlük sınır); kapatmak R1.
- **Yalnız yerel ağ geçidi**: adres 127.0.0.1 / localhost / ::1 olmalı (OmniRoute bilgisayarda çalışır; sağlayıcı
  anahtarları onda kalır). Uzak adres reddedilir.
- **İstek başına açık izin**: sohbette "☁ Bulut", zamanlanmış görevde "buluta izin ver". İzin yoksa hiçbir şey gitmez.
- **Veri kapısı**: buluta giden metinden hafıza, yerel belge parçaları ve görüntüler ÇIKARILIR; sohbet ve sahibin o istekte
  eklediği dosya metni (iş verisi) gider. Gizli bilgi algılayıcı (parola, anahtar, kart, IBAN…) bir şey bulursa istek
  gitmez, iş yerelde yapılır.
- **Sınır ve kayıt**: günlük çağrı sınırı; her çağrı `cloud.call` olayına (ajan, model, karakter sayıları, süre — METİN
  YOK). Hata, zaman aşımı, sınır → yerel modele düşülür.
- Anahtar (ağ geçidinin kendi anahtarı) `KAYAAI_CLOUD_KEY` ortam değişkeninden ya da sahibin terminalde açıkça kaydettiği
  `data/cloud.key` dosyasından okunur; API/arayüz anahtarı ne alır ne gösterir.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from ..config import LOCAL_HOSTS
from ..core.permissions import Risk, SubmitResult, ToolAction
from .ollama_client import ChatResult

if TYPE_CHECKING:
    from ..core.task import Task
    from ..runtime import Runtime

META_KEY = "cloud"
DEFAULT_URL = "http://127.0.0.1:20128/v1"   # OmniRoute varsayılanı
PRIVATE_INPUT_KEYS = ("memory", "documents", "_images", "images", "recall")
DEFAULT_AGENTS = ["general", "coder", "document", "planner", "reviewer"]


class CloudError(RuntimeError):
    pass


class CloudSettings(BaseModel):
    enabled: bool = False
    base_url: str = DEFAULT_URL
    model: str = "auto"
    agents: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENTS))
    daily_limit: int = Field(200, ge=1, le=10000)
    timeout_s: float = Field(90, ge=5, le=600)

    @field_validator("base_url")
    @classmethod
    def _local_only(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        u = urlparse(v)
        if u.scheme not in ("http", "https") or (u.hostname or "") not in LOCAL_HOSTS:
            raise ValueError("bulut köprüsü yalnız bu bilgisayardaki ağ geçidine bağlanır (127.0.0.1 / localhost)")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 120:
            raise ValueError("model adı gerekli (ör. auto, auto/fast, groq/llama-3.3-70b)")
        return v


def get_settings(rt: "Runtime") -> CloudSettings:
    raw = rt.store.get_meta(META_KEY)
    try:
        return CloudSettings.model_validate(json.loads(raw)) if raw else CloudSettings()
    except ValueError:
        return CloudSettings()


def _save(rt: "Runtime", s: CloudSettings) -> None:
    rt.store.set_meta(META_KEY, s.model_dump_json())


def key_path(rt: "Runtime") -> Path:
    return rt.settings.data_dir / "cloud.key"


def read_key(rt: "Runtime") -> str | None:
    env = os.environ.get("KAYAAI_CLOUD_KEY", "").strip()
    if env:
        return env
    p = key_path(rt)
    try:
        return p.read_text(encoding="utf-8").strip() or None if p.is_file() else None
    except OSError:
        return None


def save_key(rt: "Runtime", key: str) -> Path:
    """Yalnız CLI'dan, sahip terminalde açıkça onaylayınca çağrılır."""
    p = key_path(rt)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(key.strip(), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def usage_today(rt: "Runtime", today: date | None = None) -> int:
    raw = rt.store.get_meta(f"cloud_count:{(today or date.today()).isoformat()}")
    return int(raw or 0)


_count_lock = threading.Lock()


def _count(rt: "Runtime") -> int:
    with _count_lock:
        k = f"cloud_count:{date.today().isoformat()}"
        n = int(rt.store.get_meta(k) or 0) + 1
        rt.store.set_meta(k, str(n))
        return n


def status(rt: "Runtime") -> dict[str, Any]:
    s = get_settings(rt)
    return {**s.model_dump(), "has_key": bool(read_key(rt)), "used_today": usage_today(rt),
            "key_source": "env" if os.environ.get("KAYAAI_CLOUD_KEY") else ("file" if key_path(rt).is_file() else None)}


# ---------------------------------------------------------------- izinler (R2 aç / R1 kapat)


def request_enable(rt: "Runtime", settings: CloudSettings, requested_by: str = "user") -> SubmitResult:
    unknown = [a for a in settings.agents if a not in rt.workers.names()]
    if unknown:
        raise CloudError(f"Bilinmeyen ajan: {', '.join(unknown)}")
    if "vision" in settings.agents:
        raise CloudError("Görsel ajan buluta verilemez (ekran görüntüleri bilgisayardan çıkmaz)")
    assert rt.permissions is not None
    s = settings.model_copy(update={"enabled": True})
    return rt.permissions.submit(ToolAction(
        tool="cloud.enable", params=s.model_dump(), risk=Risk.R2,
        summary=f"Bulut köprüsünü aç: {s.model} ({s.base_url})",
        reason="İzin verdiğin isteklerde metin, bilgisayardaki ağ geçidi üzerinden bulut sağlayıcılarına gider.",
        preview={"new_head": (
            f"Ağ geçidi: {s.base_url} (yalnız bu bilgisayar)\nModel: {s.model}\nAjanlar: {', '.join(s.agents)}\n"
            f"Günlük sınır: {s.daily_limit} çağrı\n\nYalnız sen bir istekte '☁ Bulut' dersen kullanılır.\n"
            "Gider: istek, sohbet, o istekte eklediğin dosya metni.\n"
            "Asla gitmez: hafıza, yerel belge parçaları, ekran görüntüleri; gizli bilgi görülen istek (yerelde yapılır).")},
        undo="kayaai cloud disable", requested_by=requested_by))


def request_disable(rt: "Runtime", requested_by: str = "user") -> SubmitResult:
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(tool="cloud.disable", params={}, risk=Risk.R1,
                                            summary="Bulut köprüsünü kapat", requested_by=requested_by))


def executors(rt: "Runtime") -> dict[str, Any]:
    def enable(p: dict[str, Any]) -> dict[str, Any]:
        s = CloudSettings.model_validate({**p, "enabled": True})
        _save(rt, s)
        rt.store.emit("cloud.enabled", {"model": s.model, "agents": s.agents})
        return {"enabled": True}

    def disable(p: dict[str, Any]) -> dict[str, Any]:
        s = get_settings(rt)
        s.enabled = False
        _save(rt, s)
        rt.store.emit("cloud.disabled", {})
        return {"enabled": False}

    return {"cloud.enable": enable, "cloud.disable": disable}


# ---------------------------------------------------------------- veri kapısı


def cloud_input(data: dict[str, Any] | None) -> dict[str, Any]:
    """Buluta gidecek görev girdisi: hafıza, belge parçaları ve görüntüler (iç içe 'context' dahil) çıkarılır."""
    def clean(d: Any) -> Any:
        if isinstance(d, dict):
            return {k: clean(v) for k, v in d.items() if k not in PRIVATE_INPUT_KEYS}
        if isinstance(d, list):
            return [clean(x) for x in d]
        return d
    return clean(dict(data or {}))


def gate(messages: list[dict[str, Any]]) -> list[str]:
    """Gizli bilgi algılayıcı (tam kurallar). Boş liste: gidebilir."""
    from ..memory.secrets import detect_secrets

    text = "\n".join(str(m.get("content", "")) for m in messages)
    return detect_secrets(text)


class CloudBridge:
    """Orkestratörün işçilere verdiği bulut istemcisi. Her çağrıda ayarlar yeniden okunur (başka süreç değiştirmiş olabilir)."""

    def __init__(self, rt: "Runtime", transport: httpx.BaseTransport | None = None):
        self.rt = rt
        self._transport = transport

    def permits(self, agent: str, task: "Task") -> str | None:
        """None: buluta gidebilir. Aksi halde neden (yerelde yapılır)."""
        if not (task.input or {}).get("_cloud"):
            return "istekte bulut izni yok"
        s = get_settings(self.rt)
        if not s.enabled:
            return "bulut köprüsü kapalı"
        if agent.split(".")[0] not in s.agents:
            return f"{agent} ajanı buluta izinli değil"
        if (task.input or {}).get("_images"):
            return "görüntü içeren istek buluta gitmez"
        if usage_today(self.rt) >= s.daily_limit:
            return f"günlük bulut sınırı doldu ({s.daily_limit})"
        if not read_key(self.rt):
            return "ağ geçidi anahtarı yok (KAYAAI_CLOUD_KEY ya da kayaai cloud key)"
        return None

    def chat(self, agent: str, messages: list[dict[str, Any]], *, timeout: float | None = None,
             cancel_event: threading.Event | None = None) -> ChatResult:
        s = get_settings(self.rt)
        found = gate(messages)
        if found:
            self.rt.store.emit("cloud.blocked", {"agent": agent, "reason": f"gizli bilgi: {', '.join(found)}"})
            raise CloudError(f"gizli bilgi görüldü ({', '.join(found)}); istek buluta gönderilmedi")
        if cancel_event is not None and cancel_event.is_set():
            raise CloudError("iptal edildi")
        body = {"model": s.model, "messages": [{"role": m["role"], "content": m.get("content", "")} for m in messages],
                "response_format": {"type": "json_object"}, "stream": False}
        out_chars = sum(len(str(m.get("content", ""))) for m in messages)
        t0 = time.monotonic()
        _count(self.rt)
        try:
            with httpx.Client(base_url=s.base_url, timeout=timeout or s.timeout_s, transport=self._transport,
                              headers={"Authorization": f"Bearer {read_key(self.rt)}"}, follow_redirects=False) as c:
                r = c.post("/chat/completions", json=body)
                if r.status_code >= 400:
                    raise CloudError(f"ağ geçidi HTTP {r.status_code}: {r.text[:200]}")
                data = r.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            if not content:
                raise CloudError("ağ geçidi boş cevap döndürdü")
        except (httpx.HTTPError, ValueError, CloudError) as exc:
            self.rt.store.emit("cloud.call", {"agent": agent, "model": s.model, "ok": False, "chars_out": out_chars,
                                              "ms": int((time.monotonic() - t0) * 1000), "error": str(exc)[:200]})
            raise CloudError(str(exc)) from exc
        ms = int((time.monotonic() - t0) * 1000)
        usage = data.get("usage") or {}
        model = str(data.get("model") or s.model)
        self.rt.store.emit("cloud.call", {"agent": agent, "model": model, "ok": True, "chars_out": out_chars,
                                          "chars_in": len(content), "ms": ms})
        return ChatResult(content=content, model=f"☁ {model}", done_reason=choice.get("finish_reason"),
                          prompt_tokens=int(usage.get("prompt_tokens") or 0),
                          output_tokens=int(usage.get("completion_tokens") or 0),
                          total_duration_s=ms / 1000, eval_duration_s=ms / 1000, raw={})

    def models(self) -> list[str]:
        s = get_settings(self.rt)
        key = read_key(self.rt)
        if not key:
            raise CloudError("ağ geçidi anahtarı yok")
        with httpx.Client(base_url=s.base_url, timeout=15, transport=self._transport,
                          headers={"Authorization": f"Bearer {key}"}, follow_redirects=False) as c:
            r = c.get("/models")
            if r.status_code >= 400:
                raise CloudError(f"ağ geçidi HTTP {r.status_code}: {r.text[:200]}")
            return [str(m.get("id")) for m in (r.json().get("data") or []) if m.get("id")]
