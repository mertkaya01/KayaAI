"""scripts/agents_check.py: gerçek modelsiz (sahte Ollama) uçtan uca çalışır, rapor yazar, gerçek geçmişe dokunmaz."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kayaai.config import PROJECT_ROOT
from kayaai.core.store import TaskStore

from .conductor_helpers import APPROVE, answer, plan_direct, revision, step_review

CODE = "Fonksiyon şöyle:\n\n```python\ndef f(x:\n    return x\n```"
FIXED = "Fonksiyon şöyle:\n\n```python\ndef f(x):\n    return x\n```"


def test_agents_check_script(fake_ollama, tmp_path: Path):
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 1})

    def reply(body):
        title = (body.get("format") or {}).get("title")
        q = body["messages"][-1]["content"]
        en = q.startswith(("Write", "Compute"))
        if title == "RoutePlan":
            agent = "coder" if ("fonksiyon" in q or "function" in q) else (
                "data" if ("hesapla" in q.lower() or "Compute" in q) else "document")
            return plan_direct(agent)
        if title == "StepReview":
            return APPROVE if "Fonksiyon şöyle" not in q else step_review()
        if title == "Revision":
            return revision(FIXED, accepted=["c1"])
        if title == "GeneralAnswer":
            if "çift" in q:
                return answer(CODE)
            if "toplamını" in q:
                return answer("Toplam: 120 + 80 + 100 = 300. Ortalama: 300 / 3 = 100.")
            if "expenses" in q:
                return answer("Total: 40 + 60 + 50 + 90 = 240. Average: 240 / 4 = 60.", language="en")
            if en:
                return answer("Here is a palindrome checker with an example.", language="en")
            return answer("Sayın ilgili, toplantımız gelecek haftaya ertelenmiştir. Bilginize sunarız.")
        return "{}"

    fake_ollama.chat_replies = [reply] * 300
    env = dict(os.environ, KAYAAI_OLLAMA_URL=fake_ollama.url, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "scripts/agents_check.py"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((tmp_path / "agents_check.json").read_text(encoding="utf-8"))
    s = report["summary"]
    assert s["cases"] == s["succeeded"] == s["agent_ok"] == s["reviewed"] == s["values_ok"] == 6
    assert s["revised"] == 1
    even = report["rows"][0]
    assert even["code_check_failures"] and even["revised"] and even["final_answer_syntax_ok"]
    # ölçüm ayrı veritabanında: ana veritabanı oluşmadı / boş
    assert not (tmp_path / "kayaai.db").exists() or TaskStore(tmp_path / "kayaai.db").list_tasks() == []
    assert (tmp_path / "checks" / "agents" / "kayaai.db").exists()
