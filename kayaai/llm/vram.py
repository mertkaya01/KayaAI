"""VRAM bekçisi (Adım 13b): büyük bir model (görsel model, Whisper) yüklenmeden önce boş GPU belleğini ölçer; yetmiyorsa
o işe gerekmeyen, Ollama'da yüklü duran modelleri boşaltır.

Neden: Windows ölçümü (2026-11-01) — qwen3:8b + qwen2.5vl:7b + bge-m3 + Whisper birlikte 15,4/15,9 GB (%97). VRAM dolunca
Ollama yeni modeli kısmen işlemciye taşır ve her şey yavaşlar; önceden boşaltmak daha hızlıdır (model gerekince
saniyeler içinde yeniden yüklenir).
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)
MARGIN_MB = 600  # sürücü / masaüstü / bağlam büyümesi için pay


class VramReport(BaseModel):
    ok: bool = True
    free_mb: int | None = None
    need_mb: int = 0
    unloaded: list[str] = Field(default_factory=list)
    warning: str | None = None


def _query() -> tuple[int, int] | None:
    """(boş_mb, toplam_mb) — ilk NVIDIA GPU; yoksa None."""
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        free, total = (int(float(x)) for x in p.stdout.strip().splitlines()[0].split(","))
    except ValueError:
        return None
    return free, total


FreeFn = Callable[[], tuple[int, int] | None]
_FREE: FreeFn | None = None


def set_probe(fn: FreeFn | None) -> None:
    """Testler için sahte ölçüm."""
    global _FREE
    _FREE = fn


def _base(name: str) -> str:
    return name.removesuffix(":latest")


def free_vram() -> tuple[int, int] | None:
    return (_FREE or _query)()


def ensure_vram(rt: "Runtime", need_gb: float, purpose: str, keep: set[str] = frozenset()) -> VramReport:
    """`need_gb` için yer aç: boş VRAM yetmiyorsa `keep` dışındaki yüklü Ollama modellerini büyükten küçüğe boşaltır."""
    need = int(need_gb * 1024) + MARGIN_MB
    rep = VramReport(need_mb=need)
    probe = free_vram()
    if probe is None:
        return rep  # NVIDIA yok / ölçülemiyor: karışma
    rep.free_mb = probe[0]
    if rep.free_mb >= need:
        return rep
    try:
        loaded = sorted(rt.llm.running_models(), key=lambda m: m.get("size_vram") or 0, reverse=True)
    except Exception:  # noqa: BLE001 - Ollama yoksa yapılacak bir şey yok
        loaded = []
    for m in loaded:
        name = m.get("name") or m.get("model") or ""
        if not name or _base(name) in {_base(k) for k in keep}:
            continue
        embedding = "embed" in name or "bge" in name
        try:
            rt.llm.unload_model(name, embedding=embedding)
        except Exception as exc:  # noqa: BLE001
            log.warning("VRAM için %s boşaltılamadı: %s", name, exc)
            continue
        rep.unloaded.append(name)
        rt.store.emit("model.unloaded", {"name": name, "reason": f"VRAM: {purpose}"})
        probe = free_vram()
        rep.free_mb = probe[0] if probe else None
        if rep.free_mb is None or rep.free_mb >= need:
            break
    if rep.free_mb is not None and rep.free_mb < need:
        rep.ok = False
        rep.warning = (f"GPU belleği yetersiz ({purpose}: ~{need_gb:.1f} GB gerekli, {rep.free_mb / 1024:.1f} GB boş); "
                       "model kısmen işlemcide çalışabilir (yavaş). Başka GPU kullanan programları kapatmayı dene.")
    return rep


def model_loaded(rt: "Runtime", name: str) -> bool:
    try:
        return any((m.get("name") or "") in (name, f"{name}:latest") for m in rt.llm.running_models())
    except Exception:  # noqa: BLE001
        return False


def status() -> dict[str, Any]:
    p = free_vram()
    return {"free_mb": p[0], "total_mb": p[1]} if p else {"free_mb": None, "total_mb": None}
