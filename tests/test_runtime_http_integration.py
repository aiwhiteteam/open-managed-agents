import asyncio

from app.config import get_settings
from app.runtime.providers import resolve_runtime_provider
from app.runtime.runner import RuntimeResult
from tests.conftest import TEST_HEADERS


async def _wait_for_agent_message(client, session_id: str):
    for _ in range(30):
        response = await client.get(f"/v1/sessions/{session_id}/events", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        events = response.json()["data"]
        messages = [event for event in events if event["type"] == "agent.message"]
        if messages:
            return messages[-1]
        await asyncio.sleep(0.05)
    raise AssertionError(f"session did not emit agent.message; last={events}")


async def test_http_session_turn_uses_mocked_openai_compatible_runtime(client, monkeypatch):
    monkeypatch.setenv("OMA_RUNTIME_BACKEND", "openai_compatible")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"deepseek":{"api_key_env":"DEEPSEEK_API_KEY","base_url":"https://api.deepseek.com/v1","default_model":"deepseek-chat"}}',
    )
    get_settings.cache_clear()

    from app.runtime import runner

    async def fake_execute_openai(version, history, environment_config, *, runtime_context=None):
        provider = resolve_runtime_provider(version.model)
        assert provider.provider == "deepseek"
        assert provider.model_id == "deepseek-chat"
        assert provider.base_url == "https://api.deepseek.com/v1"
        assert provider.api_key == "test-deepseek-key"
        user_messages = [event for event in history if event.type == "user.message"]
        assert user_messages[-1].payload["content"] == "call compatible provider"
        assert environment_config["type"] == "cloud"
        assert runtime_context["memory_stores"] == []
        return RuntimeResult(
            final_text="mocked openai-compatible response",
            run_state={
                "backend": "mocked_openai_compatible",
                "provider": provider.provider,
                "model": provider.model_id,
            },
            sandbox_state={"enabled": False, "runtime_backend": "mocked"},
            usage={"input_tokens": 3, "output_tokens": 4},
        )

    monkeypatch.setattr(runner, "_execute_openai", fake_execute_openai)

    agent_response = await client.post(
        "/v1/agents",
        headers=TEST_HEADERS,
        json={"name": "DeepSeek Agent", "model": {"provider": "deepseek", "id": "deepseek-chat"}},
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()

    environment_response = await client.post(
        "/v1/environments",
        headers=TEST_HEADERS,
        json={"name": "cloud-runtime", "config": {"type": "cloud"}},
    )
    assert environment_response.status_code == 201, environment_response.text
    environment = environment_response.json()

    session_response = await client.post(
        "/v1/sessions",
        headers=TEST_HEADERS,
        json={
            "agent": {"type": "agent", "id": agent["id"], "version": 1},
            "environment_id": environment["id"],
        },
    )
    assert session_response.status_code == 201, session_response.text
    session = session_response.json()

    send_response = await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=TEST_HEADERS,
        json={"events": [{"type": "user.message", "content": "call compatible provider"}]},
    )
    assert send_response.status_code == 200, send_response.text

    message = await _wait_for_agent_message(client, session["id"])
    assert message["content"] == [{"type": "text", "text": "mocked openai-compatible response"}]

    response = await client.get(f"/v1/sessions/{session['id']}", headers=TEST_HEADERS)
    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "idle"
    assert completed["stop_reason"] == {"type": "end_turn"}
    assert completed["run_state"] == {
        "backend": "mocked_openai_compatible",
        "provider": "deepseek",
        "model": "deepseek-chat",
    }

    events_response = await client.get(f"/v1/sessions/{session['id']}/events", headers=TEST_HEADERS)
    assert events_response.status_code == 200, events_response.text
    idle_events = [event for event in events_response.json()["data"] if event["type"] == "session.status_idle"]
    assert idle_events[-1]["usage"] == {"input_tokens": 3, "output_tokens": 4}
