"""Windows scriptleri için yapısal kontroller (PowerShell burada çalıştırılamıyor)."""

from pathlib import Path

from kayaai.config import PROJECT_ROOT

PS1_FILES = sorted((PROJECT_ROOT / "scripts").rglob("*.ps1"))


def test_ps1_files_exist():
    names = {p.name for p in PS1_FILES}
    assert {"audit_windows.ps1", "setup.ps1", "smoke.ps1", "run.ps1"} <= names


def test_ps1_files_have_utf8_bom():
    # Windows PowerShell 5.1, BOM'suz UTF-8 dosyalarını ANSI sanar ve Türkçe karakterleri bozar.
    for p in PS1_FILES:
        assert p.read_bytes().startswith(b"\xef\xbb\xbf"), f"{p} UTF-8 BOM ile kaydedilmeli"


def test_ps1_balanced_braces():
    for p in PS1_FILES:
        text = p.read_text(encoding="utf-8-sig")
        assert text.count("{") == text.count("}"), f"{p}: süslü parantez dengesiz"
        assert text.count("(") == text.count(")"), f"{p}: parantez dengesiz"


def test_audit_module_is_stdlib_only():
    """audit.py bağımlılık kurulmadan çalışabilmeli."""
    src = (PROJECT_ROOT / "kayaai" / "system" / "audit.py").read_text(encoding="utf-8")
    for dep in ("httpx", "pydantic", "yaml"):
        assert f"import {dep}" not in src


def test_package_init_has_no_third_party_imports():
    src = (Path(PROJECT_ROOT) / "kayaai" / "__init__.py").read_text(encoding="utf-8")
    assert "import httpx" not in src and "import pydantic" not in src
