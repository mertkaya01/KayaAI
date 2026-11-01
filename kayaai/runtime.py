"""Çalışma zamanı bileşenlerini bir araya getirir (CLI, smoke testleri ve ileride API/MCP için)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings, load_settings
from .core.claude_mode import ClaudeMode
from .core.disputes import DisputeBook
from .core.permissions import PermissionEngine
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
    claude: ClaudeMode | None = None
    recovered_task_ids: list[str] = field(default_factory=list)
    permissions: PermissionEngine | None = None
    files: "FileTools | None" = None  # noqa: F821 - aşağıda import edilir
    disputes: DisputeBook | None = None
    memory: "Memory | None" = None  # noqa: F821 - Adım 9
    # API sunucusu: uzun işler (model indirme, karşılaştırma) arka planda sürer; CLI'da süreç bitene kadar beklenir.
    background_ok: bool = False

    def close(self) -> None:
        if self.memory is not None:
            self.memory.close()
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
    registry = ModelRegistry.load_for(settings)
    llm = llm or OllamaClient(settings.ollama)
    load_user_agents = workers is None
    workers = workers or default_workers(registry, settings.config_dir / "agents")
    orch = Orchestrator(
        store, workers, llm, registry, settings.orchestrator, settings.permissions, approver=approver
    )
    from .tools.files import FileTools

    files = FileTools(settings)
    permissions = PermissionEngine(store, files.executors(), expire_hours=settings.approvals.expire_hours)
    files.engine = permissions
    rt = Runtime(
        settings, store, llm, registry, workers, orch,
        claude=ClaudeMode(store, settings.claude), recovered_task_ids=recovered,
        permissions=permissions, files=files, disputes=DisputeBook(store),
    )
    from .agents.lifecycle import exec_promote, sync_user_agents

    permissions.executors["agent.promote"] = lambda params: exec_promote(rt, params)
    from .llm.manager import executors as model_executors

    permissions.executors.update(model_executors(rt))
    from .speech import executors as speech_executors

    permissions.executors.update(speech_executors(rt))
    from .browser.agent import BrowserStepWorker
    from .browser.agent import executors as browser_executors

    permissions.executors.update(browser_executors(rt))
    from .schedule import executors as schedule_executors

    permissions.executors.update(schedule_executors(rt))
    from .llm.cloud import CloudBridge, executors as cloud_executors  # Adım 17

    permissions.executors.update(cloud_executors(rt))
    rt.orchestrator.cloud = CloudBridge(rt)
    from .integrations import executors as integration_executors

    permissions.executors.update(integration_executors(rt))
    if "browser.step" not in workers:
        workers.register(BrowserStepWorker(), internal=True)
    if load_user_agents:
        sync_user_agents(rt)  # data/agents: sonradan oluşturulan (geçici / kalıcı yapılmış) ajanlar
    from .memory import Memory
    from .memory.classify import MemoryClassifierWorker

    if "memory.classify" not in workers:
        workers.register(MemoryClassifierWorker(), internal=True)
    from .business import register_workers as register_business_workers

    register_business_workers(workers)
    rt.memory = Memory(rt)
    return rt
