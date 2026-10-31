"""kayaAI komut satırı arayüzü.

    kayaai doctor            Sistem/Ollama/model kontrolü
    kayaai ask "soru"        Genel worker'a görev ver
    kayaai tasks             Görev geçmişi
    kayaai task <id>         Görev ayrıntısı ve olayları
    kayaai models            Model kayıt defteri ve kurulu modeller
    kayaai audit             Ortam denetimi (data/audit_report.json)
    kayaai claude [on|off]   Claude modu durumu / aç / kapat
    kayaai mcp               MCP sunucusu (stdio) - Claude Code bunu kendisi başlatır
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import APP_NAME, __version__
from .config import load_settings
from .core.task import Task, TaskStatus
from .llm.ollama_client import OllamaClient, OllamaError
from .llm.registry import ModelRegistry


def _print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc))


def _enable_utf8_console() -> None:
    # Windows konsolunda Türkçe karakterler için.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def interactive_approver(task: Task, permissions: list[str]) -> bool:
    _print(f"\n[ONAY GEREKLİ] Görev {task.id} ({task.worker}) şu izinleri istiyor: {', '.join(permissions)}")
    _print(f"  Amaç: {task.objective[:300]}")
    try:
        answer = input("  Onaylıyor musunuz? [e/H]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"e", "evet", "y", "yes"}


# --------------------------------------------------------------------------- komutlar


def cmd_doctor(args: argparse.Namespace) -> int:
    from .system.audit import gpu_info

    settings = load_settings()
    ok = True
    _print(f"{APP_NAME} v{__version__} - sistem kontrolü\n")

    py_ok = sys.version_info >= (3, 11)
    ok &= py_ok
    _print(f"[{'OK' if py_ok else 'HATA'}] Python {sys.version.split()[0]} (gereken >= 3.11)")
    _print(f"[OK] Yapılandırma: {settings.config_dir}")

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _print(f"[OK] Veri klasörü yazılabilir: {settings.data_dir}")
    except OSError as exc:
        ok = False
        _print(f"[HATA] Veri klasörü yazılamıyor: {settings.data_dir} ({exc})")

    gpu = gpu_info()
    if gpu["gpus"]:
        for g in gpu["gpus"]:
            _print(
                f"[OK] GPU: {g.get('name')} | VRAM {g.get('memory.total_mb')} MB, boş {g.get('memory.free_mb')} MB "
                f"| sürücü {g.get('driver_version')} | CUDA {gpu.get('cuda_driver_version')}"
            )
    else:
        _print("[UYARI] NVIDIA GPU algılanmadı (nvidia-smi yok). Modeller CPU'da yavaş çalışır.")
    for note in gpu.get("notes", []):
        _print(f"       not: {note}")

    if not settings.ollama.is_local:
        _print(f"[UYARI] Ollama adresi yerel değil: {settings.ollama.base_url}")

    try:
        registry = ModelRegistry.load(settings.models_file)
        _print(f"[OK] Model kayıt defteri: {len(registry.models)} model, {len(registry.worker_assignments)} worker ataması")
    except (OSError, ValueError, KeyError) as exc:
        _print(f"[HATA] Model kayıt defteri okunamadı: {exc}")
        return 1

    client = OllamaClient(settings.ollama.model_copy(update={"max_retries": 0}))
    try:
        version = client.version()
        _print(f"[OK] Ollama çalışıyor: v{version} ({settings.ollama.base_url})")
        installed = {m.get("name") for m in client.list_models()}
        for worker, key in registry.worker_assignments.items():
            spec = registry.get(key)
            present = spec.name in installed or f"{spec.name}:latest" in installed
            ok &= present
            if present:
                _print(f"[OK] Model kurulu: {spec.name} (worker: {worker})")
            else:
                _print(f"[HATA] Model kurulu değil: {spec.name} (worker: {worker}) -> çalıştırın: ollama pull {spec.name}")
        for m in client.running_models():
            vram = (m.get("size_vram") or 0) / 1024**3
            total = (m.get("size") or 0) / 1024**3
            _print(f"       yüklü: {m.get('name')} - bellek {total:.1f} GB, bunun {vram:.1f} GB'ı VRAM'de")
    except OllamaError as exc:
        ok = False
        _print(f"[HATA] Ollama'ya ulaşılamadı: {exc}")
        _print("       Kurulum: winget install Ollama.Ollama  (veya https://ollama.com/download)")
    finally:
        client.close()

    try:
        from .core.claude_mode import ClaudeMode
        from .core.store import TaskStore

        store = TaskStore(settings.db_path)
        try:
            _print(f"[BİLGİ] {ClaudeMode(store, settings.claude).status().label}")
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - doctor bilgi satırı yüzünden düşmemeli
        _print(f"[UYARI] Claude modu okunamadı: {exc}")

    _print("\nSonuç: " + ("HAZIR" if ok else "EKSİKLER VAR (yukarıdaki HATA satırlarına bakın)"))
    return 0 if ok else 1


def cmd_ask(args: argparse.Namespace) -> int:
    from .logging_setup import setup_logging
    from .runtime import build_runtime

    settings = load_settings()
    setup_logging(settings, console=True)
    question = " ".join(args.question).strip()
    if not question:
        _print("Soru boş olamaz.")
        return 2
    with build_runtime(settings, approver=interactive_approver) as rt:
        if rt.recovered_task_ids:
            _print(f"(Önceki oturumdan yarım kalan {len(rt.recovered_task_ids)} görev 'failed' olarak işaretlendi.)")
        _print(f"[{args.worker or settings.orchestrator.default_worker}] düşünüyor... (ilk istekte model yüklenir)")
        task = rt.orchestrator.ask(question, worker=args.worker, timeout_s=args.timeout)
    if args.json:
        _print(task.model_dump_json(indent=2))
    else:
        _print_task_result(task)
    return 0 if task.status == TaskStatus.SUCCEEDED else 1


def _print_task_result(task: Task) -> None:
    if task.status == TaskStatus.SUCCEEDED and task.result:
        _print("\n" + str(task.result.get("answer", json.dumps(task.result, ensure_ascii=False, indent=2))))
        m = task.metrics
        extras = {k: task.result[k] for k in ("language", "task_type", "confidence", "needs_tools") if k in task.result}
        _print(
            f"\n— görev {task.id} | {task.model} | {m.get('tokens_per_second')} token/sn | "
            f"{task.duration_s:.1f} sn | {extras}"
        )
    else:
        _print(f"\nGörev {task.id} -> {task.status.value}: {task.error}")
        if task.validation and task.validation.errors:
            for e in task.validation.errors:
                _print(f"  - {e}")


def cmd_tasks(args: argparse.Namespace) -> int:
    from .core.store import TaskStore

    settings = load_settings()
    store = TaskStore(settings.db_path)
    try:
        status = TaskStatus(args.status) if args.status else None
        tasks = store.list_tasks(limit=args.limit, status=status)
        if not tasks:
            _print("Görev geçmişi boş.")
        for t in tasks:
            dur = f"{t.duration_s:.1f}s" if t.duration_s is not None else "-"
            _print(f"{t.id}  {t.created_at:%Y-%m-%d %H:%M}  {t.status.value:<17} {t.worker:<10} {dur:>7}  {t.objective[:60]}")
        _print(f"\nToplam kayıtlı görev: {store.count()}")
    finally:
        store.close()
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    from .core.store import TaskStore

    settings = load_settings()
    store = TaskStore(settings.db_path)
    try:
        task = store.get(args.task_id)
        if task is None:
            _print(f"Görev bulunamadı: {args.task_id}")
            return 1
        _print(task.model_dump_json(indent=2))
        _print("\nOlaylar:")
        for ev in store.events(task.id):
            _print(f"  {ev['ts']}  {ev['event']:<20} {ev['detail'] or ''}")
    finally:
        store.close()
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    settings = load_settings()
    registry = ModelRegistry.load(settings.models_file)
    installed: set[str] | None = None
    client = OllamaClient(settings.ollama.model_copy(update={"max_retries": 0}))
    try:
        installed = {m.get("name") for m in client.list_models()}
    except OllamaError:
        _print("(Ollama'ya ulaşılamadı; kurulu olma durumu gösterilemiyor)")
    finally:
        client.close()
    assignments: dict[str, list[str]] = {}
    for w, k in registry.worker_assignments.items():
        assignments.setdefault(k, []).append(w)
    for key, spec in registry.models.items():
        state = "?" if installed is None else ("kurulu" if spec.name in installed else "KURULU DEĞİL")
        _print(
            f"{key:<14} {spec.name:<18} {state:<13} ~{spec.approx_vram_gb} GB VRAM  "
            f"lisans: {spec.license}  worker: {', '.join(assignments.get(key, [])) or '-'}"
        )
        _print(f"{'':<14} {spec.purpose}")
    return 0


def cmd_claude(args: argparse.Namespace) -> int:
    from .core.claude_mode import ClaudeMode
    from .core.store import TaskStore

    settings = load_settings()
    store = TaskStore(settings.db_path)
    try:
        mode = ClaudeMode(store, settings.claude)
        if args.action == "on":
            st = mode.enable()
            _print(f"[AÇIK] {st.label}")
            _print("Not: Claude için çalışma klasörü (CLAUDE.md, alt ajanlar) üretimi Adım 3e'de eklenecek.")
            _print("Şimdilik Claude Code'u proje klasöründe açıp kayaai MCP araçlarını kullanabilirsiniz.")
        elif args.action == "off":
            st = mode.disable()
            _print(f"[KAPALI] {st.label}")
            if st.waiting_tasks:
                _print(f"Uyarı: Claude kutusunda {st.waiting_tasks} görev bekliyor. Bunları yerelde yapma "
                       "özelliği Adım 3d'de eklenecek; görevler silinmedi.")
        else:
            st = mode.status()
            _print(st.label)
            if st.last_contact:
                _print(f"Son temas (UTC): {st.last_contact:%Y-%m-%d %H:%M:%S}")
        if args.json:
            _print(st.model_dump_json(indent=2))
    finally:
        store.close()
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()  # stdio üzerinden MCP; istemci (Claude Code) bu süreci kendisi başlatır
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .config import PROJECT_ROOT
    from .system.audit import main as audit_main

    out = load_settings().data_dir / "audit_report.json"
    return audit_main(["--project-dir", str(PROJECT_ROOT), "--out", str(out)])


# --------------------------------------------------------------------------- giriş


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kayaai", description=f"{APP_NAME} - yerel kişisel yapay zeka sistemi")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="sistem, Ollama ve model kontrolü").set_defaults(func=cmd_doctor)

    a = sub.add_parser("ask", help="bir worker'a soru/görev ver")
    a.add_argument("question", nargs="+")
    a.add_argument("--worker", default=None)
    a.add_argument("--timeout", type=float, default=None, help="saniye")
    a.add_argument("--json", action="store_true", help="tüm görev nesnesini JSON olarak yazdır")
    a.set_defaults(func=cmd_ask)

    t = sub.add_parser("tasks", help="görev geçmişi")
    t.add_argument("--limit", type=int, default=20)
    t.add_argument("--status", choices=[s.value for s in TaskStatus])
    t.set_defaults(func=cmd_tasks)

    d = sub.add_parser("task", help="görev ayrıntısı")
    d.add_argument("task_id")
    d.set_defaults(func=cmd_task)

    sub.add_parser("models", help="model kayıt defteri").set_defaults(func=cmd_models)
    sub.add_parser("audit", help="ortam denetimi raporu").set_defaults(func=cmd_audit)
    c = sub.add_parser("claude", help="Claude modu: durum / aç / kapat")
    c.add_argument("action", nargs="?", choices=["status", "on", "off"], default="status")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_claude)

    sub.add_parser("mcp", help="MCP sunucusunu stdio üzerinden başlat (Claude Code için)").set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    _enable_utf8_console()
    args = build_parser().parse_args(argv)
    result: Any = args.func(args)
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
