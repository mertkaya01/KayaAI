"""kayaAI komut satırı arayüzü.

    kayaai doctor            Sistem/Ollama/model kontrolü
    kayaai ask "soru"        Genel worker'a görev ver
    kayaai tasks             Görev geçmişi
    kayaai task <id>         Görev ayrıntısı ve olayları
    kayaai models [load|unload|assign|pull|compare|activate]  Modeller (ajan ataması/indirme sahip onaylı)
    kayaai audit             Ortam denetimi (data/audit_report.json)
    kayaai do "istek"        Şef: planla → ajanlara dağıt → birleştir → gözden geçir
    kayaai agents            Tanımlı ajanlar (config/agents/*.yaml)
    kayaai claude [on|off|sync]  Claude modu durumu / aç (+çalışma alanı) / kapat / alanı yeniden üret
    kayaai inbox [run|cancel] [id]  Claude kutusu
    kayaai files roots|ls|read|write  Dosya araçları (izinli klasörler; üzerine yazma onay ister)
    kayaai approvals [show|approve|reject] [id]  Onay kuyruğu
    kayaai pause | resume    Otomasyonu duraklat / sürdür (zamanlanmış görevler, tarayıcı)
    kayaai schedule [list|add|run|rm|…]  Zamanlanmış görevler (Windows Görev Zamanlayıcı)
    kayaai browse "hedef" --url ADRES  Tarayıcı ajanı (ayrı Edge profili; form/gönder/öde onaylı)
    kayaai speech [status|download|transcribe <dosya>]  Yerel ses tanıma (faster-whisper)
    kayaai screen ["soru"]   Ekran görüntüsü (tek kare) + yerel görsel model (OCR ile doğrulama)
    kayaai api [token]       Yerel API sunucusu (127.0.0.1:8765) / erişim anahtarı
    kayaai mcp               MCP sunucusu (stdio) - Claude Code bunu kendisi başlatır
"""

from __future__ import annotations

import argparse
from pathlib import Path
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
        registry = ModelRegistry.load_for(settings)
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
        try:  # Adım 9: hafıza modeli zorunlu değil (yoksa kelime araması), ama önerilir
            emb = registry.get(settings.memory.embed_model)
            if emb.name in installed or f"{emb.name}:latest" in installed:
                _print(f"[OK] Hafıza modeli kurulu: {emb.name}")
            else:
                _print(f"[UYARI] Hafıza modeli kurulu değil: {emb.name} — anlam araması için: ollama pull {emb.name} "
                       "(yoksa hafıza yalnızca kelime aramasıyla çalışır)")
        except KeyError as exc:
            _print(f"[UYARI] Hafıza modeli tanımlı değil: {exc}")
        vis = registry.models.get("vision-7b")  # Adım 12a: isteğe bağlı
        if vis is not None:
            if vis.name in installed or f"{vis.name}:latest" in installed:
                _print(f"[OK] Görsel model kurulu: {vis.name}")
            else:
                _print(f"[UYARI] Görsel model kurulu değil: {vis.name} — ekranı okumak için: ollama pull {vis.name}")
        from .perception.ocr import available as ocr_available

        _print(("[OK] " if ocr_available()[0] else "[UYARI] ") + "OCR: " + ocr_available()[1])
        from .speech.stt import is_installed as speech_installed

        if speech_installed(settings):
            _print(f"[OK] Ses tanıma modeli kurulu: whisper {settings.speech.model}")
        else:
            _print(f"[UYARI] Ses tanıma modeli kurulu değil (whisper {settings.speech.model}) — kayaai speech download")
        import importlib.util as _iu

        if _iu.find_spec("playwright") is not None:
            _print(f"[OK] Tarayıcı otomasyonu: Playwright kurulu · tarayıcı: {settings.browser.channel or settings.browser.executable_path}"
                   " (ayrı profil)")
        else:
            _print("[UYARI] Tarayıcı otomasyonu: Playwright kurulu değil (setup.ps1)")
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


def _print_model_submit(res: Any, done_msg: str) -> int:
    if res.status == "awaiting_approval":
        _print(f"[ONAY BEKLİYOR] {res.message}")
        _print(f"Onayla: kayaai approvals approve {res.approval_id}  (ya da Control Center → Onay merkezi)")
        return 0
    if res.status == "failed":
        _print(f"[HATA] {res.error}")
        return 1
    _print(f"[OK] {done_msg}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from .llm import manager as mm
    from .llm.compare import CompareError, start_compare
    from .runtime import build_runtime

    with build_runtime(load_settings()) as rt:
        try:
            if args.action in ("load", "unload", "pull"):
                if not args.name:
                    _print(f"Model adı gerekli: kayaai models {args.action} <ollama-adı>  (ör. qwen3:8b)")
                    return 2
                if args.action == "pull":
                    return _print_model_submit(mm.request_pull(rt, args.name, requested_by="cli"), f"İndirildi: {args.name}")
                res = mm.request_load(rt, args.name, unload=args.action == "unload", requested_by="cli")
                return _print_model_submit(res, f"{args.name} {'bellekten çıkarıldı' if args.action == 'unload' else 'belleğe yüklendi'}")
            if args.action == "assign":
                if not args.name or not args.model:
                    _print("Kullanım: kayaai models assign <ajan> <model>  (anahtar ya da Ollama adı, ör. data coder-7b)")
                    return 2
                return _print_model_submit(mm.request_agent_model(rt, args.name, args.model, requested_by="cli"), "Atandı")
            if args.action == "activate":
                if not args.name:
                    _print("Model anahtarı gerekli: kayaai models activate <anahtar>")
                    return 2
                return _print_model_submit(mm.request_activate(rt, args.name, requested_by="cli"), "Aktif")
            if args.action == "compare":
                if not args.name or not args.model:
                    _print("Kullanım: kayaai models compare <ajan> <aday>  (anahtar ya da Ollama adı, ör. data qwen3:4b)")
                    return 2
                _print(f"Karşılaştırılıyor: {args.name} ajanı, mevcut model ↔ {args.model} (birkaç dakika sürebilir)...")
                rec = start_compare(rt, args.name, args.model)
                if rec["status"] != "done":
                    _print(f"[HATA] {rec.get('error')}")
                    return 1
                for side, title in (("current", "Mevcut"), ("candidate", "Aday")):
                    sm = rec["summary"][side]
                    load = (rec.get("load_seconds") or {}).get(side)
                    _print(f"{title:<7} {sm['model']:<20} {sm['ok']}/{sm['cases']} doğru  ort. {sm['avg_seconds']} sn  "
                           f"{sm['avg_tokens_per_second'] or '-'} token/sn"
                           + (f"  (belleğe yükleme {load} sn, ortalamaya dahil değil)" if load is not None else ""))
                    for r in rec["rows"][side]:
                        why = [] if r["ok"] else ([f"eksik: {', '.join(r['missing'])}"] if r["missing"] else []) + \
                            (["dil"] if not r["language_ok"] else []) + (["kod"] if not r["code_ok"] else []) + \
                            (["yabancı yazı"] if r["foreign_script"] else []) + (["görev başarısız"] if not r["succeeded"] else []) + \
                            (["soruyu tekrarladı"] if r.get("echo") else [])
                        _print(f"        {'OK ' if r['ok'] else 'X  '} {r['request'][:60]}  {'; '.join(why)}")
                _print(f"Sonuç: {rt.settings.data_dir / 'model_compare' / (rec['id'] + '.json')}")
                return 0
        except (mm.ModelAdminError, CompareError, OllamaError) as exc:
            _print(f"[HATA] {exc}")
            return 1
        ov = mm.overview(rt)
        if not ov["ollama_reachable"]:
            _print("(Ollama'ya ulaşılamadı; kurulu/yüklü durumu gösterilemiyor)")
        for m in ov["models"]:
            state = "?" if m["installed"] is None else ("kurulu" if m["installed"] else "KURULU DEĞİL")
            if m["loaded"]:
                state = f"YÜKLÜ {m['loaded']['vram_gb']} GB"
            status = {"active": "aktif", "candidate": "ADAY", "unregistered": "kayıtsız"}.get(m["status"], m["status"])
            _print(f"{m['key'] or '-':<14} {m['name']:<20} {state:<14} {status:<8} ~{m['approx_vram_gb'] or '?'} GB VRAM  "
                   f"lisans: {m['license'] or '-'}  kullanan: {', '.join(m['agents']) or '-'}")
            if m["purpose"]:
                _print(f"{'':<14} {m['purpose']}")
            if m["status"] == "unregistered":
                _print(f"{'':<14} kayaAI kaydında yok (Ollama'da kurulu). Karşılaştırmak için: "
                       f"kayaai models compare <ajan> {m['name']}")
        _print("\nKomutlar: kayaai models load|unload <ad> · assign <ajan> <anahtar> · pull <ad> · "
               "compare <ajan> <aday> · activate <model>  (model: anahtar ya da Ollama adı, ör. qwen3:4b)")
    return 0


def cmd_do(args: argparse.Namespace) -> int:
    from .conductor import Conductor
    from .logging_setup import setup_logging
    from .runtime import build_runtime

    settings = load_settings()
    setup_logging(settings, console=True)
    request = " ".join(args.request).strip()
    if not request:
        _print("İstek boş olamaz.")
        return 2
    force = "local" if args.local else ("claude" if args.claude else None)
    with build_runtime(settings, approver=interactive_approver) as rt:
        _print("[şef] planlıyor... (yerel modeller)")
        res = Conductor(rt).run(request, force=force)
    if args.json:
        _print(res.model_dump_json(indent=2))
        return 0 if res.status == "succeeded" else 1
    if res.status == "succeeded":
        _print("\n" + res.answer)
    elif res.status == "waiting_claude":
        _print(f"\nİş Claude kutusunda bekliyor (iş {res.job_id}). Sebep: {res.routing.reason}")
        _print("Yerelde yaptırmak için:  kayaai do --local \"...\"")
    else:
        _print(f"\nİş başarısız: {res.error}")
    for w in res.warnings:
        _print(f"[UYARI] {w}")
    for s in res.steps:
        if s.review:
            rv = s.review
            parts = [f"karar: {rv.verdict or '-'}"]
            if rv.checks and (rv.checks.checked_blocks or rv.checks.failures):
                parts.append(f"kontrol: {rv.checks.checked_blocks} blok, {len(rv.checks.failures)} hata")
            if rv.dropped_issues:
                parts.append(f"{rv.dropped_issues} kanıtsız not elendi")
            if rv.revised:
                parts.append("düzeltildi")
            if rv.disputes:
                parts.append(f"{len(rv.disputes)} anlaşmazlık")
            if rv.skipped:
                parts.append(rv.skipped)
            _print(f"[gözden geçirme] {s.agent} → {rv.reviewer}: " + ", ".join(parts))
    steps = " → ".join(f"{s.agent}({s.status})" for s in res.steps)
    review = f" | gözden geçirme: {res.review.verdict}{' (düzeltildi)' if res.review.revised else ''}" if res.review.performed else ""
    _print(f"\n— iş {res.job_id} | {res.mode} | {steps}{review} | {res.duration_s} sn | yönlendirme: {res.routing.decision}")
    return 0 if res.status in ("succeeded", "waiting_claude") else 1


def cmd_agents(args: argparse.Namespace) -> int:
    from .agents.definitions import AgentDefinitionError
    from .agents.lifecycle import (
        AgentLifecycleError,
        AgentProposal,
        create_temporary,
        remove_temporary,
        request_promotion,
        usage,
        user_agents_dir,
    )
    from .runtime import build_runtime

    settings = load_settings()
    try:
        rt = build_runtime(settings)
    except AgentDefinitionError as exc:
        _print(f"[HATA] Ajan tanımı geçersiz: {exc}")
        return 1
    with rt:
        try:
            if args.action == "new":
                if not args.name or not args.description or not (args.role or args.role_file):
                    _print("Kullanım: kayaai agents new <ad> --base general --description \"...\" --role \"...\" "
                           "(ya da --role-file dosya.txt)")
                    return 2
                role = Path(args.role_file).read_text(encoding="utf-8") if args.role_file else args.role
                d = create_temporary(rt, AgentProposal(name=args.name, description=args.description, role=role,
                                                       base=args.base), created_by="owner")
                _print(f"[OK] Geçici ajan oluşturuldu: {d.name} (temel: {d.base}, model: {d.local_model})")
                _print(f"Dene: kayaai do \"...\"  ya da  kayaai ask --worker {d.name} \"...\"")
                return 0
            if args.action in ("promote", "remove"):
                if not args.name:
                    _print(f"Ajan adı gerekli: kayaai agents {args.action} <ad>")
                    return 2
                if args.action == "remove":
                    remove_temporary(rt, args.name)
                    _print(f"[OK] Geçici ajan kaldırıldı: {args.name}")
                    return 0
                res = request_promotion(rt, args.name, requested_by="cli")
                _print(f"[ONAY BEKLİYOR] {res.message}")
                _print(f"Onayla: kayaai approvals approve {res.approval_id}  (ya da Control Center → Onay merkezi)")
                return 0
        except (AgentLifecycleError, ValueError, OSError) as exc:
            _print(f"[HATA] {exc}")
            return 1
        for w in rt.workers.all():
            d = getattr(w, "definition", None)
            spec = w.model_spec(rt.registry)
            extra = ""
            if d is not None and d.created_by:
                done, ok = usage(rt, w.name)
                kind = "GEÇİCİ" if d.status == "temporary" else "kalıcı"
                extra = f"  [{kind}, temel: {d.base}, oluşturan: {d.created_by}, kullanım: {ok}/{done} başarılı]"
            _print(
                f"{w.name:<10} yerel model: {spec.name:<16} çıktı: {w.output_model.__name__:<14} "
                f"Claude karşılığı: {d.claude_tier if d else '-':<7} izinler: {', '.join(p.value for p in w.required_permissions)}"
                + extra
            )
            review = f" · gözden geçiren: {d.review.reviewer}" if d is not None and d.review.required else ""
            _print(f"{'':<10} {w.description}{review}")
        _print(f"\nTanımlar: {settings.config_dir / 'agents'}  ·  sonradan oluşturulanlar: {user_agents_dir(rt)}")
    return 0


def cmd_claude(args: argparse.Namespace) -> int:
    from .core.claude_mode import ClaudeMode
    from .core.store import TaskStore

    settings = load_settings()
    store = TaskStore(settings.db_path)
    try:
        mode = ClaudeMode(store, settings.claude)
        if args.action in ("on", "sync"):
            if args.action == "on":
                st = mode.enable()
                _print(f"[AÇIK] {st.label}")
            code = _claude_sync(settings, args.workspace)
            if code:
                return code
            st = mode.status()
        elif args.action == "off":
            st = mode.disable()
            _print(f"[KAPALI] {st.label}")
            if st.waiting_tasks:
                if args.keep:
                    _print(f"Claude kutusunda {st.waiting_tasks} iş bekletiliyor (--keep). Sonra: kayaai inbox run <id>")
                else:
                    go = args.yes
                    if not go:
                        try:
                            ans = input(f"Claude kutusunda {st.waiting_tasks} iş var. Şimdi yerelde yapayım mı? [E/h]: ")
                        except EOFError:
                            ans = ""
                        go = ans.strip().lower() not in {"h", "hayır", "hayir", "n", "no"}
                    if go:
                        store.close()
                        return _inbox_run_all()
                    _print("İşler bekletildi. Sonra: kayaai inbox run <id>")
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


def _claude_sync(settings, workspace: str | None) -> int:  # noqa: ANN001
    from pathlib import Path

    from .agents.definitions import AgentDefinitionError
    from .agents.lifecycle import claude_definitions
    from .claude_workspace import WorkspaceError, default_workspace, sync_workspace
    from .runtime import build_runtime

    try:
        with build_runtime(settings) as rt:
            agents = claude_definitions(rt)  # repo ajanları + kalıcı yapılmış kullanıcı ajanları
        report = sync_workspace(settings, agents, Path(workspace) if workspace else default_workspace(settings))
    except (AgentDefinitionError, WorkspaceError, OSError) as exc:
        _print(f"[HATA] Çalışma alanı üretilemedi: {exc}")
        return 1
    _print(f"Claude çalışma alanı: {report.workspace}")
    for f in report.written:
        _print(f"  yazıldı      {f}")
    for f in report.unchanged:
        _print(f"  değişmedi    {f}")
    for f in report.removed:
        _print(f"  kaldırıldı   {f}")
    for f in report.skipped_foreign:
        _print(f"  [ATLANDI] {f} — kayaAI'nin üretmediği bir dosya; üzerine yazılmadı")
    _print("\nŞef oturumunu başlatmak için:")
    _print(f'  cd "{report.workspace}"')
    _print("  claude")
    _print("İlk açılışta 'kayaai' MCP sunucusunu onaylayın; sonra örneğin: \"kutuyu işle\".")
    return 0


def _inbox_run_all() -> int:
    from .conductor import ClaudeInbox
    from .logging_setup import setup_logging
    from .runtime import build_runtime

    settings = load_settings()
    setup_logging(settings, console=True)
    ok = True
    with build_runtime(settings, approver=interactive_approver) as rt:
        inbox = ClaudeInbox(rt)
        for item in inbox.items():
            _print(f"\n[yerelde] {item.job_id}: {item.request[:80]}")
            res = inbox.release(item.job_id)
            ok &= res.status == "succeeded"
            _print(res.answer if res.status == "succeeded" else f"başarısız: {res.error}")
            for w in res.warnings:
                _print(f"[UYARI] {w}")
    return 0 if ok else 1


def cmd_inbox(args: argparse.Namespace) -> int:
    from .conductor import ClaudeInbox
    from .runtime import build_runtime

    settings = load_settings()
    if args.action == "run" and args.job_id == "all":
        return _inbox_run_all()
    with build_runtime(settings, approver=interactive_approver) as rt:
        inbox = ClaudeInbox(rt)
        if args.action == "list":
            view = inbox.view()
            _print(view.note)
            for i in view.items:
                _print(f"  {i.job_id}  {i.created_at:%Y-%m-%d %H:%M}  {i.request[:70]}")
                if i.reason:
                    _print(f"  {'':12}  sebep: {i.reason[:110]}")
            return 0
        if not args.job_id:
            _print("İş id gerekli: kayaai inbox run <id>  (hepsi için: kayaai inbox run all)")
            return 2
        if args.action == "cancel":
            done = inbox.cancel(args.job_id)
            _print("İptal edildi." if done else "Kutuda böyle bekleyen bir iş yok.")
            return 0 if done else 1
        try:
            res = inbox.release(args.job_id)
        except (KeyError, ValueError) as exc:
            _print(f"[HATA] {exc}")
            return 1
    _print("\n" + (res.answer if res.status == "succeeded" else f"İş başarısız: {res.error}"))
    for w in res.warnings:
        _print(f"[UYARI] {w}")
    return 0 if res.status == "succeeded" else 1


def _print_submit(res) -> int:  # noqa: ANN001 - SubmitResult
    if res.status == "done":
        r = res.result or {}
        if "entries" in r:
            _print(r["path"])
            for e in r["entries"]:
                size = f"{e['size']:>10,}" if e["size"] is not None else f"{'<klasör>':>10}"
                _print(f"  {size}  {e['modified']}  {e['name']}")
            if not r["entries"]:
                _print("  (boş)")
        elif "content" in r:
            _print(r["content"])
        else:
            _print(f"[TAMAM] {r.get('path')} ({r.get('bytes')} bayt)" + (f" — yedek: {r['backup']}" if r.get("backup") else ""))
        return 0
    if res.status == "awaiting_approval":
        _print(f"[ONAY BEKLİYOR] {res.risk.value}: {res.message}")
        return 0
    _print(f"[HATA] {res.error}")
    return 1


def cmd_files(args: argparse.Namespace) -> int:
    from .core.permissions import ApprovalError
    from .runtime import build_runtime
    from .tools.files import PathNotAllowed, roots

    settings = load_settings()
    if args.action == "roots":
        for r in roots(settings):
            _print(f"  {'okuma+yazma' if r.writable else 'yalnızca okuma':<15} {r.path}")
        return 0
    with build_runtime(settings) as rt:
        try:
            if args.action == "ls":
                return _print_submit(rt.files.list_dir(args.path or ".", requested_by="cli"))
            if not args.path:
                _print("Yol gerekli.")
                return 2
            if args.action == "read":
                return _print_submit(rt.files.read(args.path, requested_by="cli"))
            if args.text is None and args.from_file is None:
                _print("İçerik gerekli: --text \"...\" ya da --from <dosya>")
                return 2
            content = args.text if args.text is not None else Path(args.from_file).read_text(encoding="utf-8")
            return _print_submit(rt.files.write(args.path, content, requested_by="cli"))
        except (PathNotAllowed, ApprovalError, ValueError, OSError) as exc:
            _print(f"[REDDEDİLDİ] {exc}")
            return 1


def capture_screen(monitor: int = 1) -> bytes:
    """Tek ekran görüntüsü (mss). Yalnızca açık komutla çağrılır; sürekli kayıt yok."""
    import mss
    import mss.tools

    with mss.mss() as sct:
        if not 0 <= monitor < len(sct.monitors):
            raise ValueError(f"Ekran {monitor} yok (0: tümü, 1..{len(sct.monitors) - 1})")
        shot = sct.grab(sct.monitors[monitor])
        return mss.tools.to_png(shot.rgb, shot.size)


def cmd_screen(args: argparse.Namespace) -> int:
    from .perception.ocr import available
    from .perception.vision import VisionError, see
    from .runtime import build_runtime

    question = " ".join(args.question)
    try:
        data = Path(args.file).read_bytes() if args.file else capture_screen(args.monitor)
    except (OSError, ValueError) as exc:
        _print(f"[HATA] Görüntü alınamadı: {exc}")
        return 1
    with build_runtime(load_settings()) as rt:
        if args.save and not args.file:
            out = rt.settings.data_dir / "perception" / f"ekran-{__import__('datetime').datetime.now():%Y%m%d-%H%M%S}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            _print(f"Kaydedildi: {out}")
        ok, why = available()
        _print(f"OCR: {why}")
        _print("Görsel model düşünüyor…")
        try:
            res = see(rt, [data], question)
        except VisionError as exc:
            _print(f"[HATA] {exc}")
            return 1
        if args.json:
            _print(json.dumps(res.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0
        _print(res.markdown())
        for w in res.warnings:
            _print(f"[UYARI] {w}")
        _print(f"({res.seconds} sn)")
    return 0


def cmd_speech(args: argparse.Namespace) -> int:
    from .speech import SpeechError, request_download
    from .speech.stt import status, transcribe
    from .runtime import build_runtime

    settings = load_settings()
    if args.action == "status":
        st = status(settings)
        _print(f"Model: whisper {st['model']} · {'kurulu' if st['installed'] else 'KURULU DEĞİL'} · {st['dir']}")
        if not st["installed"]:
            _print("İndir: kayaai speech download  (~%s MB, sahip onayı gerekir)" % (st["approx_mb"] or "?"))
        return 0
    if args.action == "download":
        with build_runtime(settings) as rt:
            try:
                res = request_download(rt, requested_by="cli")
            except SpeechError as exc:
                _print(f"[HATA] {exc}")
                return 1
            _print(f"[ONAY BEKLİYOR] {res.message}")
            _print(f"Onayla: kayaai approvals approve {res.approval_id}  (onaylayınca indirme başlar)")
        return 0
    if not args.file:
        _print("Kullanım: kayaai speech transcribe <ses-dosyası> [--lang tr|en]")
        return 2
    try:
        t = transcribe(settings, Path(args.file).read_bytes(), args.lang)
    except (OSError, SpeechError) as exc:
        _print(f"[HATA] {exc}")
        return 1
    _print(t.text or "(konuşma algılanmadı)")
    _print(f"({t.audio_seconds} sn ses · {t.seconds} sn işlem · {t.device} · dil: {t.language})")
    return 0


DAY_KEYS = {"pzt": 0, "pts": 0, "mon": 0, "sal": 1, "tue": 1, "çar": 2, "car": 2, "wed": 2, "per": 3, "thu": 3,
            "cum": 4, "fri": 4, "cmt": 5, "sat": 5, "paz": 6, "sun": 6}


def cmd_schedule(args: argparse.Namespace) -> int:
    if args.action == "run" and args.trigger == "windows" and args.id:
        return _windows_logged(args)
    return _cmd_schedule(args)


def _windows_logged(args: argparse.Namespace) -> int:
    """Görev Zamanlayıcı çalıştırması (pythonw: konsol yok) — çıktı ve olası hata `data/schedule/<id>.log`'a yazılır,
    yoksa sessizce düşen bir çalışma hiç görülmezdi (Windows gözlemi, 2026-11-01)."""
    import datetime as _dt
    import os
    import traceback

    log_dir = load_settings().data_dir / "schedule"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{Path(args.id).name}.log"
    if path.is_file() and path.stat().st_size > 1_000_000:
        path.replace(path.with_suffix(".log.1"))
    old = sys.stdout, sys.stderr
    with path.open("a", encoding="utf-8", buffering=1) as f:
        sys.stdout = sys.stderr = f
        try:
            print(f"--- {_dt.datetime.now():%Y-%m-%d %H:%M:%S} Windows çalıştırması · pid {os.getpid()} · "
                  f"{sys.executable} · klasör {os.getcwd()}")
            code = _cmd_schedule(args)
            print(f"çıkış kodu {code}")
            return code
        except BaseException:  # noqa: BLE001 - her hata günlüğe
            traceback.print_exc()
            return 1
        finally:
            sys.stdout, sys.stderr = old


def _cmd_schedule(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from .schedule import (Cadence, Schedule, ScheduleError, list_schedules, request_create, request_delete,
                           request_enable, sync_report)
    from .schedule.runner import run_due, run_schedule
    from .tools.files import PathNotAllowed
    from .runtime import build_runtime

    def submitted(res: Any, ok: str) -> int:
        if res.status == "awaiting_approval":
            _print(f"[ONAY BEKLİYOR] {res.message}")
            _print(f"Onayla: kayaai approvals approve {res.approval_id}  (ya da Control Center → Onay merkezi)")
            return 0
        if res.status == "failed":
            _print(f"[HATA] {res.error}")
            return 1
        _print(f"[OK] {ok}")
        return 0

    with build_runtime(load_settings()) as rt:
        try:
            a = args.action
            if a == "list":
                rows = list_schedules(rt)
                if not rows:
                    _print("Zamanlanmış görev yok. Ekle: kayaai schedule add --kind reindex --daily --at 03:00 --name \"Gece dizin\"")
                for r in rows:
                    win = "" if r["in_windows"] is None else (" · Windows'ta kayıtlı" if r["in_windows"] else " · WINDOWS'TA YOK")
                    _print(f"{r['id']}  {'açık ' if r['enabled'] else 'KAPALI'}  {r['summary']}")
                    _print(f"          sonraki: {r['next_run'] or '-'} · son: {r['last_run'] or '-'} {r['last_status'] or ''}{win}")
                return 0
            if a == "add":
                if args.weekly:
                    days = [DAY_KEYS[d.strip().lower()[:3]] for d in args.weekly.split(",")]
                    cad = Cadence(freq="weekly", at=args.at, days=days)
                elif args.monthly:
                    cad = Cadence(freq="monthly", at=args.at, day=args.monthly)
                elif args.once:
                    cad = Cadence(freq="once", at=args.at, on=args.once)
                else:
                    cad = Cadence(freq="daily", at=args.at)
                params: dict[str, Any] = {}
                if args.path:
                    params["path"] = args.path
                if args.folder:
                    params["folder"] = args.folder
                if args.request:
                    params["request"] = args.request
                if args.formats:
                    params["formats"] = args.formats.split(",")
                s = Schedule(name=args.name or args.kind, kind=args.kind, params=params, cadence=cad,
                             catch_up=not args.no_catch_up, skip_holidays=args.skip_holidays)
                return submitted(request_create(rt, s, requested_by="cli"), f"Eklendi: {s.id}")
            if a == "run-due":
                runs = run_due(rt)
                _print(f"{len(runs)} görev çalıştı" + "".join(f"\n  {r.schedule_id}: {r.status} {r.message[:80]}" for r in runs))
                return 0
            if a == "sync":
                rep = sync_report(rt)
                if not rep["supported"]:
                    _print("Windows Görev Zamanlayıcı yok (yalnız Windows); kayaai schedule run-due kullan")
                    return 0
                _print(f"Windows'ta eksik: {', '.join(rep['missing']) or 'yok'} · kayaAI'de olmayan: {', '.join(rep['orphans']) or 'yok'}")
                return 0
            if not args.id:
                _print(f"Görev kimliği gerekli: kayaai schedule {a} <id>  (liste: kayaai schedule list)")
                return 2
            if a == "run":
                run = run_schedule(rt, args.id, args.trigger)
                _print(f"{run.status}: {run.message}")
                return 0 if run.status in ("succeeded", "skipped") else 1
            if a in ("enable", "disable"):
                return submitted(request_enable(rt, args.id, a == "enable", requested_by="cli"), a)
            if a == "rm":
                return submitted(request_delete(rt, args.id, requested_by="cli"), "Silindi")
        except (ScheduleError, ValidationError, ValueError, KeyError, PathNotAllowed) as exc:
            _print(f"[HATA] {exc}")
            return 1
    return 2


def cmd_pause(args: argparse.Namespace) -> int:
    from .automation import set_paused, state
    from .runtime import build_runtime

    with build_runtime(load_settings()) as rt:
        if args.func_name == "status":
            st = state(rt)
            _print("Otomasyon DURAKLATILDI" + (f" ({st['at']}, {st['by']})" if st["at"] else "") if st["paused"] else "Otomasyon açık")
            return 0
        st = set_paused(rt, args.func_name == "pause", by="cli", reason=" ".join(getattr(args, "reason", []) or []))
        if st["paused"]:
            _print("[OK] Otomasyon duraklatıldı: zamanlanmış görevler atlanır, tarayıcı işi başlamaz"
                   + (f" (durdurulan tarayıcı işi: {', '.join(st['stopped_browser_jobs'])})" if st["stopped_browser_jobs"] else ""))
        else:
            _print("[OK] Otomasyon sürüyor")
    return 0


def cmd_integrations(args: argparse.Namespace) -> int:
    from datetime import date as _date

    from .integrations import IntegrationError, holidays, rates, rates_note, request_disable, request_enable, status
    from .runtime import build_runtime

    with build_runtime(load_settings()) as rt:
        try:
            if args.action == "list":
                for s in status(rt):
                    _print(f"{s['name']:<15} {'AÇIK ' if s['enabled'] else 'kapalı'}  {s['label']} — {s['provider']} "
                           f"(https://{s['host']}; gönderilen: {s['sends']})")
                return 0
            if args.action in ("enable", "disable"):
                if not args.name:
                    _print("Kaynak adı gerekli: exchange_rates | holidays")
                    return 2
                res = (request_enable if args.action == "enable" else request_disable)(rt, args.name, requested_by="cli")
                if res.status == "awaiting_approval":
                    _print(f"[ONAY BEKLİYOR] {res.message}\nOnayla: kayaai approvals approve {res.approval_id}")
                else:
                    _print(f"[OK] {args.name}: {res.status}")
                return 0
            if args.action == "rates":
                _print(rates_note(rates(rt)))
                return 0
            if args.action == "holidays":
                year = int(args.name or _date.today().year)
                for h in holidays(rt, year):
                    _print(f"{h['date']}  {h['name']}")
                return 0
            if args.action == "test":  # gerçek bağlantı denemesi (açık olanlar)
                ok = True
                for s in status(rt):
                    if not s["enabled"]:
                        _print(f"{s['name']}: kapalı (atlandı)")
                        continue
                    try:
                        out = rates_note(rates(rt)) if s["name"] == "exchange_rates" else \
                            f"{len(holidays(rt, _date.today().year))} tatil ({_date.today().year})"
                        _print(f"{s['name']}: OK — {out}")
                    except IntegrationError as exc:
                        ok = False
                        _print(f"{s['name']}: HATA — {exc}")
                return 0 if ok else 1
        except IntegrationError as exc:
            _print(f"[HATA] {exc}")
            return 1
    return 2


def cmd_bench(args: argparse.Namespace) -> int:
    from .bench import run_bench

    _print("Ölçülüyor (kurulu modeller; birkaç dakika sürebilir)…")
    out = run_bench(load_settings(), log=_print)
    if out.get("error"):
        _print(f"[HATA] {out['error']}")
        return 1
    _print(f"Sonuç: {out['path']}")
    return 0


def cmd_quality(args: argparse.Namespace) -> int:
    """Yerel ajanların çıktı kalitesi (yalnız görev kayıtları; model çağrılmaz, dışarı bir şey gitmez)."""
    from . import quality
    from .core.store import TaskStore

    s = load_settings()
    store = TaskStore(s.db_path)
    try:
        out = quality.run(store, s.data_dir, args.days)
    finally:
        store.close()
    for line in quality.format_table(out):
        _print(line)
    _print(f"Ayrıntı: {out['path']}")
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    """Tarayıcı ajanı: onay gereken adımlar onay kuyruğuna düşer (başka bir terminalde: kayaai approvals approve <id>)."""
    from .browser.agent import BrowserJobError, start_job
    from .runtime import build_runtime

    goal = " ".join(args.goal)
    with build_runtime(load_settings()) as rt:
        try:
            job = start_job(rt, goal, args.url, background=True)
        except BrowserJobError as exc:
            _print(f"[HATA] {exc}")
            return 1
        _print(f"Tarayıcı açıldı (ayrı profil). Hedef: {goal}")
        seen = 0
        while not job.finished.wait(0.5):
            for s in job.state.steps[seen:]:
                if s.status == "onay bekliyor":
                    _print(f"  {s.n}. [{s.risk}] {s.description} — ONAY BEKLİYOR: kayaai approvals approve {s.approval_id}"
                           f"  (reddet: kayaai approvals reject {s.approval_id})")
                    if s is job.state.steps[-1]:
                        break
                else:
                    _print(f"  {s.n}. [{s.risk}] {s.description} — {s.status}{' (' + s.reason + ')' if s.status == 'kural dışı' else ''}")
                seen += 1
        for s in job.state.steps[seen:]:
            _print(f"  {s.n}. [{s.risk}] {s.description} — {s.status}")
        st = job.state
        _print(f"Sonuç: {st.status}" + (f" — {st.error}" if st.error else ""))
        if st.answer:
            _print(st.answer)
    return 0 if job.state.status == "done" else 1


def cmd_business(args: argparse.Namespace) -> int:
    """İş modülleri (Adım 10): kayaai analyze | summarize | invoice <dosya> [soru] [--report biçim]."""
    from .business import from_result, run_mode, save
    from .business.readers import ReadError
    from .runtime import build_runtime

    path = Path(args.file).expanduser()
    if not path.is_file():
        _print(f"[HATA] Dosya yok: {path}")
        return 1
    settings = load_settings()
    mode = {"analyze": "analyze", "summarize": "summarize", "invoice": "invoice"}[args.command]
    with build_runtime(settings) as rt:
        _print(f"[{mode}] {path.name} işleniyor... (yerel modeller)")
        try:
            result = run_mode(rt, mode, path.read_bytes(), path.name, " ".join(args.question))
        except (ReadError, ValueError) as exc:
            _print(f"[HATA] {exc}")
            return 1
        _print("\n" + result.markdown())
        for w in result.warnings:
            _print(f"[UYARI] {w}")
        if args.report:
            res = save(rt, from_result(result.model_dump(mode="json")), args.report, requested_by="cli")
            if res.status == "done" and res.result:
                _print(f"\n[RAPOR] {res.result['path']}")
            else:
                _print(f"\n[RAPOR] {res.message or res.error}")
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    """Hafıza (Adım 9): kişisel notlar + belge dizini. Her şey yerel."""
    import json as _json

    from .memory import CATEGORY_LABELS, SENSITIVITY_LABELS, MemoryError as MemError, remember
    from .runtime import build_runtime

    settings = load_settings()
    with build_runtime(settings) as rt:
        mem = rt.memory
        assert mem is not None
        try:
            if args.action == "list":
                items = mem.book.list()
                if not items:
                    _print("Hafıza boş. Eklemek için: kayaai memory add \"...\"  (ya da sohbette: hatırla: ...)")
                for m in items:
                    flag = " [ÖNERİ]" if m.status == "proposed" else ""
                    text = "•••• (gizli)" if m.sensitivity == "secret" else m.text[:90]
                    _print(f"  {m.id}  {CATEGORY_LABELS[m.category]:<8} {SENSITIVITY_LABELS[m.sensitivity]:<13}{flag} {text}")
                return 0
            if args.action == "add":
                text = " ".join(args.text).strip()
                if not text:
                    _print("Metin gerekli: kayaai memory add \"Kahvemi şekersiz içerim\"")
                    return 2
                if args.category or args.sensitivity or args.secret:
                    item, warnings = mem.book.add(text, category=args.category or "note",
                                                  sensitivity="secret" if args.secret else (args.sensitivity or "personal"),
                                                  source="owner", allow_secret=args.secret)
                    _print(f"[OK] Kaydedildi: {item.id} ({CATEGORY_LABELS[item.category]} · {SENSITIVITY_LABELS[item.sensitivity]})")
                else:
                    item, message, warnings = remember(rt, text, source="owner")
                    _print(("[OK] " if item else "[REDDEDİLDİ] ") + message.replace("*", ""))
                for w in warnings:
                    _print(f"[UYARI] {w}")
                return 0 if item else 1
            if args.action in ("rm", "approve"):
                if not args.text:
                    _print(f"Öğe numarası gerekli: kayaai memory {args.action} <id>")
                    return 2
                if args.action == "rm":
                    mem.book.delete(args.text[0])
                    _print(f"[OK] Silindi: {args.text[0]}")
                else:
                    mem.book.approve(args.text[0])
                    _print(f"[OK] Onaylandı: {args.text[0]}")
                return 0
            if args.action == "scan":
                from .memory import scan_secrets

                out = scan_secrets(rt, fix=args.fix)
                for it in out["items"]:
                    _print(f"  hafıza  {it['id']}  {', '.join(it['kinds'])}" + ("  → gizli yapıldı" if args.fix else ""))
                for d in out["documents"]:
                    _print(f"  belge   {d['path']}  {d['chunks']} parça" + ("  → dizinden çıkarıldı" if args.fix else ""))
                if not (out["items"] or out["documents"]):
                    _print("[OK] Gizli bilgi görünen kayıt yok.")
                elif not args.fix:
                    _print("Düzeltmek için: kayaai memory scan --fix  (hafıza öğeleri 'gizli' yapılır, belge parçaları "
                           "dizinden çıkar; dosyalarına dokunulmaz). Silmek istersen: kayaai memory rm <id>")
                return 0
            if args.action == "search":
                res = mem.recall(" ".join(args.text))
                for m in res.memories:
                    _print(f"  hafıza  {m['score']:.2f}  {m['text'][:100]}")
                for d in res.documents:
                    _print(f"  belge   {d['score']:.2f}  {d['name']}:{d['line']}  {d['text'][:80]!r}")
                if not (res.memories or res.documents):
                    _print("İlgili bir şey bulunamadı.")
                for w in res.warnings:
                    _print(f"[UYARI] {w}")
                return 0
            if args.action == "index":
                _print("Belgeler dizinleniyor (izinli klasörler)...")
                rep = mem.docs.index()
                _print(f"Taranan {rep.scanned}, işlenen {rep.indexed}, değişmeyen {rep.unchanged}, kaldırılan {rep.removed}, "
                       f"parça {rep.chunks_total}, gizli bilgi nedeniyle atlanan parça {rep.secret_chunks_skipped}, "
                       f"{rep.duration_s} sn")
                for reason, n in rep.skipped.items():
                    _print(f"  atlandı ({reason}): {n}")
                for e in rep.errors:
                    _print(f"[UYARI] {e}")
                if mem.book.reindex():
                    _print("Vektörü eksik hafıza öğeleri tamamlandı.")
                return 0
            if args.action == "status":
                st = mem.docs.status()
                items = mem.book.list()
                _print(f"Hafıza öğeleri: {len(items)} (öneri: {sum(m.status == 'proposed' for m in items)})")
                _print(f"Belgeler: {st['documents']} dosya, {st['chunks']} parça; vektörsüz: {st['not_embedded']}; "
                       f"model: {st['embed_model']}")
                _print("Kökler: " + ", ".join(st["roots"]))
                return 0
            if args.action == "export":
                out = Path(args.out or (settings.data_dir / "memory_export.json"))
                out.write_text(_json.dumps({"items": mem.book.export()}, ensure_ascii=False, indent=2), encoding="utf-8")
                _print(f"[OK] Dışa aktarıldı: {out}")
                return 0
        except MemError as exc:
            _print(f"[HATA] {exc}")
            return 1
    return 2


def cmd_disputes(args: argparse.Namespace) -> int:
    """Ajan anlaşmazlıkları (Adım 7): listele / göster / karar ver. Kararı yalnızca sahip verir."""
    from .core.disputes import DisputeError
    from .runtime import build_runtime

    settings = load_settings()
    with build_runtime(settings) as rt:
        book = rt.disputes
        assert book is not None
        try:
            if args.action == "list":
                items = book.list(None if args.all else "open")
                if not items:
                    _print("Açık anlaşmazlık yok." if not args.all else "Anlaşmazlık kaydı yok.")
                for d in items:
                    state = d.status if d.status == "open" else f"{d.resolution}"
                    _print(f"  {d.id}  {d.created_at:%Y-%m-%d %H:%M}  {state:<10} {d.producer} ↔ {d.reviewer}: {d.issue[:70]}")
                return 0
            if not args.dispute_id:
                _print("Anlaşmazlık numarası gerekli: kayaai disputes show <id>")
                return 2
            if args.action == "show":
                d = book.get(args.dispute_id)
                if d is None:
                    raise DisputeError(f"Anlaşmazlık bulunamadı: {args.dispute_id}")
                _print(f"Anlaşmazlık {d.id} — {d.status}" + (f" ({d.resolution}, {d.decided_by})" if d.resolution else ""))
                _print(f"İş           : {d.job_id} / adım {d.step_id}")
                _print(f"İstek       : {d.request[:300]}")
                _print(f"Gözden geçirici ({d.reviewer}), {d.severity}: {d.issue}")
                if d.evidence:
                    _print(f"  Kanıt (cevaptan alıntı): {d.evidence}")
                _print(f"Üretici ({d.producer}) itirazı: {d.producer_position}")
                _print(f"Yükseltildi : {'Claude şef' if d.escalated_to == 'claude' else 'sahip (sen)'}")
                if d.note:
                    _print(f"Not         : {d.note}")
                if d.status == "open":
                    _print(f"\nKarar: kayaai disputes resolve {d.id} --side producer|reviewer [--note \"...\"]")
                return 0
            if not args.side:
                _print("Taraf gerekli: --side producer (üretici haklı) | reviewer (gözden geçirici haklı)")
                return 2
            d = book.resolve(args.dispute_id, args.side, decided_by="cli", note=args.note or "")
            who = d.producer if args.side == "producer" else d.reviewer
            _print(f"[KARAR] {d.id}: {who} haklı bulundu.")
            return 0
        except DisputeError as exc:
            _print(f"[HATA] {exc}")
            return 1


def cmd_approvals(args: argparse.Namespace) -> int:
    import json as _json

    from .core.permissions import RISK_LABELS, ApprovalError
    from .runtime import build_runtime

    settings = load_settings()
    with build_runtime(settings) as rt:
        eng = rt.permissions
        try:
            if args.action == "list":
                items = eng.list_approvals(None if args.all else "pending")
                if not items:
                    _print("Bekleyen onay talebi yok." if not args.all else "Onay talebi yok.")
                for a in items:
                    _print(f"  {a.id}  {a.created_at:%Y-%m-%d %H:%M}  {a.status:<9} {a.action.risk.value}  {a.action.summary[:80]}")
                return 0
            if not args.approval_id:
                _print("Talep numarası gerekli: kayaai approvals show <id>")
                return 2
            a = eng.get(args.approval_id)
            if args.action == "show":
                _print(f"Talep {a.id} — {a.status}")
                _print(f"Risk    : {a.action.risk.value} — {RISK_LABELS[a.action.risk]}")
                _print(f"İşlem   : {a.action.summary}")
                _print(f"İsteyen : {a.action.requested_by}")
                if a.action.reason:
                    _print(f"Neden   : {a.action.reason}")
                if a.action.undo:
                    _print(f"Geri al : {a.action.undo}")
                _print("Önizleme:")
                _print(_json.dumps(a.action.preview, ensure_ascii=False, indent=2))
                if a.status == "pending":
                    _print(f"\nOnay: kayaai approvals approve {a.id}   |   Ret: kayaai approvals reject {a.id}")
                return 0
            if args.action == "approve":
                a = eng.approve(args.approval_id, decided_by="cli", note=args.note or "")
                _print(f"[{a.status.upper()}] {a.action.summary}" + (f" — {a.error}" if a.error else ""))
                return 0 if a.status == "approved" else 1
            a = eng.reject(args.approval_id, decided_by="cli", note=args.note or "")
            _print(f"[REDDEDİLDİ] {a.action.summary}")
            return 0
        except ApprovalError as exc:
            _print(f"[HATA] {exc}")
            return 1


def cmd_api(args: argparse.Namespace) -> int:
    from .api.app import load_or_create_token, token_path
    from .config import LOCAL_HOSTS

    settings = load_settings()
    if args.action == "token":
        token = load_or_create_token(settings)
        _print(token)
        _print(f"(dosya: {token_path(settings)})", )
        return 0
    host = args.host or settings.api.host
    port = args.port or settings.api.port
    if host not in LOCAL_HOSTS:
        _print(f"[HATA] API yalnızca bu bilgisayarda çalışabilir (127.0.0.1). '{host}' reddedildi.")
        _print("Ağa açmak güvenlik kararıdır (MASTER_PROMPT §10) ve bu sürümde desteklenmez.")
        return 2
    import uvicorn

    from .api import create_app
    from .logging_setup import setup_logging

    setup_logging(settings, console=True)
    app = create_app(settings)
    _print(f"{APP_NAME} API: http://{host}:{port}   (deneme sayfası: http://{host}:{port}/docs)")
    _print(f"Erişim anahtarı: {token_path(settings)}  — göstermek için: kayaai api token")
    if args.open:
        _open_when_ready(host, port, app.state.token)
        _print("Control Center sunucu hazır olunca tarayıcıda açılacak.")
    else:
        _print("Control Center için ikinci terminalde:  kayaai ui   (anahtarla açar; adresi elle açarsan anahtar sorar)")
    _print("Durdurmak için Ctrl+C.")
    uvicorn.run(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=3)
    return 0


def _open_when_ready(host: str, port: int, token: str, timeout_s: float = 20) -> None:
    """Sunucu yanıt verince tarayıcıyı anahtarlı adresle açar (arka plan iş parçacığı; anahtar ekrana yazılmaz)."""
    import threading
    import time
    import webbrowser

    import httpx

    def run() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://{host}:{port}/api/health", headers={"Authorization": f"Bearer {token}"},
                             timeout=2).status_code == 200:
                    webbrowser.open(f"http://{host}:{port}/#token={token}")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)

    threading.Thread(target=run, name="kayaai-open-ui", daemon=True).start()


def cmd_ui(args: argparse.Namespace) -> int:
    """Control Center'ı tarayıcıda açar: http://127.0.0.1:8765/#token=... (URL parçası sunucuya gitmez)."""
    import webbrowser

    import httpx

    from .api.app import UI_DIST, load_or_create_token
    from .config import LOCAL_HOSTS

    settings = load_settings()
    host = args.host or settings.api.host
    port = args.port or settings.api.port
    if host not in LOCAL_HOSTS:
        _print(f"[HATA] Control Center yalnızca bu bilgisayarda açılır (127.0.0.1). '{host}' reddedildi.")
        return 2
    token = load_or_create_token(settings)
    base = f"http://{host}:{port}/"
    url = f"{base}#token={token}"
    if args.print:
        _print(url)
        return 0
    if not (UI_DIST / "index.html").is_file():
        _print("[UYARI] Arayüz derlenmemiş (ui/dist yok). Derlemek için: cd ui; npm ci; npm run build")
        _print("        (ya da scripts\\windows\\setup.ps1). Tarayıcıda şimdilik bilgilendirme sayfası görünecek.")
    try:
        r = httpx.get(f"{base}api/health", headers={"Authorization": f"Bearer {token}"}, timeout=3)
        ok = r.status_code == 200
    except httpx.HTTPError:
        ok = False
    if not ok:
        _print(f"[HATA] {base} adresinde kayaAI API'ye ulaşılamadı.")
        _print("Önce başka bir terminalde çalıştırın:  kayaai api   — sonra yeniden:  kayaai ui")
        return 1
    _print(f"Control Center açılıyor: {base}")
    _print("(Tarayıcı açılmazsa adresi görmek için: kayaai ui --print — adres erişim anahtarını içerir, paylaşmayın.)")
    webbrowser.open(url)
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

    mo = sub.add_parser("models", help="modeller: listele / yükle / boşalt / ajana ata / indir / karşılaştır / aktif yap")
    mo.add_argument("action", nargs="?", choices=["list", "load", "unload", "assign", "pull", "compare", "activate"],
                    default="list")
    mo.add_argument("name", nargs="?", help="model adı (load/unload/pull), ajan (assign/compare) ya da anahtar (activate)")
    mo.add_argument("model", nargs="?", help="assign/compare: model anahtarı")
    mo.set_defaults(func=cmd_models)
    sub.add_parser("audit", help="ortam denetimi raporu").set_defaults(func=cmd_audit)
    do = sub.add_parser("do", help="şef: isteği planlayıp ajanlara dağıtır")
    do.add_argument("request", nargs="+")
    g = do.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true", help="Claude gerekse bile yerelde yap")
    g.add_argument("--claude", action="store_true", help="Claude modu açıksa Claude kutusuna bırak")
    do.add_argument("--json", action="store_true")
    do.set_defaults(func=cmd_do)

    ag = sub.add_parser("agents", help="ajanlar: listele / geçici ajan oluştur / kalıcı yap / kaldır")
    ag.add_argument("action", nargs="?", choices=["list", "new", "promote", "remove"], default="list")
    ag.add_argument("name", nargs="?")
    ag.add_argument("--base", default="general", help="new: dayandığı ajan (model ve izinler buradan gelir)")
    ag.add_argument("--description", default=None)
    ag.add_argument("--role", default=None, help="new: rol talimatı")
    ag.add_argument("--role-file", default=None, help="new: rol talimatını dosyadan oku")
    ag.set_defaults(func=cmd_agents)

    c = sub.add_parser("claude", help="Claude modu: durum / aç / kapat")
    c.add_argument("action", nargs="?", choices=["status", "on", "off", "sync"], default="status")
    c.add_argument("--workspace", default=None, help="şef çalışma klasörü (varsayılan: ~/kayaAI-workspace)")
    c.add_argument("--json", action="store_true")
    c.add_argument("--keep", action="store_true", help="kapatırken kutudaki işleri beklet")
    c.add_argument("--yes", action="store_true", help="kapatırken kutudaki işleri sormadan yerelde yap")

    fl = sub.add_parser("files", help="dosya araçları (yalnızca izinli klasörler)")
    fl.add_argument("action", choices=["roots", "ls", "read", "write"])
    fl.add_argument("path", nargs="?")
    fl.add_argument("--text", default=None, help="write: yazılacak metin")
    fl.add_argument("--from", dest="from_file", default=None, help="write: içeriği bu yerel dosyadan al")
    fl.set_defaults(func=cmd_files)

    apv = sub.add_parser("approvals", help="onay kuyruğu: listele / göster / onayla / reddet")
    apv.add_argument("action", nargs="?", choices=["list", "show", "approve", "reject"], default="list")
    apv.add_argument("approval_id", nargs="?")
    apv.add_argument("--all", action="store_true", help="list: tüm talepler (yalnızca bekleyenler değil)")
    apv.add_argument("--note", default=None)
    apv.set_defaults(func=cmd_approvals)

    pz = sub.add_parser("pause", help="otomasyonu duraklat (zamanlanmış görevler, tarayıcı işleri)")
    pz.add_argument("reason", nargs="*")
    pz.set_defaults(func=cmd_pause, func_name="pause")
    sub.add_parser("resume", help="otomasyonu sürdür").set_defaults(func=cmd_pause, func_name="resume")
    sub.add_parser("automation", help="otomasyon durumu (açık / duraklatıldı)").set_defaults(func=cmd_pause, func_name="status")

    ig = sub.add_parser("integrations", help="isteğe bağlı dış veri: döviz kurları, resmi tatiller (açmak onaylı)")
    ig.add_argument("action", nargs="?", choices=["list", "enable", "disable", "rates", "holidays", "test"], default="list")
    ig.add_argument("name", nargs="?", help="exchange_rates | holidays (holidays komutunda: yıl)")
    ig.set_defaults(func=cmd_integrations)

    sub.add_parser("bench", help="donanımda ölçüm: sohbet, embedding, görsel, Whisper, VRAM tepe → data/bench.json"
                   ).set_defaults(func=cmd_bench)

    qp = sub.add_parser("quality", help="ajan çıktı kalitesi (ilk denemede geçerli, geçersiz, zaman aşımı) → data/quality.json")
    qp.add_argument("--days", type=int, default=None, help="yalnız son N gün")
    qp.set_defaults(func=cmd_quality)

    sh = sub.add_parser("schedule", help="zamanlanmış görevler (Windows Görev Zamanlayıcı; ekleme/silme onaylı)")
    sh.add_argument("action", nargs="?", choices=["list", "add", "run", "run-due", "enable", "disable", "rm", "sync"],
                    default="list")
    sh.add_argument("id", nargs="?")
    sh.add_argument("--name", default=None)
    sh.add_argument("--kind", choices=["docs_digest", "sales_report", "reindex", "free"], default="reindex")
    sh.add_argument("--at", default="09:00", help="saat HH:MM (yerel)")
    sh.add_argument("--weekly", default=None, help="günler: pzt,sal,çar,per,cum,cmt,paz")
    sh.add_argument("--monthly", type=int, default=None, help="ayın günü 1-28")
    sh.add_argument("--once", default=None, help="tarih YYYY-MM-DD")
    sh.add_argument("--path", default=None, help="sales_report: Excel/CSV dosyası (izinli klasör)")
    sh.add_argument("--folder", default=None, help="docs_digest: yalnız bu klasör")
    sh.add_argument("--request", default=None, help="free: şefe verilecek istek")
    sh.add_argument("--formats", default=None, help="sales_report: xlsx,pdf,docx,md")
    sh.add_argument("--no-catch-up", action="store_true", help="kaçırılan çalışmayı sonradan yapma")
    sh.add_argument("--skip-holidays", action="store_true", help="resmi tatilde çalışma (tatil takvimi açık olmalı)")
    sh.add_argument("--trigger", choices=["manual", "windows", "run-due"], default="manual", help=argparse.SUPPRESS)
    sh.set_defaults(func=cmd_schedule)

    br = sub.add_parser("browse", help="tarayıcı ajanı (Edge, ayrı profil): hedefi adım adım yapar, riskli adımlar onaylı")
    br.add_argument("goal", nargs="+", help="ne yapılacak (ör. 'python kitaplarının fiyatlarını listele')")
    br.add_argument("--url", required=True, help="başlangıç adresi")
    br.set_defaults(func=cmd_browse)

    sp = sub.add_parser("speech", help="ses tanıma: durum / modeli indir (onaylı) / dosyayı yazıya çevir")
    sp.add_argument("action", nargs="?", choices=["status", "download", "transcribe"], default="status")
    sp.add_argument("file", nargs="?")
    sp.add_argument("--lang", choices=["auto", "tr", "en"], default=None)
    sp.set_defaults(func=cmd_speech)

    sc = sub.add_parser("screen", help="ekran görüntüsü al (tek kare) ve yerel görsel modelle yorumla")
    sc.add_argument("question", nargs="*", help="soru (boşsa: ekranda ne var?)")
    sc.add_argument("--file", default=None, help="ekran yerine bu görüntü dosyasını yorumla")
    sc.add_argument("--monitor", type=int, default=1, help="ekran no (0: tümü, 1: birincil)")
    sc.add_argument("--save", action="store_true", help="görüntüyü data/perception altına kaydet")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_screen)

    for name, help_text in (("analyze", "Excel/CSV analizi (sayıları program hesaplar)"),
                            ("summarize", "PDF özeti"), ("invoice", "PDF faturadan alanlar + tutar denetimi")):
        bp = sub.add_parser(name, help=help_text)
        bp.add_argument("file")
        bp.add_argument("question", nargs="*")
        bp.add_argument("--report", choices=["md", "xlsx", "docx", "pdf"], default=None,
                        help="raporu ~/kayaAI-files/raporlar altına kaydet")
        bp.set_defaults(func=cmd_business)

    mp = sub.add_parser("memory", help="hafıza: listele / ekle / sil / ara / belgeleri dizinle / dışa aktar")
    mp.add_argument("action", nargs="?", choices=["list", "add", "rm", "approve", "search", "index", "status", "export", "scan"],
                    default="list")
    mp.add_argument("text", nargs="*")
    mp.add_argument("--category", choices=["preference", "project", "decision", "instruction", "file", "note"])
    mp.add_argument("--sensitivity", choices=["public", "personal", "private"])
    mp.add_argument("--secret", action="store_true", help="add: GİZLİ olarak kaydet (açık izin; bağlama girmez)")
    mp.add_argument("--out", default=None, help="export: dosya yolu")
    mp.add_argument("--fix", action="store_true", help="scan: eşleşenleri gizli yap / dizinden çıkar")
    mp.set_defaults(func=cmd_memory)

    dp = sub.add_parser("disputes", help="ajan anlaşmazlıkları: listele / göster / karar ver")
    dp.add_argument("action", nargs="?", choices=["list", "show", "resolve"], default="list")
    dp.add_argument("dispute_id", nargs="?")
    dp.add_argument("--all", action="store_true", help="list: kapananlar dahil")
    dp.add_argument("--side", choices=["producer", "reviewer"], default=None, help="resolve: kim haklı")
    dp.add_argument("--note", default=None)
    dp.set_defaults(func=cmd_disputes)

    ap = sub.add_parser("api", help="yerel API sunucusu (yalnızca 127.0.0.1)")
    ap.add_argument("action", nargs="?", choices=["serve", "token"], default="serve")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--open", action="store_true", help="sunucu hazır olunca Control Center'ı tarayıcıda aç")
    ap.set_defaults(func=cmd_api)

    ui = sub.add_parser("ui", help="Control Center'ı tarayıcıda aç (önce: kayaai api)")
    ui.add_argument("--print", action="store_true", help="tarayıcı açma; yalnızca anahtarlı adresi yaz")
    ui.add_argument("--host", default=None)
    ui.add_argument("--port", type=int, default=None)
    ui.set_defaults(func=cmd_ui)

    ib = sub.add_parser("inbox", help="Claude kutusu: listele / yerelde yap / iptal")
    ib.add_argument("action", nargs="?", choices=["list", "run", "cancel"], default="list")
    ib.add_argument("job_id", nargs="?")
    ib.set_defaults(func=cmd_inbox)
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
