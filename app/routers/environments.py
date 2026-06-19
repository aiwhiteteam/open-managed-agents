from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.db.engine import get_session
from app.db.queries import environments as env_q
from app.db.queries import resources as res_q
from app.models.common import ListResponse
from app.models.environments import (
    EnvironmentCreateRequest,
    EnvironmentResponse,
    EnvironmentUpdateRequest,
    environment_to_response,
)
from app.models.resources import GenericBody, resource_to_response
from app.runtime.work_queue import ack_work, heartbeat_work, lease_next_work, stop_work

router = APIRouter(
    prefix="/v1/environments",
    tags=["environments"],
    dependencies=[Depends(require_api_access)],
)


@router.post("", response_model=EnvironmentResponse, status_code=201)
async def create_environment(
    body: EnvironmentCreateRequest,
    db: AsyncSession = Depends(get_session),
):
    environment = await env_q.create_environment(
        db,
        name=body.name,
        config=body.config,
        metadata=body.metadata,
    )
    await db.commit()
    return environment_to_response(environment)


@router.get("", response_model=ListResponse[EnvironmentResponse])
async def list_environments(
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    environments = await env_q.list_environments(db, limit=limit)
    return ListResponse[EnvironmentResponse].from_items(
        [environment_to_response(env) for env in environments]
    )


@router.get("/{environment_id}", response_model=EnvironmentResponse)
async def retrieve_environment(
    environment_id: str,
    db: AsyncSession = Depends(get_session),
):
    environment = await env_q.get_environment(db, environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    return environment_to_response(environment)


@router.post("/{environment_id}", response_model=EnvironmentResponse)
@router.patch("/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
    environment_id: str,
    body: EnvironmentUpdateRequest,
    db: AsyncSession = Depends(get_session),
):
    environment = await env_q.get_environment(db, environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    environment = await env_q.update_environment(
        db,
        environment,
        name=body.name,
        config=body.config,
        metadata=body.metadata,
    )
    await db.commit()
    return environment_to_response(environment)


@router.post("/{environment_id}/archive", response_model=EnvironmentResponse)
async def archive_environment(
    environment_id: str,
    db: AsyncSession = Depends(get_session),
):
    environment = await env_q.get_environment(db, environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    environment = await env_q.archive_environment(db, environment)
    await db.commit()
    return environment_to_response(environment)


@router.delete("/{environment_id}", status_code=204)
async def delete_environment(
    environment_id: str,
    db: AsyncSession = Depends(get_session),
):
    environment = await env_q.get_environment(db, environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    await env_q.delete_environment(db, environment)
    await db.commit()


@router.get("/{environment_id}/work")
async def list_environment_work(
    environment_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await res_q.list_resources(
        db,
        resource_type="environment_work",
        parent_id=environment_id,
        limit=limit,
    )
    return ListResponse[dict].from_items([resource_to_response(item, public_type="self_hosted_work") for item in work])


@router.get("/{environment_id}/work/poll")
async def poll_environment_work(
    environment_id: str,
    worker_id: str = Query(default="anonymous"),
    lease_seconds: int = Query(default=60, ge=5, le=3600),
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await lease_next_work(
        db,
        environment_id=environment_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    if work is None:
        return None
    await db.commit()
    return resource_to_response(work, public_type="self_hosted_work")


@router.get("/{environment_id}/work/stats")
async def environment_work_stats(
    environment_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    queued = await res_q.list_resources(
        db,
        resource_type="environment_work",
        parent_id=environment_id,
        limit=1000,
    )
    return {
        "type": "self_hosted_work_queue_stats",
        "environment_id": environment_id,
        "queued": len([w for w in queued if w.status == "queued"]),
        "leased": len([w for w in queued if w.status == "leased"]),
        "running": len([w for w in queued if w.status == "running"]),
        "completed": len([w for w in queued if w.status == "completed"]),
        "error": len([w for w in queued if w.status == "error"]),
        "stopped": len([w for w in queued if w.status == "stopped"]),
    }


@router.get("/{environment_id}/work/{work_id}")
async def retrieve_environment_work(
    environment_id: str,
    work_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await _must_get_work(db, environment_id, work_id)
    return resource_to_response(work, public_type="self_hosted_work")


@router.post("/{environment_id}/work/{work_id}")
async def update_environment_work(
    environment_id: str,
    work_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await _must_get_work(db, environment_id, work_id)
    data = dict(work.data)
    data.update(body.model_dump(mode="json"))
    await res_q.update_resource(db, work, data=data, status=data.get("status", work.status))
    await db.commit()
    return resource_to_response(work, public_type="self_hosted_work")


@router.post("/{environment_id}/work/{work_id}/ack")
async def ack_environment_work(
    environment_id: str,
    work_id: str,
    worker_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await _must_get_work(db, environment_id, work_id)
    await ack_work(db, work, worker_id=worker_id)
    await db.commit()
    return resource_to_response(work, public_type="self_hosted_work")


@router.post("/{environment_id}/work/{work_id}/heartbeat")
async def heartbeat_environment_work(
    environment_id: str,
    work_id: str,
    body: GenericBody,
    worker_id: str | None = Query(default=None),
    lease_seconds: int = Query(default=60, ge=5, le=3600),
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await _must_get_work(db, environment_id, work_id)
    await heartbeat_work(
        db,
        work,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        payload=body.model_dump(mode="json"),
    )
    await db.commit()
    return resource_to_response(work, public_type="self_hosted_work")


@router.post("/{environment_id}/work/{work_id}/stop")
async def stop_environment_work(
    environment_id: str,
    work_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    await _must_get_environment(db, environment_id)
    work = await _must_get_work(db, environment_id, work_id)
    await stop_work(db, work, payload=body.model_dump(mode="json"))
    await db.commit()
    return resource_to_response(work, public_type="self_hosted_work")


async def _must_get_environment(db: AsyncSession, environment_id: str):
    environment = await env_q.get_environment(db, environment_id)
    if environment is None or environment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Environment not found")
    return environment


async def _must_get_work(db: AsyncSession, environment_id: str, work_id: str):
    work = await res_q.get_resource(
        db,
        resource_id=work_id,
        resource_type="environment_work",
        parent_id=environment_id,
    )
    if work is None:
        raise HTTPException(status_code=404, detail="Environment work item not found")
    return work
