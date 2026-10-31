"""Yapılandırma yükleme: config/settings.yaml (+ settings.local.yaml) + ortam değişkenleri."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OllamaSettings(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    connect_timeout_s: float = 5
    request_timeout_s: float = 300
    max_retries: int = Field(2, ge=0, le=10)
    retry_backoff_s: float = Field(1.5, ge=0)

    @field_validator("base_url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_local(self) -> bool:
        return (urlparse(self.base_url).hostname or "") in LOCAL_HOSTS


class OrchestratorSettings(BaseModel):
    default_worker: str = "general"
    default_timeout_s: float = Field(240, gt=0)
    max_parallel: int = Field(1, ge=1, le=16)
    max_output_attempts: int = Field(3, ge=1, le=10)


class PermissionSettings(BaseModel):
    auto_approve: list[str] = Field(default_factory=lambda: ["llm.inference"])


class LoggingSettings(BaseModel):
    level: str = "INFO"
    file: str = "logs/kayaai.log"
    max_bytes: int = 5_000_000
    backup_count: int = 5


class Settings(BaseModel):
    app_name: str = "kayaAI"
    data_dir: Path = Path("data")
    config_dir: Path = PROJECT_ROOT / "config"
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    permissions: PermissionSettings = Field(default_factory=PermissionSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kayaai.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / self.logging.file

    @property
    def models_file(self) -> Path:
        return self.config_dir / "models.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} bir YAML sözlüğü olmalı")
    return data


def load_settings(config_dir: Path | None = None) -> Settings:
    """Ayarları yükler. Öncelik: ortam değişkeni > settings.local.yaml > settings.yaml > varsayılan."""
    config_dir = Path(os.environ.get("KAYAAI_CONFIG_DIR", config_dir or PROJECT_ROOT / "config"))
    raw = _deep_merge(_read_yaml(config_dir / "settings.yaml"), _read_yaml(config_dir / "settings.local.yaml"))

    if url := os.environ.get("KAYAAI_OLLAMA_URL"):
        raw.setdefault("ollama", {})["base_url"] = url
    if data_dir := os.environ.get("KAYAAI_DATA_DIR"):
        raw["data_dir"] = data_dir
    if level := os.environ.get("KAYAAI_LOG_LEVEL"):
        raw.setdefault("logging", {})["level"] = level

    raw["config_dir"] = config_dir
    settings = Settings.model_validate(raw)
    if not settings.data_dir.is_absolute():
        settings.data_dir = (PROJECT_ROOT / settings.data_dir).resolve()
    return settings
