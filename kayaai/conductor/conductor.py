"""Yerel şef (Adım 3c): planla → (Claude yönlendirmesi) → yürüt → birleştir → gözden geçir.

MASTER_PROMPT v2:
- D15: her modda önce yerel; Claude yalnızca gerçekten gerekiyorsa (planlayıcının görüşü, kullanıcının
  isteği ya da yerel sonucun üretilememesi) ve Claude modu açıksa → Claude kutusu (waiting_claude).
- D16: Claude gerekir ama Claude kapalı → yerelde yap, açık bir kalite uyarısı ekle.
- Doğrulanmamış hiçbir sonuç başarılı sayılmaz; her yönlendirme kararı sebebiyle kayda geçer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.lang import detect_language
from ..core.task import Task, TaskStatus, ValidationResult, utcnow
from ..runtime import Runtime
from ..workers.planner import FORBIDDEN_STEP_AGENTS, RoutePlan
from .complexity import complexity_signals

log = logging.getLogger(__name__)

Force = Literal["local", "claude"] | None
Origin = Literal["user", "claude"]

CLAUDE_WARNING_TR = "Bu iş Claude ile muhtemelen daha iyi olurdu (Claude modu kapalı, yerel modelle yapıldı)."
CLAUDE_WARNING_EN = "This task would likely be done better by Claude (Claude mode is off; done with the local model)."


class StepView(BaseModel):
    id: str
    agent: str
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    task_id: str | None = None
    status: str = "pending"
    error: str | None = None


class Routing(BaseModel):
    needs_claude: bool = False
    reason: str = ""
    complexity_score: int = 0
    decision: Literal["local", "local_with_warning", "claude_inbox"] = "local"
    why: str = ""


class Review(BaseModel):
    performed: bool = False
    verdict: str | None = None
    missing_parts: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)  # tavsiye niteliğinde; düzeltme tetiklemez
    revised: bool = False  # eksik kısımlar eklendi mi


class ConductorResult(BaseModel):
    job_id: str
    status: str
    answer: str = ""
    mode: Literal["direct", "plan"] = "direct"
    steps: list[StepView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    routing: Routing = Field(default_factory=Routing)
    review: Review = Field(default_factory=Review)
    duration_s: float | None = None
    error: str | None = None


def _lang_note(request: str, tr: str, en: str) -> str:
    return en if detect_language(request) == "en" else tr


class Conductor:
    def __init__(self, runtime: Runtime):
        self.rt = runtime
        self.settings = runtime.settings.conductor

    # ------------------------------------------------------------------ giriş noktası

    def run(self, request: str, *, force: Force = None, origin: Origin = "user") -> ConductorResult:
        request = request.strip()
        if not request:
            raise ValueError("istek boş olamaz")
        t0 = time.perf_counter()
        job = Task(worker="conductor", objective=request, status=TaskStatus.RUNNING, started_at=utcnow(),
                   expected_output="ConductorResult", input={"force": force, "origin": origin})
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, "submitted", {"origin": origin, "force": force})
        result = ConductorResult(job_id=job.id, status="running")
        try:
            self._run(job, request, force, origin, result)
        except Exception as exc:  # noqa: BLE001 - iş kaydı her durumda kapanmalı
            log.exception("şef işi %s beklenmeyen hata", job.id)
            result.status, result.error = TaskStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
        result.duration_s = round(time.perf_counter() - t0, 3)
        self._close_job(job, result)
        return result

    # ------------------------------------------------------------------ akış

    def _run(self, job: Task, request: str, force: Force, origin: Origin, result: ConductorResult) -> None:
        plan = self._plan(job, request, result)
        result.mode = plan.mode
        result.steps = self._steps_of(plan, request)

        # Claude yönlendirmesi (D15/D16)
        result.routing = self._route(plan, force, origin, request)
        self.rt.store.log_event(job.id, "routing.decision", result.routing.model_dump())
        if result.routing.decision == "claude_inbox":
            result.status = TaskStatus.WAITING_CLAUDE.value
            result.warnings.append("İş Claude kutusuna bırakıldı; Claude Code oturumunda işlenecek (kutu araçları Adım 3d).")
            return
        if result.routing.decision == "local_with_warning":
            result.warnings.append(_lang_note(request, CLAUDE_WARNING_TR, CLAUDE_WARNING_EN))

        # Yürütme
        outputs = self._execute(job, result.steps)
        succeeded = [s for s in result.steps if s.status == TaskStatus.SUCCEEDED.value]
        if not succeeded:
            self._fail_or_escalate(result, request, "hiçbir adım başarılı olmadı")
            return
        if len(succeeded) < len(result.steps):
            result.warnings.append(f"{len(result.steps) - len(succeeded)} adım başarısız oldu; cevap eksik olabilir.")

        # Birleştirme: tek adımlıysa adımın cevabı nihaidir. Çok adımlıysa varsayılan "assemble":
        # adım cevapları başlıklarla sırayla (LLM'siz, bilgi kaybı yok). "llm": genel ajan yeniden yazar.
        if len(result.steps) == 1:
            answer = self._answer_of(outputs[succeeded[0].id])
        elif self.settings.merge == "assemble":
            answer = self._assemble(result.steps, outputs, request)
        else:
            merged = self._ask(job, "general", self._merge_objective(request), {"step_results": outputs})
            if merged.status != TaskStatus.SUCCEEDED:
                self._fail_or_escalate(result, request, f"birleştirme başarısız: {merged.error}")
                return
            answer = self._answer_of(merged.result)

        # Gözden geçirme: eksik kısım varsa tamamlanıp EKLENİR (mevcut cevap ezilmez)
        if self._should_review(plan):
            answer = self._review_loop(job, request, answer, result)
        result.answer = answer
        result.status = TaskStatus.SUCCEEDED.value if result.answer.strip() else TaskStatus.FAILED.value
        if not result.answer.strip():
            result.error = "boş cevap"

    # ------------------------------------------------------------------ plan

    def _agents_for_planner(self) -> list[dict[str, str]]:
        return [
            {"name": w.name, "description": w.description}
            for w in self.rt.workers.all()
            if w.name not in FORBIDDEN_STEP_AGENTS
        ]

    def _plan(self, job: Task, request: str, result: ConductorResult) -> RoutePlan:
        if "planner" not in self.rt.workers:
            result.warnings.append("planlayıcı ajan tanımlı değil; tek ajanla cevaplandı")
            return RoutePlan(mode="direct", agent="general")
        task = self._ask(job, "planner", request, {"agents": self._agents_for_planner(), "max_steps": self.settings.max_steps})
        if task.status != TaskStatus.SUCCEEDED or not task.result:
            result.warnings.append("Plan yapılamadı; istek genel ajanla tek adımda cevaplandı.")
            self.rt.store.log_event(job.id, "plan.fallback", {"error": task.error})
            return RoutePlan(mode="direct", agent="general")
        plan = RoutePlan.model_validate(task.result)
        self.rt.store.log_event(job.id, "plan.created", plan.model_dump())
        return plan

    @staticmethod
    def _steps_of(plan: RoutePlan, request: str) -> list[StepView]:
        if plan.mode == "direct":
            return [StepView(id="s1", agent=plan.agent or "general", objective=request)]
        return [StepView(id=s.id, agent=s.agent, objective=s.objective, depends_on=list(s.depends_on)) for s in plan.steps]

    # ------------------------------------------------------------------ yönlendirme

    def _route(self, plan: RoutePlan, force: Force, origin: Origin, request: str) -> Routing:
        claude_on = bool(self.rt.claude and self.rt.claude.is_enabled())
        score, signals = complexity_signals(request, plan)
        by_signals = score >= self.settings.claude_threshold
        needs = plan.needs_claude or by_signals or force == "claude"
        reasons = []
        if plan.needs_claude:
            reasons.append(f"planlayıcı: {plan.claude_reason}")
        if by_signals:
            reasons.append(f"karmaşıklık sinyalleri (skor {score}): " + "; ".join(signals))
        if force == "claude":
            reasons.append("kullanıcı Claude istedi")
        r = Routing(needs_claude=needs, reason=" | ".join(reasons), complexity_score=score)
        if not needs:
            r.decision, r.why = "local", "yerel ajanlar yeterli (D15: önce yerel)"
        elif origin == "claude":
            r.decision, r.why = "local", "istek zaten Claude'dan geldi; yerel ekip çalışır, görüş uyarı olarak döner"
        elif force == "local":
            r.decision, r.why = "local_with_warning", "kullanıcı yerelde yapılmasını istedi"
        elif claude_on:
            r.decision, r.why = "claude_inbox", "Claude gerekli ve Claude modu açık"
        else:
            r.decision, r.why = "local_with_warning", "Claude gerekli ama Claude modu kapalı (D16)"
        return r

    # ------------------------------------------------------------------ yürütme

    def _execute(self, job: Task, steps: list[StepView]) -> dict[str, dict[str, Any]]:
        """Adımları plan sırasıyla çalıştırır (planlayıcı doğrulaması bağımlılıkların hep önce gelmesini garanti eder).

        Önceki adımların sonuçları, sonraki adıma `previous_results` olarak (güvenilmez veri) verilir.
        """
        outputs: dict[str, dict[str, Any]] = {}
        by_id = {s.id: s for s in steps}
        for s in steps:
            failed_deps = [d for d in s.depends_on if by_id[d].status != TaskStatus.SUCCEEDED.value]
            if failed_deps:
                s.status, s.error = TaskStatus.FAILED.value, f"bağımlılık başarısız: {failed_deps}"
                continue
            prev = {d: outputs[d] for d in s.depends_on}
            task = self._ask(job, s.agent, s.objective, {"previous_results": prev} if prev else {})
            s.task_id, s.status, s.error = task.id, task.status.value, task.error
            if task.status == TaskStatus.SUCCEEDED and task.result:
                outputs[s.id] = task.result
        return outputs

    def _ask(self, job: Task, worker: str, objective: str, input: dict[str, Any]) -> Task:
        task = self.rt.orchestrator.submit(objective, worker=worker, input=input or None, parent_id=job.id)
        return self.rt.orchestrator.run(task.id)

    @staticmethod
    def _answer_of(output: dict[str, Any] | None) -> str:
        if not output:
            return ""
        return str(output.get("answer", ""))

    @staticmethod
    def _heading(objective: str) -> str:
        first = objective.strip().splitlines()[0] if objective.strip() else ""
        first = first.split(". ")[0].rstrip(" .:;")
        return (first[:77] + "...") if len(first) > 80 else first

    def _assemble(self, steps: list[StepView], outputs: dict[str, dict[str, Any]], request: str) -> str:
        missing = _lang_note(request, "(bu kısım üretilemedi)", "(this part could not be produced)")
        parts = []
        for s in steps:
            body = self._answer_of(outputs.get(s.id)) if s.id in outputs else missing
            parts.append(f"### {self._heading(s.objective) or s.id}\n\n{body.strip()}")
        return "\n\n".join(parts)

    def _merge_objective(self, request: str) -> str:
        return request + "\n\n" + _lang_note(
            request,
            "(Not: Girdi verisindeki adım sonuçlarını kullanarak bu isteğe tek, eksiksiz bir nihai cevap yaz.)",
            "(Note: use the step results in the input data to write one complete final answer to this request.)",
        )

    # ------------------------------------------------------------------ gözden geçirme

    def _should_review(self, plan: RoutePlan) -> bool:
        mode = self.settings.review
        return mode == "always" or (mode == "plan" and plan.mode == "plan")

    def _review_loop(self, job: Task, request: str, answer: str, result: ConductorResult) -> str:
        """Gözden geçirici yalnızca eksiklik + dil kontrol eder (8B model kod doğruluğunu güvenilir yargılayamadı).

        missing_parts varsa: genel ajan eksik kısımları yazar ve cevaba "Ek" başlığıyla EKLENİR (en fazla
        max_revisions kez). Diğer notlar düzeltme tetiklemez; tek bir "doğrulanmadı" uyarısı olarak gösterilir.
        """
        if "reviewer" not in self.rt.workers:
            result.warnings.append("gözden geçirici ajan tanımlı değil; cevap kontrol edilmedi")
            return answer
        result.review.performed = True
        notes: list[str] = []
        for revision in range(self.settings.max_revisions + 1):
            review = self._ask(job, "reviewer", _lang_note(
                request, "Bu cevapta isteğin tüm parçalarının olup olmadığını kontrol et.",
                "Check whether every part of the request is present in this answer."),
                {"request": request, "answer": answer})
            if review.status != TaskStatus.SUCCEEDED or not review.result:
                result.warnings.append("Gözden geçirme yapılamadı; cevap kontrol edilmeden döndü.")
                return answer
            r = review.result
            self.rt.store.log_event(job.id, "review.result", r)
            result.review.verdict = r.get("verdict")
            result.review.missing_parts = [m for m in r.get("missing_parts", []) if str(m).strip()]
            result.review.issues = [i for i in r.get("issues", []) if str(i).strip()]
            notes = result.review.issues
            if not result.review.missing_parts or revision == self.settings.max_revisions:
                break
            extra = self._ask(job, "general", request + "\n\n" + _lang_note(
                request,
                "(Not: Mevcut cevapta eksik kalan kısımları yaz; zaten var olanları tekrarlama.)",
                "(Note: write only the parts that are missing from the current answer; do not repeat existing parts.)"),
                {"current_answer": answer, "missing_parts": result.review.missing_parts})
            text = self._answer_of(extra.result) if extra.status == TaskStatus.SUCCEEDED else ""
            if not text.strip():
                result.warnings.append("Eksik kısımlar tamamlanamadı.")
                break
            answer = f"{answer}\n\n### {_lang_note(request, 'Ek', 'Addendum')}\n\n{text.strip()}"
            result.review.revised = True
        if result.review.missing_parts and result.review.verdict != "ok":
            result.warnings.append(
                _lang_note(request, "Cevapta eksik kalmış olabilir: ", "The answer may still be missing: ")
                + "; ".join(result.review.missing_parts[:3]))
        if notes:
            result.warnings.append(
                _lang_note(request, "Gözden geçirici notları (doğrulanmadı): ", "Reviewer notes (unverified): ")
                + "; ".join(notes[:3]))
        return answer

    # ------------------------------------------------------------------ hata / kapanış

    def _fail_or_escalate(self, result: ConductorResult, request: str, why: str) -> None:
        if self.rt.claude and self.rt.claude.is_enabled():
            result.routing.decision = "claude_inbox"
            result.routing.why = f"yerel sonuç üretilemedi ({why}); Claude modu açık"
            result.status = TaskStatus.WAITING_CLAUDE.value
            result.warnings.append("Yerel ekip başaramadı; iş Claude kutusuna bırakıldı.")
        else:
            result.status, result.error = TaskStatus.FAILED.value, why

    def _close_job(self, job: Task, result: ConductorResult) -> None:
        job.status = TaskStatus(result.status)
        job.result = result.model_dump(mode="json")
        job.error = result.error
        job.validation = ValidationResult(
            passed=job.status == TaskStatus.SUCCEEDED, validator="conductor",
            errors=[result.error] if result.error else [],
        )
        if job.status != TaskStatus.WAITING_CLAUDE:
            job.finished_at = utcnow()
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, job.status.value, {"warnings": result.warnings, "duration_s": result.duration_s})
