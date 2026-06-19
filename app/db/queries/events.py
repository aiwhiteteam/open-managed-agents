from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ManagedSession, SessionEvent
from app.ids import new_id


async def append_event(
    db: AsyncSession,
    session: ManagedSession,
    *,
    event_type: str,
    payload: dict[str, Any] | None = None,
    source: str | None = None,
) -> SessionEvent:
    session.last_event_seq += 1
    event = SessionEvent(
        id=new_id("evt"),
        session_id=session.id,
        seq=session.last_event_seq,
        type=event_type,
        source=source or event_source(event_type),
        payload=_normalize_payload(event_type, payload),
    )
    db.add(event)
    await db.flush()
    return event


async def list_events(
    db: AsyncSession,
    *,
    session_id: str,
    after_seq: int = 0,
    limit: int = 100,
) -> list[SessionEvent]:
    result = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.seq > after_seq)
        .order_by(SessionEvent.seq.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_latest_event_seq(db: AsyncSession, *, session_id: str) -> int:
    result = await db.execute(
        select(SessionEvent.seq)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.seq.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or 0


def event_source(event_type: str) -> str:
    return event_type.split(".", 1)[0] if "." in event_type else "system"


def _normalize_payload(event_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("type", event_type)
    return normalized

