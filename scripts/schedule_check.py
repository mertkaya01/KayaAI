"""Adım 13 doğrulaması — kabul: "zamanlanmış görev Claude Code (ve kayaAI) açık olmadan çalışır".

Kullanım (Windows, proje klasöründe, venv etkin; kayaai api KAPALI olabilir):
    python scripts/schedule_check.py
Akış: 2 dk sonrasına tek seferlik "belge dizini yenileme" görevi → ekleme onayını TERMİNALDE sana sorar → Windows Görev
Zamanlayıcı'ya kaydedilir → betik yalnızca BEKLER (görevi kendisi çalıştırmaz) → Windows çalıştırınca çalışma kaydı
(`trigger: windows`) ve Asistan'daki "Zamanlanmış görevler" sohbetine düşen mesaj doğrulanır → test görevi silinir
(onay sorar). Sonuç: data/schedule_check.json
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.config import load_settings  # noqa: E402
from kayaai.runtime import build_runtime  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def ask(rt, approval_id: str) -> bool:
    a = rt.permissions.get(approval_id)
    print(f"\n[ONAY] {a.action.risk.value} · {a.action.summary}\n{a.action.preview.get('new_head', '')}")
    yes = input("Onaylıyor musun? [e/H]: ").strip().lower() in ("e", "evet", "y")
    (rt.permissions.approve if yes else rt.permissions.reject)(approval_id, decided_by="owner")
    return yes


def task_query(sid: str) -> str:
    """Görev Zamanlayıcı'nın kendi kaydı (son çalışma zamanı, son sonuç kodu) — ham metin."""
    import subprocess

    from kayaai.schedule import windows

    try:
        p = subprocess.run(["schtasks", "/Query", "/TN", windows.task_name(sid), "/V", "/FO", "LIST"], capture_output=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    raw = (p.stdout or b"") + (p.stderr or b"")
    for enc in ("utf-8", "cp857", "cp1254"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main() -> int:
    from kayaai.schedule import Cadence, Schedule, request_create, request_delete, windows

    settings = load_settings()
    out = settings.data_dir / "schedule_check.json"
    report: dict = {"windows": windows.supported(), "stage": "başlangıç"}
    if not windows.supported():
        print("Bu kontrol yalnız Windows'ta (Görev Zamanlayıcı) çalışır.")
        return 1
    when = (datetime.now() + timedelta(minutes=2)).replace(second=0, microsecond=0)
    if (when - datetime.now()).total_seconds() < 75:
        when += timedelta(minutes=1)
    s = Schedule(name="kayaAI kontrol (silinecek)", kind="reindex",
                 cadence=Cadence(freq="once", at=when.strftime("%H:%M"), on=when.strftime("%Y-%m-%d")))
    report["id"], report["when"] = s.id, when.isoformat()
    created = False
    try:
        with build_runtime(settings) as rt:
            r = request_create(rt, s, requested_by="schedule_check")
            if not ask(rt, r.approval_id):
                print("Onay verilmedi; kontrol yapılmadı.")
                report["stage"] = "onay verilmedi"
                return 1
            created = True
            saved = rt.store.get_schedule(s.id)
            report["registered"] = bool(saved and saved.get("registered"))
            report["register_note"] = saved.get("register_note") if saved else None
            report["in_windows"] = s.id in (windows.registered_ids() or set())
            print(f"Görev Zamanlayıcı'da: \\{windows.task_name(s.id)} — {when:%H:%M}'de Windows çalıştıracak.")
            print("İstersen şimdi 'kayaai api' penceresini kapat; bu betik görevi ÇALIŞTIRMAZ, yalnız bekler…")
        report["stage"] = "bekleniyor"
        deadline = when + timedelta(minutes=4)
        run = None
        while datetime.now() < deadline:
            time.sleep(10)
            with build_runtime(settings) as rt:
                runs = [x for x in rt.store.list_schedule_runs(s.id) if x.get("trigger") == "windows"]
                if runs and runs[0]["status"] != "running":
                    run = runs[0]
                    break
            print(f"  bekleniyor… ({datetime.now():%H:%M:%S})")
        report["run"] = run
        report["stage"] = "doğrulama"
        with build_runtime(settings) as rt:
            cid = rt.store.get_meta("schedule_conv")
            msgs = [m for m in rt.store.list_messages(cid)] if cid else []
            report["chat_message"] = any((m.get("meta") or {}).get("schedule", {}).get("id") == s.id for m in msgs)
        report["ok"] = bool(run and run["status"] == "succeeded" and report["chat_message"])
    except BaseException as exc:  # noqa: BLE001 - Ctrl+C dahil: rapor yine yazılsın
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["ok"] = False
    finally:
        if created:
            report["task_scheduler"] = task_query(s.id)  # Son Çalışma Zamanı / Son Sonuç (0 = başarılı)
            log = settings.data_dir / "schedule" / f"{s.id}.log"
            report["run_log"] = log.read_text(encoding="utf-8", errors="replace")[-4000:] if log.is_file() else None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"Rapor: {out}")
    if created:
        try:
            with build_runtime(settings) as rt:
                d = request_delete(rt, s.id, requested_by="schedule_check")
                report["deleted"] = ask(rt, d.approval_id)
        except BaseException as exc:  # noqa: BLE001
            print(f"Test görevi silinemedi ({exc}); elle: kayaai schedule rm {s.id}")
    run = report.get("run")
    print("Sonuç:", "Windows görevi kayaAI'yi kendiliğinden çalıştırdı ✓" if report.get("ok") else
          f"çalışma görülmedi — {('durum: ' + run['status'] + ' ' + run['message']) if run else 'raporda task_scheduler ve run_log alanlarına bak'}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
