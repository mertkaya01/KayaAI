"""Tarayıcı ajanı (Adım 12d, kabul #11): hedef + başlangıç adresi → adım adım (gör → karar ver → risk → [onay] → yap).

- Model yalnız bir sonraki eylemi önerir (`BrowserAction` şeması; öğe numaraları sayfadan, KODLA doğrulanır).
- Risk sınıfını KOD belirler (browser/risk.py): R0/R1 hemen (kayda geçer), R2/R3 onay merkezine — önizleme: hedef öğesi
  kırmızıyla çizilmiş ekran görüntüsü + açıklama. Reddedilen/kural dışı eylem yapılmaz; sahip reddederse iş durur.
- Aynı anda tek iş (tek profil). Her adım görev olayıdır; model çağrıları alt görev olarak kayıtlı.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.permissions import Risk, ToolAction
from ..core.task import Permission, Task, TaskStatus, ValidationResult, utcnow
from ..workers.base import LLMWorker
from .driver import BrowserDriver, BrowserError, Driver, PageState, thumbnail
from .risk import Decision, classify, describe, goal_permits_irreversible

if TYPE_CHECKING:
    from ..config import Settings
    from ..runtime import Runtime

_JOBS: dict[str, "BrowserJob"] = {}
_ACTIVE = threading.Lock()


class BrowserJobError(ValueError):
    pass


class BrowserAction(BaseModel):
    thought: str = Field(description="One short sentence: what you see and why you choose this action (user's language)")
    action: Literal["goto", "click", "type", "select", "scroll", "extract", "done"]
    element_id: int | None = Field(None, description="Number of the element from the list (click/type/select)")
    value: str = Field("", description="type: text to enter · select: option label · goto: full https URL · scroll: down|up")
    answer: str = Field("", description="extract: the information read from the page · done: final answer for the user")


class BrowserStepWorker(LLMWorker):
    name: ClassVar[str] = "browser.step"
    description: ClassVar[str] = "Tarayıcıda bir sonraki adımı seçer (iç worker)"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = BrowserAction
    system_prompt: ClassVar[str] = (
        "You are the browser agent of kayaAI. You control a web browser for the user, ONE action at a time. "
        "The input data has the user's goal, the current page (url, title, visible text) and a numbered list of "
        "interactive elements, plus your previous steps and their results. Choose the single next action:\n"
        "- extract: when the needed information is visible in the page text, put it in 'answer'.\n"
        "- done: when the goal is reached (or impossible); write the final answer for the user in 'answer'.\n"
        "- click / type / select: use an element number from the list ONLY. type = fill a form field with 'value'.\n"
        "- goto: open a full https URL. scroll: 'down' or 'up' to see more.\n"
        "Rules: NEVER propose sending, paying, buying, ordering, deleting, publishing or signing up unless the goal "
        "explicitly asks for exactly that (the program refuses it otherwise); when the goal says not to do something, "
        "do not do it; prefer reading over acting; never invent element numbers; never type passwords, card numbers or ID "
        "numbers (the program refuses them); do not repeat an action that already failed or was refused; if a step "
        "was refused, choose another way or finish with done. Risky steps (forms, sending, paying) need the owner's "
        "approval — that is normal, still propose them when the goal requires it."
    )

    def model_spec(self, registry: Any):  # -> ModelSpec
        return registry.model_for_worker("general")

    def build_messages(self, task: Task) -> list[dict[str, Any]]:
        visible = Task(**{**task.model_dump(), "input": {k: v for k, v in task.input.items() if not k.startswith("_")}})
        return super().build_messages(visible)

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, BrowserAction)
        ids = set(task.input.get("_ids", []))
        errors = []
        if output.action in ("click", "type", "select"):
            if output.element_id is None or output.element_id not in ids:
                errors.append(f"element_id {output.element_id} listede yok; listedeki numaralardan birini seç")
        if output.action == "goto" and not output.value.startswith(("http://", "https://")):
            errors.append("goto için value tam bir http(s) adresi olmalı")
        if output.action in ("type", "select") and not output.value:
            errors.append(f"{output.action} için value gerekli")
        if output.action == "done" and not output.answer.strip():
            errors.append("done için answer (kullanıcıya son cevap) gerekli")
        return ValidationResult(passed=not errors, validator="browser.step", errors=errors)


class Step(BaseModel):
    n: int
    action: str
    description: str
    thought: str = ""
    risk: str = ""
    reason: str = ""
    status: Literal["yapıldı", "onay bekliyor", "reddedildi", "kural dışı", "atlandı", "hata", "bitti"] = "yapıldı"
    approval_id: str | None = None
    url: str = ""
    error: str | None = None


class JobState(BaseModel):
    id: str
    goal: str
    start_url: str
    status: Literal["running", "waiting", "done", "failed", "stopped"] = "running"
    steps: list[Step] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    answer: str = ""
    error: str | None = None
    url: str = ""
    title: str = ""
    screenshot: str | None = None      # son sayfanın küçük görüntüsü (data URL)
    task_id: str | None = None
    started_at: float = Field(default_factory=time.time)


DriverFactory = Callable[["Settings"], Driver]


class BrowserJob:
    def __init__(self, rt: "Runtime", goal: str, start_url: str, driver_factory: DriverFactory | None = None):
        self.rt = rt
        self.state = JobState(id=uuid.uuid4().hex[:10], goal=goal.strip(), start_url=start_url.strip())
        self.factory = driver_factory or BrowserDriver
        self.driver: Driver | None = None
        self.stop_event = threading.Event()
        self.finished = threading.Event()  # run() tamamen bitti (kayıt yazıldı, kilit bırakıldı)
        self.page: PageState | None = None

    # -------------------------------------------------------------- yardımcılar

    def _log(self, step: Step) -> None:
        if self.state.task_id:
            self.rt.store.log_event(self.state.task_id, "browser.step",
                                    {"n": step.n, "action": step.action, "risk": step.risk, "status": step.status,
                                     "description": step.description[:200]})
        self.rt.store.emit("browser.step", {"job": self.state.id, "n": step.n, "status": step.status, "risk": step.risk,
                                            "description": step.description[:160]})

    def _shot(self, element_id: int | None = None) -> str | None:
        try:
            return thumbnail(self.driver.screenshot(element_id))  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - görüntü olmadan da devam
            return None

    def _wait_approval(self, approval_id: str) -> str:
        assert self.rt.permissions is not None
        deadline = time.monotonic() + self.rt.settings.browser.approval_timeout_s
        while not self.stop_event.is_set():
            a = self.rt.permissions.get(approval_id)
            if a.status != "pending":
                return a.status if a.status != "failed" else f"failed: {a.error}"
            if time.monotonic() > deadline:
                self.rt.permissions.reject(approval_id, decided_by="system", note="tarayıcı işi onay beklerken zaman aşımı")
                return "timeout"
            time.sleep(0.4)
        try:
            self.rt.permissions.reject(approval_id, decided_by="system", note="tarayıcı işi durduruldu")
        except Exception:  # noqa: BLE001
            pass
        return "stopped"

    def _elements_text(self) -> list[str]:
        assert self.page is not None
        out = []
        for e in self.page.elements:
            bits = [f"[{e.id}] {e.tag}"]
            if e.type:
                bits.append(e.type)
            if e.role:
                bits.append(f"role={e.role}")
            bits.append(f"\"{e.name[:70]}\"" if e.name else (f"({e.field[:40]})" if e.field else ""))
            if e.href:
                bits.append(f"→ {e.href[:80]}")
            out.append(" ".join(b for b in bits if b))
        return out[:100]

    # -------------------------------------------------------------- döngü

    def run(self) -> JobState:
        st = self.state
        task = Task(worker="browser", objective=st.goal[:2000], input={"start_url": st.start_url},
                    status=TaskStatus.RUNNING, started_at=utcnow())
        self.rt.store.save(task)
        st.task_id = task.id
        self.rt.store.emit("task.status", {"task_id": task.id, "worker": "browser", "status": "running",
                                           "objective": st.goal[:200]})
        try:
            self.driver = self.factory(self.rt.settings)
            self.driver.open(st.start_url)
            self._loop()
        except (BrowserError, TimeoutError, OSError) as exc:
            st.status, st.error = "failed", str(exc)[:400]
        except Exception as exc:  # noqa: BLE001 - iş kaydı her durumda kapanmalı
            st.status, st.error = "failed", f"{type(exc).__name__}: {exc}"[:400]
        finally:
            if self.driver is not None:
                try:
                    self.driver.close()
                except Exception:  # noqa: BLE001
                    pass
            if not st.answer and st.notes:
                st.answer = "\n".join(st.notes)
            task.status = TaskStatus.SUCCEEDED if st.status == "done" else (
                TaskStatus.CANCELLED if st.status == "stopped" else TaskStatus.FAILED)
            task.finished_at = utcnow()
            task.error = st.error
            task.result = {"answer": st.answer, "steps": [s.model_dump() for s in st.steps], "url": st.url}
            self.rt.store.save(task)
            self.rt.store.emit("task.status", {"task_id": task.id, "worker": "browser", "status": task.status.value})
            _ACTIVE.release()
            self.finished.set()
        return st

    def _loop(self) -> None:
        st = self.state
        b = self.rt.settings.browser
        refused, last_sig, repeats = 0, None, 0
        done_sig: tuple | None = None
        history: list[str] = []
        for n in range(1, b.max_steps + 1):
            if self.stop_event.is_set():
                st.status = "stopped"
                return
            self.page = self.driver.snapshot()  # type: ignore[union-attr]
            st.url, st.title = self.page.url, self.page.title
            st.screenshot = self._shot()
            ids = [e.id for e in self.page.elements]
            t = self.rt.orchestrator.ask(
                f"Goal: {st.goal}", worker="browser.step", parent_id=st.task_id,
                input={"goal": st.goal, "url": self.page.url, "title": self.page.title, "page_text": self.page.text[:3000],
                       "elements": self._elements_text(), "previous_steps": history[-8:], "notes": st.notes[-5:],
                       "_ids": ids})
            if t.status != TaskStatus.SUCCEEDED or not t.result:
                st.status, st.error = "failed", f"Model adım seçemedi: {t.error or t.status.value}"
                return
            act = BrowserAction.model_validate(t.result)
            el = next((e for e in self.page.elements if e.id == act.element_id), None)
            desc = describe(act.action, el, act.value)
            step = Step(n=n, action=act.action, description=desc, thought=act.thought[:300], url=self.page.url)
            st.steps.append(step)
            if act.action == "done":
                step.status, step.risk = "bitti", "R0"
                st.answer, st.status = act.answer.strip(), "done"
                self._log(step)
                return
            if act.action == "extract":
                step.risk = "R0"
                if act.answer.strip():
                    st.notes.append(act.answer.strip())
                history.append(f"{n}. extract → not alındı: {act.answer[:150]}")
                self._log(step)
                continue
            sig = (act.action, act.element_id, act.value, self.page.url)
            repeats = repeats + 1 if sig == last_sig else 0
            last_sig = sig
            if repeats >= 2:
                st.status, st.error = "failed", "Aynı adım tekrarlanıyor; iş durduruldu"
                return
            # Aynı sayfada az önce YAPILMIŞ eylemin aynısı → yapılmaz, sorulmaz (gözlem: "Python" iki kez yazdırıldı)
            if done_sig == (act.action, act.element_id, act.value, self.page.url):
                step.status, step.risk, step.reason = "atlandı", "R0", "az önce yapıldı"
                history.append(f"{n}. {desc} → ATLANDI (az önce yapıldı; tekrar etme, sonraki adıma geç)")
                self._log(step)
                continue
            d = classify(act.action, self.page.url, el, act.value, allow_local=b.allow_local)
            if d.verdict == "R3":
                ok, why = goal_permits_irreversible(st.goal)
                if not ok:
                    d = Decision(verdict="refuse", reason=f"geri alınamaz eylem ({d.reason}) ama {why}")
            step.risk, step.reason = d.verdict, d.reason
            if d.verdict == "refuse":
                step.status = "kural dışı"
                refused += 1
                history.append(f"{n}. {desc} → YAPILMADI (kural: {d.reason})")
                self._log(step)
                if refused >= 3:
                    st.status, st.error = "failed", "Üst üste kural dışı adımlar; iş durduruldu"
                    return
                continue
            refused = 0
            preview: dict[str, Any] = {"new_head": f"Sayfa: {self.page.title}\n{self.page.url}\n\n{desc}\nNeden riskli: {d.reason}"
                                                   f"\nAjanın gerekçesi: {act.thought[:200]}"}
            if d.verdict in ("R2", "R3"):
                shot = self._shot(act.element_id)
                if shot:
                    preview["image"] = shot
            assert self.rt.permissions is not None
            res = self.rt.permissions.submit(ToolAction(
                tool="browser.action", params={"job": st.id, "action": act.action, "element_id": act.element_id,
                                               "value": act.value},
                risk=Risk(d.verdict), summary=f"Tarayıcı: {desc}", reason=d.reason, preview=preview,
                undo="Tarayıcıda geri git / değişikliği elle geri al", requested_by=f"browser:{st.id}"))
            if res.status == "awaiting_approval":
                step.status, step.approval_id, st.status = "onay bekliyor", res.approval_id, "waiting"
                self._log(step)
                decision = self._wait_approval(res.approval_id)  # type: ignore[arg-type]
                st.status = "running"
                if decision == "approved":
                    step.status = "yapıldı"
                elif decision == "stopped":
                    step.status, st.status = "reddedildi", "stopped"
                    self._log(step)
                    return
                else:
                    step.status = "reddedildi" if not decision.startswith("failed") else "hata"
                    step.error = decision
                    st.status, st.error = ("failed", "Sahip onaylamadı; iş durduruldu") if step.status == "reddedildi" \
                        else ("failed", f"Eylem yapılamadı: {decision}")
                    self._log(step)
                    return
            elif res.status == "failed":
                step.status, step.error = "hata", res.error
                history.append(f"{n}. {desc} → HATA: {str(res.error)[:120]}")
                self._log(step)
                continue
            history.append(f"{n}. {desc} → yapıldı")
            done_sig = (act.action, act.element_id, act.value, step.url)
            self._log(step)
        st.status, st.error = "failed", f"{b.max_steps} adımda bitmedi"


# ---------------------------------------------------------------------------- başlatma / yürütücü


def start_job(rt: "Runtime", goal: str, url: str, driver_factory: DriverFactory | None = None,
              background: bool | None = None) -> BrowserJob:
    from .risk import check_url

    from ..automation import is_paused

    if is_paused(rt):
        raise BrowserJobError("Otomasyon duraklatıldı: tarayıcı işi başlatılamaz (sol menüde Otomasyon anahtarı ya da: kayaai resume)")
    if len(goal.strip()) < 5:
        raise BrowserJobError("Ne yapılacağını yaz (hedef)")
    url = url.strip()
    if "://" not in url and not url.lower().startswith(("file:", "javascript:", "data:")):
        url = "https://" + url  # şemasız adres (kitap.com) → https
    why = check_url(url, rt.settings.browser.allow_local)
    if why:
        raise BrowserJobError(f"Başlangıç adresi kabul edilmedi: {why}")
    if "browser.step" not in rt.workers:
        rt.workers.register(BrowserStepWorker(), internal=True)
    if not _ACTIVE.acquire(blocking=False):
        raise BrowserJobError("Zaten bir tarayıcı işi sürüyor; bitmesini bekle ya da durdur")
    job = BrowserJob(rt, goal, url, driver_factory)
    _JOBS[job.state.id] = job
    if background if background is not None else getattr(rt, "background_ok", False):
        threading.Thread(target=job.run, name=f"kayaai-browser-{job.state.id}", daemon=True).start()
    else:
        job.run()
    return job


def get_job(job_id: str) -> BrowserJob:
    if job_id not in _JOBS:
        raise BrowserJobError(f"Tarayıcı işi bulunamadı: {job_id}")
    return _JOBS[job_id]


def list_jobs() -> list[JobState]:
    return sorted((j.state for j in _JOBS.values()), key=lambda s: s.started_at, reverse=True)[:20]


def _exec_action(params: dict[str, Any]) -> dict[str, Any]:
    job = get_job(params["job"])
    if job.driver is None or job.state.status in ("done", "failed", "stopped"):
        raise BrowserJobError("Tarayıcı işi artık açık değil")
    job.driver.act(params["action"], params.get("element_id"), params.get("value", ""))
    return {"job": job.state.id, "action": params["action"]}


def executors(rt: "Runtime") -> dict[str, Any]:
    return {"browser.action": _exec_action}
