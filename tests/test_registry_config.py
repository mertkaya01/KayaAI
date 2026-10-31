from pathlib import Path

import pytest

from kayaai.config import PROJECT_ROOT, load_settings
from kayaai.llm.registry import ModelRegistry


def test_project_models_yaml_is_valid():
    reg = ModelRegistry.load(PROJECT_ROOT / "config" / "models.yaml")
    spec = reg.model_for_worker("general")
    assert spec.name
    assert spec.ollama_options()["num_ctx"] == spec.context_length


def test_worker_pointing_to_unknown_model_rejected():
    with pytest.raises(ValueError, match="tanımsız"):
        ModelRegistry.from_dict({"models": {"a": {"name": "x"}}, "workers": {"general": "b"}})


def test_unknown_worker_lookup(registry):
    with pytest.raises(KeyError):
        registry.model_for_worker("vision")


def test_settings_local_override_and_env(tmp_path: Path, monkeypatch):
    (tmp_path / "settings.yaml").write_text("ollama:\n  base_url: http://127.0.0.1:1111\n  max_retries: 4\n", encoding="utf-8")
    (tmp_path / "settings.local.yaml").write_text("ollama:\n  max_retries: 1\n", encoding="utf-8")
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "d"))
    s = load_settings(tmp_path)
    assert s.ollama.base_url == "http://127.0.0.1:1111"
    assert s.ollama.max_retries == 1
    assert s.data_dir == tmp_path / "d"
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", "http://localhost:2222/")
    assert load_settings(tmp_path).ollama.base_url == "http://localhost:2222"


def test_project_settings_load(monkeypatch, tmp_path):
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path))
    s = load_settings()
    assert s.ollama.is_local, "varsayılan Ollama adresi localhost olmalı"
    assert "llm.inference" in s.permissions.auto_approve
