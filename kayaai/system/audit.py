"""Ortam denetimi (Faz 0).

SADECE standart kütüphane kullanır: Python kurulur kurulmaz, hiçbir bağımlılık
yüklenmeden çalışabilmelidir. Hiçbir şey kurmaz, hiçbir dosyayı değiştirmez;
yalnızca okur ve bir JSON raporu üretir.

Windows, Linux ve macOS'ta çalışır. Asıl hedef Windows'tur.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IS_WINDOWS = os.name == "nt"

# Sürümü kontrol edilecek araçlar: ad -> sürüm argümanları
TOOLS: dict[str, list[str]] = {
    "python": [sys.executable, "--version"],
    "git": ["git", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "docker": ["docker", "--version"],
    "ollama": ["ollama", "--version"],
    "tesseract": ["tesseract", "--version"],
    "ffmpeg": ["ffmpeg", "-version"],
    "nvcc": ["nvcc", "--version"],
    "winget": ["winget", "--version"],
}


def _run(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    """Komutu çalıştırır; (dönüş kodu, çıktı) döner. Komut yoksa (-1, '')."""
    exe = cmd[0]
    if not os.path.isabs(exe):
        resolved = shutil.which(exe) or _windows_fallback(exe)
        if resolved is None:
            return -1, ""
        cmd = [resolved, *cmd[1:]]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,  # MCP gibi stdio protokollerinde ebeveynin stdin'ini devralma
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -2, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- OS / CPU / RAM


def os_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
    }
    if IS_WINDOWS:
        win = platform.win32_ver()
        info["windows"] = {"release": win[0], "version": win[1], "edition": platform.win32_edition()}
        # Windows 11, build >= 22000 olarak raporlanır ama platform.release() bazen "10" der.
        try:
            build = int(win[1].split(".")[-1])
            info["windows"]["build"] = build
            info["windows"]["is_windows_11"] = build >= 22000
        except (ValueError, IndexError):
            pass
    return info


def cpu_info() -> dict[str, Any]:
    name = platform.processor() or ""
    if IS_WINDOWS:
        code, out = _run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"]
        )
        if code == 0 and out.strip():
            name = out.strip()
    elif Path("/proc/cpuinfo").exists():
        m = re.search(r"model name\s*:\s*(.+)", Path("/proc/cpuinfo").read_text(errors="replace"))
        if m:
            name = m.group(1).strip()
    elif sys.platform == "darwin":
        code, out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if code == 0:
            name = out.strip()
    return {"name": name, "logical_cores": os.cpu_count()}


def ram_info() -> dict[str, Any]:
    total = avail = None
    if IS_WINDOWS:

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            total, avail = stat.ullTotalPhys, stat.ullAvailPhys
    elif Path("/proc/meminfo").exists():
        mem = Path("/proc/meminfo").read_text()
        t = re.search(r"MemTotal:\s+(\d+) kB", mem)
        a = re.search(r"MemAvailable:\s+(\d+) kB", mem)
        total = int(t.group(1)) * 1024 if t else None
        avail = int(a.group(1)) * 1024 if a else None
    elif sys.platform == "darwin":
        code, out = _run(["sysctl", "-n", "hw.memsize"])
        if code == 0 and out.strip().isdigit():
            total = int(out.strip())
    return {"total_gb": _gb(total), "available_gb": _gb(avail)}


def disk_info(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_gb": _gb(usage.total),
        "free_gb": _gb(usage.free),
        "used_gb": _gb(usage.used),
    }


def _gb(value: int | None) -> float | None:
    return round(value / 1024**3, 2) if value else None


# --------------------------------------------------------------------------- GPU


def _windows_fallback(exe: str) -> str | None:
    """PATH kısıtlı olduğunda (ör. MCP alt süreci) bilinen Windows konumlarına bak."""
    if not IS_WINDOWS or exe != "nvidia-smi":
        return None
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    for candidate in (
        Path(system_root) / "System32" / "nvidia-smi.exe",
        Path(program_files) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def gpu_info() -> dict[str, Any]:
    """nvidia-smi ile NVIDIA GPU bilgisi. Sürücü yoksa açıklayıcı not döner."""
    result: dict[str, Any] = {"nvidia_smi_found": False, "gpus": [], "notes": []}
    query = "name,driver_version,memory.total,memory.used,memory.free,compute_cap,utilization.gpu"
    code, out = _run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if code == -1:
        result["notes"].append("nvidia-smi bulunamadı: NVIDIA sürücüsü kurulu değil veya PATH'te yok.")
        return result
    result["nvidia_smi_found"] = True
    if code == -2:
        result["notes"].append(f"nvidia-smi çalıştırılamadı: {out[:200]}")
        return result
    if code != 0:
        # Eski sürücüler compute_cap alanını desteklemeyebilir; onsuz tekrar dene.
        query = "name,driver_version,memory.total,memory.used,memory.free,utilization.gpu"
        code, out = _run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    fields = query.split(",")
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(fields):
            continue
        gpu = dict(zip(fields, parts))
        for key in ("memory.total", "memory.used", "memory.free"):
            try:
                gpu[key + "_mb"] = int(float(gpu.pop(key)))
            except (KeyError, ValueError):
                pass
        result["gpus"].append(gpu)

    if not result["gpus"]:
        result["notes"].append(f"nvidia-smi çıktısı okunamadı (kod {code}): {out.strip()[:200]!r}")
        return result

    # CUDA sürücü API sürümü: önce nvidia-smi başlığı, sonra ayrıntılı sorgu (-q).
    _, header = _run(["nvidia-smi"])
    cuda = parse_cuda_version(header)
    if cuda is None:
        _, detail = _run(["nvidia-smi", "-q"])
        cuda = parse_cuda_version(detail)
    result["cuda_driver_version"] = cuda
    if cuda is None:
        # Biçim değişmiş olabilir: teşhis için başlığın ilk satırlarını sakla.
        result["cuda_header_sample"] = [ln.rstrip() for ln in header.splitlines()[:6]]

    for gpu in result["gpus"]:
        cap = gpu.get("compute_cap", "")
        name = gpu.get("name", "")
        if cap.startswith("12") or "RTX 50" in name:
            result["notes"].append(
                f"{name}: Blackwell mimarisi (sm_120). CUDA 12.8+ destekli sürücü ve güncel "
                "kütüphaneler gerekir (Ollama güncel sürüm, PyTorch cu128+ wheel)."
            )
            cuda = result.get("cuda_driver_version")
            if cuda and _version_tuple(cuda) < (12, 8):
                result["notes"].append(
                    f"UYARI: Sürücünün desteklediği CUDA {cuda} < 12.8. NVIDIA sürücüsünü güncelleyin."
                )
    return result


_CUDA_RE = re.compile(r"CUDA(?:[ \t]+[A-Za-z]+)?[ \t]+Version[ \t]*:[ \t]*(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_cuda_version(text: str) -> str | None:
    """'CUDA Version: 12.8', 'CUDA Version : 13.0', 'CUDA Driver Version: 13.1' biçimlerini tanır."""
    m = _CUDA_RE.search(text or "")
    return m.group(1) if m else None


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


# --------------------------------------------------------------------------- Yazılımlar


def tool_versions() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, cmd in TOOLS.items():
        code, text = _run(cmd)
        if code == -1:
            out[name] = {"installed": False}
            continue
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        out[name] = {"installed": code == 0, "version": first[:200], "exit_code": code}
    return out


def ollama_status(base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    status: dict[str, Any] = {"base_url": base_url, "reachable": False}
    try:
        with urllib.request.urlopen(base_url + "/api/version", timeout=3) as resp:
            status["version"] = json.loads(resp.read()).get("version")
            status["reachable"] = True
        with urllib.request.urlopen(base_url + "/api/tags", timeout=5) as resp:
            models = json.loads(resp.read()).get("models", [])
            status["models"] = [
                {"name": m.get("name"), "size_gb": _gb(m.get("size"))} for m in models
            ]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def python_check() -> dict[str, Any]:
    ok = sys.version_info >= (3, 11)
    return {
        "executable": sys.executable,
        "version": platform.python_version(),
        "meets_minimum_3_11": ok,
        "in_virtualenv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
    }


# --------------------------------------------------------------------------- Öneriler


def recommendations(report: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    gpus = report["gpu"].get("gpus", [])
    vram_mb = max((g.get("memory.total_mb", 0) for g in gpus), default=0)
    if not gpus:
        recs.append("GPU algılanmadı: modeller CPU'da çok yavaş çalışır. Sürücüyü kontrol edin.")
    elif vram_mb >= 15000:
        recs.append(
            "VRAM >= 16 GB: başlangıç modeli qwen3:8b (~5.2 GB). Benchmark iyi giderse ana model "
            "olarak qwen3:14b (~9.3 GB) denenebilir. Aynı anda tek büyük model yüklü tutun."
        )
    elif vram_mb >= 7500:
        recs.append("VRAM 8-12 GB: qwen3:8b ana model, qwen3:4b hızlı model olarak uygundur.")
    else:
        recs.append("VRAM < 8 GB: qwen3:4b veya daha küçük modellerle başlayın.")

    if not report["python"]["meets_minimum_3_11"]:
        recs.append("Python 3.11+ gerekli. https://www.python.org/downloads/ adresinden kurun.")
    tools = report["tools"]
    if not tools.get("ollama", {}).get("installed"):
        recs.append("Ollama kurulu değil: 'winget install Ollama.Ollama' veya https://ollama.com/download")
    elif not report["ollama"].get("reachable"):
        recs.append("Ollama kurulu ama servis yanıt vermiyor: Ollama uygulamasını başlatın.")
    if not tools.get("git", {}).get("installed"):
        recs.append("Git kurulu değil: 'winget install Git.Git'")
    if not tools.get("tesseract", {}).get("installed"):
        recs.append("Tesseract OCR yok (Faz 5'te gerekecek, şimdilik gerekmez).")
    if not tools.get("ffmpeg", {}).get("installed"):
        recs.append("ffmpeg yok (Faz 6 ses işleme için gerekecek, şimdilik gerekmez).")
    free = report["disk"].get("free_gb") or 0
    if free < 60:
        recs.append(f"Diskte {free} GB boş alan var; modeller için en az 60 GB önerilir.")
    recs.extend(report["gpu"].get("notes", []))
    return recs


def run_audit(project_dir: Path | None = None, ollama_url: str | None = None) -> dict[str, Any]:
    project_dir = (project_dir or Path.cwd()).resolve()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_dir": str(project_dir),
        "os": os_info(),
        "cpu": cpu_info(),
        "ram": ram_info(),
        "disk": disk_info(project_dir),
        "gpu": gpu_info(),
        "python": python_check(),
        "tools": tool_versions(),
        "ollama": ollama_status(ollama_url or os.environ.get("KAYAAI_OLLAMA_URL", "http://127.0.0.1:11434")),
    }
    report["recommendations"] = recommendations(report)
    return report


def format_summary(report: dict[str, Any]) -> str:
    lines = ["=== kayaAI Ortam Denetimi ==="]
    o = report["os"]
    lines.append(f"İşletim sistemi : {o['system']} {o['release']} ({o['version']}) {o['machine']}")
    lines.append(f"CPU             : {report['cpu']['name']} - {report['cpu']['logical_cores']} mantıksal çekirdek")
    r = report["ram"]
    lines.append(f"RAM             : toplam {r['total_gb']} GB, boş {r['available_gb']} GB")
    d = report["disk"]
    lines.append(f"Disk ({d['path']}): toplam {d['total_gb']} GB, boş {d['free_gb']} GB")
    gpus = report["gpu"]["gpus"]
    if gpus:
        for g in gpus:
            lines.append(
                f"GPU             : {g.get('name')} | VRAM {g.get('memory.total_mb')} MB "
                f"(boş {g.get('memory.free_mb')} MB) | sürücü {g.get('driver_version')} | "
                f"compute {g.get('compute_cap', '?')} | CUDA {report['gpu'].get('cuda_driver_version')}"
            )
    else:
        lines.append("GPU             : NVIDIA GPU algılanmadı")
    lines.append("Yazılımlar:")
    for name, t in report["tools"].items():
        mark = "OK " if t.get("installed") else "-- "
        lines.append(f"  {mark}{name:<10} {t.get('version', 'kurulu değil')}")
    ol = report["ollama"]
    if ol.get("reachable"):
        names = ", ".join(m["name"] for m in ol.get("models", [])) or "(model yok)"
        lines.append(f"Ollama servisi  : çalışıyor v{ol.get('version')} - modeller: {names}")
    else:
        lines.append("Ollama servisi  : erişilemiyor")
    lines.append("Öneriler:")
    for rec in report["recommendations"]:
        lines.append(f"  * {rec}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="kayaAI ortam denetimi (salt okunur)")
    parser.add_argument("--out", type=Path, default=Path("data") / "audit_report.json")
    parser.add_argument("--project-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    report = run_audit(args.project_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _safe_print(format_summary(report))
    _safe_print(f"\nRapor yazıldı: {args.out.resolve()}")
    return 0


def _safe_print(text: str) -> None:
    """Eski Windows konsollarında (cp1254/cp437) Türkçe karakterler hata vermesin."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc))


if __name__ == "__main__":
    raise SystemExit(main())
