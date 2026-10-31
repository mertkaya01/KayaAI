"""scripts/conductor_check.py: Claude modu AÇIKKEN de tüm işler yerelde ölçülmeli (Windows'ta yakalandı)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kayaai.config import PROJECT_ROOT, load_settings
from kayaai.core.claude_mode import ClaudeMode
from kayaai.core.store import TaskStore

from .conductor_helpers import answer, plan_direct, plan_steps, review


def test_conductor_check_with_claude_mode_on(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 1})
    settings = load_settings()
    store = TaskStore(settings.db_path)
    ClaudeMode(store, settings.claude).enable()  # kullanıcının durumu: Claude modu açık kalmış
    store.close()

    def reply(body):
        title = (body.get("format") or {}).get("title")
        q = body["messages"][-1]["content"]
        if title == "RoutePlan":
            if "CSV" in q:
                return plan_steps([("s1", "coder", "Kodu yaz", []), ("s2", "general", "Açıkla", ["s1"])])
            if "SaaS" in q:
                return plan_steps([(f"s{i}", "general", f"Bölüm {i}", []) for i in range(1, 5)])
            return plan_direct("coder" if ("fonksiyon" in q or "function" in q) else "general")
        if title == "ReviewResult":
            return review("ok")
        en = q.startswith(("Explain", "Write"))
        return answer("This is a sufficiently long English answer." if en else "Bu yeterince uzun bir Türkçe cevaptır.",
                      language="en" if en else "tr")

    fake_ollama.chat_replies = [reply] * 300
    env = dict(os.environ, KAYAAI_OLLAMA_URL=fake_ollama.url, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "scripts/conductor_check.py"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((tmp_path / "conductor_check.json").read_text(encoding="utf-8"))
    assert report["summary"]["success_rate"] == "6/6"
    assert all(row["status"] == "succeeded" for row in report["rows"])
    saas = [row for row in report["rows"] if "SaaS" in row["request"]][0]
    assert saas["needs_claude"] and saas["routing"] == "local_with_warning"
    assert "uncovered_topics_total" in report["summary"]
