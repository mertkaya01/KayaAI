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
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.disputes import DisputeRecord
from ..core.lang import detect_language
from ..core.task import Task, TaskStatus, ValidationResult, utcnow
from ..runtime import Runtime
from ..workers.planner import FORBIDDEN_STEP_AGENTS, RoutePlan
from ..workers.step_review import issue_payload
from .checks import CheckReport, run_checks
from ..core.lang import mentions_target_language
from .complexity import complexity_signals
from .coverage import missing_topics

log = logging.getLogger(__name__)

Force = Literal["local", "claude"] | None
Origin = Literal["user", "claude"]

CLAUDE_WARNING_TR = "Bu iş Claude ile muhtemelen daha iyi olurdu (Claude modu kapalı, yerel modelle yapıldı)."
CLAUDE_WARNING_EN = "This task would likely be done better by Claude (Claude mode is off; done with the local model)."


class StepReviewView(BaseModel):
    """Üretici → gözden geçirici akışının özeti (Adım 7)."""

    reviewer: str
    verdict: str | None = None
    issues: list[str] = Field(default_factory=list)          # "major: iddia"
    missing_parts: list[str] = Field(default_factory=list)
    dropped_issues: int = 0                                   # kanıtı cevapta olmadığı için elenen
    checks: CheckReport | None = None
    revised: bool = False
    accepted: list[str] = Field(default_factory=list)
    disputes: list[str] = Field(default_factory=list)        # anlaşmazlık kayıt id'leri
    unresolved_checks: list[str] = Field(default_factory=list)
    skipped: str | None = None


class StepView(BaseModel):
    id: str
    agent: str
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    task_id: str | None = None
    status: str = "pending"
    error: str | None = None
    review: StepReviewView | None = None


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
    uncovered_topics: list[str] = Field(default_factory=list)  # kodla kapsam kontrolü (coverage.py)
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


@dataclass
class _Run:
    """Tek bir şef işinin yürütme bağlamı."""

    job: Task
    request: str
    force: Force
    origin: Origin
    result: ConductorResult
    deadline: float
    disputes: list[DisputeRecord] = field(default_factory=list)
    # Adım 8: sohbet bağlamı (önceki mesajlar, ek içerikleri) — adımlara güvenilmez veri olarak verilir
    context: dict[str, Any] = field(default_factory=dict)

    def over_budget(self) -> bool:
        return time.monotonic() > self.deadline


class Conductor:
    def __init__(self, runtime: Runtime):
        self.rt = runtime
        self.settings = runtime.settings.conductor

    # ------------------------------------------------------------------ giriş noktası

    def run(self, request: str, *, force: Force = None, origin: Origin = "user",
            context: dict[str, Any] | None = None) -> ConductorResult:
        return self.run_job(self.create_job(request, force=force, origin=origin, context=context))

    def create_job(self, request: str, *, force: Force = None, origin: Origin = "user",
                   context: dict[str, Any] | None = None) -> Task:
        """İş kaydını oluşturur (API arka planda çalıştırmadan önce iş numarasını hemen döndürebilsin diye)."""
        request = request.strip()
        if not request:
            raise ValueError("istek boş olamaz")
        job = Task(worker="conductor", objective=request, status=TaskStatus.PENDING,
                   expected_output="ConductorResult",
                   input={"force": force, "origin": origin, **({"context": context} if context else {})})
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, "submitted", {"origin": origin, "force": force})
        return job

    def run_job(self, job: Task) -> ConductorResult:
        job.status, job.started_at = TaskStatus.RUNNING, utcnow()
        self.rt.store.save(job)
        return self._execute_job(job, job.objective, job.input.get("force"), job.input.get("origin", "user"))

    def resume_local(self, job_id: str) -> ConductorResult:
        """Claude kutusunda bekleyen işi AYNI iş kaydında yerel ekiple tamamlar (D16 uyarısıyla)."""
        job = self.rt.store.get(job_id)
        if job is None or job.worker != "conductor":
            raise KeyError(f"Şef işi bulunamadı: {job_id}")
        if job.status != TaskStatus.WAITING_CLAUDE:
            raise ValueError(f"İş Claude kutusunda değil (durum: {job.status.value})")
        job.status = TaskStatus.RUNNING
        self.rt.store.save(job)
        self.rt.store.log_event(job.id, "claude.released", {"to": "local"})
        result = self._execute_job(job, job.objective, "local", "user", released=True)
        return result

    def _execute_job(
        self, job: Task, request: str, force: Force, origin: Origin, released: bool = False
    ) -> ConductorResult:
        t0 = time.perf_counter()
        result = ConductorResult(job_id=job.id, status="running")
        if released:
            result.warnings.append(_lang_note(
                request, "Claude kutusundan yerel ekibe geri verildi.", "Handed back from the Claude inbox to the local team."))
        try:
            if released and self.rt.disputes:
                self.rt.disputes.close_for_job(job.id, "superseded", "kayaai", "iş yerel ekiple yeniden yapıldı")
            self._run(job, request, force, origin, result)
        except Exception as exc:  # noqa: BLE001 - iş kaydı her durumda kapanmalı
            log.exception("şef işi %s beklenmeyen hata", job.id)
            result.status, result.error = TaskStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
        if released and result.status == TaskStatus.SUCCEEDED.value:
            warning = _lang_note(request, CLAUDE_WARNING_TR, CLAUDE_WARNING_EN)
            if warning not in result.warnings:
                result.warnings.append(warning)  # D16: Claude gerekli görülmüştü
        result.duration_s = round(time.perf_counter() - t0, 3)
        self._close_job(job, result)
        return result

    # ------------------------------------------------------------------ akış

    def _run(self, job: Task, request: str, force: Force, origin: Origin, result: ConductorResult) -> None:
        run = _Run(job, request, force, origin, result, time.monotonic() + self.settings.time_budget_s,
                   context=dict(job.input.get("context") or {}))
        plan = self._plan(job, request, result, run.context)
        result.mode = plan.mode
        result.steps = self._steps_of(plan, request)

        # Claude yönlendirmesi (D15/D16)
        result.routing = self._route(plan, force, origin, request)
        self.rt.store.log_event(job.id, "routing.decision", result.routing.model_dump())
        if result.routing.decision == "claude_inbox":
            result.status = TaskStatus.WAITING_CLAUDE.value
            result.warnings.append(_lang_note(
                request,
                "İş Claude kutusuna bırakıldı: Claude Code oturumunda işlenir (kayaai inbox ile görebilir, "
                "kayaai inbox run <id> ile yerelde yaptırabilirsin).",
                "The job was left in the Claude inbox: a Claude Code session will process it "
                "(see it with kayaai inbox, run it locally with kayaai inbox run <id>)."))
            return
        if result.routing.decision == "local_with_warning":
            result.warnings.append(_lang_note(request, CLAUDE_WARNING_TR, CLAUDE_WARNING_EN))

        # Yürütme
        outputs = self._execute(run)
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
        topics = [] if mentions_target_language(request) else list(plan.key_topics)
        if self._should_review(plan):
            answer = self._review_loop(job, request, answer, result, topics)
        result.review.uncovered_topics = missing_topics(topics, answer)
        if result.review.uncovered_topics:
            result.warnings.append(_lang_note(
                request,
                "Cevap şu konulara yeterince değinmiyor olabilir (kodla kontrol edildi): ",
                "The answer may not really cover these topics (checked by code): ")
                + "; ".join(result.review.uncovered_topics))
        result.answer = answer
        result.status = TaskStatus.SUCCEEDED.value if result.answer.strip() else TaskStatus.FAILED.value
        if not result.answer.strip():
            result.error = "boş cevap"
        elif run.disputes:
            self._escalate_disputes(run)
        self.rt.store.emit("decision.summary", {
            "job_id": job.id, "status": result.status, "mode": result.mode, "decision": result.routing.decision,
            "steps": len(result.steps), "reviewed_steps": sum(1 for s in result.steps if s.review),
            "revised_steps": sum(1 for s in result.steps if s.review and s.review.revised),
            "disputes": len(run.disputes), "warnings": len(result.warnings),
        }, task_id=job.id)
    # ------------------------------------------------------------------ plan

    def _agents_for_planner(self) -> list[dict[str, str]]:
        return [
            {"name": w.name, "description": w.description}
            for w in self.rt.workers.all()
            if w.name not in FORBIDDEN_STEP_AGENTS
        ]

    def _plan(self, job: Task, request: str, result: ConductorResult,
              context: dict[str, Any] | None = None) -> RoutePlan:
        if "planner" not in self.rt.workers:
            result.warnings.append("planlayıcı ajan tanımlı değil; tek ajanla cevaplandı")
            return RoutePlan(mode="direct", agent="general")
        from ..agents.lifecycle import sync_user_agents

        sync_user_agents(self.rt)  # başka süreçte (MCP/CLI) oluşturulan ajanları da gör
        planner_input: dict[str, Any] = {
            "agents": self._agents_for_planner(), "max_steps": self.settings.max_steps,
            "allow_new_agent": self._new_agents_allowed()}
        if context:
            # Yönlendirme için: kısa sohbet geçmişi ("bunu Python'a çevir" gibi devam mesajları) ve ek ADLARI
            planner_input["conversation"] = context.get("conversation", [])[-4:]
            planner_input["attachment_names"] = [a.get("name") for a in context.get("attachments", [])]
        task = self._ask(job, "planner", request, planner_input)
        if task.status != TaskStatus.SUCCEEDED or not task.result:
            result.warnings.append("Plan yapılamadı; istek genel ajanla tek adımda cevaplandı.")
            self.rt.store.log_event(job.id, "plan.fallback", {"error": task.error})
            return RoutePlan(mode="direct", agent="general")
        plan = RoutePlan.model_validate(task.result)
        self.rt.store.log_event(job.id, "plan.created", plan.model_dump())
        if plan.new_agent is not None:
            plan = self._adopt_new_agent(job, plan, result)
        return plan

    def _new_agents_allowed(self) -> bool:
        if not self.settings.allow_temp_agents or self.settings.max_temp_agents == 0:
            return False
        temp = [w for w in self.rt.workers.all()
                if (d := getattr(w, "definition", None)) is not None and d.status == "temporary"]
        return len(temp) < self.settings.max_temp_agents

    def _adopt_new_agent(self, job: Task, plan: RoutePlan, result: ConductorResult) -> RoutePlan:
        """Planlayıcının önerdiği geçici ajanı oluşturur; olmazsa adımlar temel ajana döner (iş durmaz)."""
        from ..agents.lifecycle import AgentLifecycleError, AgentProposal, create_temporary

        na = plan.new_agent
        assert na is not None
        planner = self.rt.workers.get("planner")
        ceiling = {p.value for p in planner.required_permissions}
        try:
            defn = create_temporary(self.rt, AgentProposal(name=na.name, description=na.description, role=na.role,
                                                           base=na.base), created_by="planner", ceiling=ceiling)
            result.warnings.append(_lang_note(
                job.objective,
                f"Yeni geçici ajan oluşturuldu: {defn.name} ({defn.description}). Kalıcı yapmak için: "
                f"kayaai agents promote {defn.name}",
                f"New temporary agent created: {defn.name}. To make it permanent: kayaai agents promote {defn.name}"))
            self.rt.store.log_event(job.id, "agent.created", {"name": defn.name, "base": na.base})
            return plan
        except (AgentLifecycleError, ValueError) as exc:
            result.warnings.append(f"Geçici ajan oluşturulamadı ({exc}); '{na.base}' ajanı kullanıldı.")
            agent = plan.agent if plan.agent != na.name else na.base
            steps = [s.model_copy(update={"agent": na.base if s.agent == na.name else s.agent}) for s in plan.steps]
            return plan.model_copy(update={"agent": agent, "steps": steps, "new_agent": None})

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

    def _execute(self, run: _Run) -> dict[str, dict[str, Any]]:
        """Adımları plan sırasıyla çalıştırır (planlayıcı doğrulaması bağımlılıkların hep önce gelmesini garanti eder).

        Önceki adımların sonuçları, sonraki adıma `previous_results` olarak (güvenilmez veri) verilir.
        Ajan tanımında `review.required` varsa her adım gözden geçirilir (`_review_step`).
        """
        job, steps = run.job, run.result.steps
        outputs: dict[str, dict[str, Any]] = {}
        by_id = {s.id: s for s in steps}
        for s in steps:
            failed_deps = [d for d in s.depends_on if by_id[d].status != TaskStatus.SUCCEEDED.value]
            if failed_deps:
                s.status, s.error = TaskStatus.FAILED.value, f"bağımlılık başarısız: {failed_deps}"
                continue
            prev = {d: outputs[d] for d in s.depends_on}
            objective = s.objective
            if prev:
                # Gerçek ölçüm: adımlar önceki sonuçları baştan tekrar yazıyordu (aynı içerik 3 bölümde).
                objective += "\n\n" + _lang_note(
                    s.objective,
                    "(Not: Önceki adımların sonuçları girdi verisinde. Onları tekrarlama; yalnızca bu adımın kendi kısmını yaz.)",
                    "(Note: earlier step results are in the input data. Do not repeat them; write only this step's own part.)")
            task = self._ask(job, s.agent, objective,
                             {**run.context, **({"previous_results": prev} if prev else {})})
            s.task_id, s.status, s.error = task.id, task.status.value, task.error
            if task.status == TaskStatus.SUCCEEDED and task.result:
                outputs[s.id] = self._review_step(run, s, task.result)
        return outputs

    # ------------------------------------------------------------------ üretici → gözden geçirici (Adım 7)

    def _review_step(self, run: _Run, s: StepView, output: dict[str, Any]) -> dict[str, Any]:
        """Kontroller → gözden geçirme → (gerekirse) bir tur revizyon → itirazlar anlaşmazlık olur."""
        defn = getattr(self.rt.workers.get(s.agent), "definition", None)
        if defn is None or not defn.review.required or self.settings.review == "never":
            return output
        req, job, result = run.request, run.job, run.result
        view = StepReviewView(reviewer=defn.review.reviewer)
        s.review = view
        if run.over_budget():
            view.skipped = "zaman bütçesi doldu"
            result.warnings.append(_lang_note(req, f"{s.agent} cevabı zaman bütçesi dolduğu için gözden geçirilmedi.",
                                              f"The {s.agent} answer was not reviewed: time budget exhausted."))
            return output
        answer = self._answer_of(output)
        view.checks = run_checks(answer, list(defn.review.checks))
        check_worker = f"{defn.review.reviewer}.check"
        review: dict[str, Any] = {}
        if check_worker in self.rt.workers:
            rv = self._ask(job, check_worker, _lang_note(
                s.objective, "Bu cevabı isteğe göre incele: eksik kısımlar ve kanıtlı hatalar.",
                "Review this answer against the request: missing parts and errors with evidence."),
                {"request": s.objective, "answer": answer,
                 "automatic_checks": [f.message for f in view.checks.failures],
                 **({"source_context": run.context} if run.context else {})})
            if rv.status == TaskStatus.SUCCEEDED and rv.result:
                review = rv.result
                view.verdict = review.get("verdict")
                view.missing_parts = list(review.get("missing_parts", []))
                view.issues = [f"{i.get('severity')}: {i.get('claim')}" for i in review.get("issues", [])]
                view.dropped_issues = int(rv.metrics.get("dropped_issues", 0))
            else:
                view.skipped = "gözden geçirme yapılamadı"
                result.warnings.append(_lang_note(req, f"{s.agent} cevabı gözden geçirilemedi.",
                                                  f"The {s.agent} answer could not be reviewed."))
        issues = issue_payload(review, [f.model_dump() for f in view.checks.failures])
        self.rt.store.log_event(job.id, "step.review", {"step": s.id, "agent": s.agent, "issues": issues,
                                                        "dropped": view.dropped_issues})
        if not issues:
            return output
        if self.settings.max_revisions == 0 or run.over_budget():
            result.warnings.append(_lang_note(
                req, f"{s.agent} cevabında düzeltilmemiş sorunlar var: ", f"Unfixed issues in the {s.agent} answer: ")
                + "; ".join(i["claim"] for i in issues[:3]))
            return output
        reviser = f"{s.agent}.revise"
        rev = self._ask(job, reviser, s.objective + "\n\n" + _lang_note(
            s.objective,
            "(Not: Gözden geçirme sorunları girdi verisinde. Her birini düzelt ya da gerekçeyle itiraz et.)",
            "(Note: the review issues are in the input data. Fix each one or dispute it with a reason.)"),
            {"current_answer": answer, "issues": issues, **run.context})
        if rev.status != TaskStatus.SUCCEEDED or not rev.result:
            result.warnings.append(_lang_note(
                req, f"{s.agent} cevabı düzeltilemedi; sorunlar: ", f"The {s.agent} answer could not be revised; issues: ")
                + "; ".join(i["claim"] for i in issues[:3]))
            return output
        r = rev.result
        new_answer = str(r.get("answer", "")).strip() or answer
        view.revised = new_answer != answer
        view.accepted = list(r.get("accepted", []))
        after = run_checks(new_answer, list(defn.review.checks))
        view.unresolved_checks = [f.message for f in after.failures]
        if view.unresolved_checks:
            result.warnings.append(_lang_note(
                req, "Otomatik kontrol düzeltmeden sonra da başarısız (doğrulanamadı): ",
                "Automatic check still fails after revision (unverified): ") + "; ".join(view.unresolved_checks[:3]))
        by_id = {i["id"]: i for i in issues}
        target = self._dispute_target(run)
        for d in r.get("disputed", []):
            issue = by_id.get(str(d.get("id")))
            if issue is None or issue["source"] == "check":
                continue  # doğrulama zaten engeller; savunma amaçlı
            rec = DisputeRecord(
                job_id=job.id, step_id=s.id, request=s.objective[:2000], producer=s.agent,
                reviewer=defn.review.reviewer, issue_id=issue["id"], severity=issue["severity"],
                issue=issue["claim"], evidence=issue.get("evidence", ""), producer_position=str(d.get("reason", "")),
                escalated_to=target,
            )
            if self.rt.disputes:
                self.rt.disputes.open(rec)
            run.disputes.append(rec)
            view.disputes.append(rec.id)
        return {**output, "answer": new_answer}

    def _dispute_target(self, run: _Run) -> Literal["owner", "claude"]:
        """Anlaşmazlığa kim karar verir: Claude şef mi (kutu ya da çağıran), yoksa sahip mi."""
        if run.origin == "claude":
            return "claude"  # isteği zaten Claude şef gönderdi: iki görüş ona döner
        claude_on = bool(self.rt.claude and self.rt.claude.is_enabled())
        if self.settings.disputes == "claude_first" and claude_on and run.force != "local":
            return "claude"
        return "owner"

    def _escalate_disputes(self, run: _Run) -> None:
        result, req = run.result, run.request
        summary = "; ".join(f"{d.producer} ↔ {d.reviewer}: {d.issue[:120]}" for d in run.disputes[:3])
        n = len(run.disputes)
        if run.origin == "claude":
            result.warnings.append(_lang_note(
                req, f"Ajanlar {n} konuda anlaşamadı (karar senin): {summary}",
                f"The agents disagreed on {n} point(s) (your call): {summary}"))
        elif run.disputes[0].escalated_to == "claude":
            result.routing.decision = "claude_inbox"
            result.routing.why = f"ajanlar {n} konuda anlaşamadı; Claude modu açık (anlaşmazlık politikası: claude_first)"
            result.status = TaskStatus.WAITING_CLAUDE.value
            result.warnings.append(_lang_note(
                req, f"Ajanlar {n} konuda anlaşamadı; iş iki görüşle Claude kutusuna bırakıldı: {summary}",
                f"The agents disagreed on {n} point(s); the job was left in the Claude inbox: {summary}"))
        else:
            result.warnings.append(_lang_note(
                req, f"Ajanlar {n} konuda anlaşamadı; karar sana bırakıldı (kayaai disputes): {summary}",
                f"The agents disagreed on {n} point(s); the decision is yours (kayaai disputes): {summary}"))
        self.rt.store.log_event(run.job.id, "disputes.escalated",
                                {"count": n, "to": run.disputes[0].escalated_to, "ids": [d.id for d in run.disputes]})

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
        if len(first) <= 80:
            return first
        cut = first[:80].rsplit(" ", 1)[0]  # kelime ortasından kesme
        return cut.rstrip(" ,;:") + "…"

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

    def _review_loop(
        self, job: Task, request: str, answer: str, result: ConductorResult, topics: list[str] | None = None
    ) -> str:
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
            # Gözden geçirici "ok" dese bile ana konu cevapta yoksa eksik say (Opus'un gözlemi, 2026-10-31).
            uncovered = missing_topics(topics or [], answer)
            topic_label = _lang_note(request, "ele alınmamış konu: ", "topic not covered: ")
            result.review.missing_parts += [topic_label + t for t in uncovered
                                            if topic_label + t not in result.review.missing_parts]
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
        # Konu eksikleri _run'da kapsam uyarısı olarak tek seferde raporlanır; burada yalnızca gözden geçiricininkiler.
        topic_label = _lang_note(request, "ele alınmamış konu: ", "topic not covered: ")
        reviewer_missing = [m for m in result.review.missing_parts if not m.startswith(topic_label)]
        if reviewer_missing and result.review.verdict != "ok":
            result.warnings.append(
                _lang_note(request, "Cevapta eksik kalmış olabilir: ", "The answer may still be missing: ")
                + "; ".join(reviewer_missing[:3]))
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
