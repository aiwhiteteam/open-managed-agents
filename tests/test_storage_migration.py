from app.db.engine import session_scope
from app.db.queries import resources as res_q
from app.storage import StoredObject
from app.storage_migration import migrate_legacy_blobs


async def test_legacy_blob_migration_dry_run_reports_candidates():
    async with session_scope() as db:
        resource = await res_q.create_resource(
            db,
            resource_type="file",
            filename="legacy.txt",
            content=b"legacy",
            content_type="text/plain",
        )
        await db.commit()
        resource_id = resource.id

    summary = await migrate_legacy_blobs(dry_run=True, limit=10)

    assert summary.dry_run is True
    assert summary.scanned == 1
    assert summary.migrated == 0
    assert summary.resource_ids == [resource_id]

    async with session_scope() as db:
        resource = await res_q.get_resource(db, resource_id=resource_id)
        assert resource is not None
        assert resource.content == b"legacy"
        assert resource.storage_key is None


async def test_legacy_blob_migration_uploads_and_clears_db_content(monkeypatch):
    async with session_scope() as db:
        resource = await res_q.create_resource(
            db,
            resource_type="skill_version",
            parent_id="skill_123",
            version=1,
            filename="skill.zip",
            content=b"zip-bytes",
            content_type="application/zip",
        )
        await db.commit()
        resource_id = resource.id

    calls = []

    async def fake_save_file_bytes(data, mime_type, *, namespace, filename, category, workspace_id=None):
        calls.append(
            {
                "data": data,
                "mime_type": mime_type,
                "namespace": namespace,
                "filename": filename,
                "category": category,
                "workspace_id": workspace_id,
            }
        )
        return StoredObject(
            backend="s3",
            key="skill_version/skill.zip",
            url="https://cdn.example.com/skill_version/skill.zip",
            content_type=mime_type,
            size_bytes=len(data),
            sha256="abc123",
        )

    monkeypatch.setattr("app.storage_migration.should_store_in_object_storage", lambda: True)
    monkeypatch.setattr("app.storage_migration.save_file_bytes", fake_save_file_bytes)

    summary = await migrate_legacy_blobs(dry_run=False, limit=10)

    assert summary.dry_run is False
    assert summary.scanned == 1
    assert summary.migrated == 1
    assert calls == [
        {
            "data": b"zip-bytes",
            "mime_type": "application/zip",
            "namespace": "skill_version/skill_123",
            "filename": "skill.zip",
            "category": "skill_version",
            "workspace_id": "wrkspc_default",
        }
    ]

    async with session_scope() as db:
        resource = await res_q.get_resource(db, resource_id=resource_id)
        assert resource is not None
        assert resource.content is None
        assert resource.storage_backend == "s3"
        assert resource.storage_key == "skill_version/skill.zip"
        assert resource.storage_url == "https://cdn.example.com/skill_version/skill.zip"
        assert resource.size_bytes == len(b"zip-bytes")
        assert resource.sha256 == "abc123"
