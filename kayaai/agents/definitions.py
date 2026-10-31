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
from ..workers.reviewer import ReviewerWorker

# Çıktı türü -> temel worker sınıfı (şema + anlamsal doğrulama oradan gelir)
OUTPUT_TYPES: dict[str, type[LLMWorker]] = {
    "answer": GeneralWorker,
    "review": ReviewerWorker,
}
_VALID_PERMISSIONS = {p.value for p in Permission}


class AgentDefinitionError(ValueError):
    pass


class AgentLimits(BaseModel):
    timeout_s: float | None = Field(None, gt=0, le=600)


class AgentDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    description: str
    output: Literal["answer", "review"] = "answer"
    # Rol talimatı (sistem promptu). Boşsa çıktı türünün varsayılan talimatı kullanılır.
    role: str = ""
    local_model: str = Field(description="config/models.yaml içindeki model anahtarı")
    # Claude modu açıkken bu ajanın Claude karşılığı (Adım 3e'de alt ajan dosyası üretilir).
    # none: Claude karşılığı yok, her zaman yerel.
    claude_tier: Literal["none", "haiku", "sonnet", "opus"] = "none"
    permissions: list[str] = Field(default_factory=lambda: [Permission.LLM_INFERENCE.value])
    limits: AgentLimits = Field(default_factory=AgentLimits)
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
    return defs


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


def build_workers(agents_dir: Path, registry: ModelRegistry):  # -> WorkerRegistry
    from ..workers import WorkerRegistry

    reg = WorkerRegistry()
    for d in load_definitions(agents_dir, registry):
        reg.register(make_worker(d))
    return reg
