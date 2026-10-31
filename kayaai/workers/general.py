"""Genel Zeka Worker'ı: Türkçe/İngilizce sohbet, özet, planlama, sınıflandırma."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.lang import LANGUAGE_NAMES, detect_language, expected_answer_language
from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker, WorkerContext


class GeneralAnswer(BaseModel):
    answer: str = Field(description="The answer for the user, in the user's language")
    language: Literal["tr", "en", "other"] = Field(description="Language of the answer text")
    task_type: Literal["question", "summary", "plan", "translation", "classification", "chat", "other"] = Field(
        description="Type of the user's request"
    )
    confidence: float = Field(ge=0, le=1, description="Confidence in the answer, 0-1")
    needs_tools: list[str] = Field(
        default_factory=list,
        description="Capabilities needed for a complete answer that this worker lacks (e.g. web, files, screen)",
    )


class GeneralWorker(LLMWorker):
    name: ClassVar[str] = "general"
    description: ClassVar[str] = "Genel akıl yürütme, Türkçe/İngilizce sohbet, özet, planlama, görev sınıflandırma"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = GeneralAnswer
    system_prompt: ClassVar[str] = (
        "You are the general intelligence worker of kayaAI, running locally on the user's own computer. "
        "Always answer in the SAME language the user wrote in: a question in English gets an answer in English, "
        "a question in Turkish gets an answer in Turkish, unless the user explicitly asks for another language "
        "or for a translation. Be concise, accurate and honest. Never invent facts; lower 'confidence' when unsure. "
        "You have NO access to the internet, files or the screen; if the request needs them, list them in "
        "'needs_tools' and say clearly that you cannot access them."
    )

    def postprocess(self, task: Task, output: BaseModel, ctx: WorkerContext) -> BaseModel:
        assert isinstance(output, GeneralAnswer)
        actual = detect_language(output.answer)
        if actual in LANGUAGE_NAMES and output.language != actual:
            # Etiket yanlışsa deterministik tespite göre düzelt ve kayda geçir (sessizce değil).
            ctx.metrics.setdefault("corrections", []).append(f"language {output.language} -> {actual}")
            output = output.model_copy(update={"language": actual})
        return output

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, GeneralAnswer)
        errors = []
        if not output.answer.strip():
            errors.append("answer boş")
        expected = expected_answer_language(task.objective)
        actual = detect_language(output.answer)
        if (
            output.task_type != "translation"
            and expected in LANGUAGE_NAMES
            and actual in LANGUAGE_NAMES
            and actual != expected
        ):
            errors.append(
                f"answer dili yanlış: kullanıcı {LANGUAGE_NAMES[expected]} yazdı, cevap {LANGUAGE_NAMES[actual]}. "
                f"Cevabı {LANGUAGE_NAMES[expected]} yaz."
            )
        return ValidationResult(passed=not errors, validator="general.semantic", errors=errors)
