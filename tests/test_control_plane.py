import asyncio

from tests.conftest import OPEN_MANAGED_AGENTS_HEADERS, TEST_HEADERS


async def _create_agent(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Coding Assistant",
            "model": {"id": "gpt-5.5"},
            "system": "You are concise.",
            "tools": [{"type": "agent_toolset_20260401"}],
            "metadata": {"team": "platform"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment(client):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={
            "name": "local-dev",
            "config": {"type": "cloud", "networking": {"type": "unrestricted"}},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_agent_update_creates_immutable_versions(client):
    agent = await _create_agent(client)

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={
            "version": agent["version"],
            "system": "You are very concise.",
            "metadata": {"team": "platform-v2", "remove_me": "x"},
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 2
    assert updated["metadata"]["team"] == "platform-v2"

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": 2, "metadata": {"remove_me": ""}},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 3
    assert "remove_me" not in updated["metadata"]

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 3

    response = await client.get(f"/v1/agents/{agent['id']}/versions", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    versions = response.json()["data"]
    assert [v["version"] for v in versions] == [3, 2, 1]


async def test_agent_update_rejects_stale_version(client):
    agent = await _create_agent(client)

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": agent["version"], "system": "v2"},
    )
    assert response.status_code == 200, response.text

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": agent["version"], "system": "stale write"},
    )
    assert response.status_code == 409


async def test_agent_metadata_limits_are_enforced(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Too Much Metadata",
            "model": {"id": "gpt-5.5"},
            "metadata": {f"k{index}": "v" for index in range(17)},
        },
    )
    assert response.status_code == 422
    assert "at most 16 keys" in response.json()["error"]["message"]

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Long Metadata Key", "model": {"id": "gpt-5.5"}, "metadata": {"x" * 65: "v"}},
    )
    assert response.status_code == 422
    assert "at most 64 characters" in response.json()["error"]["message"]

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Long Metadata Value", "model": {"id": "gpt-5.5"}, "metadata": {"key": "v" * 513}},
    )
    assert response.status_code == 422
    assert "at most 512 characters" in response.json()["error"]["message"]

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Non String Metadata", "model": {"id": "gpt-5.5"}, "metadata": {"key": 1}},
    )
    assert response.status_code == 422
    assert "values must be strings" in response.json()["error"]["message"]

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Full Metadata",
            "model": {"id": "gpt-5.5"},
            "metadata": {f"k{index}": "v" for index in range(16)},
        },
    )
    assert response.status_code == 201, response.text
    agent = response.json()

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": agent["version"], "metadata": {"extra": "v"}},
    )
    assert response.status_code == 422
    assert "at most 16 keys" in response.json()["error"]["message"]


async def test_multiagent_roster_pins_referenced_agent_versions(client):
    reviewer = await _create_agent(client)

    response = await client.patch(
        f"/v1/agents/{reviewer['id']}",
        headers=TEST_HEADERS,
        json={"version": reviewer["version"], "system": "Reviewer v2"},
    )
    assert response.status_code == 200, response.text
    reviewer_v2 = response.json()

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Coordinator",
            "model": {"id": "gpt-5.5"},
            "tools": [{"type": "agent_toolset_20260401"}],
            "multiagent": {
                "type": "coordinator",
                "agents": [
                    {"type": "agent", "id": reviewer["id"]},
                    {"type": "self"},
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    coordinator = response.json()
    assert coordinator["multiagent"]["agents"][0]["version"] == reviewer_v2["version"]

    response = await client.patch(
        f"/v1/agents/{reviewer['id']}",
        headers=TEST_HEADERS,
        json={"version": reviewer_v2["version"], "system": "Reviewer v3"},
    )
    assert response.status_code == 200, response.text
    reviewer_v3 = response.json()

    response = await client.get(f"/v1/agents/{coordinator['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["multiagent"]["agents"][0]["version"] == reviewer_v2["version"]

    response = await client.patch(
        f"/v1/agents/{coordinator['id']}",
        headers=TEST_HEADERS,
        json={
            "version": coordinator["version"],
            "multiagent": {
                "type": "coordinator",
                "agents": [{"type": "agent", "id": reviewer["id"]}],
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["multiagent"]["agents"][0]["version"] == reviewer_v3["version"]


async def test_agent_mcp_servers_must_match_mcp_toolsets(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Dangling MCP Server",
            "model": {"id": "gpt-5.5"},
            "mcp_servers": [{"type": "url", "name": "github", "url": "https://mcp.example.com/github"}],
            "tools": [{"type": "agent_toolset_20260401"}],
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Dangling MCP Toolset",
            "model": {"id": "gpt-5.5"},
            "tools": [{"type": "mcp_toolset", "mcp_server_name": "github"}],
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Bound MCP",
            "model": {"id": "gpt-5.5"},
            "mcp_servers": [{"type": "url", "name": "github", "url": "https://mcp.example.com/github"}],
            "tools": [{"type": "mcp_toolset", "mcp_server_name": "github"}],
        },
    )
    assert response.status_code == 201, response.text


async def test_session_pins_agent_version_and_processes_user_event(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "title": "First task",
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["agent_version"] == 1

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={
            "events": [
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": "Say hello"}],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    sent_event = response.json()["data"][0]
    assert sent_event["type"] == "user.message"
    assert sent_event["processed_at"] is None

    for _ in range(20):
        response = await client.get(
            f"/v1/sessions/{session['id']}/events",
            headers=TEST_HEADERS,
        )
        assert response.status_code == 200, response.text
        types = [event["type"] for event in response.json()["data"]]
        if "agent.message" in types and "session.status_idle" in types:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"runtime did not emit completion events; saw {types}")

    assert types[0] == "session.status_idle"
    assert "user.message" in types
    assert "session.status_running" in types
    assert "agent.message" in types
    by_type = {event["type"]: event for event in response.json()["data"]}
    assert by_type["user.message"]["processed_at"] is None
    assert by_type["session.status_idle"]["processed_at"] is not None
    assert by_type["session.status_running"]["processed_at"] is not None
    assert by_type["agent.message"]["processed_at"] is not None


async def test_missing_beta_header_is_rejected(client):
    response = await client.post(
        "/v1/agents",
        headers={"anthropic-version": "2023-06-01"},
        json={"name": "No Beta", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


async def test_open_managed_agents_beta_alias_is_accepted(client):
    response = await client.post(
        "/v1/agents",
        headers=OPEN_MANAGED_AGENTS_HEADERS,
        json={"name": "Open Beta", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text

    response = await client.post(
        "/v1/agents",
        headers={
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "open-managed-agents-2026-04-01",
        },
        json={"name": "Open Beta Anthropic Header", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text


async def test_missing_anthropic_version_header_is_rejected(client):
    headers = {"anthropic-beta": "managed-agents-2026-04-01"}
    response = await client.post(
        "/v1/agents",
        headers=headers,
        json={"name": "No Version", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 400
    assert "Anthropic API version" in response.json()["error"]["message"]
