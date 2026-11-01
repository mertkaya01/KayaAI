"""Test altyapısı: gerçek bir yerel HTTP sunucusu olarak çalışan sahte Ollama.

Bu sahte sunucu Ollama REST API biçimini taklit eder; böylece istemci, retry, JSON
doğrulama ve orkestratör mantığı gerçek HTTP üzerinden test edilir. Gerçek model
kalitesini ÖLÇMEZ - onun için scripts/smoke_ollama.py gerçek Ollama ile çalıştırılır.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from kayaai.config import OllamaSettings, OrchestratorSettings, PermissionSettings
from kayaai.core.orchestrator import Orchestrator
from kayaai.core.store import TaskStore
from kayaai.llm.ollama_client import OllamaClient
from kayaai.llm.registry import ModelRegistry
from kayaai.workers import default_workers

Handler = Callable[[dict[str, Any]], tuple[int, Any]]


def fake_embedding(text: str, dim: int = 64) -> list[float]:
    """Deterministik "anlam" vektörü: kelime köklerinin (ilk 5 harf) karma torbası. Ortak kelime → yüksek benzerlik."""
    import hashlib
    import math
    import re

    vec = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        if len(w) < 3:
            continue
        h = int(hashlib.md5(w[:5].encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class NDJSON(list):
    """Akışlı (satır satır JSON) cevap: /api/pull."""


class FakeOllama:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.chat_replies: list[Any] = []  # sırayla tüketilir: str içerik | (status, body) | callable
        self.models = [{"name": "qwen3:8b", "model": "qwen3:8b", "size": 5_200_000_000},
                       {"name": "bge-m3", "model": "bge-m3", "size": 1_200_000_000}]
        self.chat_delay_s = 0.0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def chat_paths(self) -> list[Any]:
        return [body for (m, p, body) in self.requests if p == "/api/chat"]

    # ------------------------------------------------------------------

    def _respond(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        self.requests.append((method, path, body))
        if path == "/api/version":
            return 200, {"version": "0.0.0-fake"}
        if path == "/api/tags":
            return 200, {"models": self.models}
        if path == "/api/ps":
            return 200, {"models": [{"name": n, "model": n, "size": 1_000_000_000, "size_vram": 1_000_000_000,
                                     "expires_at": "2026-10-31T23:00:00Z"} for n in getattr(self, "loaded", {})]}
        if path == "/api/generate":  # Adım 11: modeli yükle / boşalt
            if body.get("model") not in {m["name"] for m in self.models}:
                return 404, {"error": f"model \"{body.get('model')}\" not found"}
            self.loaded = getattr(self, "loaded", {})
            if body.get("keep_alive") in (0, "0"):
                self.loaded.pop(body["model"], None)
            else:
                self.loaded[body["model"]] = body.get("keep_alive")
            return 200, {"model": body["model"], "response": "", "done": True}
        if path == "/api/pull":
            name = body.get("model", "")
            if name.startswith("yok"):
                return 200, NDJSON([{"status": "pulling manifest"}, {"error": f"pull model manifest: file does not exist"}])
            self.models.append({"name": name, "model": name, "size": 2_500_000_000,
                                "details": {"family": "qwen3", "parameter_size": "4B", "quantization_level": "Q4_K_M"}})
            return 200, NDJSON([{"status": "pulling manifest"},
                                {"status": "downloading", "total": 1000, "completed": 500},
                                {"status": "downloading", "total": 1000, "completed": 1000},
                                {"status": "success"}])
        if path == "/api/show":
            if body.get("model") not in {m["name"] for m in self.models}:
                return 404, {"error": f"model '{body.get('model')}' not found"}
            caps = ["completion", "thinking"] if body["model"].startswith("qwen3") else ["completion"]
            return 200, {"capabilities": caps, "details": {}}
        if path == "/api/embed":
            if body.get("model") not in {m["name"] for m in self.models}:
                return 404, {"error": f"model \"{body.get('model')}\" not found, try pulling it first"}
            return 200, {"model": body["model"], "embeddings": [fake_embedding(t) for t in body["input"]]}
        if path == "/api/chat":
            if self.chat_delay_s:
                import time

                time.sleep(self.chat_delay_s)
            if not any(m["name"] == body.get("model") for m in self.models):
                return 404, {"error": f"model \"{body.get('model')}\" not found, try pulling it first"}
            reply = self.chat_replies.pop(0) if self.chat_replies else "{}"
            if callable(reply):
                reply = reply(body)
            if isinstance(reply, tuple):
                return reply
            if body.get("stream"):
                n = max(1, len(reply) // 4)
                parts = [reply[i:i + n] for i in range(0, len(reply), n)] or [""]
                return 200, NDJSON([{"model": body["model"], "message": {"role": "assistant", "content": p}, "done": False}
                                    for p in parts] + [{
                    "model": body["model"], "message": {"role": "assistant", "content": ""}, "done": True,
                    "done_reason": "stop", "prompt_eval_count": 20, "eval_count": 40, "eval_duration": 1_000_000_000,
                    "total_duration": 1_500_000_000, "load_duration": 100_000_000}])
            return 200, {
                "model": body["model"],
                "message": {"role": "assistant", "content": reply},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 20,
                "eval_count": 40,
                "eval_duration": 1_000_000_000,
                "total_duration": 1_500_000_000,
                "load_duration": 100_000_000,
            }
        return 404, {"error": "unknown path"}

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # sessiz
                pass

            def _send(self, status: int, body: Any) -> None:
                if isinstance(body, NDJSON):
                    data = "".join(json.dumps(x) + "\n" for x in body).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._send(*fake._respond("GET", self.path, None))

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                try:
                    self._send(*fake._respond("POST", self.path, body))
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return H


@pytest.fixture
def fake_ollama() -> Iterator[FakeOllama]:
    srv = FakeOllama().start()
    yield srv
    srv.stop()


@pytest.fixture
def ollama_settings(fake_ollama: FakeOllama) -> OllamaSettings:
    return OllamaSettings(base_url=fake_ollama.url, max_retries=1, retry_backoff_s=0.01, request_timeout_s=10)


@pytest.fixture
def client(ollama_settings: OllamaSettings) -> Iterator[OllamaClient]:
    c = OllamaClient(ollama_settings)
    yield c
    c.close()


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry.from_dict(
        {
            "models": {"general-8b": {"name": "qwen3:8b", "context_length": 4096, "think": False}},
            "workers": {"general": "general-8b"},
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TaskStore]:
    s = TaskStore(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def make_orchestrator(store: TaskStore, client: OllamaClient, registry: ModelRegistry):
    def factory(**kwargs: Any) -> Orchestrator:
        settings = kwargs.pop("settings", OrchestratorSettings(default_timeout_s=10, max_output_attempts=3))
        return Orchestrator(
            store,
            kwargs.pop("workers", default_workers()),
            client,
            registry,
            settings,
            kwargs.pop("permissions", PermissionSettings()),
            approver=kwargs.pop("approver", None),
        )

    return factory


def good_answer(answer: str = "Merhaba! Size nasıl yardımcı olabilirim?", **over: Any) -> str:
    data = {"answer": answer, "language": "tr", "task_type": "chat", "confidence": 0.9, "needs_tools": []}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)
