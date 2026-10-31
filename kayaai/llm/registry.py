"""Model kayıt defteri: config/models.yaml -> worker başına model seçimi.

Model değiştirmek kod değişikliği gerektirmez; sadece YAML güncellenir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ModelSpec(BaseModel):
    key: str
    name: str
    purpose: str = ""
    context_length: int | None = Field(None, gt=0)
    think: bool | None = None
    keep_alive: str | int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    approx_vram_gb: float | None = None
    license: str | None = None
    # active: bir worker'a atanabilir; candidate: kurulu/aday, benchmark bekliyor
    status: Literal["active", "candidate"] = "active"

    def ollama_options(self) -> dict[str, Any]:
        opts = dict(self.options)
        if self.context_length and "num_ctx" not in opts:
            opts["num_ctx"] = self.context_length
        return opts


def local_registry_path(settings: Any) -> Path:
    """Adım 11: sonradan indirilen (aday) ve karşılaştırmayla aktif yapılan modeller — repo dosyası değişmez."""
    return Path(settings.data_dir) / "models.local.yaml"


class RegistryFile(BaseModel):
    models: dict[str, dict[str, Any]]
    workers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_refs(self) -> "RegistryFile":
        missing = {w: m for w, m in self.workers.items() if m not in self.models}
        if missing:
            raise ValueError(f"workers bölümü tanımsız modellere işaret ediyor: {missing}")
        candidates = {w: m for w, m in self.workers.items() if self.models[m].get("status") == "candidate"}
        if candidates:
            raise ValueError(f"'candidate' modeller worker'a atanamaz (önce benchmark): {candidates}")
        return self


class ModelRegistry:
    def __init__(self, models: dict[str, ModelSpec], workers: dict[str, str]):
        self._models = models
        self._workers = workers

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelRegistry":
        parsed = RegistryFile.model_validate(data)
        models = {k: ModelSpec(key=k, **v) for k, v in parsed.models.items()}
        return cls(models, dict(parsed.workers))

    @classmethod
    def load(cls, path: Path, local: Path | None = None) -> "ModelRegistry":
        """`config/models.yaml` (+ isteğe bağlı yerel katman: sonradan indirilen/aktif yapılan modeller, git dışı)."""
        if not path.exists():
            raise FileNotFoundError(f"Model kayıt dosyası yok: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if local is not None and local.is_file():
            extra = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
            models = dict(data.get("models") or {})
            for key, spec in (extra.get("models") or {}).items():
                models[key] = {**models.get(key, {}), **(spec or {})}
            data = {**data, "models": models}
        return cls.from_dict(data)

    @classmethod
    def load_for(cls, settings: Any) -> "ModelRegistry":  # settings: kayaai.config.Settings
        return cls.load(settings.models_file, local_registry_path(settings))

    def key_for_name(self, name: str) -> str | None:
        """Ollama adından kayıt anahtarı ('qwen3' ≡ 'qwen3:latest')."""
        for k, s in self._models.items():
            if s.name == name or f"{s.name}:latest" == name or s.name == f"{name}:latest":
                return k
        return None

    @property
    def models(self) -> dict[str, ModelSpec]:
        return dict(self._models)

    @property
    def worker_assignments(self) -> dict[str, str]:
        return dict(self._workers)

    def get(self, key: str) -> ModelSpec:
        try:
            return self._models[key]
        except KeyError:
            raise KeyError(f"Model kayıtlı değil: {key}") from None

    def model_for_worker(self, worker: str) -> ModelSpec:
        key = self._workers.get(worker)
        if key is None:
            raise KeyError(f"'{worker}' worker'ı için config/models.yaml içinde model ataması yok")
        return self._models[key]
