from typing import Annotated

from fastapi import Header, HTTPException

from app.config import get_settings

MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
ANTHROPIC_API_VERSION = "2023-06-01"


async def require_api_access(
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    authorization: Annotated[str | None, Header(alias="authorization")] = None,
    anthropic_beta: Annotated[str | None, Header(alias="anthropic-beta")] = None,
    anthropic_version: Annotated[str | None, Header(alias="anthropic-version")] = None,
):
    settings = get_settings()

    if settings.oma_require_anthropic_version_header and not anthropic_version:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required Anthropic API version header: {ANTHROPIC_API_VERSION}",
        )

    if settings.oma_require_beta_header:
        beta_values = _split_header_values(anthropic_beta)
        if MANAGED_AGENTS_BETA not in beta_values:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required beta header: {MANAGED_AGENTS_BETA}",
            )

    if not settings.oma_api_keys:
        return

    token = x_api_key or _bearer_token(authorization)
    if token not in settings.oma_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")


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
