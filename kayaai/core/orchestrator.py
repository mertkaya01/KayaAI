"""Çalışma zamanı orkestratörü.

Akış: submit -> (bağımlılık kontrolü) -> (izin/onay) -> çalıştır (timeout + iptal) -> doğrula -> kaydet.

Kurallar:
- Doğrulamadan geçmeyen hiçbir çıktı "succeeded" olmaz.
- auto_approve dışında izin isteyen görevler onaylayıcı (approver) olmadan çalışmaz.
- Zaman aşımı/iptal durumunda arka plandaki iş parçacığının sonucu yok sayılır.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from pydantic import BaseModel

from ..config import OrchestratorSettings, PermissionSettings
from ..llm.ollama_client import OllamaCancelled, OllamaClient, OllamaError
from ..llm.registry import ModelRegistry
from ..workers import WorkerRegistry
from ..workers.base import WorkerCancelled, WorkerContext, WorkerOutputInvalid
from .store import TaskStore
from .task import Task, TaskStatus, ValidationResult, utcnow

log = logging.getLogger(__name__)

# (görev, onay gerektiren izinler) -> onaylandı mı
Approver = Callable[[Task, list[str]], bool]

_POLL_S = 0.1


def _agent_timeout(worker: Any) -> float | None:
    """config/agents tanımındaki limits.timeout_s (varsa)."""
    definition = getattr(worker, "definition", None)
    return definition.limits.timeout_s if definition is not None else None


class Orchestrator:
    def __init__(
        self,
        store: TaskStore,
        workers: WorkerRegistry,
        llm: OllamaClient,
        registry: ModelRegistry,
        settings: OrchestratorSettings | None = None,
        permissions: PermissionSettings | None = None,
        approver: Approver | None = None,
    ):
        self.store = store
        self.workers = workers
        self.llm = llm
        self.registry = registry
        self.settings = settings or OrchestratorSettings()
        self.permissions = permissions or PermissionSettings()
        self.approver = approver
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ oluşturma

    def submit(
        self,
        objective: str,
        *,
        worker: str | None = None,
        input: dict[str, Any] | None = None,
        expected_output: str | None = None,
        timeout_s: float | None = None,
        permissions: Iterable[str] = (),
        depends_on: Iterable[str] = (),
        parent_id: str | None = None,
    ) -> Task:
        worker_name = worker or self.settings.default_worker
        w = self.workers.get(worker_name)  # bilinmeyen worker'da hemen hata
        task = Task(
            worker=worker_name,
            objective=objective,
            input=input or {},
            expected_output=expected_output or w.output_model.__name__,
            timeout_s=timeout_s or _agent_timeout(w) or self.settings.default_timeout_s,
            permissions=sorted({p.value for p in w.required_permissions} | set(permissions)),
            depends_on=list(depends_on),
            parent_id=parent_id,
        )
        self.store.save(task)
        self.store.log_event(task.id, "submitted", {"worker": worker_name, "objective": objective[:200]})
        return task

    def ask(self, objective: str, **kwargs: Any) -> Task:
        """submit + run kısayolu."""
        return self.run(self.submit(objective, **kwargs).id)

    # ------------------------------------------------------------------ yürütme

    def run(self, task_id: str) -> Task:
        task = self._require(task_id)
        if task.status.is_terminal:
            return task

        # 1) Bağımlılıklar
        for dep_id in task.depends_on:
            dep = self.store.get(dep_id)
            if dep is None:
                return self._finish(task, TaskStatus.FAILED, error=f"bağımlılık bulunamadı: {dep_id}")
            if dep.status != TaskStatus.SUCCEEDED:
                return self._finish(
                    task, TaskStatus.FAILED, error=f"bağımlılık başarısız: {dep_id} ({dep.status.value})"
                )

        # 2) İzinler / insan onayı
        needs = [p for p in task.permissions if p not in self.permissions.auto_approve]
        if needs:
            task.status = TaskStatus.AWAITING_APPROVAL
            self.store.save(task)
            self.store.log_event(task.id, "approval_requested", {"permissions": needs})
            approved = bool(self.approver and self.approver(task, needs))
            self.store.log_event(task.id, "approval_decision", {"approved": approved})
            if not approved:
                reason = "onaylayıcı tanımlı değil" if self.approver is None else "kullanıcı onaylamadı"
                return self._finish(task, TaskStatus.REJECTED, error=f"izin reddedildi ({reason}): {needs}")

        # 3) Çalıştır
        worker = self.workers.get(task.worker)
        cancel_event = self._cancel_event(task.id)
        if cancel_event.is_set():
            return self._finish(task, TaskStatus.CANCELLED, error="çalışmadan önce iptal edildi")

        ctx = WorkerContext(
            llm=self.llm,
            registry=self.registry,
            cancel_event=cancel_event,
            max_output_attempts=self.settings.max_output_attempts,
        )
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        task.attempts += 1
        self.store.save(task)
        self.store.log_event(task.id, "started", {"attempt": task.attempts})

        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["output"] = worker.run(task, ctx)
            except BaseException as exc:  # noqa: BLE001 - iş parçacığı sınırında her şeyi yakala
                box["error"] = exc

        thread = threading.Thread(target=target, name=f"task-{task.id}", daemon=True)
        thread.start()
        deadline = task.started_at.timestamp() + task.timeout_s
        while thread.is_alive():
            thread.join(_POLL_S)
            if cancel_event.is_set():
                break
            if utcnow().timestamp() >= deadline:
                break

        task.metrics = dict(ctx.metrics)
        task.model = ctx.metrics.get("model")
        try:
            if thread.is_alive():
                cancel_event.set()  # arka plandaki işi en kısa sürede durdur
                if utcnow().timestamp() >= deadline:
                    return self._finish(task, TaskStatus.TIMED_OUT, error=f"{task.timeout_s:.0f} sn zaman aşımı")
                return self._finish(task, TaskStatus.CANCELLED, error="kullanıcı iptal etti")
            if "error" in box:
                return self._handle_error(task, box["error"])
            return self._handle_output(task, worker, box["output"])
        finally:
            with self._lock:
                self._cancel_events.pop(task.id, None)

    def run_all(self, task_ids: Iterable[str]) -> list[Task]:
        """Görevleri bağımlılık sırasına göre, en fazla max_parallel paralel çalıştırır."""
        ids = list(dict.fromkeys(task_ids))
        batch = set(ids)
        remaining = set(ids)   # henüz başlatılmamış
        finished: set[str] = set()  # bitmiş (sonucu ne olursa olsun)
        running: dict[Future[Task], str] = {}
        with ThreadPoolExecutor(max_workers=self.settings.max_parallel, thread_name_prefix="kayaai") as pool:
            while remaining or running:
                ready = [tid for tid in ids if tid in remaining and self._deps_finished(tid, batch, finished)]
                for tid in ready:
                    remaining.discard(tid)
                    running[pool.submit(self.run, tid)] = tid
                if not running:
                    # Hazır görev yok ve hiçbiri çalışmıyor: döngüsel bağımlılık.
                    for tid in list(remaining):
                        t = self._require(tid)
                        self._finish(t, TaskStatus.FAILED, error="döngüsel bağımlılık")
                        remaining.discard(tid)
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in done:
                    tid = running.pop(fut)
                    finished.add(tid)
                    exc = fut.exception()
                    if exc is not None:  # run() kendi hatalarını yakalar; buraya düşmemeli
                        log.exception("run(%s) beklenmeyen hata", tid, exc_info=exc)
                        self._finish(self._require(tid), TaskStatus.FAILED, error=f"iç hata: {exc!r}")
        return [self._require(tid) for tid in ids]

    def cancel(self, task_id: str) -> bool:
        task = self._require(task_id)
        if task.status.is_terminal:
            return False
        self._cancel_event(task_id).set()
        if task.status in (TaskStatus.PENDING, TaskStatus.WAITING_CLAUDE):
            self._finish(task, TaskStatus.CANCELLED, error="kullanıcı iptal etti")
        self.store.log_event(task_id, "cancel_requested")
        return True

    # ------------------------------------------------------------------ yardımcılar

    def _deps_finished(self, tid: str, batch: set[str], finished: set[str]) -> bool:
        """Bu partideki bağımlılıklar BİTMİŞ olmalı (yalnızca başlatılmış olması yetmez).

        Parti dışındaki bağımlılıkların durumunu run() kontrol eder.
        """
        task = self._require(tid)
        return all(dep not in batch or dep in finished for dep in task.depends_on)

    def _cancel_event(self, task_id: str) -> threading.Event:
        with self._lock:
            return self._cancel_events.setdefault(task_id, threading.Event())

    def _require(self, task_id: str) -> Task:
        task = self.store.get(task_id)
        if task is None:
            raise KeyError(f"Görev bulunamadı: {task_id}")
        return task

    def _handle_output(self, task: Task, worker: Any, output: Any) -> Task:
        if not isinstance(output, BaseModel) or not isinstance(output, worker.output_model):
            return self._finish(
                task,
                TaskStatus.FAILED,
                error=f"worker beklenen tipte çıktı döndürmedi: {type(output).__name__}",
                validation=ValidationResult(passed=False, validator="orchestrator.type", errors=["tip uyumsuz"]),
            )
        validation = worker.validate(task, output)
        task.result = output.model_dump(mode="json")
        if not validation.passed:
            return self._finish(task, TaskStatus.FAILED, error="çıktı doğrulamadan geçemedi", validation=validation)
        return self._finish(task, TaskStatus.SUCCEEDED, validation=validation)

    def _handle_error(self, task: Task, exc: BaseException) -> Task:
        if isinstance(exc, (WorkerCancelled, OllamaCancelled)):
            return self._finish(task, TaskStatus.CANCELLED, error=str(exc))
        if isinstance(exc, WorkerOutputInvalid):
            task.result = {"raw_output": (exc.last_output or "")[:4000]}
            return self._finish(
                task,
                TaskStatus.FAILED,
                error=str(exc),
                validation=ValidationResult(passed=False, validator="schema", errors=exc.errors),
            )
        if isinstance(exc, OllamaError):
            return self._finish(task, TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        log.error("Görev %s beklenmeyen hata", task.id, exc_info=exc)
        return self._finish(task, TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")

    def _finish(
        self,
        task: Task,
        status: TaskStatus,
        *,
        error: str | None = None,
        validation: ValidationResult | None = None,
    ) -> Task:
        task.status = status
        task.error = error
        if validation is not None:
            task.validation = validation
        task.finished_at = utcnow()
        self.store.save(task)
        self.store.log_event(
            task.id, status.value, {"error": error, "duration_s": task.duration_s, "metrics": task.metrics}
        )
        log.info("görev %s [%s] -> %s %s", task.id, task.worker, status.value, error or "")
        return task
