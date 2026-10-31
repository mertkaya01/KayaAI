"""kayaAI MCP sunucusu (Faz 2) — Claude Code gibi MCP istemcilerinin yerel worker'ları çağırması için.

Güvenlik:
- Yalnızca stdio taşıma: ağ portu AÇMAZ. İstemci sunucuyu alt süreç olarak başlatır.
- Onaylayıcı (approver) yoktur: `llm.inference` dışında izin isteyen her görev otomatik reddedilir.
  Bu fazda dosya yazma / komut çalıştırma / ağ aracı YOKTUR.
- Görev girdisi (input) güvenilmez veri olarak modele <input_data> içinde verilir.
- Başarısız/doğrulanmamış görevler MCP hata sonucu (is_error) olarak döner; asla başarılı gösterilmez.
- stdout MCP protokolüne aittir; loglar yalnızca data/logs/ dosyasına yazılır.

Çalıştırma:  python -m kayaai.mcp_server   (veya: kayaai mcp)
"""

from __future__ import annotations

import threading
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from . import APP_NAME, __version__
from .conductor import ClaudeInbox, Conductor, ConductorResult, InboxView
from .config import Settings, load_settings
from .core.task import Task, TaskStatus
from .llm.ollama_client import OllamaError
from .runtime import Runtime, build_runtime

MAX_TEXT_CHARS = 20_000
MAX_TIMEOUT_S = 600

INSTRUCTIONS = (
    "kayaAI is the user's local AI system running on their own GPU via Ollama. "
    "Use kayaai_ask to delegate a self-contained question or text task (summarize, translate, classify, "
    "draft, explain) to the local model; data never leaves the computer. "
    "The local model has no internet, file or screen access. Every result is schema-validated; "
    "a failed or unvalidated task is returned as an error, never as a success. "
    "Use kayaai_health first if you are unsure whether the local model is available."
)


# ----------------------------------------------------------------------------- çıktı şemaları


class TaskView(BaseModel):
    task_id: str
    worker: str
    status: str
    objective: str
    result: dict[str, Any] | None = None
    error: str | None = None
    validation_passed: bool | None = None
    validation_errors: list[str] = Field(default_factory=list)
    model: str | None = None
    duration_s: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    created_at: str


class AskResult(BaseModel):
    answer: str
    task_id: str
    model: str | None
    language: str | None = None
    task_type: str | None = None
    duration_s: float | None = None
    tokens_per_second: float | None = None
    result: dict[str, Any]


class AgentInfo(BaseModel):
    name: str
    description: str
    output: str
    local_model: str
    claude_tier: str
    permissions: list[str]


class AgentList(BaseModel):
    agents: list[AgentInfo]


class TaskList(BaseModel):
    tasks: list[TaskView]
    total_in_history: int


class ModelInfo(BaseModel):
    key: str
    name: str
    status: str
    installed: bool | None
    workers: list[str]
    approx_vram_gb: float | None
    license: str | None
    purpose: str


class ModelList(BaseModel):
    models: list[ModelInfo]
    ollama_reachable: bool


class Health(BaseModel):
    app: str
    version: str
    ollama_reachable: bool
    ollama_version: str | None = None
    ollama_url: str
    worker_models_installed: dict[str, bool] = Field(default_factory=dict)
    loaded_models: list[dict[str, Any]] = Field(default_factory=list)
    gpus: list[dict[str, Any]] = Field(default_factory=list)
    gpu_notes: list[str] = Field(default_factory=list)
    workers: list[str]
    claude_mode: dict[str, Any] | None = None
    problems: list[str] = Field(default_factory=list)


def _view(task: Task) -> TaskView:
    return TaskView(
        task_id=task.id,
        worker=task.worker,
        status=task.status.value,
        objective=task.objective[:500],
        result=task.result,
        error=task.error,
        validation_passed=task.validation.passed if task.validation else None,
        validation_errors=task.validation.errors if task.validation else [],
        model=task.model,
        duration_s=task.duration_s,
        metrics=task.metrics,
        depends_on=task.depends_on,
        created_at=task.created_at.isoformat(),
    )


def _check_text(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ToolError(f"'{name}' boş olamaz")
    if len(value) > MAX_TEXT_CHARS:
        raise ToolError(f"'{name}' en fazla {MAX_TEXT_CHARS} karakter olabilir (gelen: {len(value)})")
    return value


def _check_timeout(timeout_s: float | None) -> float | None:
    if timeout_s is None:
        return None
    if not 1 <= timeout_s <= MAX_TIMEOUT_S:
        raise ToolError(f"timeout_s 1 ile {MAX_TIMEOUT_S} arasında olmalı")
    return timeout_s


def _raise_if_not_succeeded(task: Task) -> None:
    if task.status != TaskStatus.SUCCEEDED:
        detail = f"; doğrulama hataları: {task.validation.errors}" if task.validation and task.validation.errors else ""
        raise ToolError(f"görev {task.id} {task.status.value}: {task.error}{detail}")


# ----------------------------------------------------------------------------- sunucu


def create_server(settings: Settings | None = None, runtime: Runtime | None = None) -> MCPServer:
    settings = settings or load_settings()
    state: dict[str, Runtime] = {}
    lock = threading.Lock()

    def rt() -> Runtime:
        # Runtime ilk araç çağrısında kurulur: sunucu Ollama kapalıyken de başlayıp health raporlayabilir.
        with lock:
            if "rt" not in state:
                state["rt"] = runtime or build_runtime(settings)  # approver=None -> hassas izinler reddedilir
            r = state["rt"]
        # Her araç çağrısı = Claude Code'dan temas ("son temas" göstergesi için).
        if r.claude is not None:
            try:
                r.claude.record_contact()
            except Exception:  # noqa: BLE001 - temas kaydı asla aracı düşürmemeli
                pass
        return r

    server = MCPServer(name="kayaai", title=APP_NAME, version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="kayaai_ask",
        description=(
            "Ask kayaAI's local LLM worker a self-contained question or text task. Runs on the user's GPU; "
            "no data leaves the machine. Returns a schema-validated answer. Optional 'context' is passed as "
            "untrusted data (e.g. a text to summarize or translate)."
        ),
    )
    def kayaai_ask(
        question: str,
        context: str | None = None,
        worker: str = "general",
        timeout_s: float | None = None,
    ) -> AskResult:
        question = _check_text("question", question)
        task_input = {"context": _check_text("context", context)} if context else None
        r = rt()
        try:
            task = r.orchestrator.ask(question, worker=worker, input=task_input, timeout_s=_check_timeout(timeout_s))
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        _raise_if_not_succeeded(task)
        res = task.result or {}
        answer = res.get("answer")
        if answer is None and "verdict" in res:  # reviewer çıktısı
            answer = f"verdict: {res['verdict']}" + (f" — {'; '.join(res.get('issues', []))}" if res.get("issues") else "")
        return AskResult(
            answer=str(answer or ""),
            task_id=task.id,
            model=task.model,
            language=res.get("language"),
            task_type=res.get("task_type"),
            duration_s=task.duration_s,
            tokens_per_second=task.metrics.get("tokens_per_second"),
            result=res,
        )

    @server.tool(
        name="kayaai_submit_task",
        description=(
            "Create a pending kayaAI task without running it (use kayaai_run_task to execute). "
            "'depends_on' lists task ids that must succeed first. 'input' is treated as untrusted data."
        ),
    )
    def kayaai_submit_task(
        objective: str,
        worker: str = "general",
        input: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        timeout_s: float | None = None,
    ) -> TaskView:
        objective = _check_text("objective", objective)
        if input is not None and len(str(input)) > MAX_TEXT_CHARS:
            raise ToolError(f"'input' en fazla {MAX_TEXT_CHARS} karakter olabilir")
        try:
            task = rt().orchestrator.submit(
                objective, worker=worker, input=input, depends_on=depends_on or [], timeout_s=_check_timeout(timeout_s)
            )
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return _view(task)

    @server.tool(
        name="kayaai_run_task",
        description="Run a pending kayaAI task (and wait for it). Returns an error if it does not succeed.",
    )
    def kayaai_run_task(task_id: str) -> TaskView:
        try:
            task = rt().orchestrator.run(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        _raise_if_not_succeeded(task)
        return _view(task)

    @server.tool(name="kayaai_task_status", description="Get a kayaAI task with its result and validation.")
    def kayaai_task_status(task_id: str) -> TaskView:
        task = rt().store.get(task_id)
        if task is None:
            raise ToolError(f"Görev bulunamadı: {task_id}")
        return _view(task)

    @server.tool(name="kayaai_cancel_task", description="Cancel a pending or running kayaAI task.")
    def kayaai_cancel_task(task_id: str) -> TaskView:
        r = rt()
        try:
            cancelled = r.orchestrator.cancel(task_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        if not cancelled:
            raise ToolError(f"Görev zaten bitmiş, iptal edilemez: {task_id}")
        return _view(r.store.get(task_id))  # type: ignore[arg-type]

    @server.tool(name="kayaai_list_tasks", description="List recent kayaAI tasks (newest first).")
    def kayaai_list_tasks(
        limit: int = 20,
        status: Literal[
            "pending", "awaiting_approval", "running", "succeeded", "failed", "rejected", "cancelled", "timed_out",
            "waiting_claude",
        ]
        | None = None,
    ) -> TaskList:
        r = rt()
        limit = max(1, min(limit, 200))
        tasks = r.store.list_tasks(limit=limit, status=TaskStatus(status) if status else None)
        return TaskList(tasks=[_view(t) for t in tasks], total_in_history=r.store.count())

    @server.tool(
        name="kayaai_do",
        description=(
            "Hand a whole multi-part request to kayaAI's LOCAL team: the local planner splits it into steps, "
            "local agents (general, coder, ...) do them, the results are merged and reviewed. Runs on the user's "
            "GPU, free and private. Use for routine or bulk work you do not need to do yourself. The result may "
            "include warnings (e.g. the local planner thinks the task needs a stronger model)."
        ),
    )
    def kayaai_do(request: str) -> ConductorResult:
        request = _check_text("request", request)
        res = Conductor(rt()).run(request, origin="claude")
        if res.status != TaskStatus.SUCCEEDED.value:
            raise ToolError(f"iş {res.job_id} {res.status}: {res.error}; uyarılar: {res.warnings}")
        return res

    @server.tool(
        name="kayaai_claude_inbox",
        description=(
            "List kayaAI jobs that the local team judged too hard and left for Claude (you). For each job, do the "
            "work yourself (you may still delegate parts to kayaai_ask/kayaai_do) and then call "
            "kayaai_claude_complete with the final answer, or kayaai_claude_release to give it back to the local team."
        ),
    )
    def kayaai_claude_inbox() -> InboxView:
        return ClaudeInbox(rt()).view()

    @server.tool(
        name="kayaai_claude_complete",
        description="Write Claude's final answer for a job from the Claude inbox into kayaAI's task history.",
    )
    def kayaai_claude_complete(job_id: str, answer: str, summary: str = "") -> ConductorResult:
        try:
            return ClaudeInbox(rt()).complete(job_id, answer, summary)
        except (KeyError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="kayaai_claude_release",
        description="Give a job from the Claude inbox back to kayaAI's local team; it runs locally now and returns the result.",
    )
    def kayaai_claude_release(job_id: str) -> ConductorResult:
        try:
            res = ClaudeInbox(rt()).release(job_id)
        except (KeyError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        if res.status != TaskStatus.SUCCEEDED.value:
            raise ToolError(f"iş {res.job_id} {res.status}: {res.error}")
        return res

    @server.tool(
        name="kayaai_list_agents",
        description=(
            "List kayaAI's local agents (name, what they do, local model). Use an agent name as the 'worker' "
            "argument of kayaai_ask, e.g. 'coder' for code or 'reviewer' to check an answer."
        ),
    )
    def kayaai_list_agents() -> AgentList:
        r = rt()
        out = []
        for w in r.workers.all():
            d = getattr(w, "definition", None)
            out.append(
                AgentInfo(
                    name=w.name,
                    description=w.description,
                    output=w.output_model.__name__,
                    local_model=w.model_spec(r.registry).name,
                    claude_tier=d.claude_tier if d else "none",
                    permissions=[p.value for p in w.required_permissions],
                )
            )
        return AgentList(agents=out)

    @server.tool(name="kayaai_list_models", description="List kayaAI's model registry and which models are installed.")
    def kayaai_list_models() -> ModelList:
        r = rt()
        installed: set[str] | None
        try:
            installed = {m.get("name") for m in r.llm.list_models()}
        except OllamaError:
            installed = None
        assignments: dict[str, list[str]] = {}
        for w, k in r.registry.worker_assignments.items():
            assignments.setdefault(k, []).append(w)
        return ModelList(
            ollama_reachable=installed is not None,
            models=[
                ModelInfo(
                    key=key,
                    name=spec.name,
                    status=spec.status,
                    installed=None if installed is None else spec.name in installed,
                    workers=assignments.get(key, []),
                    approx_vram_gb=spec.approx_vram_gb,
                    license=spec.license,
                    purpose=spec.purpose,
                )
                for key, spec in r.registry.models.items()
            ],
        )

    @server.tool(
        name="kayaai_health",
        description="Check whether kayaAI's local model runtime (Ollama, models, GPU) is ready.",
    )
    def kayaai_health() -> Health:
        from .system.audit import gpu_info

        r = rt()
        h = Health(
            app=APP_NAME,
            version=__version__,
            ollama_reachable=False,
            ollama_url=r.settings.ollama.base_url,
            workers=r.workers.names(),
            claude_mode=r.claude.status().model_dump(mode="json") if r.claude else None,
        )
        try:
            h.ollama_version = r.llm.version()
            h.ollama_reachable = True
            names = {m.get("name") for m in r.llm.list_models()}
            for worker, key in r.registry.worker_assignments.items():
                spec = r.registry.get(key)
                ok = spec.name in names or f"{spec.name}:latest" in names
                h.worker_models_installed[f"{worker}:{spec.name}"] = ok
                if not ok:
                    h.problems.append(f"Model kurulu değil: ollama pull {spec.name}")
            h.loaded_models = [
                {
                    "name": m.get("name"),
                    "size_gb": round((m.get("size") or 0) / 1024**3, 2),
                    "size_vram_gb": round((m.get("size_vram") or 0) / 1024**3, 2),
                }
                for m in r.llm.running_models()
            ]
        except OllamaError as exc:
            h.problems.append(f"Ollama'ya ulaşılamıyor: {exc}")
        gpu = gpu_info()
        h.gpus = gpu.get("gpus", [])
        h.gpu_notes = gpu.get("notes", [])
        if not h.gpus:
            h.problems.append("NVIDIA GPU algılanmadı")
        return h

    return server


def main() -> None:
    from .logging_setup import setup_logging

    import logging

    settings = load_settings()
    setup_logging(settings, console=False)  # stdout protokole ait: konsola log yok
    logging.getLogger("httpx").setLevel(logging.WARNING)  # her Ollama isteği için INFO satırı basmasın
    logging.getLogger("kayaai").propagate = False  # kayaAI logları yalnızca dosyaya (data/logs/kayaai.log)
    create_server(settings).run("stdio")


if __name__ == "__main__":
    main()
