import asyncio

from tests.conftest import TEST_HEADERS


async def _create_agent(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Sandbox Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_environment_sandbox_plan_is_recorded_in_local_runtime(client):
    agent = await _create_agent(client)
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={
            "name": "local-sandbox",
            "config": {
                "type": "local",
                "sandbox": {
                    "enabled": True,
                    "backend": "unix_local",
                    "root": "/workspace",
                    "capabilities": ["filesystem", "shell", "compaction"],
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    environment = response.json()

    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "test sandbox"}]},
    )
    assert response.status_code == 200, response.text

    for _ in range(20):
        response = await client.get(f"/v1/sessions/{session['id']}", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        current = response.json()
        if current["status"] == "idle" and current.get("sandbox_state"):
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("session did not complete with sandbox state")

    sandbox_state = current["sandbox_state"]
    assert sandbox_state["enabled"] is True
    assert sandbox_state["backend"] == "unix_local"
    assert sandbox_state["runtime_backend"] == "local"


async def test_environment_rejects_unknown_sandbox_backend(client):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={
            "name": "bad-sandbox",
            "config": {"type": "local", "sandbox": {"enabled": True, "backend": "unknown"}},
        },
    )

    assert response.status_code == 422


async def test_environment_policy_config_is_recorded_in_sandbox_state(client):
    agent = await _create_agent(client)
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={
            "name": "policy-sandbox",
            "config": {
                "type": "cloud",
                "networking": {
                    "type": "limited",
                    "allowed_hosts": ["api.example.com"],
                    "allow_mcp_servers": True,
                    "allow_package_managers": False,
                },
                "packages": {"pip": ["requests"], "npm": ["typescript"]},
                "resources": {"cpu": 2, "memory_mb": 2048, "timeout_seconds": 600},
            },
        },
    )
    assert response.status_code == 201, response.text
    environment = response.json()
    assert environment["config"]["networking"] == {
        "type": "limited",
        "allowed_hosts": ["api.example.com"],
        "allow_mcp_servers": True,
        "allow_package_managers": False,
    }
    assert environment["config"]["packages"]["pip"] == ["requests"]
    assert environment["config"]["packages"]["npm"] == ["typescript"]

    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "test policy"}]},
    )
    assert response.status_code == 200, response.text

    for _ in range(20):
        response = await client.get(f"/v1/sessions/{session['id']}", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        current = response.json()
        if current["status"] == "idle" and current.get("sandbox_state"):
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("session did not complete with sandbox policy state")

    policy = current["sandbox_state"]["policy"]
    assert policy["networking"]["allowed_hosts"] == ["api.example.com"]
    assert policy["networking"]["allow_mcp_servers"] is True
    assert policy["packages"]["pip"] == ["requests"]
    assert policy["resources"] == {"cpu": 2, "memory_mb": 2048, "timeout_seconds": 600}


async def test_environment_rejects_invalid_policy_shapes(client):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={
            "name": "bad-policy",
            "config": {
                "type": "cloud",
                "networking": {"type": "limited", "allowed_hosts": "api.example.com"},
            },
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": "bad-packages", "config": {"type": "cloud", "packages": {"pip": [""]}}},
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": "bad-resources", "config": {"type": "cloud", "resources": {"memory_mb": 0}}},
    )
    assert response.status_code == 422
