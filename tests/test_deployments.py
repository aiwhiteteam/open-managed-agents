from tests.conftest import TEST_HEADERS


async def _create_agent(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Deployment Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment(client):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": "deployment-env", "config": {"type": "cloud"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_deployment_schedule_validation_and_run_session_linkage(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Daily report",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": [{"type": "text", "text": "Run report."}]}],
            "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "America/New_York"},
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()
    assert deployment["schedule"]["cron"] == "0 9 * * *"
    assert deployment["schedule"]["timezone"] == "America/New_York"
    assert deployment["schedule"]["enabled"] is True
    assert len(deployment["schedule"]["upcoming_runs_at"]) == 5

    response = await client.post(
        f"/v1/deployments/{deployment['id']}/run",
        headers=TEST_HEADERS,
        json={"trigger": "manual", "title": "Run now"},
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["type"] == "deployment_run"
    assert run["deployment_id"] == deployment["id"]
    assert run["session_id"].startswith("sess_")

    response = await client.get(f"/v1/sessions/{run['session_id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["metadata"]["deployment_id"] == deployment["id"]
    assert session["metadata"]["deployment_run_id"] == run["id"]

    response = await client.get(f"/v1/sessions/{run['session_id']}/events", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    events = response.json()["data"]
    assert [event["type"] for event in events][:2] == ["session.status_idle", "user.message"]
    assert events[1]["processed_at"] is None

    response = await client.post(
        f"/v1/deployments/{deployment['id']}/run",
        headers=TEST_HEADERS,
        json={"trigger": "schedule", "scheduled_for": deployment["schedule"]["upcoming_runs_at"][0]},
    )
    assert response.status_code == 200, response.text

    response = await client.get(f"/v1/deployments/{deployment['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    scheduled_deployment = response.json()
    assert scheduled_deployment["schedule"]["last_run_at"] is not None
    assert len(scheduled_deployment["schedule"]["upcoming_runs_at"]) == 5


async def test_deployment_agent_string_pins_latest_version(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.patch(
        f"/v1/agents/{agent['id']}",
        headers=TEST_HEADERS,
        json={"version": agent["version"], "system": "v2"},
    )
    assert response.status_code == 200, response.text
    agent_v2 = response.json()

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Latest agent deployment",
            "agent": agent["id"],
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "latest"}],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()
    assert deployment["agent"]["version"] == agent_v2["version"]

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    run = response.json()
    response = await client.get(f"/v1/sessions/{run['session_id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["agent_version"] == agent_v2["version"]


async def test_deployment_run_validates_session_vault_ids(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)
    response = await client.post("/v1/vaults", headers=TEST_HEADERS, json={"display_name": "Deployment Vault"})
    assert response.status_code == 201, response.text
    vault = response.json()

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Vaulted deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "vaulted run"}],
            "vault_ids": [vault["id"], vault["id"]],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    run = response.json()
    response = await client.get(f"/v1/sessions/{run['session_id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["vault_ids"] == [vault["id"]]

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Missing vault deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "missing vault"}],
            "vault_ids": ["vault_missing"],
        },
    )
    assert response.status_code == 201, response.text
    missing_vault_deployment = response.json()

    response = await client.post(f"/v1/deployments/{missing_vault_deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 404


async def test_deployment_run_mounts_deployment_resources(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/files",
        headers=TEST_HEADERS,
        files={"file": ("deployment-notes.txt", b"deployment notes", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file = response.json()

    response = await client.post(
        "/v1/memory_stores",
        headers=TEST_HEADERS,
        json={"name": "Deployment memory", "description": "Shared deployment context."},
    )
    assert response.status_code == 201, response.text
    memory_store = response.json()

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Resource deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "resource run"}],
            "resources": [
                {
                    "type": "file",
                    "file_id": file["id"],
                    "mount_path": "/workspace/deployment-notes.txt",
                },
                {
                    "type": "github_repository",
                    "url": "https://github.com/example/resource-repo",
                    "mount_path": "/workspace/resource-repo",
                    "authorization_token": "ghp_secret",
                    "checkout": {"type": "branch", "name": "main"},
                },
                {
                    "type": "memory_store",
                    "memory_store_id": memory_store["id"],
                    "access": "read_only",
                    "instructions": "Use deployment memory.",
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()
    deployment_resources_by_type = {resource["type"]: resource for resource in deployment["resources"]}
    assert "authorization_token" not in deployment_resources_by_type["github_repository"]

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    run = response.json()

    response = await client.get(f"/v1/sessions/{run['session_id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    session = response.json()
    resources_by_type = {resource["type"]: resource for resource in session["resources"]}
    assert resources_by_type["file"]["file_id"] != file["id"]
    assert resources_by_type["file"]["mount_path"] == "/workspace/deployment-notes.txt"
    assert resources_by_type["github_repository"]["url"] == "https://github.com/example/resource-repo"
    assert resources_by_type["github_repository"]["checkout"] == {"type": "branch", "name": "main"}
    assert "authorization_token" not in resources_by_type["github_repository"]
    assert resources_by_type["memory_store"]["memory_store_id"] == memory_store["id"]
    assert resources_by_type["memory_store"]["instructions"] == "Use deployment memory."

    response = await client.get(f"/v1/sessions/{run['session_id']}/resources", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert {resource["type"] for resource in response.json()["data"]} == {"file", "github_repository", "memory_store"}


async def test_deployment_rejects_bad_timezone_and_paused_run(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Bad schedule",
            "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "Mars/Base"},
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={"name": "Bad cron", "schedule": {"type": "cron", "cron": "99 9 * * *", "timezone": "UTC"}},
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Missing initial events",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "System-only initial events",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "system.message", "content": "context only"}],
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Paused deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "paused"}],
            "status": "paused",
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()
    assert deployment["paused_reason"] == {"type": "manual"}

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["session_id"].startswith("sess_")

    response = await client.post(
        f"/v1/deployments/{deployment['id']}/run",
        headers=TEST_HEADERS,
        json={"trigger": "schedule", "scheduled_for": "2026-06-20T12:00:00Z"},
    )
    assert response.status_code == 409


async def test_deployment_run_records_session_creation_errors(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Archived environment deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "run"}],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/environments/{environment['id']}/archive", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["type"] == "deployment_run"
    assert run["session_id"] is None
    assert run["error"]["type"] == "environment_archived_error"


async def test_deployment_archives_without_run_when_primary_agent_is_archived(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Archived agent deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "run"}],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/agents/{agent['id']}/archive", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 409

    response = await client.get(f"/v1/deployments/{deployment['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["archived_at"] is not None

    response = await client.get(
        "/v1/deployment_runs",
        headers=TEST_HEADERS,
        params={"deployment_id": deployment["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


async def test_archived_deployment_is_terminal(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client)

    response = await client.post(
        "/v1/deployments",
        headers=TEST_HEADERS,
        json={
            "name": "Terminal deployment",
            "agent": {"id": agent["id"], "version": 1},
            "environment_id": environment["id"],
            "initial_events": [{"type": "user.message", "content": "run"}],
        },
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/deployments/{deployment['id']}/archive", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text

    response = await client.post(
        f"/v1/deployments/{deployment['id']}",
        headers=TEST_HEADERS,
        json={"metadata": {"after": "archive"}},
    )
    assert response.status_code == 409

    response = await client.post(f"/v1/deployments/{deployment['id']}/pause", headers=TEST_HEADERS)
    assert response.status_code == 409

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 409
