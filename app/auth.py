from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable

from fastapi import Header, HTTPException, Request

from app.config import get_settings
from app.workspace import (
    CurrentWorkspace,
    DEFAULT_WORKSPACE_ID,
    current_workspace,
    default_workspace,
    set_current_workspace,
)

CMA_MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
OPEN_MANAGED_AGENTS_BETA = "open-managed-agents-2026-04-01"
ANTHROPIC_SKILLS_BETA = "skills-2025-10-02"
ANTHROPIC_USER_PROFILES_BETA = "user-profiles-2026-03-24"
ACCEPTED_MANAGED_AGENTS_BETAS = {
    CMA_MANAGED_AGENTS_BETA,
    OPEN_MANAGED_AGENTS_BETA,
    ANTHROPIC_SKILLS_BETA,
    ANTHROPIC_USER_PROFILES_BETA,
}
ANTHROPIC_API_VERSION = "2023-06-01"


@dataclass(frozen=True)
class RequestCredentials:
    x_api_key: str | None
    authorization: str | None


@runtime_checkable
class AuthProvider(Protocol):
    async def authenticate(self, request: Request, credentials: RequestCredentials) -> CurrentWorkspace:
        ...


class EnvApiKeyAuthProvider:
    async def authenticate(self, request: Request, credentials: RequestCredentials) -> CurrentWorkspace:
        settings = get_settings()
        workspace = default_workspace()
        api_keys = _configured_api_keys(settings.oma_api_key, settings.oma_api_keys)
        if not api_keys:
            return workspace

        token = credentials.x_api_key or _bearer_token(credentials.authorization)
        if token not in api_keys:
            raise HTTPException(status_code=401, detail="Invalid API key")
        workspace_id = (
            settings.oma_api_key_workspaces.get(token)
            or settings.oma_default_workspace_id
            or DEFAULT_WORKSPACE_ID
        )
        return CurrentWorkspace(
            id=workspace_id,
            slug="default" if workspace_id == DEFAULT_WORKSPACE_ID else workspace_id,
            source="api_key",
        )


class DatabaseApiKeyAuthProvider:
    async def authenticate(self, request: Request, credentials: RequestCredentials) -> CurrentWorkspace:
        from app.db.engine import session_scope
        from app.db.queries import api_keys as api_keys_q

        token = credentials.x_api_key or _bearer_token(credentials.authorization)
        if not token:
            raise HTTPException(status_code=401, detail="Missing API key")

        async with session_scope() as db:
            api_key = await api_keys_q.get_api_key_by_token(db, token)
            if api_key is None:
                raise HTTPException(status_code=401, detail="Invalid API key")
            await api_keys_q.touch_api_key(db, api_key)
            await db.commit()
            return CurrentWorkspace(
                id=api_key.workspace_id,
                slug=api_key.workspace_id,
                source="database_api_key",
            )


async def require_api_access(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    authorization: Annotated[str | None, Header(alias="authorization")] = None,
    anthropic_beta: Annotated[str | None, Header(alias="anthropic-beta")] = None,
    open_managed_agents_beta: Annotated[
        str | None,
        Header(alias="open-managed-agents-beta"),
    ] = None,
    anthropic_version: Annotated[str | None, Header(alias="anthropic-version")] = None,
):
    settings = get_settings()

    anthropic_beta_values = _split_header_values(anthropic_beta)
    native_beta_values = _split_header_values(open_managed_agents_beta)
    beta_values = anthropic_beta_values | native_beta_values

    if settings.oma_require_beta_header:
        if not beta_values.intersection(ACCEPTED_MANAGED_AGENTS_BETAS):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing required beta header: "
                    f"{CMA_MANAGED_AGENTS_BETA}, {OPEN_MANAGED_AGENTS_BETA}, "
                    f"{ANTHROPIC_SKILLS_BETA}, or {ANTHROPIC_USER_PROFILES_BETA}"
                ),
            )

    compatibility_mode = bool(anthropic_beta_values.intersection(ACCEPTED_MANAGED_AGENTS_BETAS))
    if settings.oma_require_anthropic_version_header and compatibility_mode and not anthropic_version:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required Anthropic API version header: {ANTHROPIC_API_VERSION}",
        )

    provider: AuthProvider = getattr(request.app.state, "auth_provider", EnvApiKeyAuthProvider())
    workspace = await provider.authenticate(
        request,
        RequestCredentials(x_api_key=x_api_key, authorization=authorization),
    )
    request.state.current_workspace = workspace
    set_current_workspace(workspace)
    return workspace


async def get_current_workspace(request: Request) -> CurrentWorkspace:
    workspace = getattr(request.state, "current_workspace", None)
    if workspace is not None:
        return workspace
    return current_workspace()


def _split_header_values(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "Bearer "
    if value.startswith(prefix):
        return value[len(prefix) :]
    return None


def _configured_api_keys(primary: str, legacy: list[str]) -> set[str]:
    keys = {primary.strip()} if primary.strip() else set()
    keys.update(key.strip() for key in legacy if key.strip())
    return keys
