"""scripts/business_check.py sahte Ollama ile uçtan uca çalışır, raporları üretir, gerçek veriye dokunmaz."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kayaai.config import PROJECT_ROOT

from .conftest import good_answer


def test_business_check_script(fake_ollama, tmp_path: Path):
    plan = json.dumps({"operations": [{"title": "Bölgeler", "group_by": ["Bölge"], "metrics": [{"agg": "sum", "column": "Tutar (TL)"}]}]})
    inv = json.dumps({"seller": "Kaya", "subtotal": 1400, "vat": 280, "vat_rate": 20, "total": 1680, "date": "2026-01-15",
                      "lines": [{"description": "A4 Defter", "quantity": 10, "unit_price": 25, "amount": 250},
                                {"description": "Kalem", "quantity": 50, "unit_price": 5, "amount": 250},
                                {"description": "Çanta", "quantity": 2, "unit_price": 450, "amount": 900}]})

    def reply(body):
        title = (body.get("format") or {}).get("title")
        if title == "AnalysisPlan":
            return plan
        if title == "Invoice":
            return inv
        return good_answer("Bütçe 1,2 milyon TL, yüzde 35 harcandı; PostgreSQL'e geçildi [s.1] [s.2].")

    fake_ollama.chat_replies = [reply] * 300
    env = dict(os.environ, KAYAAI_OLLAMA_URL=fake_ollama.url, KAYAAI_DATA_DIR=str(tmp_path), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "scripts/business_check.py"], env=env, cwd=str(PROJECT_ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    rep = json.loads((tmp_path / "business_check.json").read_text(encoding="utf-8"))
    assert rep["summary"]["invoice_ok"] and rep["summary"]["pdf_summary_ok"] and rep["summary"]["reports"] == 4
    assert rep["analysis"][0]["expected_found"]
    assert len(list((tmp_path / "checks" / "business" / "raporlar").iterdir())) == 4
    assert not (tmp_path / "kayaai.db").exists()
