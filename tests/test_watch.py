"""Adım 18b: kayaai watch — olay → Türkçe satır, filtreler, canlı yazım seyreltme, CLI."""

from __future__ import annotations

import pytest

from kayaai import watch
from kayaai.core.store import TaskStore


def ev(type_, data, id_=1, ts="2026-11-01T10:00:00+00:00", task_id=None):
    return {"id": id_, "type": type_, "data": data, "ts": ts, "task_id": task_id}


@pytest.mark.parametrize("e,color,text", [
    (ev("task.status", {"worker": "data", "status": "running", "objective": "Satış tablosunu analiz et"}), "blue", "▶ Veri başladı: Satış tablosunu analiz et"),
    (ev("task.status", {"worker": "reviewer.check", "status": "succeeded", "model": "qwen3:8b", "parent_id": "j1"}), "green", "  ✓ Denetçi (kontrol) bitti · qwen3:8b"),
    (ev("task.status", {"worker": "coder", "status": "timed_out", "objective": "x"}), "red", "✗ Kod zaman aşımı: x"),
    (ev("approval.requested", {"risk": "R2", "summary": "rapor.xlsx yaz", "approval_id": "a1"}), "yellow", "🔔 Onay bekliyor [R2]: rapor.xlsx yaz  →  kayaai approvals approve a1"),
    (ev("approval.decided", {"approval_id": "a1", "status": "approved"}), "green", "✓ Onaylandı (a1)"),
    (ev("chat.message", {"role": "assistant", "status": "done"}), "cyan", "💬 Asistan cevabı hazır"),
    (ev("schedule.run", {"name": "Gece", "status": "succeeded", "seconds": 3.2}), "green", "⏰ Zamanlanmış görev bitti: Gece (3.2 sn)"),
    (ev("automation.paused", {}), "red", "⏸ Otomasyon duraklatıldı"),
])
def test_describe(e, color, text):
    assert watch.describe(e) == (color, text)


def test_progress_lines_only_readable_text():
    assert watch.describe(ev("task.progress", {"worker": "planner", "field": "id", "tail": "s1"})) is None
    assert watch.describe(ev("task.progress", {"worker": "reviewer.check", "field": "verdict", "tail": "a"})) is None
    assert watch.describe(ev("task.progress", {"worker": "data", "field": "answer", "tail": "Ankara önde"}))[1] == "    … Veri yazıyor: Ankara önde"


def test_quiet_events():
    assert watch.describe(ev("task.status", {"worker": "data", "status": "pending"})) is None
    assert watch.describe(ev("chat.message", {"role": "assistant", "status": "running"})) is None


def test_filters():
    assert watch.wanted("approval.requested", "approvals", False) and not watch.wanted("task.status", "approvals", False)
    assert watch.wanted("task.status", "jobs", False) and not watch.wanted("chat.message", "jobs", False)
    assert watch.wanted("integration.call", "all", False) and not watch.wanted("integration.call", "important", False)
    assert not watch.wanted("task.progress", "all", False) and watch.wanted("task.progress", "important", True)


def test_format_plain_and_color():
    e = ev("automation.resumed", {})
    assert watch.format_line(e, False).endswith("  ▶ Otomasyon sürdürüldü")
    colored = watch.format_line(e, True)
    assert "\033[32m▶ Otomasyon sürdürüldü\033[0m" in colored


def test_run_backlog_live_and_progress_throttle(tmp_path):
    store = TaskStore(tmp_path / "k.db")
    store.emit("automation.paused", {})
    store.emit("integration.call", {"name": "x"})  # önemli değil → gösterilmez
    lines: list[str] = []
    rounds = iter(range(3))

    def stop():
        n = next(rounds, None)
        if n == 0:
            store.emit("task.status", {"worker": "general", "status": "running", "objective": "Merhaba"}, task_id="t1")
            for i in range(5):
                store.emit("task.progress", {"worker": "general", "tail": f"parça {i}"}, task_id="t1")
        return n is None

    watch.run(store, lines.append, live=True, backlog=5, interval_s=0, stop=stop)
    texts = [ln.split("  ", 1)[1] for ln in lines]
    assert texts[0] == "⏸ Otomasyon duraklatıldı" and "integration.call" not in " ".join(texts)
    assert "▶ Genel başladı: Merhaba" in texts
    assert sum("yazıyor" in t for t in texts) == 1  # 2 sn seyreltme
    store.close()


def test_cli(fake_ollama, tmp_path, monkeypatch, capsys):
    from kayaai.cli import main

    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    (tmp_path / "data").mkdir()
    store = TaskStore(tmp_path / "data" / "kayaai.db")
    store.emit("claude.mode", {"enabled": True})
    store.close()

    def fake_run(store, out, **kw):
        assert kw["mode"] == "approvals" and kw["live"] is False and kw["color"] is False
        raise KeyboardInterrupt

    monkeypatch.setattr(watch, "run", fake_run)
    assert main(["watch", "--onay", "--renksiz"]) == 0
    out = capsys.readouterr().out
    assert "yalnız onaylar" in out and "İzleme bitti." in out
