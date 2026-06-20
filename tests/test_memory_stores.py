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
