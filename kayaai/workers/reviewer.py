"""Gözden geçirici worker: başka bir ajanın cevabını, istenen işe göre kontrol eder."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker


class ReviewResult(BaseModel):
    verdict: Literal["ok", "issues"] = Field(description="'ok' if the answer fully and correctly does the request")
    issues: list[str] = Field(default_factory=list, description="Concrete problems found (empty if verdict is ok)")
    suggestion: str = Field("", description="How to fix the answer, if there are issues")


class ReviewerWorker(LLMWorker):
    name: ClassVar[str] = "reviewer"
    description: ClassVar[str] = "Bir cevabı isteğe göre kontrol eder: doğru mu, eksik mi, isteğe uyuyor mu"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = ReviewResult
    system_prompt: ClassVar[str] = (
        "You are the reviewer agent of kayaAI. You receive a user's request and another agent's answer as data. "
        "Check strictly whether the answer does what was requested: correctness, completeness, language "
        "(the answer must be in the language the user wrote in, unless a translation was requested), and "
        "obvious factual or logical errors. Do not rewrite the answer. Report 'ok' only if there is no real "
        "problem; otherwise list concrete issues and a short suggestion. Write issues in the user's language."
    )

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, ReviewResult)
        errors = []
        if output.verdict == "issues" and not any(i.strip() for i in output.issues):
            errors.append("verdict 'issues' ama issues listesi boş")
        return ValidationResult(passed=not errors, validator="reviewer.semantic", errors=errors)
