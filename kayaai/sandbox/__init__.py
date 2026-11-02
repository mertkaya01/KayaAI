"""Kod kum havuzu (Adım 19c): ajanların yazdığı Python kodu yalnız izole bir Docker konteynerinde çalışır.

Güvenlik katmanları (sahip kararı: kum havuzu içi çalıştırma R1 — otomatik ve kayıtlı):
1. **Politika** (`policy.check`): kod boyutu; ağ, alt süreç, sistem çağrısı kullanan kod ÇALIŞTIRILMAZ, ajana
   "bunsuz yeniden yaz" denir. Bu ek kontroldür; asıl sınır konteynerdir.
2. **Konteyner** (`runner.docker_cmd`): ağ yok, kök dosya sistemi salt-okunur, root değil (uid 10001), bütün
   yetkiler düşürülmüş, yeni yetki kazanılamaz, bellek/CPU/süreç/dosya sınırı, süre sınırı; yalnız o çalıştırmanın
   `in` (salt-okunur: kod + ekler) ve `out` klasörleri bağlı. Bilgisayarındaki dosyaları göremez.
3. **İzin motoru**: her çalıştırma `sandbox.python` (R1) olarak kayda geçer; `sandbox.run` olayı (kod uzunluğu,
   çıkış kodu, süre). Kod ve çıktılar `data/sandbox/<çalıştırma>/` altında saklanır (son 50).
Docker ya da imaj yoksa araç kapalıdır; kod hiçbir koşulda doğrudan bilgisayarda çalışmaz.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.permissions import Risk, ToolAction
from . import policy, runner

if TYPE_CHECKING:
    from ..runtime import Runtime

KEEP_RUNS = 50


class Sandbox:
    """Orkestratörün işçilere verdiği kum havuzu (ajan → `run(...)`)."""

    def __init__(self, rt: "Runtime", exec_fn: Any = None):
        self.rt = rt
        self.cfg = rt.settings.sandbox
        self._exec = exec_fn  # None: gerçek docker (runner.execute)
        self._avail: tuple[float, bool, str] | None = None

    # ------------------------------------------------------------------ durum

    def available(self) -> bool:
        return self.availability()[0]

    def availability(self) -> tuple[bool, str]:
        if not self.cfg.enabled:
            return False, "kum havuzu ayarda kapalı (sandbox.enabled)"
        now = time.monotonic()
        if self._avail and now - self._avail[0] < 60:
            return self._avail[1], self._avail[2]
        ok, why = runner.image_ready(self.cfg, self._exec)
        self._avail = (now, ok, why)
        return ok, why

    def root(self) -> Path:
        return self.rt.settings.data_dir / "sandbox"

    # ------------------------------------------------------------------ çalıştırma

    def run(self, code: str, files: dict[str, str] | None = None, *, agent: str = "?", task_id: str | None = None) -> dict[str, Any]:
        """Kodu kum havuzunda çalıştırır; sonuç sözlüğü (ajana geri verilir). Politika reddi de sonuçtur."""
        problems = policy.check(code, self.cfg)
        if problems:
            self.rt.store.emit("sandbox.refused", {"agent": agent, "task_id": task_id, "reasons": problems})
            return {"status": "refused", "reasons": problems,
                    "hint": "Bu kum havuzunda ağ, alt süreç ve sistem çağrısı yok; kodu bunlar olmadan yeniden yaz."}
        ok, why = self.availability()
        if not ok:
            return {"status": "unavailable", "reason": why}
        run_id = uuid.uuid4().hex[:12]
        rdir = self.root() / run_id
        in_dir, out_dir = rdir / "in", rdir / "out"
        in_dir.mkdir(parents=True)
        out_dir.mkdir()
        out_dir.chmod(0o777)  # konteyner kullanıcısı (uid 10001) yazabilsin
        (in_dir / "main.py").write_text(code, encoding="utf-8")
        for name, content in (files or {}).items():
            safe = policy.safe_name(name)
            if safe:
                (in_dir / safe).write_text(content, encoding="utf-8")
        assert self.rt.permissions is not None
        res = self.rt.permissions.submit(ToolAction(
            tool="sandbox.python", params={"run_id": run_id, "agent": agent, "task_id": task_id}, risk=Risk.R1,
            summary=f"Kum havuzunda Python çalıştır ({agent}, {len(code)} karakter)",
            reason="Ağsız, izole konteyner; bilgisayarındaki dosyalara erişemez.", requested_by=f"agent:{agent}"))
        self._prune()
        if res.status != "done":
            return {"status": "error", "error": res.error or res.status}
        return res.result  # type: ignore[return-value]

    def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """İzin motorunun çağırdığı yürütücü (R1)."""
        rdir = self.root() / str(params["run_id"])
        if not (rdir / "in" / "main.py").is_file():
            raise FileNotFoundError("çalıştırma klasörü yok")
        out = runner.run_container(self.cfg, rdir, self._exec)
        self.rt.store.emit("sandbox.run", {"run_id": params["run_id"], "agent": params.get("agent"),
                                           "task_id": params.get("task_id"), "exit_code": out["exit_code"],
                                           "timed_out": out["timed_out"], "seconds": out["seconds"],
                                           "files": out["files"]})
        return {"status": "ok" if out["exit_code"] == 0 and not out["timed_out"] else "failed", **out,
                "run_id": params["run_id"]}

    def _prune(self) -> None:
        root = self.root()
        if not root.is_dir():
            return
        runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in runs[KEEP_RUNS:]:
            shutil.rmtree(old, ignore_errors=True)


def executors(sb: Sandbox) -> dict[str, Any]:
    return {"sandbox.python": sb._execute}


def status(rt: "Runtime", sb: Sandbox | None = None) -> dict[str, Any]:
    sb = sb or Sandbox(rt)
    ok, why = sb.availability()
    c = rt.settings.sandbox
    return {"available": ok, "reason": why, "image": c.image, "enabled": c.enabled, "timeout_s": c.timeout_s,
            "memory": c.memory, "cpus": c.cpus, "runtime": c.runtime, "max_tool_turns": c.max_tool_turns}
