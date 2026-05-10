"""Configuración centralizada via pydantic-settings.

Lee desde .env (gitignored) + variables de entorno. Validación at-startup —
si falta una key crítica falla rápido en lugar de morir a mitad del batch.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Settings global. Una sola instancia compartida — usar `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="CI_",
        extra="ignore",
    )

    # ---- Paths ----
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path = PROJECT_ROOT / "data" / "crypto.db"
    backups_dir: Path = PROJECT_ROOT / "data" / "backups"
    logs_dir: Path = PROJECT_ROOT / "data" / "logs"
    migrations_dir: Path = PROJECT_ROOT / "migrations"
    watchlist_path: Path = PROJECT_ROOT / "data" / "watchlist.yaml"
    watchlist_fallback: Path = PROJECT_ROOT / "data" / "watchlist.example.yaml"

    # ---- API keys (todas opcionales en Fase 0) ----
    coingecko_api_key: str | None = Field(default=None, alias="CI_COINGECKO_API_KEY")
    etherscan_api_key: str | None = Field(default=None, alias="CI_ETHERSCAN_API_KEY")
    github_token: str | None = Field(default=None, alias="CI_GITHUB_TOKEN")
    helius_api_key: str | None = Field(default=None, alias="CI_HELIUS_API_KEY")
    alchemy_api_key: str | None = Field(default=None, alias="CI_ALCHEMY_API_KEY")
    moralis_api_key: str | None = Field(default=None, alias="CI_MORALIS_API_KEY")

    # ---- Batch behavior ----
    batch_timeout_seconds: int = 1800  # 30 min global
    orphan_batch_threshold_hours: int = 2
    heartbeat_interval_seconds: int = 30

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: str = "json"  # json|console

    @property
    def db_url(self) -> str:
        """SQLAlchemy URL para SQLite."""
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        """Crea directorios necesarios (idempotente)."""
        for d in (self.data_dir, self.backups_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton de settings. Lazy: no carga .env hasta primer uso."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
