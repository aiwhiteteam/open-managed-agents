from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Environment
from app.ids import new_id


async def create_environment(
    db: AsyncSession,
    *,
    name: str,
    config: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Environment:
    environment = Environment(
        id=new_id("env"),
        name=name,
        config=config,
        metadata_=metadata or {},
    )
    db.add(environment)
    await db.flush()
    return environment


async def get_environment(db: AsyncSession, environment_id: str) -> Environment | None:
    result = await db.execute(select(Environment).where(Environment.id == environment_id))
    return result.scalar_one_or_none()


async def list_environments(db: AsyncSession, *, limit: int = 50) -> list[Environment]:
    result = await db.execute(
        select(Environment)
        .where(Environment.deleted_at.is_(None))
        .order_by(Environment.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_environment(
    db: AsyncSession,
    environment: Environment,
    *,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Environment:
    if name is not None:
        environment.name = name
    if config is not None:
        environment.config = config
    if metadata is not None:
        environment.metadata_ = metadata
    await db.flush()
    return environment


async def archive_environment(db: AsyncSession, environment: Environment) -> Environment:
    environment.archived_at = datetime.now(timezone.utc)
    await db.flush()
    return environment


async def delete_environment(db: AsyncSession, environment: Environment) -> None:
    environment.deleted_at = datetime.now(timezone.utc)
    await db.flush()

