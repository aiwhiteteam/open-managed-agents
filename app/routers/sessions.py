import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.config import get_settings
from app.db.engine import get_session, session_scope
from app.db.queries import agents as agents_q
from app.db.queries import environments as env_q
from app.db.queries import events as events_q
from app.db.queries import resources as res_q
from app.db.queries import sessions as sessions_q
from app.models.common import ListResponse
from app.models.events import (
    SendEventsRequest,
    SendEventsResponse,
    SessionEventResponse,
    event_to_response,
    event_to_sse,
)
from app.models.sessions import (
    AgentReference,
    SessionCreateRequest,
    SessionResponse,
    SessionUpdateRequest,
    session_to_response,
)
from app.models.resources import GenericBody, deleted_response, resource_to_response
from app.runtime.work_queue import enqueue_session_run, execute_work_item, should_execute_inline

router = APIRouter(
    prefix="/v1/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_api_access)],
)


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreateRequest,
    db: AsyncSession = Depends(get_session),
):
    agent_id, version = _resolve_agent_ref(body.agent)
    agent = await agents_q.get_agent(db, agent_id)
    if agent is None or agent.archived_at is not None:
        raise HTTPException(status_code=404, detail="Agent not found")
    pinned_version = version or agent.active_version
    agent_version = await agents_q.get_agent_version(db, agent_id=agent.id, version=pinned_version)
    if agent_version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")

    environment = await env_q.get_environment(db, body.environment_id)
    if environment is None or environment.deleted_at is not None or environment.archived_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")

    session = await sessions_q.create_session(
        db,
        agent=agent,
        agent_version=agent_version.version,
        environment=environment,
        title=body.title,
        metadata=body.metadata,
        vault_ids=body.vault_ids,
    )
    await events_q.append_event(
        db,
        session,
        event_type="session.status_idle",
        payload={"type": "session.status_idle", "status": "idle", "stop_reason": {"type": "session_created"}},
    )
    await db.commit()
    return session_to_response(session)


@router.get("", response_model=ListResponse[SessionResponse])
async def list_sessions(
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    sessions = await sessions_q.list_sessions(db, limit=limit)
    return ListResponse[SessionResponse].from_items([session_to_response(s) for s in sessions])


@router.get("/{session_id}", response_model=SessionResponse)
async def retrieve_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_to_response(session)


@router.post("/{session_id}", response_model=SessionResponse)
@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await sessions_q.update_session(
        db,
        session,
        title=body.title,
        metadata=body.metadata,
    )
    await events_q.append_event(
        db,
        session,
        event_type="session.updated",
        payload={"type": "session.updated", "session": session_to_response(session).model_dump(mode="json")},
    )
    await db.commit()
    return session_to_response(session)


@router.post("/{session_id}/archive", response_model=SessionResponse)
async def archive_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await sessions_q.archive_session(db, session)
    await db.commit()
    return session_to_response(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    await sessions_q.delete_session(db, session)
    await events_q.append_event(
        db,
        session,
        event_type="session.deleted",
        payload={"type": "session.deleted"},
    )
    await db.commit()


@router.post("/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    stop_reason = {"type": "cancelled"}
    await sessions_q.update_session(db, session, status="terminated", stop_reason=stop_reason)
    await events_q.append_event(
        db,
        session,
        event_type="session.status_terminated",
        payload={"type": "session.status_terminated", "status": "terminated", "stop_reason": stop_reason},
    )
    await db.commit()
    return session_to_response(session)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "terminated":
        raise HTTPException(status_code=409, detail="Terminated sessions cannot be resumed")
    environment = await env_q.get_environment(db, session.environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    work = await enqueue_session_run(db, session, trigger="session.resume")
    await db.commit()
    if should_execute_inline(environment.config):
        background_tasks.add_task(execute_work_item, work.id)
    return session_to_response(session)


@router.post("/{session_id}/events", response_model=SendEventsResponse)
async def send_events(
    session_id: str,
    body: SendEventsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "terminated":
        raise HTTPException(status_code=409, detail="Session is terminated")
    environment = await env_q.get_environment(db, session.environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")

    appended = []
    should_run = False
    for event_input in body.events:
        payload = event_input.model_dump(mode="json")
        event = await events_q.append_event(
            db,
            session,
            event_type=event_input.type,
            payload=payload,
        )
        appended.append(event_to_response(event))
        if event_input.type.startswith("user."):
            should_run = True
    work = None
    if should_run:
        work = await enqueue_session_run(
            db,
            session,
            trigger="session.events",
            metadata={"event_ids": [event.id for event in appended]},
        )
    await db.commit()

    if work is not None and should_execute_inline(environment.config):
        background_tasks.add_task(execute_work_item, work.id)

    return SendEventsResponse(data=appended)


@router.get("/{session_id}/events", response_model=ListResponse[SessionEventResponse])
async def list_session_events(
    session_id: str,
    after_seq: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = await events_q.list_events(db, session_id=session.id, after_seq=after_seq, limit=limit)
    return ListResponse[SessionEventResponse].from_items([event_to_response(e) for e in events])


@router.get("/{session_id}/events/stream")
async def stream_session_events(
    session_id: str,
    request: Request,
    after_seq: int = 0,
):
    return await _stream_response(session_id, request, after_seq)


@router.get("/{session_id}/stream")
async def stream_session_events_alias(
    session_id: str,
    request: Request,
    after_seq: int = 0,
):
    return await _stream_response(session_id, request, after_seq)


@router.post("/{session_id}/resources", status_code=201)
async def add_session_resource(
    session_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    data = body.model_dump(mode="json")
    resource = await res_q.create_resource(
        db,
        resource_type="session_resource",
        parent_id=session_id,
        name=data.get("name") or data.get("file_id") or data.get("resource_id"),
        data=data,
    )
    await db.commit()
    return resource_to_response(resource, public_type="session_resource")


@router.get("/{session_id}/resources")
async def list_session_resources(
    session_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    resources = await res_q.list_resources(
        db,
        resource_type="session_resource",
        parent_id=session_id,
        limit=limit,
    )
    return ListResponse[dict].from_items(
        [resource_to_response(resource, public_type="session_resource") for resource in resources]
    )


@router.get("/{session_id}/resources/{resource_id}")
async def retrieve_session_resource(
    session_id: str,
    resource_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    resource = await res_q.get_resource(
        db,
        resource_id=resource_id,
        resource_type="session_resource",
        parent_id=session_id,
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Session resource not found")
    return resource_to_response(resource, public_type="session_resource")


@router.post("/{session_id}/resources/{resource_id}")
async def update_session_resource(
    session_id: str,
    resource_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    resource = await res_q.get_resource(
        db,
        resource_id=resource_id,
        resource_type="session_resource",
        parent_id=session_id,
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Session resource not found")
    data = dict(resource.data)
    data.update(body.model_dump(mode="json"))
    await res_q.update_resource(db, resource, data=data)
    await db.commit()
    return resource_to_response(resource, public_type="session_resource")


@router.delete("/{session_id}/resources/{resource_id}")
async def delete_session_resource(
    session_id: str,
    resource_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    resource = await res_q.get_resource(
        db,
        resource_id=resource_id,
        resource_type="session_resource",
        parent_id=session_id,
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Session resource not found")
    await res_q.delete_resource(db, resource)
    await db.commit()
    return deleted_response(resource, public_type="deleted_session_resource")


@router.get("/{session_id}/threads")
async def list_session_threads(
    session_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    threads = await res_q.list_resources(
        db,
        resource_type="session_thread",
        parent_id=session_id,
        limit=limit,
    )
    return ListResponse[dict].from_items(
        [resource_to_response(thread, public_type="session_thread") for thread in threads]
    )


@router.get("/{session_id}/threads/{thread_id}")
async def retrieve_session_thread(
    session_id: str,
    thread_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    thread = await res_q.get_resource(
        db,
        resource_id=thread_id,
        resource_type="session_thread",
        parent_id=session_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Session thread not found")
    return resource_to_response(thread, public_type="session_thread")


@router.post("/{session_id}/threads/{thread_id}/archive")
async def archive_session_thread(
    session_id: str,
    thread_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    thread = await res_q.get_resource(
        db,
        resource_id=thread_id,
        resource_type="session_thread",
        parent_id=session_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Session thread not found")
    await res_q.archive_resource(db, thread)
    await db.commit()
    return resource_to_response(thread, public_type="session_thread")


@router.get("/{session_id}/threads/{thread_id}/events")
async def list_session_thread_events(
    session_id: str,
    thread_id: str,
    after_seq: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_session(db, session_id)
    events = await events_q.list_events(db, session_id=session_id, after_seq=after_seq, limit=limit)
    filtered = [
        event_to_response(event)
        for event in events
        if event.payload.get("thread_id") == thread_id or event.payload.get("thread", {}).get("id") == thread_id
    ]
    return ListResponse[SessionEventResponse].from_items(filtered)


@router.get("/{session_id}/threads/{thread_id}/stream")
async def stream_session_thread_events(
    session_id: str,
    thread_id: str,
    request: Request,
    after_seq: int = 0,
):
    return await _stream_response(session_id, request, after_seq, thread_id=thread_id)


def _resolve_agent_ref(agent: str | AgentReference) -> tuple[str, int | None]:
    if isinstance(agent, str):
        return agent, None
    return agent.id, agent.version


async def _must_get_session(db: AsyncSession, session_id: str):
    session = await sessions_q.get_session(db, session_id)
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _stream_response(
    session_id: str,
    request: Request,
    after_seq: int,
    thread_id: str | None = None,
) -> StreamingResponse:
    async def event_generator():
        current_seq = after_seq
        interval = get_settings().oma_event_poll_interval_seconds
        while True:
            if await request.is_disconnected():
                break
            async with session_scope() as db:
                session = await sessions_q.get_session(db, session_id)
                if session is None or session.deleted_at is not None:
                    yield "event: error\ndata: {\"type\":\"not_found_error\",\"message\":\"Session not found\"}\n\n"
                    break
                events = await events_q.list_events(
                    db,
                    session_id=session_id,
                    after_seq=current_seq,
                    limit=100,
                )
            if events:
                for event in events:
                    if thread_id is not None and not (
                        event.payload.get("thread_id") == thread_id
                        or event.payload.get("thread", {}).get("id") == thread_id
                    ):
                        continue
                    current_seq = event.seq
                    yield event_to_sse(event)
            else:
                yield ": ping\n\n"
                await asyncio.sleep(interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
