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
        r = c.get("/ofis/%2E%2E/kayaai.db")  # resim değil → arayüz sayfası; veritabanı asla
        assert r.headers["content-type"].startswith("text/html") and b"SQLite" not in r.content
        assert c.get("/ofis/yok.png").status_code == 404
        assert c.get("/ofis/%2E%2E/gizli.png").status_code == 404
        # Adım 21: Ofis'te açık iş sayfası yenilenince (/ofis/<iş>) arayüz gelmeli, "Çizim bulunamadı" değil
        r = c.get("/ofis/6874db307781")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")


def test_png_sizes_and_walk_directions(tmp_path: Path):
    import struct
    import zlib

    def png(w: int, h: int) -> bytes:
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\0" * (w * 4 + 1) * h)) + chunk(b"IEND", b"")
    d = tmp_path / "ofis"
    d.mkdir()
    (d / "veri.png").write_bytes(png(128, 64))            # 2 kare masada
    (d / "veri-yuruyor-sol.png").write_bytes(png(256, 64))  # 4 kare sola yürüme
    (d / "kod-yuruyor.png").write_bytes(png(256, 64))
    (d / "veri-ziplıyor.png").write_bytes(png(64, 64))      # Türkçe karakter: geçersiz ad
    out = scan(tmp_path)
    veri = out["actors"]["data"]
    assert set(veri) == {"base", "walk_left"} and out["actors"]["coder"]["walking"]
    assert out["sizes"][veri["base"]] == [128, 64] and out["sizes"][veri["walk_left"]] == [256, 64]
    assert "veri-ziplıyor.png" in out["skipped"]


def test_photo_card_names(tmp_path: Path):
    d = tmp_path / "ofis"
    d.mkdir()
    (d / "sen-foto.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpg")
    (d / "sef-foto.png").write_bytes(PNG)
    out = scan(tmp_path)
    assert out["actors"]["owner"]["photo"].startswith("/ofis/sen-foto.jpg")
    assert out["actors"]["chef"]["photo"].startswith("/ofis/sef-foto.png")


def test_content_bounds_for_walk_sizes(tmp_path: Path):
    """Adım 21c: karenin dolu alanı (yarıdan fazla opak) — arayüz yürüyenleri her yönde aynı boya getirir."""
    from PIL import Image

    d = tmp_path / "ofis"
    d.mkdir()
    im = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
    im.paste((200, 50, 50, 255), (10, 5, 20, 40))     # 1. kare
    im.paste((50, 200, 50, 255), (94, 8, 104, 48))    # 2. kare (kare içi x 30–40)
    im.paste((0, 0, 0, 60), (0, 60, 64, 64))          # yarı saydam gölge: sayılmaz
    im.save(d / "veri-yuruyor-sag.png")
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(d / "veri-yuruyor-sol.png")  # bomboş: dolu alan yok
    (d / "veri.png").write_bytes(PNG)                  # PNG değil: çökmez, dolu alan yok
    out = scan(tmp_path)
    right = out["actors"]["data"]["walk_right"]
    assert out["bounds"][right] == [10, 5, 40, 48]
    assert out["actors"]["data"]["walk_left"] not in out["bounds"]
    assert out["actors"]["data"]["base"] not in out["bounds"]
