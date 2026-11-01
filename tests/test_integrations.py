"""Adım 14c: isteğe bağlı dış veri — açma onayı, yalnız izinli ana makineler, önbellek, sohbet bağlamı, tatil atlama."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai import integrations as ig
from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.schedule import Cadence, Schedule, ScheduleError, request_create
from kayaai.schedule.runner import run_schedule

from .conftest import good_answer

FRANKFURTER = {"amount": 1.0, "base": "EUR", "date": "2026-10-30",
               "rates": {"TRY": 48.5, "USD": 1.16, "GBP": 0.87, "CHF": 0.93, "JPY": 176.2}}
TODAY = date.today()
NAGER = [{"date": f"{TODAY.year}-01-01", "localName": "Yılbaşı", "name": "New Year's Day", "countryCode": "TR"},
         {"date": TODAY.isoformat(), "localName": "Test Bayramı", "name": "Test Holiday", "countryCode": "TR"}]


@pytest.fixture
def net(monkeypatch):
    calls: list[str] = []

    def fake(url, timeout=10):
        calls.append(url)
        if "frankfurter" in url:
            return FRANKFURTER
        if "nager" in url:
            return NAGER
        raise AssertionError(url)

    monkeypatch.setattr(ig, "_fetch_json", fake)
    return calls


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


def _enable(rt, name):
    r = ig.request_enable(rt, name)
    assert r.status == "awaiting_approval" and r.risk.value == "R2"
    assert rt.permissions.approve(r.approval_id, decided_by="owner").status == "approved"


def test_disabled_by_default_and_no_network(rt, net):
    assert ig.enabled(rt) == {"exchange_rates": False, "holidays": False}
    with pytest.raises(ig.IntegrationDisabled):
        ig.rates(rt)
    assert net == []


def test_enable_needs_approval_and_preview_says_what_is_sent(rt, net):
    r = ig.request_enable(rt, "exchange_rates")
    a = rt.permissions.get(r.approval_id)
    assert "api.frankfurter.dev" in a.action.preview["new_head"] and "para birimi kodları" in a.action.preview["new_head"]
    assert not ig.is_enabled(rt, "exchange_rates")
    rt.permissions.approve(r.approval_id, decided_by="owner")
    assert ig.is_enabled(rt, "exchange_rates")
    assert ig.request_disable(rt, "exchange_rates").status == "done" and not ig.is_enabled(rt, "exchange_rates")


def test_rates_computed_and_cached_daily(rt, net):
    _enable(rt, "exchange_rates")
    r = ig.rates(rt)
    assert r["per_try"]["EUR"] == 48.5 and r["per_try"]["USD"] == pytest.approx(48.5 / 1.16, abs=1e-3)
    assert ig.rates(rt) == r and len(net) == 1  # aynı gün önbellekten
    assert "1 USD = 41,8103 TL" in ig.rates_note(r)
    ev = [e["data"] for e in rt.store.events_since(0) if e["type"] == "integration.call"]
    assert ev == [{"name": "exchange_rates", "host": "api.frankfurter.dev", "ok": True}]


def test_only_allowed_host(rt, net):
    _enable(rt, "exchange_rates")
    with pytest.raises(ig.IntegrationError, match="İzin verilmeyen"):
        ig._get(rt, "exchange_rates", "https://evil.example.com/x")


def test_network_failure_is_reported_and_logged(rt, monkeypatch):
    _enable(rt, "holidays")
    monkeypatch.setattr(ig, "_fetch_json", lambda url, timeout=10: (_ for _ in ()).throw(OSError("bağlantı yok")))
    with pytest.raises(ig.IntegrationError, match="bağlantı yok"):
        ig.holidays(rt, 2026)
    assert [e["data"]["ok"] for e in rt.store.events_since(0) if e["type"] == "integration.call"] == [False]


def test_chat_gets_rates_only_for_currency_questions(rt, net, fake_ollama):
    from kayaai.assistant.chat import ChatBook

    book = ChatBook(rt)
    conv = book.create()
    user, reply, run = book.send(conv.id, "Merhaba nasılsın?", agent="general")
    ctx, _ = book.build_context(conv.id, user, [])
    assert "exchange_rates" not in ctx  # kapalı
    _enable(rt, "exchange_rates")
    user2, _, _ = book.send(conv.id, "1500 dolar kaç TL eder?", agent="general")
    ctx2, _ = book.build_context(conv.id, user2, [])
    assert ctx2["exchange_rates"]["1_unit_in_TRY"]["USD"] == pytest.approx(41.81, abs=0.01)
    user3, _, _ = book.send(conv.id, "Bugün hava nasıl?", agent="general")
    assert "exchange_rates" not in book.build_context(conv.id, user3, [])[0]


@pytest.mark.parametrize("text,yes", [("Euro ne kadar?", True), ("dolar kuru", True), ("USD/TRY", True),
                                      ("döviz bürosu", True), ("kuruş hesabı", False), ("toplantı yarın", False)])
def test_wants_rates(text, yes):
    assert ig.wants_rates(text) is yes


def test_schedule_skips_on_holiday(rt, net):
    with pytest.raises(ScheduleError, match="tatil takvimini aç"):
        request_create(rt, Schedule(name="x", kind="reindex", cadence=Cadence(), skip_holidays=True))
    _enable(rt, "holidays")
    s = Schedule(name="Gece", kind="reindex", cadence=Cadence(), skip_holidays=True)
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    run = run_schedule(rt, s.id, "windows")
    assert run.status == "skipped" and run.message == "resmi tatil: Test Bayramı"
    assert run_schedule(rt, s.id, "manual").status == "succeeded"  # elle çalıştırma tatilde de çalışır
    assert ig.holiday_on(rt, date(TODAY.year, 1, 1)) == "Yılbaşı" and ig.holiday_on(rt, date(TODAY.year, 1, 2)) is None
    assert len([u for u in net if "nager" in u]) == 1  # yıllık önbellek


def test_sales_report_gets_rates_note(rt, net, fake_ollama):
    from .test_business import PLAN_BY_REGION, by_title, make_xlsx

    _enable(rt, "exchange_rates")
    home = Path(rt.settings.files.home_dir)
    home.mkdir(parents=True, exist_ok=True)
    (home / "satis.xlsx").write_bytes(make_xlsx())
    fake_ollama.chat_replies = [by_title(AnalysisPlan=[PLAN_BY_REGION], GeneralAnswer=[good_answer("Ankara önde.")])] * 10
    s = Schedule(name="Satış", kind="sales_report", params={"path": "satis.xlsx", "formats": ["md"]}, cadence=Cadence())
    rt.store.save_schedule(s.id, s.created_at.isoformat(), s.model_dump(mode="json"))
    assert run_schedule(rt, s.id).status == "succeeded"
    from kayaai.assistant.chat import ChatBook

    msg = ChatBook(rt).view(rt.store.get_meta("schedule_conv")).messages[-1].content
    assert "Kurlar (Avrupa Merkez Bankası (Frankfurter), 2026-10-30)" in msg


def test_api_and_cli(env, net, tmp_path, capsys):
    from kayaai.api import create_app
    from kayaai.cli import main

    app = create_app(env, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        lst = c.get("/api/integrations", headers=h).json()
        assert {x["name"] for x in lst} == {"exchange_rates", "holidays"} and not any(x["enabled"] for x in lst)
        assert c.get("/api/integrations/rates", headers=h).status_code == 409
        r = c.post("/api/integrations/exchange_rates/enable", headers=h).json()
        assert c.post(f"/api/approvals/{r['approval_id']}/approve", headers=h).json()["status"] == "approved"
        assert c.get("/api/integrations/rates", headers=h).json()["per_try"]["EUR"] == 48.5
        assert c.post("/api/integrations/yok/enable", headers=h).status_code == 409
    assert main(["integrations"]) == 0 and "AÇIK" in capsys.readouterr().out
    assert main(["integrations", "test"]) == 0
    out = capsys.readouterr().out
    assert "exchange_rates: OK" in out and "holidays: kapalı" in out
