"""Sohbetten "hatırla: …" denildiğinde metni kısa, bağımsız bir hafıza notuna çevirir ve sınıflandırır.

Hassasiyet "secret" modele bırakılmaz: gizli bilgi KODLA tespit edilir (secrets.py) ve saklanmaz.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from ..llm.registry import ModelRegistry
from ..workers.base import LLMWorker
from ..workers.general import foreign_script_errors


class MemoryNote(BaseModel):
    text: str = Field(description="One short standalone sentence with the fact to remember, in the user's language, "
                                  "keeping every concrete detail (names, numbers, dates)")
    category: Literal["preference", "project", "decision", "instruction", "file", "note"] = Field(
        description="preference = likes/habits; project = a project and its details; decision = a decision taken; "
                    "instruction = how the assistant should behave; file = where something is stored; note = other")
    sensitivity: Literal["public", "personal", "private"] = Field(
        description="public = general/harmless; personal = about the user but not sensitive; private = health, "
                    "finance, family, address, phone, identity numbers or anything the user would not share")


class MemoryClassifierWorker(LLMWorker):
    name: ClassVar[str] = "memory.classify"
    description: ClassVar[str] = "Hatırlanacak bilgiyi kısa bir nota çevirir ve sınıflandırır"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = MemoryNote
    system_prompt: ClassVar[str] = (
        "You are the memory clerk of kayaAI, the user's local personal assistant. The user asked you to remember "
        "something. Rewrite it as ONE short standalone sentence that will still make sense months later "
        "(e.g. 'Kahvemi şekersiz içerim.' / 'Proje X'in son teslim tarihi 15 Kasım.'). Keep every concrete detail; "
        "do not add anything. Choose the category and sensitivity. Never include greetings or the word 'hatırla'."
    )

    def model_spec(self, registry: ModelRegistry):  # -> ModelSpec
        return registry.model_for_worker("general")

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, MemoryNote)
        errors = []
        if not output.text.strip():
            errors.append("text boş")
        elif len(output.text) > 1000:
            errors.append("text 1000 karakterden uzun")
        errors += foreign_script_errors(task, output.text)
        return ValidationResult(passed=not errors, validator="memory.classify", errors=errors)
