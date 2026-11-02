"""Docker ile konteyner çalıştırma (Adım 19c). `exec_fn(args, timeout) -> (returncode, stdout, stderr)` enjekte
edilebilir (testlerde sahte Docker). Gerçekte `docker` komut satırı kullanılır (ek Python bağımlılığı yok)."""

from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ExecFn = Callable[[list[str], float], tuple[int, str, str]]
OUT_FILES_MAX = 20
OUT_FILE_MAX_BYTES = 5 * 1024 * 1024


def execute(args: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "docker bulunamadı (Docker Desktop kurulu ve çalışıyor mu?)"
    except subprocess.TimeoutExpired:
        return 124, "", "zaman aşımı"


def image_ready(cfg: Any, exec_fn: ExecFn | None = None) -> tuple[bool, str]:
    exec_fn = exec_fn or execute
    code, _, err = exec_fn([cfg.docker, "image", "inspect", "--format", "{{.Id}}", cfg.image], 20)
    if code == 0:
        return True, "hazır"
    if code == 127:
        return False, err.strip() or "docker bulunamadı"
    if "daemon" in err.lower() or "pipe" in err.lower() or "connect" in err.lower():
        return False, "Docker çalışmıyor (Docker Desktop'ı başlat)"
    return False, f"kum havuzu imajı yok ({cfg.image}) — kurmak için: kayaai sandbox build"


def docker_cmd(cfg: Any, run_dir: Path, name: str) -> list[str]:
    """Kilitli konteyner komutu: ağ yok, salt-okunur kök, yetkisiz kullanıcı, kaynak sınırları, yalnız in/out bağlı."""
    args = [cfg.docker, "run", "--rm", "--name", name,
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
            "--memory", cfg.memory, "--memory-swap", cfg.memory, "--cpus", str(cfg.cpus),
            "--pids-limit", str(cfg.pids_limit), "--ulimit", "nofile=256:256",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10001:10001",
            "-e", f"MAX_OUT={cfg.max_output_kb * 1024}", "-e", f"TIME_LIMIT={int(cfg.timeout_s)}",
            "-v", f"{(run_dir / 'in').resolve()}:/in:ro",
            "-v", f"{(run_dir / 'out').resolve()}:/out:rw"]
    if cfg.runtime:
        args += ["--runtime", cfg.runtime]  # ör. gVisor (runsc) — Linux sunucuda ek yalıtım
    return args + [cfg.image]


def parse_output(raw: str) -> tuple[str, str, int | None]:
    """run.sh çıktısı: stdout · @@KAYA_STDERR@@ · stderr · @@KAYA_EXIT@@<kod>. Son işaretler esas alınır (kod içinden
    yazılan sahte işaretler sonucu bozamaz)."""
    head, sep, tail = raw.rpartition("@@KAYA_EXIT@@")
    if not sep:
        return raw, "", None
    try:
        code: int | None = int(tail.strip().splitlines()[0])
    except (ValueError, IndexError):
        code = None
    out, sep2, err = head.rpartition("\n@@KAYA_STDERR@@\n")
    if not sep2:
        out, err = head, ""
    return out.rstrip("\n"), err.rstrip("\n"), code


def run_container(cfg: Any, run_dir: Path, exec_fn: ExecFn | None = None) -> dict[str, Any]:
    exec_fn = exec_fn or execute
    name = f"kayaai-sb-{uuid.uuid4().hex[:10]}"
    t0 = time.monotonic()
    code, raw, err = exec_fn(docker_cmd(cfg, run_dir, name), cfg.timeout_s + 15)
    timed_out = code == 124
    if timed_out:  # süre aştı: konteyneri öldür (ağsız, ama işlemci/bellek tüketmesin)
        exec_fn([cfg.docker, "kill", name], 15)
        exec_fn([cfg.docker, "rm", "-f", name], 15)
    stdout, stderr, exit_code = parse_output(raw)
    if exit_code == 124:  # içerideki `timeout` durdurdu
        timed_out = True
    if exit_code is None:  # konteyner hiç başlamadı (imaj yok, Docker hatası) ya da sınır aşıldı (bellek → 137)
        exit_code, stderr = code, (stderr + "\n" + err).strip()
    if exit_code == 137 and not timed_out:
        stderr = (stderr + "\n(bellek sınırı aşıldı)").strip()
    if timed_out:
        stderr = (stderr + f"\n(süre sınırı aşıldı: {int(cfg.timeout_s)} sn)").strip()
    files = []
    out_dir = run_dir / "out"
    for p in sorted(out_dir.iterdir())[:OUT_FILES_MAX] if out_dir.is_dir() else []:
        if p.is_file() and p.stat().st_size <= OUT_FILE_MAX_BYTES:
            files.append(p.name)
    return {"exit_code": exit_code, "timed_out": timed_out, "stdout": stdout[-cfg.max_output_kb * 1024:],
            "stderr": stderr[-8000:], "seconds": round(time.monotonic() - t0, 2), "files": files}
