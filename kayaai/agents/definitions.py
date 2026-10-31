"""Ajan tanımları — tek kaynak (MASTER_PROMPT v2 D14).

`config/agents/<ad>.yaml` dosyaları kayaAI'nin ajanlarını tanımlar. Yerel worker'lar bu tanımlardan
kurulur; Claude modu açıkken (Adım 3e) Claude Code alt ajan dosyaları da bu tanımlardan ÜRETİLİR.
Yeni bir ajan eklemek kod yazmayı gerektirmez.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..core.task import Permission
from ..llm.registry import ModelRegistry, ModelSpec
from ..workers.base import LLMWorker
from ..workers.general import GeneralWorker
from ..workers.planner import PlannerWorker
from ..workers.reviewer import ReviewerWorker
from ..workers.step_review import RevisionWorker, StepReviewWorker

# Çıktı türü -> temel worker sınıfı (şema + anlamsal doğrulama oradan gelir)
OUTPUT_TYPES: dict[str, type[LLMWorker]] = {
    "answer": GeneralWorker,
    "review": ReviewerWorker,
    "plan": PlannerWorker,
}
_VALID_PERMISSIONS = {p.value for p in Permission}


class AgentDefinitionError(ValueError):
    pass


class AgentLimits(BaseModel):
    timeout_s: float | None = Field(None, gt=0, le=600)


class AgentReview(BaseModel):
    """Üretici → gözden geçirici akışı (Adım 7). required: bu ajanın her cevabı incelenir."""

    required: bool = False
    reviewer: str = "reviewer"
    # Deterministik kontroller (kayaai/conductor/checks.py); kod çalıştırılmaz, yalnızca ayrıştırılır.
    checks: list[Literal["code_syntax"]] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    description: str
    output: Literal["answer", "review", "plan"] = "answer"
    # Rol talimatı (sistem promptu). Boşsa çıktı türünün varsayılan talimatı kullanılır.
    role: str = ""
    local_model: str = Field(description="config/models.yaml içindeki model anahtarı")
    # Claude modu açıkken bu ajanın Claude karşılığı (Adım 3e'de alt ajan dosyası üretilir).
    # none: Claude karşılığı yok, her zaman yerel.
    claude_tier: Literal["none", "haiku", "sonnet", "opus"] = "none"
    # Claude alt ajanının talimatı (isteğe bağlı). Yerel `role` kullanılmaz: yerel talimat "yerel çalışıyorsun,
    # kod çalıştıramazsın" gibi Claude için yanlış bilgiler içerir. Boşsa açıklamadan genel bir rol üretilir.
    claude_role: str = ""
    permissions: list[str] = Field(default_factory=lambda: [Permission.LLM_INFERENCE.value])
    limits: AgentLimits = Field(default_factory=AgentLimits)
    review: AgentReview = Field(default_factory=AgentReview)
    # permanent: sisteme kayıtlı; temporary: şefin bir iş için oluşturduğu geçici ajan (D9)
    status: Literal["permanent", "temporary"] = "permanent"

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - _VALID_PERMISSIONS)
        if unknown:
            raise ValueError(f"bilinmeyen izin(ler): {unknown}; geçerli: {sorted(_VALID_PERMISSIONS)}")
        return v


def load_definitions(agents_dir: Path, registry: ModelRegistry) -> list[AgentDefinition]:
    """Klasördeki tüm *.yaml tanımlarını yükler ve doğrular. Hata varsa hangi dosyada olduğunu söyler."""
    if not agents_dir.is_dir():
        return []
    defs: list[AgentDefinition] = []
    for path in sorted(agents_dir.glob("*.yaml")):
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            d = AgentDefinition.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise AgentDefinitionError(f"{path.name}: {exc}") from exc
        if d.name != path.stem:
            raise AgentDefinitionError(f"{path.name}: 'name' ({d.name}) dosya adıyla aynı olmalı")
        try:
            spec = registry.get(d.local_model)
        except KeyError as exc:
            raise AgentDefinitionError(f"{path.name}: {exc}") from exc
        if spec.status == "candidate":
            raise AgentDefinitionError(
                f"{path.name}: '{d.local_model}' aday model; benchmark'tan geçmeden ajana atanamaz"
            )
        defs.append(d)
    names = [d.name for d in defs]
    if len(names) != len(set(names)):
        raise AgentDefinitionError(f"aynı adla birden fazla ajan: {names}")
    check_review_links(defs)
    return defs


def check_review_links(defs: list[AgentDefinition]) -> None:
    """review.required olan ajanın gözden geçiricisi var olmalı ve 'review' çıktılı olmalı."""
    by_name = {d.name: d for d in defs}
    for d in defs:
        if not d.review.required:
            continue
        if d.output != "answer":
            raise AgentDefinitionError(f"{d.name}.yaml: yalnızca 'answer' çıktılı ajanlar gözden geçirilebilir")
        rv = by_name.get(d.review.reviewer)
        if rv is None or rv.output != "review":
            raise AgentDefinitionError(
                f"{d.name}.yaml: gözden geçirici '{d.review.reviewer}' tanımlı değil ya da 'review' çıktılı değil")
        if rv.name == d.name:
            raise AgentDefinitionError(f"{d.name}.yaml: ajan kendi kendini gözden geçiremez")


def make_worker(defn: AgentDefinition) -> LLMWorker:
    """Tanımdan yerel worker örneği üretir (çıktı türünün şeması ve doğrulaması korunur)."""
    base = OUTPUT_TYPES[defn.output]

    class DefinedWorker(base):  # type: ignore[valid-type, misc]
        name: ClassVar[str] = defn.name
        description: ClassVar[str] = defn.description
        required_permissions: ClassVar[tuple[Permission, ...]] = tuple(Permission(p) for p in defn.permissions)
        system_prompt: ClassVar[str] = defn.role.strip() or base.system_prompt
        definition: ClassVar[AgentDefinition] = defn

        def model_spec(self, registry: ModelRegistry) -> ModelSpec:
            return registry.get(defn.local_model)

    DefinedWorker.__name__ = DefinedWorker.__qualname__ = f"Agent_{defn.name}"
    return DefinedWorker()


def make_check_worker(defn: AgentDefinition) -> LLMWorker:
    """'review' çıktılı ajandan kanıta dayalı adım incelemesi yapan iç worker (`<ad>.check`)."""

    class CheckWorker(StepReviewWorker):
        name: ClassVar[str] = f"{defn.name}.check"
        definition: ClassVar[AgentDefinition] = defn

        def model_spec(self, registry: ModelRegistry) -> ModelSpec:
            return registry.get(defn.local_model)

    CheckWorker.__name__ = CheckWorker.__qualname__ = f"Check_{defn.name}"
    return CheckWorker()


def make_revision_worker(defn: AgentDefinition) -> LLMWorker:
    """Ajanın kendi rolü + revizyon kurallarıyla düzelt/itiraz et worker'ı (`<ad>.revise`)."""
    base_prompt = defn.role.strip() or OUTPUT_TYPES[defn.output].system_prompt

    class ReviseWorker(RevisionWorker):
        name: ClassVar[str] = f"{defn.name}.revise"
        required_permissions: ClassVar[tuple[Permission, ...]] = tuple(Permission(p) for p in defn.permissions)
        system_prompt: ClassVar[str] = base_prompt + RevisionWorker.REVISION_RULES
        definition: ClassVar[AgentDefinition] = defn

        def model_spec(self, registry: ModelRegistry) -> ModelSpec:
            return registry.get(defn.local_model)

    ReviseWorker.__name__ = ReviseWorker.__qualname__ = f"Revise_{defn.name}"
    return ReviseWorker()


def register_definition(reg: Any, defn: AgentDefinition) -> None:  # reg: WorkerRegistry
    reg.register(make_worker(defn))
    if defn.output == "review":
        reg.register(make_check_worker(defn), internal=True)
    if defn.review.required:
        reg.register(make_revision_worker(defn), internal=True)


def build_workers(agents_dir: Path, registry: ModelRegistry):  # -> WorkerRegistry
    from ..workers import WorkerRegistry

    reg = WorkerRegistry()
    for d in load_definitions(agents_dir, registry):
        register_definition(reg, d)
    return reg
