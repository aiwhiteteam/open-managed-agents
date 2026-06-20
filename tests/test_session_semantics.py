import asyncio

from app.db.engine import session_scope
from app.db.queries import resources as res_q
from app.db.queries import sessions as sessions_q
from tests.conftest import TEST_HEADERS


async def _create_agent(client, *, tools=None, mcp_servers=None):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={
            "name": "Session Semantic Agent",
            "model": {"id": "gpt-5.5"},
            "tools": tools or [],
            "mcp_servers": mcp_servers or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment(client, *, env_type="cloud"):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": f"{env_type}-session-semantics", "config": {"type": env_type}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_session(client, agent, environment):
    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={"agent": {"type": "agent", "id": agent["id"], "version": 1}, "environment_id": environment["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wait_for_stop_reason(client, session_id: str, reason_type: str):
    for _ in range(30):
        response = await client.get(f"/v1/sessions/{session_id}", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        session = response.json()
        if (session.get("stop_reason") or {}).get("type") == reason_type:
            return session
        await asyncio.sleep(0.05)
    raise AssertionError(f"session did not reach stop_reason={reason_type}; last={session}")


async def _wait_for_event_type(client, session_id: str, event_type: str):
    for _ in range(30):
        response = await client.get(f"/v1/sessions/{session_id}/events", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        events = response.json()["data"]
        if any(event["type"] == event_type for event in events):
            return events
        await asyncio.sleep(0.05)
    raise AssertionError(f"session did not emit {event_type}; last={events}")


async def test_custom_tool_requires_action_and_resumes_from_result(client):
    agent = await _create_agent(client, tools=[{"type": "custom", "name": "lookup_customer"}])
    environment = await _create_environment(client)
    session = await _create_session(client, agent, environment)

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "lookup acme"}]},
    )
    assert response.status_code == 200, response.text

    session = await _wait_for_stop_reason(client, session["id"], "requires_action")
    custom_tool_use_id = session["stop_reason"]["event_ids"][0]
    events = await _wait_for_event_type(client, session["id"], "agent.custom_tool_use")
    assert next(event for event in events if event["id"] == custom_tool_use_id)["name"] == "lookup_customer"

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "new request before tool result"}]},
    )
    assert response.status_code == 409

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={
            "events": [
                {
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": custom_tool_use_id,
                    "content": [{"type": "text", "text": "ACME is enterprise."}],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    events = await _wait_for_event_type(client, session["id"], "agent.message")
    assert any("custom tool result" in str(event.get("content")) for event in events if event["type"] == "agent.message")


async def test_tool_confirmation_requires_action_and_resumes(client):
    agent = await _create_agent(
        client,
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"permission_policy": {"type": "always_ask"}},
            }
        ],
    )
    environment = await _create_environment(client)
    session = await _create_session(client, agent, environment)

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "run shell"}]},
    )
    assert response.status_code == 200, response.text

    session = await _wait_for_stop_reason(client, session["id"], "requires_action")
    tool_use_id = session["stop_reason"]["event_ids"][0]
    events = await _wait_for_event_type(client, session["id"], "agent.tool_use")
    assert next(event for event in events if event["id"] == tool_use_id)["name"] == "bash"

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.tool_confirmation", "tool_use_id": tool_use_id, "result": "allow"}]},
    )
    assert response.status_code == 200, response.text
    events = await _wait_for_event_type(client, session["id"], "agent.message")
    assert any("tool confirmation" in str(event.get("content")) for event in events if event["type"] == "agent.message")


async def test_running_session_blocks_mutations(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)
    session = await _create_session(client, agent, environment)

    async with session_scope() as db:
        db_session = await sessions_q.get_session(db, session["id"])
        assert db_session is not None
        await sessions_q.update_session(db, db_session, status="running", stop_reason={"type": "in_progress"})
        await db.commit()

    response = await client.patch(
        f"/v1/sessions/{session['id']}",
        headers=TEST_HEADERS,
        json={"title": "blocked"},
    )
    assert response.status_code == 409

    response = await client.post(f"/v1/sessions/{session['id']}/archive", headers=TEST_HEADERS)
    assert response.status_code == 409

    response = await client.delete(f"/v1/sessions/{session['id']}", headers=TEST_HEADERS)
    assert response.status_code == 409


async def test_session_local_agent_update_does_not_mutate_agent_version(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)
    session = await _create_session(client, agent, environment)

    response = await client.patch(
        f"/v1/sessions/{session['id']}",
        headers=TEST_HEADERS,
        json={"agent": {"tools": [{"type": "custom", "name": "session_lookup"}]}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status_details"]["agent"]["tools"][0]["name"] == "session_lookup"

    response = await client.get(f"/v1/agents/{agent['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["tools"] == []
    assert response.json()["version"] == 1

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "use session tool"}]},
    )
    assert response.status_code == 200, response.text
    session = await _wait_for_stop_reason(client, session["id"], "requires_action")
    events = await _wait_for_event_type(client, session["id"], "agent.custom_tool_use")
    assert next(event for event in events if event["id"] == session["stop_reason"]["event_ids"][0])["name"] == "session_lookup"


async def test_file_session_resource_creates_session_scoped_copy(client):
    response = await client.post(
        "/v1/files",
        headers=TEST_HEADERS,
        files={"file": ("notes.txt", b"session notes", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file = response.json()

    agent = await _create_agent(client)
    environment = await _create_environment(client)
    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "resources": [{"type": "file", "file_id": file["id"], "mount_path": "/workspace/notes.txt"}],
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    file_resource = next(resource for resource in session["resources"] if resource["type"] == "file")
    assert file_resource == {
        "id": file_resource["id"],
        "type": "file",
        "file_id": file["id"],
        "mount_path": "/workspace/notes.txt",
        "created_at": file_resource["created_at"],
        "updated_at": file_resource["updated_at"],
    }

    async with session_scope() as db:
        resources = await res_q.list_resources(
            db,
            resource_type="session_resource",
            parent_id=session["id"],
            limit=10,
        )

    stored = resources[0].data["session_file"]
    assert stored["source_file_id"] == file["id"]
    assert stored["filename"] == "notes.txt"
    assert stored["storage"]["key"].startswith(f"workspaces/wrkspc_default/sessions_{session['id']}/resources/")
