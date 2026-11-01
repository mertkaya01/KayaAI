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


def main() -> int:
    from kayaai.schedule import Cadence, Schedule, request_create, request_delete, windows

    settings = load_settings()
    report: dict = {"windows": windows.supported()}
    if not windows.supported():
        print("Bu kontrol yalnız Windows'ta (Görev Zamanlayıcı) çalışır.")
        return 1
    when = (datetime.now() + timedelta(minutes=2)).replace(second=0, microsecond=0)
    if (when - datetime.now()).total_seconds() < 75:
        when += timedelta(minutes=1)
    s = Schedule(name="kayaAI kontrol (silinecek)", kind="reindex",
                 cadence=Cadence(freq="once", at=when.strftime("%H:%M"), on=when.strftime("%Y-%m-%d")))
    with build_runtime(settings) as rt:
        r = request_create(rt, s, requested_by="schedule_check")
        if not ask(rt, r.approval_id):
            print("Onay verilmedi; kontrol yapılmadı.")
            return 1
        saved = rt.store.get_schedule(s.id)
        report["registered"] = bool(saved and saved.get("registered"))
        report["register_note"] = saved.get("register_note") if saved else None
        report["in_windows"] = s.id in (windows.registered_ids() or set())
        print(f"Görev Zamanlayıcı'da: \\{windows.task_name(s.id)} — {when:%H:%M}'de Windows çalıştıracak.")
        print("İstersen şimdi 'kayaai api' penceresini kapat; bu betik görevi ÇALIŞTIRMAZ, yalnız bekler…")
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
    with build_runtime(settings) as rt:
        cid = rt.store.get_meta("schedule_conv")
        msgs = [m for m in rt.store.list_messages(cid)] if cid else []
        report["chat_message"] = any((m.get("meta") or {}).get("schedule", {}).get("id") == s.id for m in msgs)
        d = request_delete(rt, s.id, requested_by="schedule_check")
        report["deleted"] = ask(rt, d.approval_id)
    report["ok"] = bool(run and run["status"] == "succeeded" and report["chat_message"])
    out = settings.data_dir / "schedule_check.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "registered", "in_windows", "chat_message", "deleted")}, ensure_ascii=False))
    print("Sonuç:", "Windows görevi kayaAI'yi kendiliğinden çalıştırdı ✓" if report["ok"] else
          f"çalışma görülmedi — {('durum: ' + run['status'] + ' ' + run['message']) if run else 'Görev Zamanlayıcı geçmişine bak'}")
    print(f"Rapor: {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
