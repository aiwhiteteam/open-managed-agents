import json
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    oma_api_key: str = ""
    oma_api_keys: Annotated[list[str], NoDecode] = []
    oma_require_beta_header: bool = True
    oma_require_anthropic_version_header: bool = True
    oma_runtime_backend: str = "openai"
    oma_default_model_provider: str = "openai"
    oma_default_openai_model: str = "gpt-5.5"
    oma_default_workspace_id: str = "wrkspc_default"
    oma_api_key_workspaces: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    oma_event_poll_interval_seconds: float = 0.5
    oma_max_file_upload_bytes: int = 50 * 1024 * 1024
    oma_max_skill_archive_bytes: int = 25 * 1024 * 1024
    oma_openai_compatible_providers: Annotated[dict[str, dict[str, Any]], NoDecode] = Field(default_factory=dict)
    oma_public_base_url: str = "https://example.invalid"
    oma_worker_token: str = ""
    oma_encryption_key: str = ""

    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = ""
    s3_public_url: str = ""
    s3_region: str = "auto"

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

    @field_validator("oma_api_key_workspaces", mode="before")
    @classmethod
    def parse_api_key_workspaces(cls, value):
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            return json.loads(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
