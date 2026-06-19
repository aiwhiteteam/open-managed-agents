from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.db.models import ManagedSession
from app.models.common import ApiModel


class AgentReference(ApiModel):
    type: Literal["agent"] = "agent"
    id: str
    version: int | None = None


class SessionCreateRequest(ApiModel):
    agent: str | AgentReference
    environment_id: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    vault_ids: list[str] = Field(default_factory=list)


class SessionUpdateRequest(ApiModel):
    title: str | None = None
    metadata: dict[str, Any] | None = None


class SessionResponse(ApiModel):
    id: str
    type: str = "session"
    agent_id: str
    agent_version: int
    environment_id: str
    title: str | None = None
    status: str
    status_details: dict[str, Any] = Field(default_factory=dict)
    stop_reason: dict[str, Any] | None = None
    run_state: dict[str, Any] | None = None
    sandbox_state: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_event_seq: int
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def session_to_response(session: ManagedSession) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        agent_id=session.agent_id,
        agent_version=session.agent_version,
        environment_id=session.environment_id,
        title=session.title,
        status=session.status,
        status_details=session.status_details,
        stop_reason=session.stop_reason,
        run_state=session.run_state,
        sandbox_state=session.sandbox_state,
        metadata=session.metadata_,
        last_event_seq=session.last_event_seq,
        archived_at=session.archived_at,
        deleted_at=session.deleted_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
