"""Adım 6: Control Center'ın API tarafından sunulması, güvenlik başlıkları ve `kayaai ui`."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kayaai import cli
from kayaai.api import create_app
from kayaai.api.app import UI_CSP
from kayaai.config import load_settings
from kayaai.runtime import build_runtime


def _client(fake_ollama, tmp_path: Path, monkeypatch, ui_dir: Path):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    settings = load_settings()
    rt = build_runtime(settings)
    app = create_app(settings, runtime=rt, ui_dir=ui_dir)
    return TestClient(app), rt, app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (d / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "gizli.txt").write_text("dışarıda", encoding="utf-8")
    return d


def test_missing_dist_shows_help_page(fake_ollama, tmp_path, monkeypatch):
    client, rt, _ = _client(fake_ollama, tmp_path, monkeypatch, tmp_path / "yok")
    with client:
        r = client.get("/")
        assert r.status_code == 200 and "derlenmemiş" in r.text and "npm run build" in r.text
    rt.close()


def test_serves_index_assets_and_spa_fallback(fake_ollama, tmp_path, monkeypatch, dist):
    client, rt, _ = _client(fake_ollama, tmp_path, monkeypatch, dist)
    with client:
        r = client.get("/")
        assert r.status_code == 200 and 'id=root' in r.text and r.headers["cache-control"] == "no-cache"
        a = client.get("/assets/index-abc.js")
        assert a.status_code == 200 and "console.log" in a.text and "immutable" in a.headers["cache-control"]
        assert 'id=root' in client.get("/onaylar/xyz").text  # SPA yolu → index
        assert client.head("/").status_code == 200
        # dist dışına çıkılamaz
        assert "dışarıda" not in client.get("/..%2Fgizli.txt").text
        assert "dışarıda" not in client.get("/assets/..%2F..%2Fgizli.txt").text
    rt.close()


def test_api_still_protected_and_unknown_api_is_404(fake_ollama, tmp_path, monkeypatch, dist):
    client, rt, app = _client(fake_ollama, tmp_path, monkeypatch, dist)
    with client:
        assert client.get("/api/health").status_code == 401
        r = client.get("/api/yok", headers={"Authorization": f"Bearer {app.state.token}"})
        assert r.status_code == 404 and "id=root" not in r.text
        assert client.get("/api").status_code == 404
    rt.close()


def test_security_headers(fake_ollama, tmp_path, monkeypatch, dist):
    client, rt, _ = _client(fake_ollama, tmp_path, monkeypatch, dist)
    with client:
        r = client.get("/")
        assert r.headers["content-security-policy"] == UI_CSP
        assert "default-src 'self'" in UI_CSP and "frame-ancestors 'none'" in UI_CSP and "unsafe" not in UI_CSP
        assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
        assert client.get("/api/health").headers["content-security-policy"] == UI_CSP
        # Swagger sayfası CDN kullanır: ona CSP konmaz ama nosniff kalır
        d = client.get("/docs")
        assert d.status_code == 200 and "content-security-policy" not in d.headers
        assert d.headers["x-content-type-options"] == "nosniff"
    rt.close()


def test_ui_print_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    assert cli.main(["ui", "--print"]) == 0
    token = (tmp_path / "api_token").read_text(encoding="utf-8").strip()
    assert capsys.readouterr().out.strip() == f"http://127.0.0.1:8765/#token={token}"


def test_ui_refuses_non_local_and_reports_missing_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    assert cli.main(["ui", "--host", "0.0.0.0"]) == 2
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    assert cli.main(["ui", "--port", "1"]) == 1  # sunucu yok
    assert not opened and "kayaai api" in capsys.readouterr().out
