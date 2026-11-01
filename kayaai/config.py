"""Yapılandırma yükleme: config/settings.yaml (+ settings.local.yaml) + ortam değişkenleri."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

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


class ClaudeSettings(BaseModel):
    """Claude modu (MASTER_PROMPT v2 D2): isteğe bağlı takviye; kayaAI onsuz tam çalışır."""

    # Varsayılan değer. Çalışma anındaki aç/kapa durumu SQLite'ta saklanır ve bunu ezer
    # (`kayaai claude on|off`), böylece arayüzden değiştirilebilir.
    enabled: bool = False
    # Claude Code'un MCP sunucusunu en son kullanmasından bu kadar dakika geçtiyse "yakın temas" sayılır.
    contact_window_min: int = Field(15, ge=1, le=24 * 60)
    # Şef (Opus) Claude Code oturumunun açılacağı klasör; boşsa ~/kayaAI-workspace. Repo'nun içinde olamaz.
    workspace_dir: str | None = None


class ConductorSettings(BaseModel):
    """Yerel şef (`kayaai do`)."""

    max_steps: int = Field(4, ge=1, le=8)
    # Gözden geçirme: never | plan (yalnızca çok adımlı işlerde) | always
    review: Literal["never", "plan", "always"] = "plan"
    max_revisions: int = Field(1, ge=0, le=3)
    # Çok adımlı işte nihai cevap: assemble = adım cevaplarını başlıklarla sırayla birleştir (LLM'siz, bilgi kaybı yok);
    # llm = genel ajan yeniden yazar (8B modelde bilgi kaybı gözlendi, 2026-10-31).
    merge: Literal["assemble", "llm"] = "assemble"
    # Karmaşıklık skoru bu eşiğe ulaşırsa planlayıcı demese de "Claude önerilir" (kayaai/conductor/complexity.py).
    claude_threshold: int = Field(3, ge=1, le=10)
    # Adım 7: üretici ↔ gözden geçirici anlaşmazlığı. claude_first: Claude modu açıksa iş Claude kutusuna,
    # kapalıysa sahibe; owner: her zaman sahibe.
    disputes: Literal["claude_first", "owner"] = "claude_first"
    # Bir işin toplam zaman bütçesi (sn). Aşılırsa gözden geçirme/revizyon turları atlanır (yerel GPU zamanı korunur).
    time_budget_s: float = Field(600, ge=30, le=3600)
    # Adım 7c: yerel planlayıcı uygun ajan yoksa bir geçici ajan önerebilir (Claude şef her zaman MCP ile önerebilir)
    allow_temp_agents: bool = True
    max_temp_agents: int = Field(5, ge=0, le=20)


class AllowedDir(BaseModel):
    path: str
    access: Literal["read", "read_write"] = "read"


class FilesSettings(BaseModel):
    """Dosya araçlarının erişebileceği klasörler (Adım 5; sahip kararı: kayaAI klasörü + seçilen klasörler)."""

    # kayaAI'nin kendi klasörü (okuma + yazma). Boşsa ~/kayaAI-files.
    home_dir: str | None = None
    # Ek klasörler; listede olmayan hiçbir yere erişilmez.
    allowed_dirs: list[AllowedDir] = Field(default_factory=list)
    max_read_mb: float = Field(2.0, gt=0, le=50)
    max_write_mb: float = Field(5.0, gt=0, le=50)
    # Adım 14b — izinli klasörde bile YAZILMAYAN dosya adları (gizli bilgi taşıyabilir / çalıştırılabilir) ve klasörler.
    deny_write: list[str] = Field(default_factory=lambda: [
        ".env", ".env.*", "*.key", "*.pem", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*", "*secret*", "*password*",
        "*credential*", "*.kdbx", "*.exe", "*.dll", "*.msi", "*.scr", "*.com", "*.lnk", "*.sys", "desktop.ini"])
    deny_write_dirs: list[str] = Field(default_factory=lambda: [
        ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".git", "secrets", "credentials"])


class MemorySettings(BaseModel):
    """Adım 9 — hafıza ve belge araması (sahip kararı: SQLite + bge-m3, tamamen yerel)."""

    enabled: bool = True
    embed_model: str = "embed-m3"            # config/models.yaml anahtarı
    # Sohbette ilgili hafıza ve belge parçaları otomatik bağlama eklensin mi
    recall_in_chat: bool = True
    top_memories: int = Field(5, ge=0, le=20)
    top_chunks: int = Field(4, ge=0, le=20)
    # Kosinüs benzerliği eşikleri (bge-m3); altındaki sonuçlar "ilgisiz" sayılır. Windows ölçümü (memory_check,
    # 2026-10-31): hafıza ilgili 0.655–0.831 / ilgisiz ≤0.541; belge ilgili 0.553–0.679 / ilgisiz ≤0.389.
    min_score_memory: float = Field(0.60, ge=0, le=1)
    min_score_docs: float = Field(0.50, ge=0, le=1)
    chunk_chars: int = Field(900, ge=200, le=4000)
    chunk_overlap: int = Field(120, ge=0, le=1000)
    max_file_mb: float = Field(2.0, gt=0, le=50)
    max_files: int = Field(5000, ge=1, le=100_000)
    # Dizinlenmeyen klasör ve dosya adları (gizli bilgi taşıyabilecek dosyalar dahil)
    skip_dirs: list[str] = Field(default_factory=lambda: [
        ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".idea", ".vscode"])
    skip_files: list[str] = Field(default_factory=lambda: [
        ".env", ".env.*", "*.key", "*.pem", "id_rsa*", "*secret*", "*password*", "*credential*", "*.kdbx"])


    @model_validator(mode="before")
    @classmethod
    def _legacy_min_score(cls, data: Any) -> Any:
        # v0.9.0'daki tek `min_score` ayarı (settings.local.yaml'da kalmış olabilir) iki eşiğe uygulanır
        if isinstance(data, dict) and "min_score" in data:
            data = dict(data)
            legacy = data.pop("min_score")
            data.setdefault("min_score_memory", legacy)
            data.setdefault("min_score_docs", legacy)
        return data


class SpeechSettings(BaseModel):
    """Adım 12b — ses tanıma (sahip kararı: faster-whisper large-v3-turbo, GPU; olmazsa işlemci). Tamamen yerel."""

    model: str = "large-v3-turbo"            # faster-whisper model adı (indirme: data/models/whisper, sahip onayıyla)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    language: Literal["auto", "tr", "en"] = "auto"
    max_seconds: int = Field(120, ge=5, le=600)        # bas-konuş kaydı üst sınırı
    idle_unload_s: int = Field(600, ge=30, le=86_400)  # bu kadar kullanılmazsa model bellekten çıkar
    beam_size: int = Field(5, ge=1, le=10)


class BrowserSettings(BaseModel):
    """Adım 12d — tarayıcı otomasyonu (sahip kararı: kurulu Edge, ayrı boş profil)."""

    channel: str | None = "msedge"           # Playwright kanalı (msedge: kurulu Edge, indirme yok)
    executable_path: str | None = None       # verilirse kanal yerine bu tarayıcı (testler)
    headless: bool = False                   # görünür pencere: ne yaptığını görürsün
    profile_dir: str = "browser_profile"     # data/ altında; senin Edge profilin DEĞİL (çerez/şifre yok)
    max_steps: int = Field(20, ge=1, le=60)
    step_timeout_s: int = Field(30, ge=5, le=180)
    approval_timeout_s: int = Field(600, ge=30, le=3600)
    allow_local: bool = False                # yerel ağ / bu bilgisayar adresleri (yalnız testler)


class ApprovalSettings(BaseModel):
    # Bu süreden uzun bekleyen onay talebi geçersiz sayılır (expired).
    expire_hours: int = Field(24, ge=1, le=24 * 30)


class ApiSettings(BaseModel):
    """Yerel API sunucusu (Adım 4). Yalnızca bu bilgisayardan erişilir."""

    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1024, le=65535)


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
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    conductor: ConductorSettings = Field(default_factory=ConductorSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    files: FilesSettings = Field(default_factory=FilesSettings)
    approvals: ApprovalSettings = Field(default_factory=ApprovalSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
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
    if files_dir := os.environ.get("KAYAAI_FILES_DIR"):
        raw.setdefault("files", {})["home_dir"] = files_dir
    if level := os.environ.get("KAYAAI_LOG_LEVEL"):
        raw.setdefault("logging", {})["level"] = level

    raw["config_dir"] = config_dir
    settings = Settings.model_validate(raw)
    if not settings.data_dir.is_absolute():
        settings.data_dir = (PROJECT_ROOT / settings.data_dir).resolve()
    return settings
