"""Bilinen iyi sürümler (constraints/windows.txt) pyproject aralıklarıyla çelişmemeli (v0.14.3: winrt '<5' sınırı
'4!10.0.x' sürüm çağlı paketleri dışlıyordu — temiz kurulum bozulurdu)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints" / "windows.txt"


def _pins() -> dict[str, Version]:
    raw = CONSTRAINTS.read_bytes()
    assert not raw.startswith((b"\xff\xfe", b"\xfe\xff")), "UTF-16 değil UTF-8 olmalı (scripts/windows/freeze.ps1)"
    out = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, ver = line.partition("==")
        assert ver, f"yalnız 'paket==sürüm' satırları: {line!r}"
        out[canonicalize_name(name)] = Version(ver)
    return out


@pytest.mark.skipif(not CONSTRAINTS.is_file(), reason="constraints/windows.txt yok")
def test_constraints_satisfy_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps = project["dependencies"] + project["optional-dependencies"]["dev"]
    pins = _pins()
    bad = []
    for d in deps:
        r = Requirement(d)
        v = pins.get(canonicalize_name(r.name))
        if v is None:
            bad.append(f"{r.name}: listede yok")
        elif not r.specifier.contains(v, prereleases=True):
            bad.append(f"{r.name}=={v} ↔ {r.specifier}")
    assert not bad, bad
    assert "kayaai" not in pins


def test_epoch_bound_note():
    assert not Requirement("x<5").specifier.contains(Version("4!10.0.28000.2957"))
    assert Requirement("x<5!0").specifier.contains(Version("4!10.0.28000.2957"))
