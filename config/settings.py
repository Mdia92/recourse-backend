"""Typed application settings loaded from environment variables and YAML."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent
ENVIRONMENTS_DIR = CONFIG_DIR / "environments"


class Settings(BaseSettings):
    """Runtime configuration for the Recourse backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Recourse"
    environment: str = Field(default="development", alias="APP_ENV")
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # UiPath Maestro
    uipath_tenant_url: str = ""
    uipath_client_id: str = ""
    uipath_client_secret: str = ""
    uipath_webhook_secret: str = ""

    # LLM / agent providers
    openai_api_key: str = ""

    def load_environment_overrides(self) -> dict:
        """Load YAML overrides for the active environment."""
        config_path = ENVIRONMENTS_DIR / f"{self.environment}.yaml"
        if not config_path.exists():
            return {}
        with config_path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    settings = Settings()
    overrides = settings.load_environment_overrides()
    if overrides:
        settings = settings.model_copy(update=overrides)
    return settings
