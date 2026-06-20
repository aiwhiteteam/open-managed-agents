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
    assert resources_by_type["file"]["file_id"] == file["id"]
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
        json={"name": "Paused deployment", "status": "paused"},
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 409
