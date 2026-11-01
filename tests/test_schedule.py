"""Adım 13a: zamanlanmış görevler — sıklık, Görev Zamanlayıcı XML'i, onay akışı (sahte schtasks), çalıştırıcı, işleyiciler, API, CLI."""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.schedule import Cadence, Schedule, ScheduleError, list_schedules, request_create, request_delete, \
    request_enable, request_run, sync_report, windows
from kayaai.schedule.runner import due, run_due, run_schedule

from .conftest import good_answer
from .test_business import PLAN_BY_REGION, by_title, make_xlsx

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


# ---------------------------------------------------------------- sıklık

@pytest.mark.parametrize("cad,now,expected", [
    (dict(freq="daily", at="09:00"), "2026-11-01 08:00", "2026-11-01 09:00"),
    (dict(freq="daily", at="09:00"), "2026-11-01 09:00", "2026-11-02 09:00"),
    (dict(freq="weekly", at="09:30", days=[0, 4]), "2026-11-01 10:00", "2026-11-02 09:30"),   # pazar → pazartesi
    (dict(freq="weekly", at="09:30", days=[4]), "2026-11-06 09:31", "2026-11-13 09:30"),      # cuma geçti → gelecek cuma
    (dict(freq="monthly", at="07:00", day=1), "2026-12-15 00:00", "2027-01-01 07:00"),        # yıl dönümü
    (dict(freq="monthly", at="07:00", day=28), "2026-02-01 00:00", "2026-02-28 07:00"),
    (dict(freq="once", at="18:00", on="2026-11-05"), "2026-11-01 00:00", "2026-11-05 18:00"),
    (dict(freq="once", at="18:00", on="2026-10-05"), "2026-11-01 00:00", None),
])
def test_next_after(cad, now, expected):
    got = Cadence(**cad).next_after(datetime.fromisoformat(now))
    assert (got.strftime("%Y-%m-%d %H:%M") if got else None) == expected


@pytest.mark.parametrize("cad,err", [(dict(at="25:00"), "HH:MM"), (dict(freq="weekly", days=[]), "en az bir gün"),
                                     (dict(freq="monthly", day=31), "28"), (dict(freq="once"), "tarih")])
def test_cadence_validation(cad, err):
    with pytest.raises(ValueError, match=err):
        Cadence(**cad)


def test_schedule_param_validation():
    with pytest.raises(ValueError, match="path"):
        Schedule(name="x", kind="sales_report", cadence=Cadence())
    with pytest.raises(ValueError, match="request"):
        Schedule(name="x", kind="free", params={"request": "a"}, cadence=Cadence())
    assert Schedule(name="x", kind="docs_digest", cadence=Cadence()).params["max_files"] == 10


def test_due_logic():
    s = Schedule(name="x", kind="reindex", cadence=Cadence(at="03:00"), created_at=datetime(2026, 11, 1, 12, 0))
    assert not due(s, datetime(2026, 11, 2, 2, 59)) and due(s, datetime(2026, 11, 2, 3, 0))
    s.last_run = datetime(2026, 11, 2, 3, 0, 5)
    assert not due(s, datetime(2026, 11, 2, 23, 0)) and due(s, datetime(2026, 11, 3, 3, 1))


# ---------------------------------------------------------------- Görev Zamanlayıcı XML'i

def test_task_xml_weekly():
    s = Schedule(name="Haftalık <rapor> & özet", kind="reindex", cadence=Cadence(freq="weekly", at="08:45", days=[0, 2]),
                 catch_up=True)
    x = windows.task_xml(s, now=datetime(2026, 11, 1, 10, 0), user="PC\\MERT")
    root = ET.fromstring(x.split("\n", 1)[1])
    trig = root.find("t:Triggers/t:CalendarTrigger", NS)
    assert trig.find("t:StartBoundary", NS).text == "2026-11-02T08:45:00"
    assert [e.tag.split("}")[1] for e in trig.find("t:ScheduleByWeek/t:DaysOfWeek", NS)] == ["Monday", "Wednesday"]
    assert root.find("t:Settings/t:StartWhenAvailable", NS).text == "true"
    assert root.find("t:Settings/t:ExecutionTimeLimit", NS).text == "PT2H"
    p = root.find("t:Principals/t:Principal", NS)
    assert p.find("t:LogonType", NS).text == "InteractiveToken" and p.find("t:RunLevel", NS).text == "LeastPrivilege"
    assert p.find("t:UserId", NS).text == "PC\\MERT"
    ex = root.find("t:Actions/t:Exec", NS)
    assert ex.find("t:Arguments", NS).text == f"-m kayaai schedule run {s.id} --trigger windows"
    assert Path(ex.find("t:WorkingDirectory", NS).text, "kayaai").is_dir()
    assert "Haftalık <rapor> & özet" in root.find("t:RegistrationInfo/t:Description", NS).text


@pytest.mark.parametrize("cad,tag", [(dict(freq="daily"), "ScheduleByDay"), (dict(freq="monthly", day=5), "ScheduleByMonth"),
                                     (dict(freq="once", on="2030-01-01"), None)])
def test_task_xml_other_triggers(cad, tag):
    s = Schedule(name="x", kind="reindex", cadence=Cadence(**cad), catch_up=False, enabled=False)
    root = ET.fromstring(windows.task_xml(s, user="u").split("\n", 1)[1])
    if tag:
        assert root.find(f"t:Triggers/t:CalendarTrigger/t:{tag}", NS) is not None
    else:
        assert root.find("t:Triggers/t:TimeTrigger/t:StartBoundary", NS).text == "2030-01-01T09:00:00"
    assert root.find("t:Settings/t:StartWhenAvailable", NS).text == "false"
    assert root.find("t:Settings/t:Enabled", NS).text == "false"


# ---------------------------------------------------------------- onay + kayıt (sahte schtasks)

@pytest.fixture
def env(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    s = load_settings()
    s.ollama.max_retries = 0
    return s


@pytest.fixture
def rt(env):
    r = build_runtime(env)
    yield r
    r.close()


@pytest.fixture
def schtasks():
    calls: list[list[str]] = []
    registered: set[str] = set()

    def runner(args):
        calls.append(args)
        if args[1] == "/Create":
            xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
            registered.add(args[3].split("\\")[1])
        elif args[1] == "/Delete":
            registered.discard(args[3].split("\\")[1])
        elif args[1] == "/Query":
            return 0, "\n".join(f'"\\kayaAI\\{i}","01.12.2026 09:00:00","Hazır"' for i in sorted(registered)) + \
                '\n"\\Microsoft\\Other","N/A","Hazır"'
        return 0, "BAŞARILI"

    windows.set_runner(runner)
    yield calls, registered
    windows.set_runner(None)


def test_create_needs_approval_then_registers(rt, schtasks):
    calls, registered = schtasks
    s = Schedule(name="Gece dizin", kind="reindex", cadence=Cadence(at="03:00"))
    r = request_create(rt, s)
    assert r.status == "awaiting_approval" and r.risk.value == "R2" and calls == [] and rt.store.list_schedules() == []
    a = rt.permissions.get(r.approval_id)
    assert "kayaAI\\" + s.id in a.action.preview["new_head"] and "schedule run" in a.action.preview["new_head"]
    assert rt.permissions.approve(r.approval_id, decided_by="owner").status == "approved"
    assert calls[0][:4] == ["schtasks", "/Create", "/TN", f"kayaAI\\{s.id}"] and s.id in registered
    rows = list_schedules(rt)
    assert rows[0]["registered"] and rows[0]["in_windows"] is True and rows[0]["next_run"].endswith("03:00:00")
    assert sync_report(rt) == {"supported": True, "missing": [], "orphans": []}

    assert request_enable(rt, s.id, False).status == "done"  # R1: onaysız, kayda geçer
    assert calls[-1] == ["schtasks", "/Change", "/TN", f"kayaAI\\{s.id}", "/DISABLE"]
    assert list_schedules(rt)[0]["enabled"] is False and list_schedules(rt)[0]["next_run"] is None
    d = request_delete(rt, s.id)
    assert d.status == "awaiting_approval"
    assert rt.permissions.approve(d.approval_id, decided_by="owner").status == "approved"
    assert calls[-1][:2] == ["schtasks", "/Delete"] and rt.store.list_schedules() == [] and not registered


def test_rejected_approval_changes_nothing(rt, schtasks):
    calls, _ = schtasks
    r = request_create(rt, Schedule(name="x", kind="reindex", cadence=Cadence()))
    rt.permissions.reject(r.approval_id, decided_by="owner")
    assert calls == [] and rt.store.list_schedules() == []


def test_without_windows_schedule_is_stored_but_not_registered(rt):
    s = Schedule(name="x", kind="reindex", cadence=Cadence())
    r = request_create(rt, s)
    if windows.supported():
        pytest.skip("Windows: gerçek Görev Zamanlayıcı'ya dokunulmaz")
    assert "run-due" in rt.permissions.get(r.approval_id).action.preview["new_head"]
    rt.permissions.approve(r.approval_id, decided_by="owner")
    row = list_schedules(rt)[0]
    assert row["registered"] is False and "yalnız Windows" in row["register_note"] and row["in_windows"] is None


def test_orphan_and_missing_tasks_are_reported(rt, schtasks):
    calls, registered = schtasks
    registered.add("eskigorev")
    s = Schedule(name="x", kind="reindex", cadence=Cadence())
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    assert sync_report(rt) == {"supported": True, "missing": [s.id], "orphans": ["eskigorev"]}


@pytest.mark.parametrize("make,err", [
    (lambda: Schedule(name="x", kind="sales_report", params={"path": "yok.xlsx"}, cadence=Cadence()), "Dosya yok"),
    (lambda: Schedule(name="x", kind="reindex", cadence=Cadence(freq="once", on="2020-01-01")), "geçmiş"),
])
def test_create_validation(rt, make, err):
    with pytest.raises(ScheduleError, match=err):
        request_create(rt, make())


def test_sales_report_outside_allowed_folder_refused(rt):
    from kayaai.tools.files import PathNotAllowed

    with pytest.raises(PathNotAllowed):
        request_create(rt, Schedule(name="x", kind="sales_report", params={"path": "/etc/passwd"}, cadence=Cadence()))


# ---------------------------------------------------------------- çalıştırıcı + işleyiciler

def _add(rt, **kw) -> Schedule:
    s = Schedule(name=kw.pop("name", "Görev"), cadence=kw.pop("cadence", Cadence()), **kw)
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    return s


def _conv_messages(rt):
    from kayaai.assistant.chat import ChatBook

    cid = rt.store.get_meta("schedule_conv")
    return ChatBook(rt).view(cid).conversation, ChatBook(rt).view(cid).messages


def test_reindex_run_posts_to_chat_and_records(rt):
    home = Path(rt.settings.files.home_dir)
    home.mkdir(parents=True, exist_ok=True)
    (home / "not.md").write_text("Atlas bütçesi 120.000 TL.", encoding="utf-8")
    s = _add(rt, kind="reindex", name="Gece dizin")
    run = run_schedule(rt, s.id, "windows")
    assert run.status == "succeeded" and run.trigger == "windows"
    conv, msgs = _conv_messages(rt)
    assert conv.title == "Zamanlanmış görevler" and "belge dizini yenilendi" in msgs[-1].content
    assert msgs[-1].agent == "zamanlayıcı" and msgs[-1].meta["schedule"]["id"] == s.id
    saved = Schedule.model_validate(rt.store.get_schedule(s.id))
    assert saved.last_status == "succeeded" and saved.last_run is not None
    assert rt.store.list_schedule_runs(s.id)[0]["status"] == "succeeded"
    run_schedule(rt, s.id)  # ikinci çalışma aynı sohbete
    assert len(_conv_messages(rt)[1]) == 2


def test_ollama_down_fails_cleanly(rt, fake_ollama):
    s = _add(rt, kind="reindex")
    fake_ollama.stop()
    run = run_schedule(rt, s.id, "windows", ollama_wait_s=0.2)
    assert run.status == "failed" and "Ollama" in run.message
    assert "çalışamadı" in _conv_messages(rt)[1][-1].content and not (rt.settings.data_dir / "schedule" / f"{s.id}.lock").exists()


def test_concurrent_run_is_skipped(rt):
    s = _add(rt, kind="reindex")
    lock = rt.settings.data_dir / "schedule" / f"{s.id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("123")
    assert run_schedule(rt, s.id, "windows").status == "skipped"
    os.utime(lock, (time.time() - 4 * 3600,) * 2)  # 3 saatten eski kilit = çökmüş çalışma
    assert run_schedule(rt, s.id, "windows").status == "succeeded"


def test_disabled_task_skipped_when_triggered_by_windows(rt):
    s = _add(rt, kind="reindex", enabled=False)
    assert run_schedule(rt, s.id, "windows").status == "skipped"
    assert run_schedule(rt, s.id, "manual").status == "succeeded"


def test_once_task_disables_itself(rt):
    s = _add(rt, kind="reindex", cadence=Cadence(freq="once", on="2030-01-01"))
    run_schedule(rt, s.id)
    assert Schedule.model_validate(rt.store.get_schedule(s.id)).enabled is False


def test_docs_digest_summarizes_changed_files_only(rt, fake_ollama):
    home = Path(rt.settings.files.home_dir)
    (home / "proje").mkdir(parents=True, exist_ok=True)
    (home / "proje" / "toplanti.md").write_text("Atlas toplantısı: teslim 15 Kasım.", encoding="utf-8")
    (home / "proje" / ".env").write_text("SECRET=1", encoding="utf-8")
    old = home / "eski.md"
    old.write_text("Eski not", encoding="utf-8")
    os.utime(old, (time.time() - 3 * 86400,) * 2)
    fake_ollama.chat_replies = [good_answer("Atlas teslim tarihi 15 Kasım olarak konuşuldu.")]
    s = _add(rt, kind="docs_digest", name="Sabah özeti")
    run = run_schedule(rt, s.id)
    msg = _conv_messages(rt)[1][-1].content
    assert run.status == "succeeded" and "toplanti.md" in msg and "15 Kasım" in msg
    assert "eski.md" not in msg and ".env" not in msg
    docs = [b for (_, p, b) in fake_ollama.requests if p == "/api/chat"]
    assert len(docs) == 1 and "SECRET" not in json.dumps(docs)
    run2 = run_schedule(rt, s.id)  # son çalışmadan beri değişen yok
    assert run2.status == "succeeded" and "değişen belge yok" in _conv_messages(rt)[1][-1].content


def test_sales_report_creates_files(rt, fake_ollama):
    home = Path(rt.settings.files.home_dir)
    home.mkdir(parents=True, exist_ok=True)
    (home / "satis.xlsx").write_bytes(make_xlsx())
    fake_ollama.chat_replies = [by_title(AnalysisPlan=[PLAN_BY_REGION], GeneralAnswer=[good_answer("Ankara 320 ile önde.")])] * 10
    s = _add(rt, kind="sales_report", name="Haftalık satış", params={"path": "satis.xlsx", "formats": ["xlsx", "pdf"]})
    run = run_schedule(rt, s.id)
    assert run.status == "succeeded", run.message
    assert sorted(Path(f).suffix for f in run.files) == [".pdf", ".xlsx"] and all(Path(f).is_file() for f in run.files)
    assert all(Path(f).parent.name == "raporlar" for f in run.files)
    assert "| Ankara | 320 |" in _conv_messages(rt)[1][-1].content


def test_free_task_runs_conductor_locally_even_if_claude_on(rt, fake_ollama):
    from .conductor_helpers import Script, answer, plan_direct

    rt.claude.enable()
    fake_ollama.chat_replies = [Script(planner=[plan_direct("general", needs_claude=True, reason="zor")],
                                       answers=[answer("Haftalık hatırlatma: raporları gönder.")])] * 10
    s = _add(rt, kind="free", params={"request": "Bana haftalık hatırlatma yaz"})
    run = run_schedule(rt, s.id)
    assert run.status == "succeeded", run.message
    assert "hatırlatma" in _conv_messages(rt)[1][-1].content
    assert rt.claude.status().waiting_tasks == 0  # Claude kutusuna bırakılmadı


def test_run_due(rt):
    s = _add(rt, kind="reindex", cadence=Cadence(at="03:00"), created_at=datetime(2026, 1, 1, 12, 0))
    runs = run_due(rt, now=datetime(2026, 1, 2, 4, 0))
    assert [r.schedule_id for r in runs] == [s.id]
    assert run_due(rt, now=datetime(2026, 1, 2, 5, 0)) == []  # az önce çalıştı (last_run güncel) → tekrar çalışmaz


# ---------------------------------------------------------------- API / CLI

def test_api_schedules(env, schtasks, tmp_path):
    from kayaai.api import create_app

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.get("/api/schedules").status_code == 401
        bad = c.post("/api/schedules", json={"name": "x", "kind": "reindex", "cadence": {"at": "99:00"}}, headers=h)
        assert bad.status_code == 409 and "HH:MM" in bad.json()["detail"]
        r = c.post("/api/schedules", json={"name": "Gece dizin", "kind": "reindex",
                                           "cadence": {"freq": "weekly", "at": "03:00", "days": [6]}}, headers=h).json()
        assert r["status"] == "awaiting_approval"
        assert c.post(f"/api/approvals/{r['approval_id']}/approve", headers=h).json()["status"] == "approved"
        data = c.get("/api/schedules", headers=h).json()
        sid = data["schedules"][0]["id"]
        assert data["schedules"][0]["cadence_text"] == "her Pazar 03:00" and data["schedules"][0]["in_windows"] is True
        assert c.post(f"/api/schedules/{sid}/run", headers=h).json()["status"] == "done"
        for _ in range(100):
            runs = c.get(f"/api/schedules/runs?sid={sid}", headers=h).json()
            if runs and runs[0]["status"] != "running":
                break
            time.sleep(0.05)
        assert runs[0]["status"] == "succeeded"
        assert c.post("/api/schedules/yok/run", headers=h).status_code == 404


def test_cli_schedule(env, schtasks, capsys):
    from kayaai.cli import main

    assert main(["schedule", "add", "--kind", "reindex", "--weekly", "pzt,cum", "--at", "07:30", "--name", "Dizin"]) == 0
    out = capsys.readouterr().out
    assert "ONAY BEKLİYOR" in out
    aid = out.split("approvals approve ")[1].split()[0]
    assert main(["approvals", "approve", aid]) == 0
    capsys.readouterr()
    assert main(["schedule", "list"]) == 0
    out = capsys.readouterr().out
    assert "her Pazartesi, Cuma 07:30" in out and "Windows'ta kayıtlı" in out
    sid = out.split()[0]
    assert main(["schedule", "run", sid]) == 0 and "succeeded" in capsys.readouterr().out
    assert main(["schedule", "add", "--kind", "free", "--request", "x"]) == 1
