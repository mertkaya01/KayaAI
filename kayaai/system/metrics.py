"""Anlık sistem ölçümleri (Control Center 'Sistem İzleme' için): CPU, RAM, GPU, VRAM."""

from __future__ import annotations

from typing import Any

import psutil

from .audit import gpu_info


def system_metrics() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    gpu = gpu_info()
    gpus = []
    for g in gpu.get("gpus", []):
        total, used = g.get("memory.total_mb"), g.get("memory.used_mb")
        gpus.append({
            "name": g.get("name"),
            "utilization_pct": _num(g.get("utilization.gpu")),
            "vram_total_mb": total,
            "vram_used_mb": used,
            "vram_used_pct": round(used / total * 100, 1) if total and used is not None else None,
        })
    return {
        "cpu_pct": psutil.cpu_percent(interval=0.2),
        "cpu_logical_cores": psutil.cpu_count(),
        "ram_total_gb": round(vm.total / 1024**3, 2),
        "ram_used_gb": round((vm.total - vm.available) / 1024**3, 2),
        "ram_used_pct": vm.percent,
        "gpus": gpus,
        "gpu_notes": gpu.get("notes", []),
    }


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
