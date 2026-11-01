"""Adım 18d: ofis çizimleri — data/ofis taraması, Türkçe adlar, durum resimleri, güvenli sunum."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kayaai.config import load_settings
from kayaai.office_assets import safe_file, scan

PNG = b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 32


def test_scan_maps_turkish_names(tmp_path: Path):
    d = tmp_path / "ofis"
    d.mkdir()
    for n in ["veri.png", "veri-calisiyor.png", "sef.svg", "masa.png", "zemin.webp", "ajan.png", "data-hata.png",
              "kedi.png", "notlar.txt", "Büyük.PNG", "OKU.txt"]:
        (d / n).write_bytes(PNG)
    (d / "alt").mkdir()
    out = scan(tmp_path)
    assert out["exists"] and out["desk"].startswith("/ofis/masa.png?v=") and out["floor"].startswith("/ofis/zemin.webp")
    assert set(out["actors"]["data"]) == {"base", "working", "error"}
    assert out["actors"]["chef"]["base"].startswith("/ofis/sef.svg") and "default" in out["actors"]
    assert out["unknown"] == ["kedi.png"] and sorted(out["skipped"]) == ["Büyük.PNG", "notlar.txt"]


def test_missing_folder(tmp_path: Path):
    out = scan(tmp_path)
    assert out["exists"] is False and out["actors"] == {}


def test_safe_file_blocks_escape_and_big_files(tmp_path: Path):
    d = tmp_path / "ofis"
    d.mkdir()
    (d / "veri.png").write_bytes(PNG)
    (d / "dev.png").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    (tmp_path / "gizli.png").write_bytes(PNG)
    assert safe_file(tmp_path, "veri.png") is not None
    for bad in ["../gizli.png", "..%2Fgizli.png", "dev.png", "yok.png", "veri.exe", ".env"]:
        assert safe_file(tmp_path, bad) is None, bad


def test_api_and_static(fake_ollama, tmp_path: Path, monkeypatch):
    from kayaai.api import create_app

    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    (tmp_path / "data" / "ofis").mkdir(parents=True)
    (tmp_path / "data" / "ofis" / "veri.png").write_bytes(PNG)
    app = create_app(s, ui_dir=tmp_path / "noui")
    h = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as c:
        assert c.get("/api/office/assets").status_code == 401
        url = c.get("/api/office/assets", headers=h).json()["actors"]["data"]["base"]
        r = c.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == PNG
        assert "default-src 'none'" in r.headers["content-security-policy"]
        r = c.get("/ofis/../kayaai.db")  # istemci yolu /kayaai.db yapar → arayüz sayfası, veritabanı değil
        assert r.headers["content-type"].startswith("text/html") and b"SQLite" not in r.content
        assert c.get("/ofis/%2E%2E/kayaai.db").status_code == 404
        assert c.get("/ofis/yok.png").status_code == 404
