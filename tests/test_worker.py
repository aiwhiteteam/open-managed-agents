from app.worker import run_worker
from tests.conftest import TEST_HEADERS


async def test_worker_once_consumes_queued_work(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Worker Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    agent = response.json()

    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": "self-hosted-worker", "config": {"type": "self_hosted"}},
    )
    assert response.status_code == 201, response.text
    environment = response.json()

    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={"agent": {"id": agent["id"], "version": 1}, "environment_id": environment["id"]},
    )
    assert response.status_code == 201, response.text
    session = response.json()

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "work"}]},
    )
    assert response.status_code == 200, response.text

    await run_worker(environment_id=environment["id"], poll_interval_seconds=0.01, once=True)

    response = await client.get(f"/v1/environments/{environment['id']}/work/stats", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["completed"] == 1


async def test_vault_credential_response_redacts_secret_fields(client):
    response = await client.post("/v1/vaults", headers=TEST_HEADERS, json={"name": "Main"})
    assert response.status_code == 201, response.text
    vault = response.json()

    response = await client.post(
        f"/v1/vaults/{vault['id']}/credentials",
        headers=TEST_HEADERS,
        json={
            "name": "github",
            "api_key": "sk-test",
            "nested": {"access_token": "secret-token", "safe": "value"},
        },
    )
    assert response.status_code == 201, response.text
    credential = response.json()

    assert credential["api_key"] == "redacted"
    assert credential["nested"]["access_token"] == "redacted"
    assert credential["nested"]["safe"] == "value"
