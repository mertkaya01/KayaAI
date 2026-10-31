"""Ollama REST API istemcisi (senkron, httpx).

Kullanılan uç noktalar: /api/version, /api/tags, /api/ps, /api/show, /api/chat.
Bağlantı hatası, zaman aşımı ve 5xx için üstel geri çekilmeli tekrar dener; 4xx için denemez.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import OllamaSettings

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Ollama genel hata."""


class OllamaUnavailable(OllamaError):
    """Ollama servisine ulaşılamıyor (kurulu değil / çalışmıyor / zaman aşımı)."""


class OllamaModelNotFound(OllamaError):
    """İstenen model yerelde yok (ollama pull gerekir)."""


class OllamaCancelled(OllamaError):
    """İstek, iptal sinyali nedeniyle gönderilmedi."""


@dataclass
class ChatResult:
    content: str
    model: str
    thinking: str | None = None
    done_reason: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_duration_s: float = 0.0
    load_duration_s: float = 0.0
    eval_duration_s: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # Çok kısa çıktılarda (ör. 4 token) token/sn ölçümü anlamsız ve yanıltıcıdır.
    MIN_TOKENS_FOR_SPEED = 16

    @property
    def tokens_per_second(self) -> float | None:
        if self.eval_duration_s > 0 and self.output_tokens >= self.MIN_TOKENS_FOR_SPEED:
            return round(self.output_tokens / self.eval_duration_s, 2)
        return None

    def metrics(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_duration_s": round(self.total_duration_s, 3),
            "load_duration_s": round(self.load_duration_s, 3),
            "tokens_per_second": self.tokens_per_second,
            "done_reason": self.done_reason,
        }


def _ns(value: Any) -> float:
    try:
        return float(value) / 1e9
    except (TypeError, ValueError):
        return 0.0


class OllamaClient:
    def __init__(self, settings: OllamaSettings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or OllamaSettings()
        if not self.settings.is_local:
            log.warning(
                "Ollama adresi yerel değil (%s). Verileriniz bu bilgisayardan çıkabilir.", self.settings.base_url
            )
        timeout = httpx.Timeout(self.settings.request_timeout_s, connect=self.settings.connect_timeout_s)
        # trust_env=False: sistem proxy'si localhost isteklerini bozmasın.
        self._http = httpx.Client(
            base_url=self.settings.base_url, timeout=timeout, transport=transport, trust_env=False
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ düşük seviye

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        attempts = self.settings.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise OllamaCancelled("istek iptal edildi")
            try:
                kwargs: dict[str, Any] = {"json": json}
                if timeout is not None:
                    kwargs["timeout"] = httpx.Timeout(timeout, connect=self.settings.connect_timeout_s)
                resp = self._http.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                    httpx.RemoteProtocolError, httpx.WriteError, httpx.ReadError) as exc:
                last_exc = exc
                log.warning("Ollama %s %s başarısız (deneme %d/%d): %s", method, path, attempt, attempts, exc)
            else:
                if resp.status_code < 400:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise OllamaError(f"Ollama geçersiz JSON döndürdü: {resp.text[:200]}") from exc
                message = _error_message(resp)
                if resp.status_code == 404 and "not found" in message.lower():
                    raise OllamaModelNotFound(message)
                if resp.status_code < 500:
                    raise OllamaError(f"HTTP {resp.status_code}: {message}")
                last_exc = OllamaError(f"HTTP {resp.status_code}: {message}")
                log.warning("Ollama %s %s HTTP %d (deneme %d/%d)", method, path, resp.status_code, attempt, attempts)
            if attempt < attempts:
                delay = self.settings.retry_backoff_s * (2 ** (attempt - 1))
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise OllamaCancelled("istek iptal edildi")
                else:
                    time.sleep(delay)

        if isinstance(last_exc, OllamaError):
            raise last_exc
        raise OllamaUnavailable(
            f"Ollama'ya ulaşılamadı ({self.settings.base_url}). Ollama çalışıyor mu? Ayrıntı: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------ API

    def version(self) -> str:
        return str(self._request("GET", "/api/version").get("version", ""))

    def is_available(self) -> bool:
        try:
            self.version()
            return True
        except OllamaError:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/api/tags").get("models", []))

    def running_models(self) -> list[dict[str, Any]]:
        """Şu an belleğe yüklü modeller (size_vram alanı VRAM kullanımını verir)."""
        return list(self._request("GET", "/api/ps").get("models", []))

    def show(self, model: str) -> dict[str, Any]:
        return self._request("POST", "/api/show", json={"model": model})

    def has_model(self, model: str) -> bool:
        installed = self.list_models()
        names = {m.get("name") for m in installed} | {m.get("model") for m in installed}
        if model in names:
            return True
        # "qwen3" ile "qwen3:latest" eşdeğerdir.
        return ":" not in model and f"{model}:latest" in names

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        format: str | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        keep_alive: str | int | None = None,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ChatResult:
        """Tek seferlik (stream=false) sohbet isteği.

        format: None, "json" veya JSON Schema sözlüğü (Ollama structured outputs).
        """
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if format is not None:
            payload["format"] = format
        if options:
            payload["options"] = options
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        data = self._request("POST", "/api/chat", json=payload, timeout=timeout, cancel_event=cancel_event)
        msg = data.get("message") or {}
        if "content" not in msg:
            raise OllamaError(f"Beklenmeyen /api/chat yanıtı: {str(data)[:300]}")
        return ChatResult(
            content=msg.get("content", ""),
            thinking=msg.get("thinking"),
            model=data.get("model", model),
            done_reason=data.get("done_reason"),
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            total_duration_s=_ns(data.get("total_duration")),
            load_duration_s=_ns(data.get("load_duration")),
            eval_duration_s=_ns(data.get("eval_duration")),
            raw=data,
        )


    def embed(self, model: str, inputs: list[str], *, keep_alive: str | int | None = None,
              timeout: float | None = None) -> list[list[float]]:
        """Metinlerin vektörleri (POST /api/embed). Hafıza ve belge araması için (Adım 9) — tamamen yerel."""
        if not inputs:
            return []
        payload: dict[str, Any] = {"model": model, "input": inputs}
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        data = self._request("POST", "/api/embed", json=payload, timeout=timeout)
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(inputs):
            raise OllamaError(f"Beklenmeyen /api/embed yanıtı: {str(data)[:200]}")
        return vectors


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
    except ValueError:
        pass
    return resp.text[:300]
