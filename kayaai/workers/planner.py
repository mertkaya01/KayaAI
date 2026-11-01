"""Planlayıcı worker: isteği tek ajana mı vereceğine, yoksa kısa bir plana mı böleceğine karar verir.

Planın geçerliliği KODLA kontrol edilir (ajan adları, bağımlılık sırası, adım sınırı); geçersiz plan
modele geri bildirilip tekrar istenir (LLMWorker'ın mevcut retry mekanizması).
"""

from __future__ import annotations

import re

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker

DEFAULT_MAX_STEPS = 4


class PlanStep(BaseModel):
    id: str = Field(description="Short step id, e.g. s1, s2")
    agent: str = Field(description="Name of the agent that does this step (from the provided agent list)")
    objective: str = Field(description="What this step must produce, written in the user's language")
    depends_on: list[str] = Field(default_factory=list, description="Ids of EARLIER steps whose results this step needs")


class NewAgent(BaseModel):
    name: str = Field(description="Short lowercase id for the new agent, e.g. 'legal' (letters, digits, - or _)")
    description: str = Field(description="What the new agent does, in the user's language")
    role: str = Field(description="Role instructions for the new agent (English, 2-5 sentences)")
    base: str = Field(description="Existing agent it is based on, e.g. 'general' or 'document'")


class RoutePlan(BaseModel):
    mode: Literal["direct", "plan"] = Field(
        description="'direct' = one agent can answer the whole request (preferred); 'plan' = needs several steps"
    )
    agent: str | None = Field(None, description="For mode 'direct': the agent that answers")
    steps: list[PlanStep] = Field(default_factory=list, description="For mode 'plan': 2-4 steps in execution order")
    needs_claude: bool = Field(
        False,
        description="True ONLY if the request clearly needs advanced reasoning beyond a small local model "
        "(complex system architecture, large multi-file code, deep multi-source analysis)",
    )
    claude_reason: str = Field("", description="Why Claude is needed (empty if needs_claude is false)")
    new_agent: NewAgent | None = Field(
        None,
        description="Almost always null. Only if NO listed agent has the expertise a part of the request clearly "
        "needs (and it will likely be needed again): define ONE new agent and use its name in agent/steps.",
    )
    key_topics: list[str] = Field(
        default_factory=list,
        description="2-5 main SUBJECTS the final answer must substantively cover (nouns, e.g. "
        "'çok kiracılı / multi-tenant', 'veri izolasyonu'); not instructions like 'write' or 'explain'. "
        "Use 'A / B' to give a Turkish and English name for the same subject.",
    )


class PlannerWorker(LLMWorker):
    name: ClassVar[str] = "planner"
    description: ClassVar[str] = "İsteği tek ajana yönlendirir ya da kısa bir plana böler"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = RoutePlan
    system_prompt: ClassVar[str] = (
        "You are the planner of kayaAI, a local multi-agent system. Decide how to handle the user's request "
        "using ONLY the agents listed in the input data.\n"
        "Rules:\n"
        "- Prefer mode 'direct' with the single best agent. Most requests are direct: questions, explanations, "
        "translations, summaries, a single piece of code.\n"
        "- Use mode 'plan' only when the request has clearly separate parts that need different agents or "
        "build on each other (e.g. write code AND then explain it for a non-technical reader AND draft an email). "
        "Use 2-4 steps; each step depends only on earlier steps.\n"
        "- Never use the agent 'planner' or 'reviewer' in steps; reviewing is done automatically afterwards.\n"
        "- Set needs_claude true only when a small local model would very likely fail; otherwise false.\n"
        "- Write step objectives in the user's language.\n"
        "- new_agent: leave null unless the input data says new agents are allowed AND no listed agent fits a "
        "clearly specialised part of the request. Prefer existing agents.\n"
        "- key_topics: the main subjects of the request that the answer must really address (not formatting or "
        "instruction words). Give 'Turkish / English' names when the subject has both."
    )

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, RoutePlan)
        agents = {a["name"] for a in task.input.get("agents", []) if isinstance(a, dict) and "name" in a}
        max_steps = int(task.input.get("max_steps", DEFAULT_MAX_STEPS))
        errors = validate_plan(output, agents, max_steps, allow_new_agent=bool(task.input.get("allow_new_agent")))
        return ValidationResult(passed=not errors, validator="planner.structure", errors=errors)


FORBIDDEN_STEP_AGENTS = {"planner", "reviewer", "vision"}  # vision: yalnız görüntü ekli isteklerde (Adım 12a)


NEW_AGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def validate_plan(plan: RoutePlan, agents: set[str], max_steps: int = DEFAULT_MAX_STEPS,
                  allow_new_agent: bool = False) -> list[str]:
    usable = agents - FORBIDDEN_STEP_AGENTS
    errors: list[str] = []
    if plan.new_agent is not None:
        na = plan.new_agent
        if not allow_new_agent:
            errors.append("new_agent şu an kullanılamaz; mevcut ajanlardan birini seç ve new_agent'ı null bırak")
        elif not NEW_AGENT_NAME.match(na.name):
            errors.append(f"new_agent.name geçersiz: {na.name!r} (küçük harf, rakam, - ya da _)")
        elif na.name in agents:
            errors.append(f"new_agent.name {na.name!r} zaten var; o ajanı doğrudan kullan")
        elif na.base not in usable:
            errors.append(f"new_agent.base bilinmeyen/kullanılamaz: {na.base!r}; kullanılabilir: {sorted(usable)}")
        elif len(na.role.strip()) < 10 or not na.description.strip():
            errors.append("new_agent için description ve role (en az bir cümle) gerekli")
        else:
            usable = usable | {na.name}
    if len(plan.key_topics) > 6:
        errors.append(f"key_topics en fazla 6 olmalı (gelen: {len(plan.key_topics)})")
    if any(not t.strip() for t in plan.key_topics):
        errors.append("key_topics içinde boş konu var")
    if plan.needs_claude and not plan.claude_reason.strip():
        errors.append("needs_claude true ise claude_reason gerekli")
    if plan.mode == "direct":
        if not plan.agent:
            errors.append("mode 'direct' için 'agent' gerekli")
        elif plan.agent not in usable:
            errors.append(f"bilinmeyen/kullanılamaz ajan: {plan.agent!r}; kullanılabilir: {sorted(usable)}")
        return errors
    if not 1 <= len(plan.steps) <= max_steps:
        errors.append(f"plan 1-{max_steps} adım olmalı (gelen: {len(plan.steps)})")
    seen: set[str] = set()
    for step in plan.steps:
        if not step.id.strip():
            errors.append("boş adım id'si")
        if step.id in seen:
            errors.append(f"tekrarlanan adım id'si: {step.id}")
        if step.agent not in usable:
            errors.append(f"adım {step.id}: bilinmeyen/kullanılamaz ajan {step.agent!r}; kullanılabilir: {sorted(usable)}")
        if not step.objective.strip():
            errors.append(f"adım {step.id}: amaç boş")
        for dep in step.depends_on:
            if dep not in seen:
                errors.append(f"adım {step.id}: bağımlılık {dep!r} daha önceki bir adım değil")
        seen.add(step.id)
    return errors
