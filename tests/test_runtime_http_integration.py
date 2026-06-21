import asyncio
import json
from types import SimpleNamespace

import httpx

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


async def test_openai_compatible_runtime_uses_provider_base_url_and_filters_unsupported_params(monkeypatch):
    monkeypatch.setenv("WIRE_API_KEY", "wire-provider-key")
    monkeypatch.setenv("OPENAI_AGENTS_DISABLE_TRACING", "true")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        json.dumps(
            {
                "wire": {
                    "api_key_env": "WIRE_API_KEY",
                    "base_url": "https://wire.example.invalid/v1",
                    "default_model": "wire-chat",
                    "capabilities": {
                        "unsupported_parameters": ["presence_penalty", "reasoning"],
                    },
                }
            }
        ),
    )
    get_settings.cache_clear()

    from agents.models import openai_provider as sdk_openai_provider

    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "body": body,
            }
        )
        chunk_base = {
            "id": "chatcmpl_wire",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "wire-chat",
        }
        chunks = [
            {**chunk_base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {**chunk_base, "choices": [{"index": 0, "delta": {"content": "wire response"}, "finish_reason": None}]},
            {
                **chunk_base,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        ]
        stream = "".join(f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n" for chunk in chunks)
        stream += "data: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream.encode("utf-8"),
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sdk_openai_provider, "shared_http_client", lambda: http_client)

    try:
        from app.runtime.runner import _execute_openai

        version = SimpleNamespace(
            id="agentver_wire",
            agent_id="agent_wire",
            version=1,
            name="Wire Agent",
            system="Use the wire provider.",
            model={
                "provider": "wire",
                "id": "wire-chat",
                "settings": {
                    "temperature": 0.4,
                    "presence_penalty": 1.0,
                    "reasoning": {"effort": "low"},
                },
            },
            runtime={},
            tools=[],
            mcp_servers=[],
            skills=[],
            multiagent=None,
            metadata_={},
        )
        history = [
            SimpleNamespace(
                type="user.message",
                payload={"content": [{"type": "text", "text": "call the wire provider"}]},
            )
        ]

        result = await _execute_openai(version, history, {"type": "cloud"}, runtime_context={"memory_stores": []})
    finally:
        await http_client.aclose()

    assert result.final_text == "wire response"
    assert result.run_state["provider"] == "wire"
    assert result.run_state["model"] == "wire-chat"
    assert result.run_state["filtered_model_settings"] == {
        "presence_penalty": 1.0,
        "reasoning": {"effort": "low"},
    }

    assert len(requests) == 1
    request = requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://wire.example.invalid/v1/chat/completions"
    assert request["authorization"] == "Bearer wire-provider-key"
    body = request["body"]
    assert body["model"] == "wire-chat"
    assert body["stream"] is True
    assert body["temperature"] == 0.4
    assert "presence_penalty" not in body
    assert "reasoning_effort" not in body
    assert body["messages"][0] == {"role": "system", "content": "Use the wire provider."}
    assert body["messages"][-1] == {"role": "user", "content": "call the wire provider"}
