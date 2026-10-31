"""Çalışma zamanı bileşenlerini bir araya getirir (CLI, smoke testleri ve ileride API/MCP için)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings, load_settings
from .core.orchestrator import Approver, Orchestrator
from .core.store import TaskStore
from .llm.ollama_client import OllamaClient
from .llm.registry import ModelRegistry
from .workers import WorkerRegistry, default_workers


@dataclass
class Runtime:
    settings: Settings
    store: TaskStore
    llm: OllamaClient
    registry: ModelRegistry
    workers: WorkerRegistry
    orchestrator: Orchestrator
    recovered_task_ids: list[str] = field(default_factory=list)

    def close(self) -> None:
        self.llm.close()
        self.store.close()

    def __enter__(self) -> "Runtime":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_runtime(
    settings: Settings | None = None,
    approver: Approver | None = None,
    llm: OllamaClient | None = None,
    workers: WorkerRegistry | None = None,
) -> Runtime:
    settings = settings or load_settings()
    store = TaskStore(settings.db_path)
    recovered = store.recover_interrupted()
    registry = ModelRegistry.load(settings.models_file)
    llm = llm or OllamaClient(settings.ollama)
    workers = workers or default_workers()
    orch = Orchestrator(
        store, workers, llm, registry, settings.orchestrator, settings.permissions, approver=approver
    )
    return Runtime(settings, store, llm, registry, workers, orch, recovered)
