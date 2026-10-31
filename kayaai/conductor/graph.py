"""Şef işinin canlı akış grafiği (Adım 11, MASTER_PROMPT §9B.2 "Visual workflow").

Grafik ayrıca saklanmaz; iş kaydı + alt görevler (`parent_id`) + görev olaylarından TÜRETİLİR. Böylece iş sürerken de
(sonuç kaydı henüz yazılmamışken) doğru görünür ve başka süreçte (MCP, CLI) başlatılan işler de izlenebilir.

İstek → Planlayıcı → adımlar (ajan) → [kontrol → revizyon] → (son gözden geçirme / ek) → Sonuç | Claude kutusu
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.store import TaskStore
from ..core.task import Task, TaskStatus

NodeKind = Literal["request", "planner", "step", "check", "revise", "review", "addendum", "merge", "result", "claude"]
NodeStatus = Literal["pending", "running", "succeeded", "failed", "waiting", "skipped"]


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    status: NodeStatus = "pending"
    agent: str | None = None
    model: str | None = None
    task_id: str | None = None
    duration_s: float | None = None
    tokens_per_second: float | None = None
    detail: str = ""
    error: str | None = None
    review: dict[str, Any] | None = None


class GraphEdge(BaseModel):
    source: str
    target: str


class JobGraph(BaseModel):
    job_id: str
    objective: str
    status: str
    mode: str | None = None
    routing: str | None = None
    duration_s: float | None = None
    warnings: list[str] = Field(default_factory=list)
    nodes: list[GraphNode]
    edges: list[GraphEdge]


_STATUS: dict[TaskStatus, NodeStatus] = {
    TaskStatus.PENDING: "pending", TaskStatus.RUNNING: "running", TaskStatus.SUCCEEDED: "succeeded",
    TaskStatus.FAILED: "failed", TaskStatus.TIMED_OUT: "failed", TaskStatus.REJECTED: "failed",
    TaskStatus.CANCELLED: "skipped", TaskStatus.AWAITING_APPROVAL: "waiting", TaskStatus.WAITING_CLAUDE: "waiting",
}


def _node(id_: str, kind: NodeKind, label: str, t: Task | None, **extra: Any) -> GraphNode:
    n = GraphNode(id=id_, kind=kind, label=label, **extra)
    if t is not None:
        n.status = _STATUS.get(t.status, "pending")
        n.task_id, n.model = t.id, t.model
        n.agent = n.agent or t.worker.split(".", 1)[0]
        n.duration_s = round(t.duration_s, 2) if t.duration_s is not None else None
        tps = t.metrics.get("tokens_per_second") if t.metrics else None
        n.tokens_per_second = round(float(tps), 1) if tps else None
        n.detail = n.detail or t.objective[:240]
        n.error = t.error
    return n


def _plan_from_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for e in events:
        if e["event"] == "plan.created" and e.get("detail"):
            try:
                return json.loads(e["detail"])
            except (TypeError, ValueError):
                return None
    return None


def list_jobs(store: TaskStore, limit: int = 30) -> list[dict[str, Any]]:
    out = []
    for j in store.list_by_worker("conductor", limit):
        res = j.result or {}
        out.append({"id": j.id, "objective": j.objective[:200], "status": j.status.value,
                    "created_at": j.created_at.isoformat(), "duration_s": res.get("duration_s"),
                    "mode": res.get("mode"), "steps": len(res.get("steps", []))})
    return out


def build_graph(store: TaskStore, job_id: str) -> JobGraph:
    job = store.get(job_id)
    if job is None or job.worker != "conductor":
        raise KeyError(f"Şef işi bulunamadı: {job_id}")
    res = job.result or {}
    events = store.events(job.id)
    children = store.list_children(job.id)
    plan = _plan_from_events(events)

    nodes: list[GraphNode] = [GraphNode(id="request", kind="request", label="İstek", detail=job.objective[:400],
                                        status="succeeded" if job.status != TaskStatus.PENDING else "pending")]
    edges: list[GraphEdge] = []

    # Adımlar: biten işte sonuç kaydı kesin; sürerken plan olayı
    if res.get("steps"):
        steps = [{"id": s["id"], "agent": s["agent"], "objective": s.get("objective", ""),
                  "depends_on": s.get("depends_on", []), "task_id": s.get("task_id"), "review": s.get("review")}
                 for s in res["steps"]]
    elif plan:
        if plan.get("mode") == "plan":
            steps = [{"id": s["id"], "agent": s["agent"], "objective": s.get("objective", ""),
                      "depends_on": s.get("depends_on", []), "task_id": None, "review": None} for s in plan["steps"]]
        else:
            steps = [{"id": "s1", "agent": plan.get("agent") or "general", "objective": job.objective,
                      "depends_on": [], "task_id": None, "review": None}]
    else:
        steps = []

    # Alt görevleri yerleştir (zaman sırasıyla)
    planner_t = next((c for c in children if c.worker == "planner"), None)
    by_id = {c.id: c for c in children}
    step_task: dict[str, Task] = {}
    step_check: dict[str, Task] = {}
    step_revise: dict[str, Task] = {}
    tail: list[Task] = []
    for s in steps:
        if s["task_id"] and s["task_id"] in by_id:
            step_task[s["id"]] = by_id[s["task_id"]]
    assigned = {t.id for t in step_task.values()}
    cursor = -1
    for c in children:
        if c is planner_t:
            continue
        if c.id in assigned:
            cursor = next(i for i, s in enumerate(steps) if step_task.get(s["id"]) is c)
            continue
        if c.worker.endswith(".check") and cursor >= 0:
            step_check.setdefault(steps[cursor]["id"], c)
            continue
        if c.worker.endswith(".revise") and cursor >= 0:
            step_revise.setdefault(steps[cursor]["id"], c)
            continue
        nxt = cursor + 1
        if nxt < len(steps) and steps[nxt]["id"] not in step_task and c.worker == steps[nxt]["agent"]:
            step_task[steps[nxt]["id"]] = c
            cursor = nxt
            continue
        if cursor >= len(steps) - 1 or not steps:
            tail.append(c)

    nodes.append(_node("planner", "planner", "Planlayıcı", planner_t, agent="planner",
                       detail=(f"{plan.get('mode')} · {len(steps)} adım" if plan else "")))
    edges.append(GraphEdge(source="request", target="planner"))

    last_of: dict[str, str] = {}
    for s in steps:
        sid = s["id"]
        t = step_task.get(sid)
        n = _node(f"step-{sid}", "step", f"{s['agent']}", t, agent=s["agent"], detail=s["objective"][:240])
        if s.get("review"):
            rv = s["review"]
            n.review = {"verdict": rv.get("verdict"), "issues": len(rv.get("issues", [])),
                        "dropped": rv.get("dropped_issues", 0), "revised": rv.get("revised", False),
                        "disputes": len(rv.get("disputes", []))}
        nodes.append(n)
        deps = [d for d in s["depends_on"] if d in last_of]
        for d in deps:
            edges.append(GraphEdge(source=last_of[d], target=n.id))
        if not deps:
            edges.append(GraphEdge(source="planner", target=n.id))
        last = n.id
        if sid in step_check:
            cn = _node(f"check-{sid}", "check", "Gözden geçirme", step_check[sid])
            nodes.append(cn)
            edges.append(GraphEdge(source=last, target=cn.id))
            last = cn.id
        if sid in step_revise:
            rn = _node(f"revise-{sid}", "revise", "Düzeltme", step_revise[sid])
            nodes.append(rn)
            edges.append(GraphEdge(source=last, target=rn.id))
            last = rn.id
        last_of[sid] = last

    depended = {d for s in steps for d in s["depends_on"]}
    leaves = [last_of[s["id"]] for s in steps if s["id"] not in depended] or ["planner"]
    prev_ids = leaves
    for i, t in enumerate(tail, 1):
        kind: NodeKind = "review" if t.worker == "reviewer" else ("addendum" if res.get("mode") == "plan" or plan else "merge")
        label = {"review": "Son kontrol", "addendum": "Ek", "merge": "Birleştirme"}[kind]
        tn = _node(f"tail-{i}", kind, label, t)
        nodes.append(tn)
        for p in prev_ids:
            edges.append(GraphEdge(source=p, target=tn.id))
        prev_ids = [tn.id]

    routing = (res.get("routing") or {}).get("decision")
    to_claude = job.status == TaskStatus.WAITING_CLAUDE or res.get("completed_by")
    end = GraphNode(id="result", kind="claude" if to_claude else "result",
                    label="Claude kutusu" if to_claude else "Sonuç",
                    status=_STATUS.get(job.status, "pending") if job.status != TaskStatus.RUNNING else "pending",
                    detail=str(res.get("answer", ""))[:300], agent="claude" if res.get("completed_by") else None)
    if res.get("completed_by"):
        end.status = "succeeded"
    nodes.append(end)
    for p in prev_ids:
        edges.append(GraphEdge(source=p, target="result"))

    return JobGraph(job_id=job.id, objective=job.objective, status=job.status.value, mode=res.get("mode") or (plan or {}).get("mode"),
                    routing=routing, duration_s=res.get("duration_s"), warnings=list(res.get("warnings", [])),
                    nodes=nodes, edges=edges)
