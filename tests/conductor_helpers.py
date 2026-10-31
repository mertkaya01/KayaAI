"""Şef testleri için sahte Ollama senaryosu: cevaplar istenen şemaya (format.title) göre sırayla verilir."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .conftest import good_answer


def answer(text: str, **kw: Any) -> str:
    return good_answer(text, **kw)


def plan_direct(agent: str, needs_claude: bool = False, reason: str = "") -> str:
    return json.dumps({"mode": "direct", "agent": agent, "steps": [], "needs_claude": needs_claude,
                       "claude_reason": reason})


def plan_steps(steps: list[tuple[str, str, str, list[str]]]) -> str:
    return json.dumps({"mode": "plan", "agent": None, "needs_claude": False, "claude_reason": "",
                       "steps": [{"id": i, "agent": a, "objective": o, "depends_on": d} for i, a, o, d in steps]})


def review(verdict: str, issues: list[str] | None = None, missing: list[str] | None = None) -> str:
    return json.dumps({"verdict": verdict, "missing_parts": missing or [], "issues": issues or [],
                       "suggestion": "tamamla" if (issues or missing) else ""})


class Script:
    """FakeOllama chat_replies içine konan çağrılabilir: her şema için ayrı kuyruk."""

    def __init__(self, planner: list[str], answers: list[str], reviews: list[str] | None = None):
        self.queues = {"RoutePlan": list(planner), "GeneralAnswer": list(answers), "ReviewResult": list(reviews or [])}
        self.calls: dict[str, int] = defaultdict(int)
        self.user_messages: dict[str, list[str]] = defaultdict(list)
        self.models_used: list[str] = []

    def __call__(self, body: dict[str, Any]) -> str:
        title = (body.get("format") or {}).get("title", "?")
        self.calls[title] += 1
        self.models_used.append(body["model"])
        self.user_messages[title].append(body["messages"][-1]["content"])
        q = self.queues.get(title, [])
        return q.pop(0) if q else "{}"
