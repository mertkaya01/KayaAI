"""Ses (Adım 12b–c): bas-konuş ses tanıma (faster-whisper, yerel) ve canlı altyazı."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ..core.permissions import Risk, SubmitResult, ToolAction
from .stt import APPROX_MB, SpeechError, download, is_installed

if TYPE_CHECKING:
    from ..runtime import Runtime


def prepare_gpu(rt: "Runtime", purpose: str = "ses tanıma", extra_gb: float = 0.0) -> str | None:
    """Whisper GPU'ya yüklenecekse önce yer aç (Adım 13b). Genel model (çeviri/sohbet) korunur. Uyarı metni ya da None."""
    from ..llm.vram import ensure_vram
    from .stt import _STATE

    if rt.settings.speech.device == "cpu" or (_STATE["model"] is not None and not extra_gb):
        return None
    general = rt.registry.model_for_worker("general").name
    need = (1.6 if _STATE["model"] is None else 0.0) + extra_gb
    return ensure_vram(rt, need, purpose, keep={general}).warning if need else None


def request_download(rt: "Runtime", requested_by: str = "user") -> SubmitResult:
    """Ses tanıma modelini indirme talebi — R2 sahip onayı (internetten ~1,6 GB)."""
    name = rt.settings.speech.model
    if is_installed(rt.settings):
        raise SpeechError(f"Ses tanıma modeli zaten kurulu: {name}")
    assert rt.permissions is not None
    mb = APPROX_MB.get(name)
    return rt.permissions.submit(ToolAction(
        tool="speech.download", params={"model": name}, risk=Risk.R2,
        summary=f"Ses tanıma modeli indir: whisper {name} (~{mb or '?'} MB, huggingface.co)",
        reason="İnternetten indirilir ve diske yazılır. Model ve faster-whisper MIT lisanslı; tanıma tamamen yerel çalışır.",
        preview={"new_head": f"faster-whisper download_model('{name}') → data/models/whisper/{name}"},
        undo=f"data/models/whisper/{name} klasörünü sil", requested_by=requested_by))


def _exec_download(rt: "Runtime", params: dict[str, Any]) -> dict[str, Any]:
    def emit(d: dict[str, Any]) -> None:
        rt.store.emit("speech.download", d)

    if getattr(rt, "background_ok", False):  # API: onay isteği beklemesin
        def bg() -> None:
            try:
                download(rt.settings, emit)
            except SpeechError:
                pass  # hata olayla bildirildi

        threading.Thread(target=bg, name="kayaai-whisper-download", daemon=True).start()
        return {"model": params["model"], "started": True}
    return download(rt.settings, emit)


def executors(rt: "Runtime") -> dict[str, Any]:
    return {"speech.download": lambda p: _exec_download(rt, p)}
