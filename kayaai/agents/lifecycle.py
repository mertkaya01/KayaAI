"""Ajan yaşam döngüsü (Adım 7c, MASTER_PROMPT v2 §6 / D9).

önerilen → geçici → denenmiş → sahip onayı → kalıcı

- Geçici ajanlar `data/agents/<ad>.yaml` dosyasında tutulur (git'e girmez); `config/agents/` repo ajanlarıdır.
- Geçici ajan bir mevcut ajana (`base`) dayanır: modeli, Claude karşılığı ve izinleri base'den gelir; izinler ayrıca
  yaratıcının izinleriyle kesişir. Yani bir geçici ajan, onu oluşturandan ya da dayandığı ajandan FAZLA izin alamaz.
- Her geçici ajanın cevabı gözden geçirilir (doğrulayıcı kapısı). Kalıcı yapmak için en az bir başarılı kullanım
  gerekir ve sahip onayı (R2) şarttır — onay merkezinde YAML önizlemesiyle görünür.
- Dosyalar başka süreçlerde de oluşabilir (MCP, CLI, API): `sync_user_agents` klasörü tarayıp kayıt defterini günceller.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from ..core.permissions import Risk, SubmitResult, ToolAction
from ..core.task import Permission, utcnow
from .definitions import (
    AgentDefinition,
    AgentDefinitionError,
    AgentReview,
    load_definition_file,
    register_definition,
)

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

NAME_PATTERN = r"^[a-z][a-z0-9_-]{1,31}$"
UNUSABLE_BASES = frozenset({"planner", "reviewer"})
HEADER = (
    "# kayaAI tarafından oluşturulan ajan (Adım 7c). status: temporary → geçici; kalıcı yapmak için:\n"
    "#   kayaai agents promote {name}   (sahip onayı gerekir)   ·   kaldırmak için: kayaai agents remove {name}\n"
)


class AgentLifecycleError(ValueError):
    pass


class AgentProposal(BaseModel):
    name: str = Field(pattern=NAME_PATTERN, description="Short lowercase id, e.g. 'legal' or 'marketing-tr'")
    description: str = Field(min_length=3, max_length=300, description="What the agent does (user's language)")
    role: str = Field(min_length=10, max_length=4000, description="The agent's role instructions (system prompt)")
    base: str = Field(description="Existing agent it is based on (model, permissions), e.g. 'general' or 'document'")


def user_agents_dir(rt: "Runtime") -> Path:
    return rt.settings.data_dir / "agents"


def _user_names(rt: "Runtime") -> set[str]:
    return rt.workers.user_names


def _definition(rt: "Runtime", name: str) -> AgentDefinition | None:
    if name not in rt.workers:
        return None
    return getattr(rt.workers.get(name), "definition", None)


# ---------------------------------------------------------------------------- yükleme / senkron


def sync_user_agents(rt: "Runtime") -> list[str]:
    """data/agents klasörünü kayıt defteriyle eşitler. Bozuk ya da çakışan dosya başlatmayı durdurmaz: atlanır."""
    warnings: list[str] = []
    folder = user_agents_dir(rt)
    seen: set[str] = set()
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            defn = load_definition_file(path, rt.registry)
        except AgentDefinitionError as exc:
            warnings.append(f"atlandı: {exc}")
            continue
        if defn.name in rt.workers and defn.name not in _user_names(rt):
            warnings.append(f"atlandı: {path.name} — '{defn.name}' adlı bir repo ajanı zaten var")
            continue
        if defn.review.required and f"{defn.review.reviewer}.check" not in rt.workers:
            warnings.append(f"atlandı: {path.name} — gözden geçirici '{defn.review.reviewer}' yok")
            continue
        seen.add(defn.name)
        if _definition(rt, defn.name) != defn:
            rt.workers.unregister(defn.name)
            register_definition(rt.workers, defn)
    for gone in _user_names(rt) - seen:
        rt.workers.unregister(gone)
    rt.workers.user_names = seen
    warnings += apply_model_overrides(rt)
    for w in warnings:
        log.warning("kullanıcı ajanı %s", w)
    return warnings


# ---------------------------------------------------------------------------- model atamaları (Adım 11)


def overrides_path(rt: "Runtime") -> Path:
    return rt.settings.data_dir / "agent_overrides.yaml"


def read_overrides(rt: "Runtime") -> dict[str, dict[str, Any]]:
    p = overrides_path(rt)
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        log.warning("agent_overrides.yaml okunamadı; yok sayıldı")
        return {}
    return {str(k): dict(v or {}) for k, v in data.items() if isinstance(v, dict)}


def refresh_registry(rt: "Runtime") -> bool:
    """Yerel model kaydı (`data/models.local.yaml`) başka süreçte değiştiyse yeniden yükler."""
    from ..llm.registry import ModelRegistry, local_registry_path

    p = local_registry_path(rt.settings)
    stamp = p.stat().st_mtime if p.is_file() else None
    if getattr(rt, "_local_registry_stamp", "unset") == stamp:
        return False
    rt._local_registry_stamp = stamp  # type: ignore[attr-defined]
    try:
        reg = ModelRegistry.load_for(rt.settings)
    except (OSError, ValueError, KeyError) as exc:
        log.warning("yerel model kaydı okunamadı: %s", exc)
        return False
    rt.registry = reg
    rt.orchestrator.registry = reg
    return True


def apply_model_overrides(rt: "Runtime") -> list[str]:
    """Repo ajanlarının modelini sahibin onayladığı geçersiz kılmalara göre ayarlar (repo dosyası değişmez).

    Kullanıcı ajanlarının (data/agents) modeli doğrudan kendi dosyasında değişir; burada yalnız repo ajanları."""
    refresh_registry(rt)
    warnings: list[str] = []
    overrides = read_overrides(rt)
    base: dict[str, AgentDefinition] = rt.workers.base_definitions
    for w in rt.workers.all():
        d = getattr(w, "definition", None)
        if d is None or w.name in _user_names(rt):
            continue
        base.setdefault(w.name, d)
    for name, original in list(base.items()):
        if name not in rt.workers:
            continue
        want = original
        key = overrides.get(name, {}).get("local_model")
        if key:
            spec = rt.registry.models.get(key)
            if spec is None or spec.status != "active":
                warnings.append(f"{name}: geçersiz kılma yok sayıldı — '{key}' kayıtlı/aktif bir model değil")
            else:
                want = original.model_copy(update={"local_model": key})
        if _definition(rt, name) != want:
            rt.workers.unregister(name)
            register_definition(rt.workers, want)
    return warnings


sync_agents = sync_user_agents  # Adım 11: kullanıcı ajanları + model geçersiz kılmaları + yerel model kaydı


def claude_definitions(rt: "Runtime") -> list[AgentDefinition]:
    """Claude çalışma alanına girecek tanımlar: repo ajanları + kalıcı yapılmış kullanıcı ajanları (geçiciler hariç)."""
    sync_user_agents(rt)
    out = []
    for w in rt.workers.all():
        d = getattr(w, "definition", None)
        if d is not None and d.status == "permanent":
            out.append(d)
    return sorted(out, key=lambda d: d.name)


def usage(rt: "Runtime", name: str) -> tuple[int, int]:
    """(biten görev, başarılı görev) — yalnızca ajanın kendi cevapları (revizyonlar hariç)."""
    return rt.store.count_worker_results(name)


def _write(rt: "Runtime", defn: AgentDefinition) -> Path:
    folder = user_agents_dir(rt)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{defn.name}.yaml"
    body = yaml.safe_dump(defn.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(HEADER.format(name=defn.name) + body, encoding="utf-8")
    os.replace(tmp, path)  # yarım yazılmış dosya başka süreçte okunmasın
    return path


# ---------------------------------------------------------------------------- oluşturma


def create_temporary(rt: "Runtime", proposal: AgentProposal, created_by: str,
                     ceiling: set[str] | None = None) -> AgentDefinition:
    """Geçici ajan oluşturur. ceiling: yaratıcının izinleri (None = sahip / Claude şef: tavan yalnızca base)."""
    sync_user_agents(rt)
    name = proposal.name
    if name in rt.workers or any(n.split(".", 1)[0] == name for n in rt.workers.internal_names()):
        raise AgentLifecycleError(f"'{name}' adlı bir ajan zaten var")
    if proposal.base in UNUSABLE_BASES:
        raise AgentLifecycleError(f"'{proposal.base}' temel alınamaz (yalnızca şefin iç ajanı)")
    base = _definition(rt, proposal.base) if proposal.base in rt.workers.names() else None
    if base is None or base.output != "answer":
        raise AgentLifecycleError(f"Temel ajan bulunamadı ya da cevap üreten bir ajan değil: '{proposal.base}'")
    if base.status != "permanent":
        raise AgentLifecycleError("Geçici bir ajan başka bir geçici ajana dayanamaz")
    temporary = [n for n in _user_names(rt) if (d := _definition(rt, n)) and d.status == "temporary"]
    limit = rt.settings.conductor.max_temp_agents
    if len(temporary) >= limit:
        raise AgentLifecycleError(
            f"En fazla {limit} geçici ajan olabilir ({', '.join(sorted(temporary))}); önce birini kalıcı yap ya da kaldır")
    permissions = [p for p in base.permissions if ceiling is None or p in ceiling]
    if Permission.LLM_INFERENCE.value not in permissions:
        raise AgentLifecycleError("Yaratıcının izinleri bu ajana yetmiyor (llm.inference yok)")
    reviewer = base.review.reviewer if base.review.required else "reviewer"
    if f"{reviewer}.check" not in rt.workers:
        raise AgentLifecycleError(f"Geçici ajanlar gözden geçirilmek zorunda; gözden geçirici '{reviewer}' yok")
    defn = AgentDefinition(
        name=name, description=proposal.description.strip(), output="answer", role=proposal.role.strip(),
        local_model=base.local_model, claude_tier=base.claude_tier, permissions=permissions, limits=base.limits,
        review=AgentReview(required=True, reviewer=reviewer, checks=list(base.review.checks)),
        status="temporary", base=base.name, created_by=created_by, created_at=utcnow().isoformat(timespec="seconds"),
    )
    _write(rt, defn)
    sync_user_agents(rt)
    rt.store.emit("agent.created", {"name": name, "base": base.name, "created_by": created_by,
                                    "description": defn.description[:200]})
    return defn


# ---------------------------------------------------------------------------- kalıcı yapma / kaldırma


def _user_definition(rt: "Runtime", name: str) -> AgentDefinition:
    sync_user_agents(rt)
    d = _definition(rt, name)
    if d is None or name not in _user_names(rt):
        raise AgentLifecycleError(f"'{name}' sonradan oluşturulmuş bir ajan değil (data/agents altında yok)")
    return d


def request_promotion(rt: "Runtime", name: str, requested_by: str) -> SubmitResult:
    """Kalıcı yapma talebi (R2, sahip onayı). Ajan en az bir kez başarıyla kullanılmış olmalı (doğrulayıcı kapısı)."""
    d = _user_definition(rt, name)
    if d.status != "temporary":
        raise AgentLifecycleError(f"'{name}' zaten kalıcı")
    finished, ok = usage(rt, name)
    if ok < 1:
        raise AgentLifecycleError(f"'{name}' henüz hiç başarıyla kullanılmadı; kalıcı yapmadan önce denenmeli")
    new = d.model_copy(update={"status": "permanent"})
    text = yaml.safe_dump(new.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False)
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="agent.promote", params={"name": name}, risk=Risk.R2,
        summary=f"Geçici ajanı kalıcı yap: {name} ({d.description[:80]})",
        reason="Ajan kalıcı olur: planlayıcı onu her işte kullanabilir; Claude modunda alt ajanı da üretilir.",
        preview={"new_head": text, "new_size": len(text.encode("utf-8")), "uses": finished, "successes": ok,
                 "base": d.base, "created_by": d.created_by},
        undo=f"data/agents/{name}.yaml dosyasında 'status: temporary' yap ya da dosyayı sil",
        requested_by=requested_by,
    ))


def exec_promote(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    """Onaylanan kalıcı yapma işlemini uygular (onayı veren süreçte çalışır)."""
    name = str(params["name"])
    d = _user_definition(rt, name)
    if d.status != "temporary":
        raise AgentLifecycleError(f"'{name}' zaten kalıcı")
    _write(rt, d.model_copy(update={"status": "permanent"}))
    sync_user_agents(rt)
    rt.store.emit("agent.promoted", {"name": name})
    out: dict[str, Any] = {"name": name, "status": "permanent"}
    if rt.claude and rt.claude.is_enabled():
        from ..claude_workspace import WorkspaceError, sync_workspace

        try:
            report = sync_workspace(rt.settings, claude_definitions(rt))
            out["claude_workspace"] = f"güncellendi ({len(report.written)} dosya)"
        except (WorkspaceError, OSError) as exc:
            out["claude_workspace"] = f"güncellenemedi: {exc} — kayaai claude sync"
    return out


def remove_temporary(rt: "Runtime", name: str) -> None:
    d = _user_definition(rt, name)
    if d.status != "temporary":
        raise AgentLifecycleError(f"'{name}' kalıcı bir ajan; kaldırmak için dosyasını elle sil: data/agents/{name}.yaml")
    (user_agents_dir(rt) / f"{name}.yaml").unlink(missing_ok=True)
    sync_user_agents(rt)
    rt.store.emit("agent.removed", {"name": name})
