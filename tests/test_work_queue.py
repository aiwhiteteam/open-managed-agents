import asyncio
from datetime import datetime, timedelta, timezone

from app.db.engine import session_scope
from app.db.queries import resources as res_q
from tests.conftest import TEST_HEADERS


async def _create_agent(client):
    response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "Queue Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment(client, env_type: str):
    response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": f"{env_type}-queue", "config": {"type": env_type}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_session(client, agent, environment):
    response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_inline_environment_queues_and_completes_work(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client, "cloud")
    session = await _create_session(client, agent, environment)

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "run inline"}]},
    )
    assert response.status_code == 200, response.text

    for _ in range(20):
        response = await client.get(f"/v1/environments/{environment['id']}/work/stats", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        stats = response.json()
        if stats["completed"] == 1:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"work did not complete; stats={stats}")


async def test_self_hosted_environment_leases_work_without_inline_execution(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client, "self_hosted")
    session = await _create_session(client, agent, environment)

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "lease me"}]},
    )
    assert response.status_code == 200, response.text

    response = await client.get(f"/v1/environments/{environment['id']}/work/stats", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["queued"] == 1

    response = await client.get(
        f"/v1/environments/{environment['id']}/work/poll",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-1", "lease_seconds": 30},
    )
    assert response.status_code == 200, response.text
    work = response.json()
    assert work["status"] == "leased"
    assert work["session_id"] == session["id"]
    assert work["lease"]["worker_id"] == "worker-1"

    response = await client.post(
        f"/v1/environments/{environment['id']}/work/{work['id']}/ack",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-2"},
    )
    assert response.status_code == 409
    assert "does not own" in response.json()["error"]["message"]

    response = await client.post(
        f"/v1/environments/{environment['id']}/work/{work['id']}/ack",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"

    response = await client.post(
        f"/v1/environments/{environment['id']}/work/{work['id']}/heartbeat",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-1", "lease_seconds": 30},
        json={"progress": 0.5},
    )
    assert response.status_code == 200, response.text
    assert response.json()["last_heartbeat"]["progress"] == 0.5

    response = await client.post(
        f"/v1/environments/{environment['id']}/work/{work['id']}/heartbeat",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-2", "lease_seconds": 30},
        json={"progress": 0.9},
    )
    assert response.status_code == 409

    response = await client.post(
        f"/v1/environments/{environment['id']}/work/{work['id']}/stop",
        headers=TEST_HEADERS,
        json={"reason": "test stop"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stopped"
    assert response.json()["stop"]["reason"] == "test stop"


async def test_expired_work_lease_can_be_recovered_by_next_worker(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client, "self_hosted")
    session = await _create_session(client, agent, environment)

    response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "recover lease"}]},
    )
    assert response.status_code == 200, response.text

    response = await client.get(
        f"/v1/environments/{environment['id']}/work/poll",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-1", "lease_seconds": 30},
    )
    assert response.status_code == 200, response.text
    first_lease = response.json()
    assert first_lease["attempt"] == 1

    async with session_scope() as db:
        work = await res_q.get_resource(
            db,
            resource_id=first_lease["id"],
            resource_type="environment_work",
            parent_id=environment["id"],
        )
        assert work is not None
        data = dict(work.data)
        data["lease"] = {
            **dict(data["lease"]),
            "expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(),
        }
        await res_q.update_resource(db, work, data=data, status="running")
        await db.commit()

    response = await client.get(
        f"/v1/environments/{environment['id']}/work/poll",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-2", "lease_seconds": 30},
    )

    assert response.status_code == 200, response.text
    recovered = response.json()
    assert recovered["id"] == first_lease["id"]
    assert recovered["status"] == "leased"
    assert recovered["attempt"] == 2
    assert recovered["lease"]["worker_id"] == "worker-2"


async def test_rescheduled_work_is_not_leased_until_retry_at(client):
    agent = await _create_agent(client)
    environment = await _create_environment(client, "self_hosted")
    session = await _create_session(client, agent, environment)
    future_retry_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    async with session_scope() as db:
        work = await res_q.create_resource(
            db,
            resource_type="environment_work",
            parent_id=environment["id"],
            name=f"session:{session['id']}",
            status="rescheduling",
            data={"session_id": session["id"], "attempt": 1, "retry_at": future_retry_at},
        )
        await db.commit()
        work_id = work.id

    response = await client.get(f"/v1/environments/{environment['id']}/work/stats", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["rescheduling"] == 1

    response = await client.get(
        f"/v1/environments/{environment['id']}/work/poll",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-1", "lease_seconds": 30},
    )
    assert response.status_code == 200, response.text
    assert response.json() is None

    async with session_scope() as db:
        work = await res_q.get_resource(
            db,
            resource_id=work_id,
            resource_type="environment_work",
            parent_id=environment["id"],
        )
        assert work is not None
        data = dict(work.data)
        data["retry_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        await res_q.update_resource(db, work, data=data, status="rescheduling")
        await db.commit()

    response = await client.get(
        f"/v1/environments/{environment['id']}/work/poll",
        headers=TEST_HEADERS,
        params={"worker_id": "worker-2", "lease_seconds": 30},
    )
    assert response.status_code == 200, response.text
    leased = response.json()
    assert leased["id"] == work_id
    assert leased["status"] == "leased"
    assert leased["lease"]["worker_id"] == "worker-2"
