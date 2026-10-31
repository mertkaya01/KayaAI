"""kayaAI yerel API sunucusu (Adım 4) — Assistant Workspace ve Control Center bu API'ye bağlanır.

Güvenlik:
- Yalnızca 127.0.0.1 (CLI başka adresi reddeder). Her istek erişim anahtarı ister
  (`Authorization: Bearer <anahtar>`; WebSocket'te `?token=`). Anahtar: data/api_token.
- CORS yalnızca localhost kökenlerine açık (yerel arayüz geliştirme sunucusu için).
- Girdi sınırları MCP sunucusuyla aynı (20.000 karakter).
- Uzun işler (ask/do/inbox run) tek iş parçacıklı arka plan kuyruğunda çalışır (tek GPU); uç nokta hemen
  iş numarasını döner, ilerleme `/api/events` akışından ve `/api/tasks/{id}`'den izlenir.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .. import APP_NAME, __version__
from ..conductor import ClaudeInbox, Conductor
from ..config import PROJECT_ROOT, Settings, load_settings
from ..core.agent_status import agent_statuses
from ..core.task import TaskStatus
from ..llm.ollama_client import OllamaError
from ..runtime import Runtime, build_runtime

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000
EVENT_POLL_S = 0.5
LOCAL_ORIGIN_REGEX = r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
UI_DIST = PROJECT_ROOT / "ui" / "dist"

# Control Center sayfaları için içerik güvenlik politikası: yalnızca kendi kökeni; dış betik/stil/çerçeve yok.
UI_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
# /docs (Swagger) betiklerini CDN'den yükler; ona CSP uygulanmaz (yalnızca bu bilgisayarda açılır).
_NO_CSP_PREFIXES = ("/docs", "/redoc", "/openapi.json")

UI_MISSING_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>kayaAI</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;max-width:640px;margin:10vh auto;padding:0 16px}
code{background:#18202b;padding:2px 6px;border-radius:4px}</style></head><body>
<h1>kayaAI API çalışıyor</h1>
<p>Control Center arayüzü henüz derlenmemiş (<code>ui/dist</code> yok).</p>
<p>Derlemek için (Node.js gerekir) proje klasöründe:</p>
<p><code>cd ui</code> → <code>npm ci</code> → <code>npm run build</code></p>
<p>ya da <code>scripts\\windows\\setup.ps1</code> komutunu yeniden çalıştırın. Sonra <code>kayaai ui</code>.</p>
<p>API deneme sayfası: <a href="/docs" style="color:#4ea1ff">/docs</a></p>
</body></html>"""


# ----------------------------------------------------------------------------- erişim anahtarı


def token_path(settings: Settings) -> Path:
    return settings.data_dir / "api_token"


def load_or_create_token(settings: Settings) -> str:
    path = token_path(settings)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)  # POSIX; Windows'ta kullanıcı profili altındaki proje klasörü korunur
    except OSError:
        pass
    return token


# ----------------------------------------------------------------------------- istek gövdeleri


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    worker: str = "general"
    context: str | None = Field(None, max_length=MAX_TEXT_CHARS)


class DoBody(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    force: Literal["local", "claude"] | None = None


class ClaudeBody(BaseModel):
    enabled: bool
    # Kapatırken kutudaki işler yerelde yapılsın mı (D16: varsayılan evet)
    handback: bool = True


class WriteBody(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=5 * 1024 * 1024)


class DecisionBody(BaseModel):
    note: str = Field("", max_length=1000)


class DisputeDecisionBody(BaseModel):
    side: Literal["producer", "reviewer"]
    note: str = Field("", max_length=1000)


class Accepted(BaseModel):
    id: str
    status: str
    message: str


# ----------------------------------------------------------------------------- uygulama


def create_app(settings: Settings | None = None, runtime: Runtime | None = None,
               ui_dir: Path | None = None) -> FastAPI:
    settings = settings or load_settings()
    ui_root = (ui_dir or UI_DIST).resolve()
    rt = runtime or build_runtime(settings)  # approver yok: hassas izinli görevler reddedilir
    token = load_or_create_token(settings)
    jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kayaai-api-job")
    lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        lifespan=lifespan,
        title=f"{APP_NAME} API",
        version=__version__,
        description="kayaAI yerel API'si (yalnızca bu bilgisayar). Kimlik: `Authorization: Bearer <data/api_token>`.",
    )
    app.state.runtime = rt
    app.state.token = token
    app.add_middleware(
        CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN_REGEX, allow_methods=["*"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(_NO_CSP_PREFIXES):
            response.headers.setdefault("Content-Security-Policy", UI_CSP)
            response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    bearer = HTTPBearer(auto_error=False)

    def auth(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        if creds is None or not secrets.compare_digest(creds.credentials, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Geçersiz ya da eksik erişim anahtarı",
                                headers={"WWW-Authenticate": "Bearer"})

    def submit(fn: Any, *args: Any) -> None:
        def wrapped() -> None:
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 - arka plan işi sunucuyu düşürmemeli; iş kaydı zaten kapanır
                log.exception("API arka plan işi başarısız")
        jobs.submit(wrapped)

    # ---------------------------------------------------------------- durum

    @app.get("/api/health", dependencies=[Depends(auth)])
    def health() -> dict[str, Any]:
        out: dict[str, Any] = {"app": APP_NAME, "version": __version__, "workers": rt.workers.names(),
                               "claude": rt.claude.status().model_dump(mode="json") if rt.claude else None,
                               "ollama": {"url": settings.ollama.base_url, "reachable": False}, "problems": []}
        try:
            out["ollama"].update(reachable=True, version=rt.llm.version())
            out["ollama"]["loaded_models"] = [
                {"name": m.get("name"), "size_vram_gb": round((m.get("size_vram") or 0) / 1024**3, 2)}
                for m in rt.llm.running_models()
            ]
        except OllamaError as exc:
            out["problems"].append(f"Ollama'ya ulaşılamıyor: {exc}")
        return out

    @app.get("/api/system", dependencies=[Depends(auth)])
    def system() -> dict[str, Any]:
        from ..system.metrics import system_metrics

        m = system_metrics()
        tasks = rt.store.list_tasks(limit=200)
        m["active_tasks"] = sum(t.status in (TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL) for t in tasks)
        return m

    @app.get("/api/agents", dependencies=[Depends(auth)])
    def agents() -> list[dict[str, Any]]:
        statuses = {s.name: s for s in agent_statuses(rt.store, rt.workers.names())}
        out = []
        for w in rt.workers.all():
            d = getattr(w, "definition", None)
            out.append({
                "name": w.name, "description": w.description, "output": w.output_model.__name__,
                "local_model": w.model_spec(rt.registry).name, "claude_tier": d.claude_tier if d else "none",
                "reviewed_by": d.review.reviewer if d and d.review.required else None,
                "checks": list(d.review.checks) if d and d.review.required else [],
                "status": statuses[w.name].model_dump(),
            })
        return out

    @app.get("/api/models", dependencies=[Depends(auth)])
    def models() -> dict[str, Any]:
        installed: set[str] | None
        loaded: list[dict[str, Any]] = []
        try:
            installed = {m.get("name") for m in rt.llm.list_models()}
            loaded = [{"name": m.get("name"), "size_vram_gb": round((m.get("size_vram") or 0) / 1024**3, 2)}
                      for m in rt.llm.running_models()]
        except OllamaError:
            installed = None
        users: dict[str, list[str]] = {}
        for w in rt.workers.all():
            users.setdefault(w.model_spec(rt.registry).key, []).append(w.name)
        return {
            "ollama_reachable": installed is not None,
            "loaded": loaded,
            "models": [
                {"key": k, "name": s.name, "status": s.status, "license": s.license, "approx_vram_gb": s.approx_vram_gb,
                 "installed": None if installed is None else s.name in installed, "agents": users.get(k, [])}
                for k, s in rt.registry.models.items()
            ],
        }

    # ---------------------------------------------------------------- görevler

    @app.get("/api/tasks", dependencies=[Depends(auth)])
    def tasks(limit: int = Query(50, ge=1, le=500), status_: str | None = Query(None, alias="status"),
              parent_id: str | None = None) -> dict[str, Any]:
        st = None
        if status_:
            try:
                st = TaskStatus(status_)
            except ValueError as exc:
                raise HTTPException(400, f"Bilinmeyen durum: {status_}") from exc
        items = rt.store.list_tasks(limit=limit if parent_id is None else 2000, status=st)
        if parent_id is not None:
            items = [t for t in items if t.parent_id == parent_id][:limit]
        return {"total": rt.store.count(), "tasks": [t.model_dump(mode="json") for t in items]}

    @app.get("/api/tasks/{task_id}", dependencies=[Depends(auth)])
    def task(task_id: str) -> dict[str, Any]:
        t = rt.store.get(task_id)
        if t is None:
            raise HTTPException(404, f"Görev bulunamadı: {task_id}")
        children = [c.model_dump(mode="json") for c in rt.store.list_tasks(limit=2000) if c.parent_id == task_id]
        return {"task": t.model_dump(mode="json"), "events": rt.store.events(task_id), "children": children}

    @app.post("/api/tasks/{task_id}/cancel", dependencies=[Depends(auth)])
    def cancel(task_id: str) -> dict[str, Any]:
        t = rt.store.get(task_id)
        if t is None:
            raise HTTPException(404, f"Görev bulunamadı: {task_id}")
        if t.worker == "conductor" and t.status == TaskStatus.WAITING_CLAUDE:
            return {"cancelled": ClaudeInbox(rt).cancel(task_id)}
        try:
            return {"cancelled": rt.orchestrator.cancel(task_id)}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/ask", status_code=202, dependencies=[Depends(auth)])
    def ask(body: AskBody) -> Accepted:
        try:
            task = rt.orchestrator.submit(body.question, worker=body.worker,
                                          input={"context": body.context} if body.context else None)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
        submit(rt.orchestrator.run, task.id)
        return Accepted(id=task.id, status=task.status.value, message="Görev kuyruğa alındı")

    @app.post("/api/do", status_code=202, dependencies=[Depends(auth)])
    def do(body: DoBody) -> Accepted:
        conductor = Conductor(rt)
        job = conductor.create_job(body.request, force=body.force)
        submit(conductor.run_job, job)
        return Accepted(id=job.id, status=job.status.value, message="Şef işi kuyruğa alındı")

    # ---------------------------------------------------------------- Claude modu ve kutu

    @app.get("/api/claude", dependencies=[Depends(auth)])
    def claude_status() -> dict[str, Any]:
        return rt.claude.status().model_dump(mode="json")

    @app.post("/api/claude", dependencies=[Depends(auth)])
    def claude_set(body: ClaudeBody) -> dict[str, Any]:
        with lock:
            st = rt.claude.enable() if body.enabled else rt.claude.disable()
        handed_back: list[str] = []
        if not body.enabled and body.handback:
            inbox = ClaudeInbox(rt)
            for item in inbox.items():
                submit(inbox.release, item.job_id)
                handed_back.append(item.job_id)
        return {"status": st.model_dump(mode="json"), "handed_back_to_local": handed_back}

    @app.get("/api/inbox", dependencies=[Depends(auth)])
    def inbox() -> dict[str, Any]:
        return ClaudeInbox(rt).view().model_dump(mode="json")

    @app.post("/api/inbox/{job_id}/run", status_code=202, dependencies=[Depends(auth)])
    def inbox_run(job_id: str) -> Accepted:
        t = rt.store.get(job_id)
        if t is None or t.status != TaskStatus.WAITING_CLAUDE:
            raise HTTPException(409, "Bu iş Claude kutusunda değil")
        submit(ClaudeInbox(rt).release, job_id)
        return Accepted(id=job_id, status="running", message="İş yerel ekibe verildi")

    @app.post("/api/inbox/{job_id}/cancel", dependencies=[Depends(auth)])
    def inbox_cancel(job_id: str) -> dict[str, Any]:
        return {"cancelled": ClaudeInbox(rt).cancel(job_id)}

    # ---------------------------------------------------------------- dosyalar ve onay kuyruğu (Adım 5)

    from ..core.permissions import ApprovalError
    from ..tools.files import PathNotAllowed, roots

    def _file_call(fn: Any, *args: Any) -> dict[str, Any]:
        try:
            res = fn(*args, requested_by="api")
        except PathNotAllowed as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if res.status == "failed":
            raise HTTPException(400, res.error)
        return res.model_dump(mode="json")

    @app.get("/api/files/roots", dependencies=[Depends(auth)])
    def files_roots() -> list[dict[str, Any]]:
        return [{"path": str(r.path), "access": "read_write" if r.writable else "read"} for r in roots(settings)]

    @app.get("/api/files", dependencies=[Depends(auth)])
    def files_list(path: str = ".") -> dict[str, Any]:
        return _file_call(rt.files.list_dir, path)

    @app.get("/api/files/read", dependencies=[Depends(auth)])
    def files_read(path: str) -> dict[str, Any]:
        return _file_call(rt.files.read, path)

    @app.post("/api/files/write", dependencies=[Depends(auth)])
    def files_write(body: WriteBody) -> dict[str, Any]:
        return _file_call(rt.files.write, body.path, body.content)

    @app.get("/api/approvals", dependencies=[Depends(auth)])
    def approvals(status_: str | None = Query("pending", alias="status")) -> list[dict[str, Any]]:
        st = None if status_ in (None, "", "all") else status_
        return [a.model_dump(mode="json") for a in rt.permissions.list_approvals(st)]  # type: ignore[arg-type]

    @app.get("/api/approvals/{approval_id}", dependencies=[Depends(auth)])
    def approval(approval_id: str) -> dict[str, Any]:
        try:
            return rt.permissions.get(approval_id).model_dump(mode="json")
        except ApprovalError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(auth)])
    def approval_approve(approval_id: str, body: DecisionBody | None = None) -> dict[str, Any]:
        try:  # yalnızca anahtar sahibi (arayüz = sahip); R3 dahil her talep tek tek onaylanır
            return rt.permissions.approve(approval_id, decided_by="api", note=(body.note if body else "")).model_dump(mode="json")
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/approvals/{approval_id}/reject", dependencies=[Depends(auth)])
    def approval_reject(approval_id: str, body: DecisionBody | None = None) -> dict[str, Any]:
        try:
            return rt.permissions.reject(approval_id, decided_by="api", note=(body.note if body else "")).model_dump(mode="json")
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ---------------------------------------------------------------- anlaşmazlıklar (Adım 7)

    @app.get("/api/disputes", dependencies=[Depends(auth)])
    def disputes(status_: Literal["open", "resolved", "all"] = Query("open", alias="status"),
                 limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        assert rt.disputes is not None
        return [d.model_dump(mode="json") for d in rt.disputes.list(None if status_ == "all" else status_, limit=limit)]

    @app.post("/api/disputes/{dispute_id}/resolve", dependencies=[Depends(auth)])
    def dispute_resolve(dispute_id: str, body: DisputeDecisionBody) -> dict[str, Any]:
        from ..core.disputes import DisputeError

        assert rt.disputes is not None
        try:
            return rt.disputes.resolve(dispute_id, body.side, decided_by="api", note=body.note).model_dump(mode="json")
        except DisputeError as exc:
            code = 404 if "bulunamadı" in str(exc) else 409
            raise HTTPException(code, str(exc)) from exc

    # ---------------------------------------------------------------- canlı olaylar

    @app.websocket("/api/events")
    async def events(ws: WebSocket, token_: str = Query("", alias="token"), after: int | None = None,
                     backlog: int = Query(0, ge=0, le=200)) -> None:
        if not secrets.compare_digest(token_, token):
            await ws.close(code=4401, reason="Geçersiz erişim anahtarı")
            return
        await ws.accept()
        # after: kaldığı yerden devam; yoksa şimdiden itibaren (+ isteğe bağlı son `backlog` olay)
        last = max(0, rt.store.last_event_id() - backlog) if after is None else after
        try:
            while True:
                batch = await asyncio.to_thread(rt.store.events_since, last, 200)
                for ev in batch:
                    await ws.send_json(ev)
                    last = ev["id"]
                if not batch:
                    # Uyumak yerine istemciyi dinle: bağlantı kopunca WebSocketDisconnect gelir ve döngü biter.
                    # (Önceden kopan bağlantılar açık kalıyor, sunucu Ctrl+C ile kapanmıyordu.)
                    try:
                        await asyncio.wait_for(ws.receive_text(), timeout=EVENT_POLL_S)
                    except asyncio.TimeoutError:
                        pass
        except (WebSocketDisconnect, RuntimeError):
            return

    # ---------------------------------------------------------------- Control Center (ui/dist)
    # En sona kaydedilir: /api/* ve /docs önce eşleşir. Arayüz dosyaları anahtarsızdır (gizli bilgi içermez);
    # veriye erişim yine /api/* üzerinden anahtarla olur.

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def ui(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Bilinmeyen API yolu")
        index = ui_root / "index.html"
        if not index.is_file():
            return HTMLResponse(UI_MISSING_HTML)
        if path:
            target = (ui_root / path).resolve()
            if target.is_relative_to(ui_root) and target.is_file():
                # Dosya adları içerik özetli (index-abc123.js): uzun süre önbelleğe alınabilir
                cache = "public, max-age=31536000, immutable" if target.parent.name == "assets" else "no-cache"
                return FileResponse(target, headers={"Cache-Control": cache})
        # SPA: bilinmeyen yollar ana sayfaya düşer
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
