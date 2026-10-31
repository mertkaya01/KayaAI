"""Windows scriptleri için yapısal kontroller (PowerShell burada çalıştırılamıyor)."""

from pathlib import Path

from kayaai.config import PROJECT_ROOT

PS1_FILES = sorted((PROJECT_ROOT / "scripts").rglob("*.ps1"))


def test_ps1_files_exist():
    names = {p.name for p in PS1_FILES}
    assert {"audit_windows.ps1", "setup.ps1", "smoke.ps1", "run.ps1", "mcp_setup.ps1"} <= names


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


def test_parse_cuda_version_formats():
    from kayaai.system.audit import parse_cuda_version

    header = "| NVIDIA-SMI 621.01      Driver Version: 621.01       CUDA Version: 13.2     |"
    assert parse_cuda_version(header) == "13.2"
    assert parse_cuda_version("    CUDA Version                          : 12.8") == "12.8"
    assert parse_cuda_version("Driver Version: 621.01   CUDA Driver Version: 13.1") == "13.1"
    assert parse_cuda_version("CUDA Version: N/A") is None
    assert parse_cuda_version("") is None


def test_gpu_info_reports_reason_when_nvidia_smi_cannot_run(monkeypatch):
    from kayaai.system import audit

    monkeypatch.setattr(audit, "_run", lambda cmd, timeout=15: (-2, "OSError: [WinError 6] The handle is invalid"))
    info = audit.gpu_info()
    assert info["gpus"] == []
    assert any("çalıştırılamadı" in n and "WinError 6" in n for n in info["notes"])


def test_gpu_info_reports_unparseable_output(monkeypatch):
    from kayaai.system import audit

    monkeypatch.setattr(audit, "_run", lambda cmd, timeout=15: (0, "garbage"))
    info = audit.gpu_info()
    assert info["gpus"] == [] and any("okunamadı" in n for n in info["notes"])


def test_gpu_info_parses_real_query_line(monkeypatch):
    from kayaai.system import audit

    line = "NVIDIA GeForce RTX 5070 Ti, 621.01, 16303, 7765, 8231, 12.0, 10"
    header = "| NVIDIA-SMI 621.01   Driver Version: 621.01   CUDA Version: 13.5 |"
    monkeypatch.setattr(audit, "_run", lambda cmd, timeout=15: (0, header if len(cmd) == 1 else line))
    info = audit.gpu_info()
    assert info["gpus"][0]["memory.total_mb"] == 16303
    assert info["cuda_driver_version"] == "13.5"
