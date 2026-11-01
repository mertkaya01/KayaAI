"""Adım 14b: izinli klasörde bile gizli bilgi / çalıştırılabilir dosyalara ve hassas klasörlere yazılmaz."""

from __future__ import annotations

from pathlib import Path

import pytest

from kayaai.config import load_settings
from kayaai.runtime import build_runtime
from kayaai.tools.files import PathNotAllowed


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    r = build_runtime(load_settings())
    yield r
    r.close()


@pytest.mark.parametrize("name", [".env", ".env.local", "server.key", "cert.pem", "id_rsa", "id_ed25519.pub",
                                  "my_secrets.txt", "Passwords.md", "aws_credentials.json", "kasa.kdbx", "setup.exe",
                                  "evil.DLL", "kisayol.lnk", "desktop.ini", ".ssh/config", "proje/.git/config",
                                  "secrets/notlar.md"])
def test_denied_names_and_dirs(rt, name):
    with pytest.raises(PathNotAllowed):
        rt.files.write(name, "x")
    with pytest.raises(PathNotAllowed):
        rt.files.write_bytes(name, b"x")
    assert rt.permissions.list_approvals("all") == []


@pytest.mark.parametrize("name", ["notlar.md", "rapor.pdf", "script.ps1", "kod/app.py", "anahtar_kelimeler.txt"])
def test_normal_files_still_allowed(rt, name):
    assert rt.files.write(name, "merhaba").status == "done"


def test_old_approval_cannot_write_denied_file(rt):
    """Kural eklenmeden önce oluşmuş bir onay talebi bile yürütmede reddedilir (savunma derinliği)."""
    home = Path(rt.settings.files.home_dir)
    home.mkdir(parents=True, exist_ok=True)
    target = home / "token.txt"
    target.write_text("eski", encoding="utf-8")
    res = rt.files.write("token.txt", "yeni")  # var olan dosya → R2 onay
    assert res.status == "awaiting_approval"
    rt.settings.files.deny_write.append("token.txt")
    a = rt.permissions.approve(res.approval_id, decided_by="owner")
    assert a.status == "failed" and "yazılmaz" in a.error and target.read_text(encoding="utf-8") == "eski"
