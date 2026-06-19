from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select

from app.db.engine import session_scope
from app.db.models import ManagedResource
from app.storage import StorageConfigurationError, save_file_bytes, should_store_in_object_storage

DEFAULT_RESOURCE_TYPES = ("file", "skill_version", "session_resource")


@dataclass
class BlobMigrationSummary:
    dry_run: bool
    scanned: int = 0
    migrated: int = 0
    skipped: int = 0
    resource_ids: list[str] = field(default_factory=list)


async def migrate_legacy_blobs(
    *,
    dry_run: bool = True,
    limit: int = 100,
    resource_types: Sequence[str] = DEFAULT_RESOURCE_TYPES,
) -> BlobMigrationSummary:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    clean_types = tuple(resource_type for resource_type in resource_types if resource_type)
    if not clean_types:
        raise ValueError("resource_types must not be empty")

    if not dry_run and not should_store_in_object_storage():
        raise StorageConfigurationError("Object storage must be configured before executing blob migration")

    summary = BlobMigrationSummary(dry_run=dry_run)
    async with session_scope() as db:
        result = await db.execute(
            select(ManagedResource)
            .where(
                ManagedResource.resource_type.in_(clean_types),
                ManagedResource.content.is_not(None),
                ManagedResource.storage_key.is_(None),
                ManagedResource.deleted_at.is_(None),
            )
            .order_by(ManagedResource.created_at.asc(), ManagedResource.id.asc())
            .limit(limit)
        )
        resources = list(result.scalars().all())
        summary.scanned = len(resources)
        summary.resource_ids = [resource.id for resource in resources]

        if dry_run:
            return summary

        for resource in resources:
            if resource.content is None:
                summary.skipped += 1
                continue
            stored = await save_file_bytes(
                resource.content,
                resource.content_type,
                namespace=_resource_namespace(resource),
                filename=resource.filename or resource.name or resource.id,
                category=resource.resource_type,
                workspace_id=resource.workspace_id,
            )
            resource.content = None
            resource.storage_backend = stored.backend
            resource.storage_key = stored.key
            resource.storage_url = stored.url
            resource.size_bytes = stored.size_bytes
            resource.sha256 = stored.sha256
            summary.migrated += 1

        await db.commit()
        return summary


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Move legacy DB-backed blobs into S3-compatible object storage.",
    )
    parser.add_argument("--execute", action="store_true", help="execute migration instead of dry-run")
    parser.add_argument("--limit", type=int, default=100, help="maximum number of resources to process")
    parser.add_argument(
        "--resource-type",
        dest="resource_types",
        action="append",
        default=[],
        help="resource type to include; repeatable. Defaults to file, skill_version, session_resource",
    )
    args = parser.parse_args()

    summary = await migrate_legacy_blobs(
        dry_run=not args.execute,
        limit=args.limit,
        resource_types=tuple(args.resource_types) or DEFAULT_RESOURCE_TYPES,
    )
    mode = "dry-run" if summary.dry_run else "execute"
    print(
        f"mode={mode} scanned={summary.scanned} migrated={summary.migrated} "
        f"skipped={summary.skipped}"
    )
    if summary.resource_ids:
        print("resource_ids=" + ",".join(summary.resource_ids))
    return 0


def _resource_namespace(resource: ManagedResource) -> str:
    if resource.parent_id:
        return f"{resource.resource_type}/{resource.parent_id}"
    return resource.resource_type
