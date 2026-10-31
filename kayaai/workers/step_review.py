"""Üretici → gözden geçirici akışı (Adım 7) için iki iç worker türü.

- StepReviewWorker (`<gözden geçirici>.check`): bir uzman ajanın cevabını isteğe göre inceler. Her sorun için cevaptan
  birebir alıntı (`evidence`) ister; alıntı cevapta geçmiyorsa sorun KODLA elenir (küçük modelin uydurduğu hataları
  ayıklamak için — gerçek ölçüm: 8B gözden geçirici var olmayan kod hataları bildirmişti).
- RevisionWorker (`<ajan>.revise`): üretici ajan sorunları alır; her birini kabul edip düzeltir ya da gerekçesiyle
  itiraz eder. İtiraz edilen sorun bir "anlaşmazlık" olur ve şef tarafından yükseltilir.

Bu worker'lar ajan tanımlarından türetilir (kayaai/agents/definitions.py); planlayıcıya ve arayüze görünmezler.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.lang import LANGUAGE_NAMES, detect_language, expected_answer_language
from ..core.task import Permission, Task, ValidationResult
from .base import LLMWorker, WorkerContext

Severity = Literal["blocker", "major", "minor"]
BLOCKING: frozenset[str] = frozenset({"blocker", "major"})
MIN_EVIDENCE_CHARS = 3


class ReviewIssue(BaseModel):
    severity: Severity = Field(description="blocker = answer is wrong/unusable; major = clear error that must be fixed; "
                                           "minor = small improvement")
    claim: str = Field(description="What exactly is wrong, in the user's language")
    evidence: str = Field(description="A short EXACT quote copied from the answer that shows the problem")


class StepReview(BaseModel):
    verdict: Literal["approve", "request_changes"] = Field(
        description="'approve' unless there is a blocker/major issue or a missing part")
    missing_parts: list[str] = Field(default_factory=list,
                                     description="Parts of the request that the answer does not contain at all")
    issues: list[ReviewIssue] = Field(default_factory=list, description="Concrete problems, each with an exact quote")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def evidence_in(evidence: str, answer: str) -> bool:
    ev = normalize(evidence).strip("\"'`“”‘’ ")
    return len(ev) >= MIN_EVIDENCE_CHARS and ev in normalize(answer)


class StepReviewWorker(LLMWorker):
    name: ClassVar[str] = "reviewer.check"
    description: ClassVar[str] = "Bir uzman ajanın cevabını kanıta dayalı inceler"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = StepReview
    system_prompt: ClassVar[str] = (
        "You are the reviewer agent of kayaAI. You receive a request and a specialist agent's answer as data, "
        "plus the results of automatic checks. Review the answer against the request:\n"
        "1. Completeness: list every part of the request that is missing from the answer in missing_parts.\n"
        "2. Clear errors: report only problems you are sure about (wrong facts, wrong calculation, code that "
        "clearly does not do what was asked, contradictions). For EACH issue copy a short EXACT quote from the "
        "answer into 'evidence'. Issues without an exact quote are discarded automatically.\n"
        "Do not report style preferences or alternative approaches as blocker/major. Do not rewrite the answer. "
        "If everything requested is present and correct, use verdict 'approve' with no blocker/major issues. "
        "Write claims and missing_parts in the user's language."
    )

    def postprocess(self, task: Task, output: BaseModel, ctx: WorkerContext) -> BaseModel:
        assert isinstance(output, StepReview)
        answer = str(task.input.get("answer", ""))
        kept = [i for i in output.issues if i.claim.strip() and evidence_in(i.evidence, answer)]
        dropped = len(output.issues) - len(kept)
        if dropped:
            # Sessizce değil: kaç sorunun kanıtsız olduğu ölçülür ve rapora girer.
            ctx.metrics["dropped_issues"] = ctx.metrics.get("dropped_issues", 0) + dropped
        missing = [m for m in output.missing_parts if m.strip()]
        blocking = missing or any(i.severity in BLOCKING for i in kept)
        verdict = "request_changes" if blocking else "approve"
        return output.model_copy(update={"issues": kept, "missing_parts": missing, "verdict": verdict})


class Dispute(BaseModel):
    id: str = Field(description="Id of the issue you disagree with (e.g. i1)")
    reason: str = Field(description="Why the issue is wrong, in the user's language")


class Revision(BaseModel):
    answer: str = Field(description="The full corrected answer (not only the changes), in the user's language")
    language: Literal["tr", "en", "other"] = Field(description="Language of the answer text")
    accepted: list[str] = Field(default_factory=list, description="Ids of the issues you accepted and fixed")
    disputed: list[Dispute] = Field(default_factory=list,
                                    description="Issues you believe are wrong, with your reason")


class RevisionWorker(LLMWorker):
    name: ClassVar[str] = "general.revise"
    description: ClassVar[str] = "Gözden geçirici sorunlarına göre cevabı düzeltir ya da itiraz eder"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = Revision
    REVISION_RULES: ClassVar[str] = (
        "\n\nREVISION MODE: the input data contains your previous answer ('current_answer') and the issues "
        "found by the reviewer and by automatic checks ('issues', each with an id). For each issue either fix it "
        "(put its id in 'accepted') or, if the reviewer is wrong, put it in 'disputed' with a clear reason. "
        "Every issue id must appear exactly once in accepted or disputed. Issues whose id starts with 'c' come "
        "from automatic checks (e.g. a syntax error) and are facts: they can only be accepted and fixed. "
        "Return the FULL corrected answer in 'answer'."
    )
    system_prompt: ClassVar[str] = "You are an agent of kayaAI." + REVISION_RULES

    def postprocess(self, task: Task, output: BaseModel, ctx: WorkerContext) -> BaseModel:
        assert isinstance(output, Revision)
        actual = detect_language(output.answer)
        if actual in LANGUAGE_NAMES and output.language != actual:
            output = output.model_copy(update={"language": actual})
        return output

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, Revision)
        ids = [str(i.get("id")) for i in task.input.get("issues", []) if isinstance(i, dict)]
        errors: list[str] = []
        if not output.answer.strip():
            errors.append("answer boş")
        seen: dict[str, int] = {}
        for x in [*output.accepted, *(d.id for d in output.disputed)]:
            seen[x] = seen.get(x, 0) + 1
        unknown = sorted(set(seen) - set(ids))
        if unknown:
            errors.append(f"bilinmeyen sorun id'leri: {unknown}; geçerli: {ids}")
        missing = [i for i in ids if i not in seen]
        if missing:
            errors.append(f"şu sorunlar ne kabul ne itiraz edildi: {missing}")
        doubled = sorted(k for k, v in seen.items() if v > 1)
        if doubled:
            errors.append(f"aynı sorun birden fazla kez: {doubled}")
        fact_disputes = [d.id for d in output.disputed if d.id.startswith("c")]
        if fact_disputes:
            errors.append(f"otomatik kontrol sonuçlarına itiraz edilemez, düzeltilmeli: {fact_disputes}")
        if any(not d.reason.strip() for d in output.disputed):
            errors.append("itirazın gerekçesi boş")
        expected = expected_answer_language(task.objective)
        actual = detect_language(output.answer)
        if expected in LANGUAGE_NAMES and actual in LANGUAGE_NAMES and actual != expected:
            errors.append(f"answer dili yanlış: cevabı {LANGUAGE_NAMES[expected]} yaz")
        return ValidationResult(passed=not errors, validator="revision.semantic", errors=errors)


def issue_payload(review: dict[str, Any], check_failures: list[dict[str, str]]) -> list[dict[str, str]]:
    """Revizyona gidecek sorun listesi (id'li): c* = otomatik kontrol, m* = eksik kısım, i* = gözden geçirici."""
    out: list[dict[str, str]] = []
    for n, f in enumerate(check_failures, 1):
        out.append({"id": f"c{n}", "severity": "blocker", "source": "check", "claim": f["message"], "evidence": ""})
    for n, m in enumerate(review.get("missing_parts", []), 1):
        out.append({"id": f"m{n}", "severity": "major", "source": "reviewer", "claim": f"Eksik: {m}", "evidence": ""})
    n = 0
    for i in review.get("issues", []):
        if i.get("severity") in BLOCKING:
            n += 1
            out.append({"id": f"i{n}", "severity": i["severity"], "source": "reviewer",
                        "claim": i.get("claim", ""), "evidence": i.get("evidence", "")})
    return out
