"""Gözden geçirici worker: başka bir ajanın cevabını, istenen işe göre kontrol eder."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker


class ReviewResult(BaseModel):
    verdict: Literal["ok", "issues"] = Field(description="'ok' if every part of the request is answered in the right language")
    missing_parts: list[str] = Field(
        default_factory=list, description="Parts of the request that the answer does not contain at all"
    )
    issues: list[str] = Field(default_factory=list, description="Other clear problems (e.g. wrong language); not code style")
    suggestion: str = Field("", description="Short hint on how to complete the answer")


class ReviewerWorker(LLMWorker):
    name: ClassVar[str] = "reviewer"
    description: ClassVar[str] = "Bir cevabı isteğe göre kontrol eder: doğru mu, eksik mi, isteğe uyuyor mu"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = ReviewResult
    system_prompt: ClassVar[str] = (
        "You are the reviewer agent of kayaAI. You receive a user's request and another agent's answer as data. "
        "Your job is a COMPLETENESS check: split the request into its parts (e.g. 'write code', 'explain it', "
        "'suggest a commit message') and check that each part is present in the answer. Put every part that is "
        "missing into missing_parts. Also check the language: the answer must be in the user's language unless "
        "another language or a translation was requested. "
        "Do NOT judge code correctness, style or best practices — you cannot run the code and such judgements "
        "are unreliable. Do not rewrite the answer. Report 'ok' if all parts are present. "
        "Write missing_parts and issues in the user's language."
    )

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, ReviewResult)
        errors = []
        if output.verdict == "issues" and not any(i.strip() for i in [*output.issues, *output.missing_parts]):
            errors.append("verdict 'issues' ama missing_parts ve issues boş")
        return ValidationResult(passed=not errors, validator="reviewer.semantic", errors=errors)
