from tests.conftest import TEST_HEADERS


async def test_post_update_alias_matches_official_sdk_shape(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Alias Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    agent = response.json()

    response = await client.post(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": agent["version"], "description": "updated via POST"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["description"] == "updated via POST"


async def test_files_upload_download_delete(client):
    response = await client.post(
        "/v1/files",
        headers=TEST_HEADERS,
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file = response.json()
    assert file["type"] == "file"
    assert file["filename"] == "hello.txt"
    assert file["size_bytes"] == 11

    response = await client.get(f"/v1/files/{file['id']}/content", headers=TEST_HEADERS)
    assert response.status_code == 200
    assert response.content == b"hello world"

    response = await client.delete(f"/v1/files/{file['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200
    assert response.json()["deleted"] is True


async def test_skill_create_version_and_download(client):
    response = await client.post(
        "/v1/skills",
        headers=TEST_HEADERS,
        data={"display_title": "Research Skill"},
        files={
            "files": (
                "skill/SKILL.md",
                b"---\nname: research\ndescription: Use sources.\n---\nUse sources.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 201, response.text
    skill = response.json()
    assert skill["type"] == "skill"
    assert skill["latest_version"] == 1

    response = await client.post(
        f"/v1/skills/{skill['id']}/versions",
        headers=TEST_HEADERS,
        files={
            "files": (
                "skill/SKILL.md",
                b"---\nname: research\ndescription: Use sources.\n---\nUpdated.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["version"] == 2

    response = await client.get(f"/v1/skills/{skill['id']}/versions/2/content", headers=TEST_HEADERS)
    assert response.status_code == 200
    assert b"Updated" in response.content


async def test_vault_credentials_memory_and_deployment_metadata(client):
    response = await client.post(
        "/v1/vaults",
        headers=TEST_HEADERS,
        json={"name": "Main Vault"},
    )
    assert response.status_code == 201, response.text
    vault = response.json()

    response = await client.post(
        f"/v1/vaults/{vault['id']}/credentials",
        headers=TEST_HEADERS,
        json={"name": "linear", "type": "mcp_oauth"},
    )
    assert response.status_code == 201, response.text
    credential = response.json()
    assert credential["type"] == "credential"

    response = await client.post(
        "/v1/memory_stores",
        headers=TEST_HEADERS,
        json={"name": "Customer memory"},
    )
    assert response.status_code == 201, response.text
    store = response.json()

    response = await client.post(
        f"/v1/memory_stores/{store['id']}/memories",
        headers=TEST_HEADERS,
        json={"path": ["customers", "acme"], "content": "ACME prefers email."},
    )
    assert response.status_code == 201, response.text
    memory = response.json()
    assert memory["type"] == "memory"

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={"name": "Daily report"},
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["type"] == "deployment_run"
