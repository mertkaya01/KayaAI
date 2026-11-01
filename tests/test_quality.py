"""Fine-tuning değerlendirmesi: `kayaai quality` — görev kayıtlarından ajan × model çıktı kalitesi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kayaai import quality
from kayaai.config import load_settings
from kayaai.core.task import Task, TaskStatus, ValidationResult
from kayaai.runtime import build_runtime


def row(worker="data", model="qwen3:8b", status="succeeded", attempts=1, vret=0, invalid=False, reason="stop", tps=100.0):
    t = {"worker": worker, "model": model, "status": status,
         "metrics": {"model": model, "output_attempts": attempts, "done_reason": reason, "tokens_per_second": tps}}
    if vret:
        t["metrics"]["validation_retries"] = vret
    if invalid:
        t["validation"] = {"passed": False, "validator": "schema", "errors": ["x"]}
    return t


def test_small_sample_is_not_judged():
    out = quality.report([row() for _ in range(5)])
    assert out["agents"][0]["verdict"] == "yetersiz veri" and out["summary"].startswith("Yetersiz veri")


def test_good_agent_needs_no_finetune():
    out = quality.report([row() for _ in range(40)] + [row(attempts=2) for _ in range(2)])
    a = out["agents"][0]
    assert a["first_try_rate"] == pytest.approx(40 / 42, abs=1e-3) and a["schema_failures"] == 2
    assert a["verdict"] == "gerek yok" and out["summary"].startswith("Fine-tuning gerekmiyor")


def test_weak_agent_is_candidate_and_infra_errors_do_not_count():
    rows = ([row(worker="planner") for _ in range(25)]
            + [row(worker="planner", attempts=3, vret=2) for _ in range(5)]                     # 2 doğrulama + 0 şema
            + [row(worker="planner", status="failed", attempts=3, invalid=True) for _ in range(3)]  # geçersiz
            + [row(worker="planner", status="failed") for _ in range(20)]                          # Ollama hatası
            + [row(worker="planner", status="cancelled") for _ in range(9)]                        # sayılmaz
            + [row(worker="planner", reason="length")])
    # 3 geçersiz × 3 şema hatası = 9; doğrulamada düşen son deneme ayrı sayılır:
    a = quality.report(rows)["agents"][0]
    assert a["tasks"] == 54 and a["judged"] == 34 and a["errors"] == 20
    assert a["first_try"] == 26 and a["invalid"] == 3 and a["validation_failures"] == 10 and a["schema_failures"] == 9
    assert a["truncated"] == 1 and a["verdict"] == "aday"
    v = row(status="failed", attempts=3, vret=2)
    v["validation"] = {"passed": False, "validator": "data", "errors": ["toplam tutmuyor"]}
    b = quality.report([v])["agents"][0]
    assert b["validation_failures"] == 3 and b["schema_failures"] == 0 and b["invalid"] == 1


def test_only_local_model_outputs_are_counted():
    parent = {"worker": "conductor", "model": None, "status": "succeeded", "metrics": {}}
    claude = row(worker="conductor", model="claude (Claude Code)")
    out = quality.report([parent, claude, row()])
    assert [(a["agent"], a["tasks"]) for a in out["agents"]] == [("data", 1)]


def test_groups_by_model():
    out = quality.report([row(model="a") for _ in range(3)] + [row(model="b")])
    assert [(a["model"], a["tasks"]) for a in out["agents"]] == [("a", 3), ("b", 1)]


def test_real_store_and_cli(fake_ollama, tmp_path: Path, monkeypatch, capsys):
    from kayaai.cli import main

    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    s = load_settings()
    with build_runtime(s) as rt:
        ok = Task(worker="general", objective="x", status=TaskStatus.SUCCEEDED, model="qwen3:8b",
                  metrics={"output_attempts": 1, "tokens_per_second": 120.0})
        bad = Task(worker="general", objective="y", status=TaskStatus.FAILED, model="qwen3:8b",
                   metrics={"output_attempts": 3},
                   validation=ValidationResult(passed=False, validator="schema", errors=["e"]))
        for t in (ok, bad, Task(worker="general", objective="z")):  # bekleyen sayılmaz
            rt.store.save(t)
    assert main(["quality"]) == 0
    out = capsys.readouterr().out
    assert "general" in out and "%50" in out and "Yetersiz veri" in out
    data = json.loads((tmp_path / "data" / "quality.json").read_text(encoding="utf-8"))
    assert data["agents"][0]["tasks"] == 2 and data["agents"][0]["invalid"] == 1
    assert main(["quality", "--days", "1"]) == 0
