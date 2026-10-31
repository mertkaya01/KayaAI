"""Genel Zeka Worker'ı: Türkçe/İngilizce sohbet, özet, planlama, sınıflandırma."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker


class GeneralAnswer(BaseModel):
    answer: str = Field(description="Kullanıcıya verilecek yanıt, kullanıcının dilinde")
    language: Literal["tr", "en", "other"] = Field(description="Yanıtın dili")
    task_type: Literal["question", "summary", "plan", "translation", "classification", "chat", "other"] = Field(
        description="İsteğin türü"
    )
    confidence: float = Field(ge=0, le=1, description="Yanıta güven, 0-1 arası")
    needs_tools: list[str] = Field(
        default_factory=list,
        description="Yanıt için gerekli olup bu worker'da olmayan yetenekler (ör. web, dosya, ekran)",
    )


class GeneralWorker(LLMWorker):
    name: ClassVar[str] = "general"
    description: ClassVar[str] = "Genel akıl yürütme, Türkçe/İngilizce sohbet, özet, planlama, görev sınıflandırma"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = GeneralAnswer
    system_prompt: ClassVar[str] = (
        "Sen kayaAI'nin genel zeka worker'ısın. Kullanıcının bilgisayarında yerel çalışıyorsun. "
        "Kullanıcı hangi dilde yazdıysa o dilde yanıt ver (varsayılan Türkçe). "
        "Kısa, doğru ve dürüst ol. Bilmediğin şeyi uydurma; emin değilsen confidence değerini düşür. "
        "İnternete, dosyalara veya ekrana erişimin YOK; bunlar gerekiyorsa needs_tools alanında belirt "
        "ve erişimin olmadığını açıkça söyle."
    )

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, GeneralAnswer)
        errors = []
        if not output.answer.strip():
            errors.append("answer boş")
        return ValidationResult(passed=not errors, validator="general.semantic", errors=errors)
