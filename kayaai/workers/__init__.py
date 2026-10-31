"""Worker kayıt defteri."""

from __future__ import annotations

from .base import LLMWorker, Worker, WorkerCancelled, WorkerContext, WorkerError, WorkerOutputInvalid
from .general import GeneralAnswer, GeneralWorker


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def register(self, worker: Worker) -> None:
        if worker.name in self._workers:
            raise ValueError(f"Worker zaten kayıtlı: {worker.name}")
        self._workers[worker.name] = worker

    def get(self, name: str) -> Worker:
        try:
            return self._workers[name]
        except KeyError:
            raise KeyError(f"Bilinmeyen worker: {name}. Kayıtlı: {', '.join(self._workers)}") from None

    def names(self) -> list[str]:
        return list(self._workers)

    def __contains__(self, name: str) -> bool:
        return name in self._workers


def default_workers() -> WorkerRegistry:
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
