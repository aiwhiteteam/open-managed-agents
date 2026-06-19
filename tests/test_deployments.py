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
        json={"name": "Paused deployment", "status": "paused"},
    )
    assert response.status_code == 201, response.text
    deployment = response.json()

    response = await client.post(f"/v1/deployments/{deployment['id']}/run", headers=TEST_HEADERS)
    assert response.status_code == 409
