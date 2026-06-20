from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.db.models import Environment
from app.models.common import ApiModel


class EnvironmentCreateRequest(ApiModel):
    name: str
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=lambda: {"type": "cloud"})
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self):
        validate_environment_config(self.config)
        return self


class EnvironmentUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
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
    description: str
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
        description=environment.description,
        config=environment_config_to_response(environment.config),
        metadata=environment.metadata_,
        archived_at=environment.archived_at,
        deleted_at=environment.deleted_at,
        created_at=environment.created_at,
        updated_at=environment.updated_at,
    )


def environment_config_to_response(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config or {})
    env_type = normalized.get("type", "cloud")
    normalized["type"] = env_type
    if env_type != "cloud":
        return normalized

    networking = normalized.get("networking") or {"type": "unrestricted"}
    if networking.get("type") in {"restricted", "none"}:
        networking = {
            "type": "limited",
            "allowed_hosts": networking.get("allowed_hosts", []),
            "allow_mcp_servers": bool(networking.get("allow_mcp_servers", False)),
            "allow_package_managers": bool(networking.get("allow_package_managers", False)),
        }
    if networking.get("type") == "limited":
        networking = {
            "type": "limited",
            "allowed_hosts": list(networking.get("allowed_hosts") or []),
            "allow_mcp_servers": bool(networking.get("allow_mcp_servers", False)),
            "allow_package_managers": bool(networking.get("allow_package_managers", False)),
        }
    normalized["networking"] = networking

    packages = dict(normalized.get("packages") or {})
    normalized["packages"] = {
        "type": "packages",
        "apt": list(packages.get("apt") or []),
        "cargo": list(packages.get("cargo") or []),
        "gem": list(packages.get("gem") or []),
        "go": list(packages.get("go") or []),
        "npm": list(packages.get("npm") or []),
        "pip": list(packages.get("pip") or []),
    }
    return normalized
