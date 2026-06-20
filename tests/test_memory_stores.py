from datetime import datetime, timedelta, timezone

from app.db.engine import session_scope
from app.db.models import ManagedResource
from app.ids import new_id
from app.workspace import DEFAULT_WORKSPACE_ID
from tests.conftest import TEST_HEADERS


async def _create_store(client):
    response = await client.post(
        "/v1/memory_stores",
        headers=TEST_HEADERS,
        json={"name": "Customer memory"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_memory_path_uniqueness_lookup_and_versions(client):
    store = await _create_store(client)

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        json={
            "path": ["customers", "acme"],
            "content": "ACME prefers email.",
            "actor": "test",
        },
    )
    assert response.status_code == 201, response.text
    memory = response.json()
    assert memory["path"] == "/customers/acme"
    assert memory["path_key"] == "customers/acme"
    assert memory["version"] == 1
    assert memory["updated_by"] == "test"
    assert memory["content_size_bytes"] == len("ACME prefers email.".encode())

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        json={"path": "customers/acme", "content": "duplicate"},
    )
    assert response.status_code == 409

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/by_path",
        headers=TEST_HEADERS,
        params={"path": "customers/acme"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == memory["id"]

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}",
        headers=TEST_HEADERS,
        json={
            "if_version": 1,
            "content": "ACME prefers email and quarterly reviews.",
            "actor": "operator",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 2
    assert updated["updated_by"] == "operator"

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}",
        headers=TEST_HEADERS,
        json={"if_version": 1, "content": "stale"},
    )
    assert response.status_code == 409

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}",
        headers=TEST_HEADERS,
        json={
            "if_version": 2,
            "path": "customers/acme-renamed",
            "content": "ACME renamed path.",
            "actor": "operator",
        },
    )
    assert response.status_code == 200, response.text
    renamed = response.json()
    assert renamed["version"] == 3
    assert renamed["path"] == "/customers/acme-renamed"
    assert renamed["path_key"] == "customers/acme-renamed"

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/by_path",
        headers=TEST_HEADERS,
        params={"path": "customers/acme"},
    )
    assert response.status_code == 404

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/by_path",
        headers=TEST_HEADERS,
        params={"path": "customers/acme-renamed"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == memory["id"]

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}/versions",
        headers=TEST_HEADERS,
    )
    assert response.status_code == 200, response.text
    versions = response.json()["data"]
    assert [version["version"] for version in versions] == [3, 2, 1]
    assert versions[0]["actor"] == "operator"
    assert versions[0]["operation"] == "modified"


async def test_memory_path_prefix_query_is_not_capped_before_filtering(client):
    store = await _create_store(client)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    target = _memory_resource(store["id"], "customers/acme", base_time)
    newer_non_matches = [
        _memory_resource(store["id"], f"other/{index}", base_time + timedelta(seconds=index + 1))
        for index in range(1001)
    ]
    async with session_scope() as db:
        db.add(target)
        db.add_all(newer_non_matches)
        await db.commit()

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        params={"path_prefix": "customers", "limit": 10},
    )

    assert response.status_code == 200, response.text
    assert [item["path_key"] for item in response.json()["data"]] == ["customers/acme"]


async def test_memory_version_redaction_removes_snapshot_content(client):
    store = await _create_store(client)
    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        json={"path": "customers/acme", "content": "secret preference"},
    )
    assert response.status_code == 201, response.text
    memory = response.json()

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}/versions/1",
        headers=TEST_HEADERS,
    )
    assert response.status_code == 200, response.text
    memory_version = response.json()
    assert memory_version["snapshot"]["content"] == "secret preference"

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memory_versions/{memory_version['id']}/redact",
        headers=TEST_HEADERS,
    )
    assert response.status_code == 200, response.text
    redacted = response.json()
    assert redacted["redacted"] is True
    assert "content" not in redacted["snapshot"]

    response = await client.get(
        f"/v1/memory_stores/{store['id']}/memories/{memory['id']}",
        headers=TEST_HEADERS,
    )
    assert response.status_code == 200, response.text
    current_memory = response.json()
    assert current_memory["redacted"] is True
    assert "content" not in current_memory


async def test_memory_version_retrieve_requires_matching_store(client):
    store = await _create_store(client)
    other_store = await _create_store(client)

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        json={"path": "customers/acme", "content": "store scoped"},
    )
    assert response.status_code == 201, response.text
    memory = response.json()

    response = await client.get(
        f"/v1/memory_stores/{other_store['id']}/memory_versions/{memory['memory_version_id']}",
        headers=TEST_HEADERS,
    )
    assert response.status_code == 404


def _memory_resource(memory_store_id: str, path_key: str, created_at: datetime) -> ManagedResource:
    return ManagedResource(
        id=new_id("mem"),
        workspace_id=DEFAULT_WORKSPACE_ID,
        resource_type="memory",
        parent_id=memory_store_id,
        name=path_key,
        data={
            "path": f"/{path_key}",
            "path_key": path_key,
            "content": "remembered",
            "version": 1,
            "metadata": {},
            "redacted": False,
            "memory_version_id": "",
        },
        created_at=created_at,
        updated_at=created_at,
    )
