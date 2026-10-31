"""Worker kayıt defteri."""

from __future__ import annotations

from .base import LLMWorker, Worker, WorkerCancelled, WorkerContext, WorkerError, WorkerOutputInvalid
from .general import GeneralAnswer, GeneralWorker


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._internal: set[str] = set()
        # data/agents altından yüklenen (sonradan oluşturulmuş) ajanlar — kayaai/agents/lifecycle.py
        self.user_names: set[str] = set()
        # Repo ajanlarının dosyadaki özgün tanımları (model geçersiz kılması kaldırılınca geri dönmek için)
        self.base_definitions: dict = {}

    def register(self, worker: Worker, *, internal: bool = False) -> None:
        """internal: ajanın iç yardımcısı (ör. `coder.revise`); planlayıcıya, arayüze ve listelere görünmez."""
        if worker.name in self._workers:
            raise ValueError(f"Worker zaten kayıtlı: {worker.name}")
        self._workers[worker.name] = worker
        if internal:
            self._internal.add(worker.name)

    def get(self, name: str) -> Worker:
        try:
            return self._workers[name]
        except KeyError:
            raise KeyError(f"Bilinmeyen worker: {name}. Kayıtlı: {', '.join(self._workers)}") from None

    def names(self) -> list[str]:
        """Görünür ajan adları (iç yardımcılar hariç)."""
        return [n for n in self._workers if n not in self._internal]

    def all(self) -> list[Worker]:
        return [w for n, w in self._workers.items() if n not in self._internal]

    def internal_names(self) -> list[str]:
        return sorted(self._internal)

    def unregister(self, name: str) -> None:
        """Ajanı ve iç yardımcılarını (`<ad>.revise`, `<ad>.check`) kaldırır."""
        for n in [n for n in self._workers if n == name or n.startswith(name + ".")]:
            del self._workers[n]
            self._internal.discard(n)

    def __contains__(self, name: str) -> bool:
        return name in self._workers


def default_workers(registry=None, agents_dir=None) -> WorkerRegistry:  # noqa: ANN001
    """Ajanları config/agents/*.yaml'dan kurar. Tanım yoksa yerleşik genel worker kullanılır."""
    if registry is not None and agents_dir is not None:
        from ..agents.definitions import build_workers

        reg = build_workers(agents_dir, registry)
        if "general" not in reg:
            reg.register(GeneralWorker())
        return reg
    reg = WorkerRegistry()
    reg.register(GeneralWorker())
    return reg


__all__ = [
    "GeneralAnswer",
    "GeneralWorker",
    "LLMWorker",
    "Worker",
    "WorkerCancelled",
    "WorkerContext",
    "WorkerError",
    "WorkerOutputInvalid",
    "WorkerRegistry",
    "default_workers",
]
