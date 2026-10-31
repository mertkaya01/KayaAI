"""scripts/memory_check.py sahte Ollama ile uçtan uca çalışır ve gerçek veriye dokunmaz."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kayaai.config import PROJECT_ROOT


def test_memory_check_script(fake_ollama, tmp_path: Path):
    env = dict(os.environ, KAYAAI_OLLAMA_URL=fake_ollama.url, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "scripts/memory_check.py"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((tmp_path / "memory_check.json").read_text(encoding="utf-8"))
    s = report["summary"]
    assert s["queries"] == 10 and "suggested" in s["memory_threshold"] and "suggested" in s["docs_threshold"]
    assert not (tmp_path / "kayaai.db").exists()  # ayrı klasörde çalıştı
    assert (tmp_path / "checks" / "memory" / "data" / "kayaai.db").exists()
