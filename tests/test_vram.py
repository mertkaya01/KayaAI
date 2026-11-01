"""Adım 13b: VRAM bekçisi — boş bellek yetmezse korunmayan, yüklü Ollama modellerini büyükten küçüğe boşaltır."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from kayaai.config import load_settings
from kayaai.llm import vram
from kayaai.runtime import build_runtime

from .conftest import good_answer
from .test_perception import VL, png


@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    s.ollama.max_retries = 0
    r = build_runtime(s)
    yield r
    r.close()
    vram.set_probe(None)


class GPU:
    """Sahte 16 GB kart: yüklü modellerin boyutu kadar dolu (+1 GB masaüstü)."""

    def __init__(self, fake, sizes):
        self.fake, self.sizes = fake, sizes

    def __call__(self):
        used = 1024 + sum(self.sizes.get(n, 0) for n in getattr(self.fake, "loaded", {}))
        return 16 * 1024 - used, 16 * 1024


def _load(fake, *names):
    fake.loaded = {n: "10m" for n in names}


def test_enough_vram_unloads_nothing(rt, fake_ollama):
    _load(fake_ollama, "qwen3:8b")
    vram.set_probe(GPU(fake_ollama, {"qwen3:8b": 6000}))
    rep = vram.ensure_vram(rt, 6.0, "görsel model")
    assert rep.ok and rep.unloaded == [] and rep.free_mb == 16 * 1024 - 7024


def test_unloads_largest_unkept_first_until_enough(rt, fake_ollama):
    fake_ollama.models += [dict(VL)]
    _load(fake_ollama, "qwen3:8b", "qwen2.5vl:7b", "bge-m3")
    sizes = {"qwen3:8b": 6000, "qwen2.5vl:7b": 5600, "bge-m3": 650}
    vram.set_probe(GPU(fake_ollama, sizes))
    fake_ollama.loaded_sizes = sizes
    rep = vram.ensure_vram(rt, 3.0, "canlı altyazı", keep={"qwen3:8b"})  # ≈3,1 GB boş < 3,0+0,6
    assert rep.ok and rep.unloaded == ["qwen2.5vl:7b"]  # genel model korundu, bir boşaltma yetti
    assert set(fake_ollama.loaded) == {"qwen3:8b", "bge-m3"}
    assert any(e["type"] == "model.unloaded" and "VRAM" in e["data"]["reason"] for e in rt.store.events_since(0))


def test_reports_when_still_not_enough(rt, fake_ollama):
    _load(fake_ollama, "qwen3:8b")
    vram.set_probe(lambda: (900, 16384))  # başka bir program GPU'yu dolduruyor
    rep = vram.ensure_vram(rt, 6.0, "görsel model", keep={"qwen3:8b"})
    assert not rep.ok and "yetersiz" in rep.warning and rep.unloaded == []


def test_no_nvidia_means_no_interference(rt, fake_ollama):
    _load(fake_ollama, "qwen3:8b")
    vram.set_probe(lambda: None)
    rep = vram.ensure_vram(rt, 99, "x")
    assert rep.ok and rep.unloaded == [] and fake_ollama.loaded == {"qwen3:8b": "10m"}


def test_vision_frees_vram_before_loading(rt, fake_ollama):
    from kayaai.perception import ocr
    from kayaai.perception.vision import see

    fake_ollama.models += [dict(VL)]
    _load(fake_ollama, "qwen3:8b", "bge-m3")
    vram.set_probe(GPU(fake_ollama, {"qwen3:8b": 9000, "bge-m3": 650}))  # 16 - 1 - 9 - 0,65 ≈ 5,3 GB boş < 6 GB
    ocr.set_engine(lambda b: ocr.OcrResult(text="Toplam: 1.680,00 TL", engine="fake"))
    try:
        fake_ollama.chat_replies = [good_answer("Toplam 1.680,00 TL.")]
        res = see(rt, [png()], "Toplam?")
    finally:
        ocr.set_engine(None)
    assert any("qwen3:8b" in w for w in res.warnings)
    assert "qwen3:8b" not in fake_ollama.loaded


def test_bench_measures_installed_models(fake_ollama, tmp_path, monkeypatch, capsys):
    from kayaai.cli import main

    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    fake_ollama.models += [dict(VL)]
    fake_ollama.chat_replies = [good_answer("Ben kayaAI, yerel asistanınım.")] * 3 + [good_answer("Genel toplam 1.680,00 TL.")] * 2
    vram.set_probe(lambda: (8000, 16384))
    try:
        assert main(["bench"]) == 0
    finally:
        vram.set_probe(None)
    out = capsys.readouterr().out
    import json as _json

    data = _json.loads((tmp_path / "data" / "bench.json").read_text(encoding="utf-8"))
    assert [r["run"] for r in data["chat"]["runs"]] == ["soğuk", "sıcak", "sıcak"] and all(r["ok"] for r in data["chat"]["runs"])
    assert data["embed"]["ms_per_text"] >= 0 and data["vision"]["runs"][0]["correct"] is True
    assert data["vram"]["peak_used_mb"] == 16384 - 8000 or data["vram"]["peak_used_mb"] is None
    assert "Sohbet (qwen3:8b)" in out and "Görsel (qwen2.5vl:7b)" in out
    from kayaai.config import load_settings as _ls
    from kayaai.core.store import TaskStore

    real = TaskStore(_ls().db_path)  # ölçüm görevleri asıl geçmişe yazılmadı (data/checks/bench)
    try:
        assert real.list_by_worker("general", 10) == []
    finally:
        real.close()
    assert (tmp_path / "data" / "checks" / "bench").is_dir()
