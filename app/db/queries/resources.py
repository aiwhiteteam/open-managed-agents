from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ManagedResource
from app.ids import new_id


PREFIXES = {
    "skill": "skill",
    "skill_version": "skver",
    "file": "file",
    "vault": "vault",
    "credential": "cred",
    "memory_store": "memstore",
    "memory": "mem",
    "memory_version": "memver",
    "deployment": "deploy",
    "deployment_run": "deprun",
    "user_profile": "uprof",
    "session_resource": "res",
    "session_thread": "thread",
    "environment_work": "work",
}


async def create_resource(
    db: AsyncSession,
    *,
    resource_type: str,
    data: dict[str, Any] | None = None,
    parent_id: str | None = None,
    version: int | None = None,
    name: str | None = None,
    status: str = "active",
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    storage_backend: str | None = None,
    storage_key: str | None = None,
    storage_url: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> ManagedResource:
    resource = ManagedResource(
        id=new_id(PREFIXES.get(resource_type, "res")),
        resource_type=resource_type,
        parent_id=parent_id,
        version=version,
        name=name,
        status=status,
        data=data or {},
        content=content,
        content_type=content_type,
        filename=filename,
        storage_backend=storage_backend,
        storage_key=storage_key,
        storage_url=storage_url,
        size_bytes=size_bytes,
        sha256=sha256,
    )
    db.add(resource)
    await db.flush()
    return resource


async def get_resource(
    db: AsyncSession,
    *,
    resource_id: str,
    resource_type: str | None = None,
    parent_id: str | None = None,
    include_deleted: bool = False,
) -> ManagedResource | None:
    stmt = select(ManagedResource).where(ManagedResource.id == resource_id)
    if resource_type is not None:
        stmt = stmt.where(ManagedResource.resource_type == resource_type)
    if parent_id is not None:
        stmt = stmt.where(ManagedResource.parent_id == parent_id)
    if not include_deleted:
        stmt = stmt.where(ManagedResource.deleted_at.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_resource_version(
    db: AsyncSession,
    *,
    resource_type: str,
    parent_id: str,
    version: int,
    include_deleted: bool = False,
) -> ManagedResource | None:
    stmt = select(ManagedResource).where(
        ManagedResource.resource_type == resource_type,
        ManagedResource.parent_id == parent_id,
        ManagedResource.version == version,
    )
    if not include_deleted:
        stmt = stmt.where(ManagedResource.deleted_at.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_resources(
    db: AsyncSession,
    *,
    resource_type: str,
    parent_id: str | None = None,
    limit: int = 50,
    include_archived: bool = True,
) -> list[ManagedResource]:
    stmt = (
        select(ManagedResource)
        .where(
            ManagedResource.resource_type == resource_type,
            ManagedResource.deleted_at.is_(None),
        )
        .order_by(ManagedResource.created_at.desc(), ManagedResource.id.desc())
        .limit(limit)
    )
    if parent_id is not None:
        stmt = stmt.where(ManagedResource.parent_id == parent_id)
    if not include_archived:
        stmt = stmt.where(ManagedResource.archived_at.is_(None))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_resource(
    db: AsyncSession,
    resource: ManagedResource,
    *,
    data: dict[str, Any] | None = None,
    name: str | None = None,
    status: str | None = None,
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    storage_backend: str | None = None,
    storage_key: str | None = None,
    storage_url: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> ManagedResource:
    if data is not None:
        resource.data = data
    if name is not None:
        resource.name = name
    if status is not None:
        resource.status = status
    if content is not None:
        resource.content = content
    if content_type is not None:
        resource.content_type = content_type
    if filename is not None:
        resource.filename = filename
    if storage_backend is not None:
        resource.storage_backend = storage_backend
    if storage_key is not None:
        resource.storage_key = storage_key
    if storage_url is not None:
        resource.storage_url = storage_url
    if size_bytes is not None:
        resource.size_bytes = size_bytes
    if sha256 is not None:
        resource.sha256 = sha256
    await db.flush()
    return resource


async def archive_resource(db: AsyncSession, resource: ManagedResource) -> ManagedResource:
    resource.archived_at = datetime.now(timezone.utc)
    resource.status = "archived"
    await db.flush()
    return resource


async def delete_resource(db: AsyncSession, resource: ManagedResource) -> ManagedResource:
    resource.deleted_at = datetime.now(timezone.utc)
    resource.status = "deleted"
    await db.flush()
    return resource


async def next_version(db: AsyncSession, *, resource_type: str, parent_id: str) -> int:
    result = await db.execute(
        select(func.max(ManagedResource.version)).where(
            ManagedResource.resource_type == resource_type,
            ManagedResource.parent_id == parent_id,
        )
    )
    return int(result.scalar_one_or_none() or 0) + 1
