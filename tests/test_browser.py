"""Adım 12d: tarayıcı otomasyonu — kodla risk sınıfı, ajan döngüsü (sahte sürücü: onay/ret/kural/durdur), gerçek sürücü, API."""

from __future__ import annotations

import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai.browser import agent as ba
from kayaai.browser.agent import BrowserJobError, start_job
from kayaai.browser.driver import PageState
from kayaai.browser.risk import Element, classify, site
from kayaai.config import load_settings
from kayaai.runtime import build_runtime

CHROMIUM = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux64/chrome"))), None) \
    if Path("/opt/pw-browsers").is_dir() else None


def E(id_: int, tag: str, name: str = "", **kw) -> Element:
    return Element(id=id_, tag=tag, name=name, **kw)


# ---------------------------------------------------------------- risk (kod)

URL = "https://kitap.example.com/ara"


@pytest.mark.parametrize("action,el,value,verdict", [
    ("scroll", None, "down", "R0"),
    ("extract", None, "", "R0"),
    ("goto", None, "https://kitap.example.com/hakkinda", "R1"),
    ("goto", None, "https://baska-site.org/", "R2"),
    ("goto", None, "file:///C:/Users/x.txt", "refuse"),
    ("goto", None, "http://192.168.1.1/admin", "refuse"),
    ("goto", None, "http://localhost:8765/api", "refuse"),
    ("click", E(1, "a", "Hakkımızda", href="https://kitap.example.com/hakkinda"), "", "R1"),
    ("click", E(2, "a", "Partner", href="https://partner.net/"), "", "R2"),
    ("click", E(3, "button", "Ara", type="submit", in_form=True), "", "R2"),
    ("click", E(4, "button", "Sepete ekle"), "", "R1"),
    ("click", E(5, "button", "Satın Al"), "", "R3"),
    ("click", E(6, "button", "Siparişi Tamamla"), "", "R3"),
    ("click", E(7, "input", "Gönder", type="submit", in_form=True), "", "R3"),
    ("click", E(8, "button", "Devam", type="submit", in_form=True, form_sensitive=True), "", "R3"),
    ("click", E(9, "button", "Delete account"), "", "R3"),
    ("click", E(10, "a", "Kurulum", href="https://kitap.example.com/setup.exe"), "", "refuse"),
    ("click", E(11, "a", "PDF", href="https://kitap.example.com/x.pdf", download=True), "", "refuse"),
    ("type", E(12, "input", "Arama", type="search"), "python", "R2"),
    ("type", E(13, "input", "", type="password"), "1234", "refuse"),
    ("type", E(14, "input", "Kart numarası", type="text"), "4111", "refuse"),
    ("type", E(15, "input", "", type="text", autocomplete="cc-number"), "4111", "refuse"),
    ("type", E(16, "input", "", type="text", field="tckn"), "1", "refuse"),
    ("type", E(17, "input", "", type="file"), "x", "refuse"),
    ("select", E(18, "select", "Sırala"), "Fiyat", "R2"),
    ("click", None, "", "refuse"),
])
def test_risk_table(action, el, value, verdict):
    assert classify(action, URL, el, value).verdict == verdict


def test_site_and_local_allowance():
    assert site("www.kitap.com.tr") == "kitap.com.tr" and site("a.b.example.com") == "example.com"
    assert classify("goto", "http://127.0.0.1:9/", None, "http://127.0.0.1:9/x", allow_local=True).verdict == "R1"


# ---------------------------------------------------------------- sahte sürücü + ajan

class FakeDriver:
    """İki sayfalı sahte site: arama formu → sonuç sayfası; 'Satın Al' düğmesi; parola alanı."""

    def __init__(self, settings):
        self.acts: list[tuple] = []
        self.url = ""
        self.typed: dict[int, str] = {}
        self.closed = False

    def open(self, url):
        self.url = url

    def snapshot(self):
        if self.url.endswith("/sonuc"):
            return PageState(url=self.url, title="Sonuçlar", text="Python ile Programlama — 250 TL\nStokta var",
                             elements=[E(1, "button", "Satın Al"), E(2, "a", "Ana sayfa", href="https://kitap.example.com/")])
        return PageState(url=self.url, title="Kitap Ara", text="Kitap ara",
                         elements=[E(1, "input", "Arama", type="search", in_form=True),
                                   E(2, "button", "Ara", type="submit", in_form=True),
                                   E(3, "input", "", type="password", field="sifre", in_form=True)])

    def screenshot(self, element_id=None):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1280, 800), "white").save(buf, format="JPEG")
        return buf.getvalue()

    def act(self, action, element_id, value):
        self.acts.append((action, element_id, value))
        if action == "click" and element_id == 2 and not self.url.endswith("/sonuc"):
            self.url = "https://kitap.example.com/sonuc"
        if action == "type":
            self.typed[element_id] = value

    def close(self):
        self.closed = True


def act(action, element_id=None, value="", answer="", thought="Sayfaya bakıyorum."):
    return json.dumps({"thought": thought, "action": action, "element_id": element_id, "value": value, "answer": answer},
                      ensure_ascii=False)


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    s.ollama.max_retries = 0
    s.browser.approval_timeout_s = 30
    r = build_runtime(s)
    yield r
    r.close()


def _drive(rt, approvals: list[str], timeout: float = 15):
    """Arka planda çalışan işin onay taleplerine sırayla karar verir (sahip gibi)."""
    decided = []
    t0 = time.monotonic()
    while len(decided) < len(approvals) and time.monotonic() - t0 < timeout:
        for a in rt.permissions.list_approvals("pending"):
            if a.id in [d.id for d in decided]:
                continue
            want = approvals[len(decided)]
            (rt.permissions.approve if want == "approve" else rt.permissions.reject)(a.id, decided_by="owner")
            decided.append(a)
        time.sleep(0.05)
    return decided


def _wait(job, timeout=15):
    assert job.finished.wait(timeout), "tarayıcı işi bitmedi"
    return job.state


def test_agent_fills_form_with_approvals_and_answers(rt, fake_ollama):
    drivers = []
    fake_ollama.chat_replies = [act("type", 1, "python"), act("click", 2),
                                act("extract", answer="Python ile Programlama 250 TL, stokta"),
                                act("done", answer="Kitap bulundu: Python ile Programlama, 250 TL (stokta).")]
    job = start_job(rt, "Python kitabı ara ve fiyatını söyle", "https://kitap.example.com/ara",
                    driver_factory=lambda s: drivers.append(FakeDriver(s)) or drivers[-1], background=True)
    decided = _drive(rt, ["approve", "approve"])
    st = _wait(job)
    assert st.status == "done" and "250 TL" in st.answer
    assert [s.risk for s in st.steps] == ["R2", "R2", "R0", "R0"] and [s.status for s in st.steps][:2] == ["yapıldı", "yapıldı"]
    assert drivers[0].acts == [("type", 1, "python"), ("click", 2, "")] and drivers[0].closed
    a0 = decided[0]
    assert a0.action.risk.value == "R2" and a0.action.preview["image"].startswith("data:image/jpeg;base64,")
    assert "Arama" in a0.action.summary and "python" in a0.action.summary
    task = rt.store.get(st.task_id)
    assert task.status.value == "succeeded" and task.worker == "browser" and task.result["answer"] == st.answer
    assert any(e["event"] == "browser.step" for e in rt.store.events(task.id))
    assert len(rt.store.list_children(task.id)) == 4  # her model adımı alt görev


def test_purchase_is_r3_and_rejection_stops(rt, fake_ollama):
    fake_ollama.chat_replies = [act("type", 1, "python"), act("click", 2), act("click", 1, thought="Satın alıyorum")]
    drv = FakeDriver(None)
    job = start_job(rt, "Python kitabını satın al", "https://kitap.example.com/ara", driver_factory=lambda s: drv,
                    background=True)
    decided = _drive(rt, ["approve", "approve", "reject"])
    st = _wait(job)
    assert decided[2].action.risk.value == "R3" and "Satın Al" in decided[2].action.summary
    assert st.status == "failed" and "onaylamadı" in st.error and st.steps[-1].status == "reddedildi"
    assert ("click", 1, "") not in drv.acts[2:]  # satın alma yapılmadı


def test_password_field_is_refused_then_model_finishes(rt, fake_ollama):
    fake_ollama.chat_replies = [act("type", 3, "gizli123"), act("done", answer="Şifre alanını sen doldurmalısın.")]
    drv = FakeDriver(None)
    job = start_job(rt, "Giriş yap", "https://kitap.example.com/ara", driver_factory=lambda s: drv, background=False)
    assert job.state.status == "done" and job.state.steps[0].status == "kural dışı"
    assert "parola" in job.state.steps[0].reason and drv.acts == [] and rt.permissions.list_approvals("all") == []
    prev = json.loads(json.dumps([b for (_, p, b) in fake_ollama.requests if p == "/api/chat"][-1]))
    assert "YAPILMADI" in prev["messages"][-1]["content"]


def test_unknown_element_id_is_retried_by_validation(rt, fake_ollama):
    fake_ollama.chat_replies = [act("click", 99), act("done", answer="Bitti.")]
    job = start_job(rt, "Bir şey yap", "https://kitap.example.com/ara", driver_factory=FakeDriver, background=False)
    assert job.state.status == "done"
    second = [b for (_, p, b) in fake_ollama.requests if p == "/api/chat"][-1]["messages"][-1]["content"]
    assert "element_id 99 listede yok" in second


def test_stop_while_waiting_for_approval(rt, fake_ollama):
    fake_ollama.chat_replies = [act("type", 1, "python")]
    job = start_job(rt, "Python ara", "https://kitap.example.com/ara", driver_factory=FakeDriver, background=True)
    t0 = time.monotonic()
    while not rt.permissions.list_approvals("pending") and time.monotonic() - t0 < 10:
        time.sleep(0.05)
    job.stop_event.set()
    st = _wait(job)
    assert st.status == "stopped" and rt.permissions.list_approvals("pending") == []
    assert rt.store.get(st.task_id).status.value == "cancelled"


def test_repeated_action_stops(rt, fake_ollama):
    fake_ollama.chat_replies = [act("scroll", value="down")] * 5
    job = start_job(rt, "Sayfayı oku", "https://kitap.example.com/ara", driver_factory=FakeDriver, background=False)
    assert job.state.status == "failed" and "tekrarlanıyor" in job.state.error


@pytest.mark.parametrize("url,err", [("file:///etc/passwd", "http/https"), ("javascript:alert(1)", "http/https"),
                                     ("ftp://x.com/a", "http/https"), ("http://192.168.0.1", "yerel ağ"),
                                     ("http://localhost:8765", "yerel ağ")])
def test_start_url_rules(rt, url, err):
    with pytest.raises(BrowserJobError, match=err):
        start_job(rt, "Bir şey yap", url, driver_factory=FakeDriver)


def test_single_job_at_a_time(rt, fake_ollama):
    fake_ollama.chat_replies = [act("type", 1, "python")]
    job = start_job(rt, "Python ara", "https://kitap.example.com/ara", driver_factory=FakeDriver, background=True)
    with pytest.raises(BrowserJobError, match="Zaten"):
        start_job(rt, "İkinci iş", "https://kitap.example.com/", driver_factory=FakeDriver)
    job.stop_event.set()
    _wait(job)


# ---------------------------------------------------------------- gerçek sürücü (Chromium varsa)

PAGE = """<!doctype html><html><head><title>Test Mağaza</title></head><body>
<h1>Kitaplar</h1><form action="/sonuc" method="get"><label for="q">Arama</label><input id="q" name="q">
<button type="submit">Ara</button></form><a href="/hakkinda">Hakkımızda</a>
<form><input type="password" name="sifre"><button>Giriş</button></form>
<button style="display:none">Gizli</button></body></html>"""


@pytest.fixture
def site_srv():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = (PAGE if not self.path.startswith("/sonuc") else
                    f"<html><title>Sonuç</title><body>Aranan: {self.path.split('q=')[-1]}</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.skipif(CHROMIUM is None, reason="Chromium yok (yalnız geliştirme ortamında)")
def test_real_driver_snapshot_act_screenshot(tmp_path, site_srv):
    from kayaai.browser.driver import BrowserDriver

    s = load_settings()
    s.data_dir = tmp_path
    s.browser.executable_path, s.browser.headless, s.browser.allow_local = str(CHROMIUM), True, True
    d = BrowserDriver(s)
    try:
        d.open(site_srv + "/")
        p = d.snapshot()
        names = {e.name: e for e in p.elements}
        assert p.title == "Test Mağaza" and "Gizli" not in names
        assert names["Arama"].tag == "input" and names["Arama"].in_form
        assert names["Ara"].type == "submit" and names["Giriş"].form_sensitive
        assert names["Hakkımızda"].href.endswith("/hakkinda")
        shot = d.screenshot(names["Ara"].id)
        assert shot[:2] == b"\xff\xd8"
        d.act("type", names["Arama"].id, "python")
        d.act("click", names["Ara"].id, "")
        p2 = d.snapshot()
        assert "Aranan: python" in p2.text and p2.url.startswith(site_srv + "/sonuc")
        with pytest.raises(Exception):
            d.act("goto", None, "file:///etc/passwd")
        assert (tmp_path / "browser_profile").is_dir()
    finally:
        d.close()


@pytest.mark.skipif(CHROMIUM is None, reason="Chromium yok")
def test_real_driver_blocks_local_network(tmp_path, site_srv):
    from kayaai.browser.driver import BrowserDriver

    s = load_settings()
    s.data_dir = tmp_path
    s.browser.executable_path, s.browser.headless = str(CHROMIUM), True  # allow_local=False
    d = BrowserDriver(s)
    try:
        with pytest.raises(Exception):
            d.open(site_srv + "/")
    finally:
        d.close()


# ---------------------------------------------------------------- API

def test_api_browser(rt, fake_ollama, tmp_path, monkeypatch):
    from kayaai.api import create_app

    monkeypatch.setattr(ba, "BrowserDriver", FakeDriver)
    fake_ollama.chat_replies = [act("type", 1, "python"), act("done", answer="Tamam.")]
    app = create_app(rt.settings, runtime=rt, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.post("/api/browser/run", json={"goal": "x", "url": "https://a.com"}).status_code == 401
        assert c.post("/api/browser/run", json={"goal": "Python ara", "url": "file:///x"}, headers=h).status_code == 409
        job = c.post("/api/browser/run", json={"goal": "Python ara", "url": "kitap.example.com/ara"}, headers=h).json()
        assert job["start_url"] == "https://kitap.example.com/ara"
        for _ in range(100):
            st = c.get(f"/api/browser/jobs/{job['id']}", headers=h).json()
            if st["status"] == "waiting":
                break
            time.sleep(0.05)
        assert st["steps"][-1]["status"] == "onay bekliyor"
        aid = st["steps"][-1]["approval_id"]
        assert c.post(f"/api/approvals/{aid}/approve", headers=h).json()["status"] == "approved"
        for _ in range(100):
            st = c.get(f"/api/browser/jobs/{job['id']}", headers=h).json()
            if st["status"] == "done":
                break
            time.sleep(0.05)
        assert st["answer"] == "Tamam." and st["screenshot"].startswith("data:image/jpeg")
        assert c.get("/api/browser/jobs", headers=h).json()[0]["id"] == job["id"]
        assert c.post("/api/browser/jobs/yok/stop", headers=h).status_code == 404
        assert ba.get_job(job["id"]).finished.wait(10)
