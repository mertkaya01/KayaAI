"""Bu bilgisayarın anlık durumu (sahip videosu, 2026-11-02): "bilgisayarımı analiz et" isteğinde ajanların elinde
hiç veri yoktu, süreci anlatan boş bir metin çıkıyordu. Bilgisayarla ilgili istekte bu YALNIZ OKUNUR özet ajanlara
veri olarak verilir (Sistem sayfasında görünenlerin aynısı). Yerel modellere gider; Claude kutusuna konmaz."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime

COMPUTER_RE = re.compile(
    r"bilgisayar\w*|\bpc\b|donanım\w*|\bcpu\b|\bgpu\b|işlemci\w*|ekran kart\w*|\bram\b|\bvram\b|"
    r"\bmy (computer|pc|machine)\b|\bhardware\b",
    re.IGNORECASE)


def wants_computer_info(text: str) -> bool:
    return bool(COMPUTER_RE.search(text or ""))


@lru_cache(maxsize=1)
def _static() -> dict[str, Any]:
    from .audit import cpu_info, os_info

    o = os_info()
    win = o.get("windows") or {}
    os_name = ("Windows 11" if win.get("is_windows_11") else f"{o.get('system')} {o.get('release')}").strip()
    return {"os": os_name, "os_build": win.get("build") or o.get("version"), "cpu": cpu_info().get("name") or "?"}


def computer_snapshot(rt: "Runtime") -> dict[str, Any]:
    from .audit import disk_info, gpu_info
    from .metrics import system_metrics

    m = system_metrics()
    st = _static()
    out: dict[str, Any] = {
        "note": "Anlık ölçüm (yalnız okundu). Sıcaklık, fan, arka plan uygulamaları ve disk sağlığı bu veride YOK.",
        "os": st["os"], "os_build": st["os_build"],
        "cpu": {"model": st["cpu"], "logical_cores": m.get("cpu_logical_cores"), "usage_pct": m.get("cpu_pct")},
        "ram": {"total_gb": m.get("ram_total_gb"), "used_gb": m.get("ram_used_gb"), "used_pct": m.get("ram_used_pct")},
        "gpus": [],
    }
    drivers = {g.get("name"): g.get("driver_version") for g in gpu_info().get("gpus", [])}
    for g in m.get("gpus", []):
        out["gpus"].append({"name": g.get("name"), "driver": drivers.get(g.get("name")), "usage_pct": g.get("utilization_pct"),
                            "vram_total_gb": round(g["vram_total_mb"] / 1024, 1) if g.get("vram_total_mb") else None,
                            "vram_used_gb": round(g["vram_used_mb"] / 1024, 1) if g.get("vram_used_mb") is not None else None})
    try:
        d = disk_info(rt.settings.data_dir)
        out["disk"] = {"total_gb": d.get("total_gb"), "free_gb": d.get("free_gb")}
    except OSError:
        pass
    try:
        out["ai_models_in_memory"] = [
            {"name": x.get("name"), "vram_gb": round((x.get("size_vram") or 0) / 1024**3, 2)} for x in rt.llm.running_models()]
    except Exception:  # noqa: BLE001 - Ollama kapalıysa bu alan yok
        pass
    return out
