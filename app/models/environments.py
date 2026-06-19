from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.db.models import Environment
from app.models.common import ApiModel


class EnvironmentCreateRequest(ApiModel):
    name: str
    config: dict[str, Any] = Field(default_factory=lambda: {"type": "cloud"})
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self):
        validate_environment_config(self.config)
        return self


class EnvironmentUpdateRequest(ApiModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_config(self):
        if self.config is not None:
            validate_environment_config(self.config)
        return self


class EnvironmentResponse(ApiModel):
    id: str
    type: str = "environment"
    name: str
    config: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def validate_environment_config(config: dict[str, Any]) -> None:
    env_type = config.get("type", "cloud")
    if env_type not in {"cloud", "self_hosted", "local"}:
        raise ValueError("environment config.type must be cloud, self_hosted, or local")
    networking = config.get("networking")
    if networking is not None:
        network_type = networking.get("type")
        if network_type not in {"unrestricted", "restricted", "none", None}:
            raise ValueError("environment config.networking.type is unsupported")
    sandbox = config.get("sandbox")
    if sandbox is not None:
        if not isinstance(sandbox, dict):
            raise ValueError("environment config.sandbox must be an object")
        backend = sandbox.get("backend")
        if backend not in {None, "unix_local", "self_hosted_worker", "unconfigured_cloud"}:
            raise ValueError("environment config.sandbox.backend is unsupported")


def environment_to_response(environment: Environment) -> EnvironmentResponse:
    return EnvironmentResponse(
        id=environment.id,
        name=environment.name,
        config=environment.config,
        metadata=environment.metadata_,
        archived_at=environment.archived_at,
        deleted_at=environment.deleted_at,
        created_at=environment.created_at,
        updated_at=environment.updated_at,
    )
