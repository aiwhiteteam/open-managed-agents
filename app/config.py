import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="",
    )

    database_url: str = "sqlite+aiosqlite:///./open_managed_agents.db"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_use_responses: bool = True

    oma_api_keys: list[str] = []
    oma_require_beta_header: bool = True
    oma_require_anthropic_version_header: bool = True
    oma_runtime_backend: str = "auto"
    oma_default_model_provider: str = "openai"
    oma_default_openai_model: str = "gpt-5.5"
    oma_event_poll_interval_seconds: float = 0.5
    oma_storage_backend: str = "database"
    oma_openai_compatible_providers: dict[str, dict[str, Any]] = Field(default_factory=dict)

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-v4-pro"

    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_default_model: str = "MiniMax-M3"

    supabase_url: str = ""
    supabase_service_key: str = ""

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_files_bucket_name: str = ""
    r2_files_url: str = ""

    app_env: str = "local"
    sentry_dsn: str = ""
    log_level: str = "INFO"

    @field_validator("oma_api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("oma_openai_compatible_providers", mode="before")
    @classmethod
    def parse_openai_compatible_providers(cls, value):
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            return json.loads(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
