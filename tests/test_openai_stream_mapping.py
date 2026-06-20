from types import SimpleNamespace

from app.runtime.runner import RuntimeResult, _is_required_action_event, _map_openai_stream_event


def _run_item_event(name: str, raw_item: dict, **item_attrs):
    item = SimpleNamespace(raw_item=raw_item, **item_attrs)
    return SimpleNamespace(type="run_item_stream_event", name=name, item=item)


def test_openai_stream_message_maps_to_agent_message():
    event = _run_item_event(
        "message_output_created",
        {"content": [{"type": "output_text", "text": "hello"}]},
    )

    mapped = _map_openai_stream_event(event)

    assert mapped == {
        "type": "agent.message",
        "content": [{"type": "text", "text": "hello"}],
        "source": "openai_agents_sdk",
    }


def test_openai_stream_tool_call_maps_arguments_and_ids():
    event = _run_item_event(
        "tool_called",
        {
            "type": "function_call",
            "name": "lookup_customer",
            "arguments": '{"customer_id":"cus_123"}',
            "call_id": "call_123",
        },
    )

    mapped = _map_openai_stream_event(event)

    assert mapped["type"] == "agent.tool_use"
    assert mapped["name"] == "lookup_customer"
    assert mapped["tool_use_id"] == "call_123"
    assert mapped["input"] == {"customer_id": "cus_123"}


def test_openai_stream_tool_output_maps_to_tool_result():
    event = _run_item_event(
        "tool_output",
        {"type": "function_call_output", "call_id": "call_123"},
        output="customer found",
    )

    mapped = _map_openai_stream_event(event)

    assert mapped["type"] == "agent.tool_result"
    assert mapped["tool_use_id"] == "call_123"
    assert mapped["content"] == [{"type": "text", "text": "customer found"}]


def test_openai_stream_mcp_approval_maps_to_confirmable_tool_use():
    event = _run_item_event(
        "mcp_approval_requested",
        {
            "type": "mcp_approval_request",
            "name": "read_file",
            "arguments": {"path": "/workspace/report.md"},
            "id": "mcp_123",
        },
    )

    mapped = _map_openai_stream_event(event)

    assert mapped["type"] == "agent.mcp_tool_use"
    assert mapped["name"] == "read_file"
    assert mapped["tool_use_id"] == "mcp_123"
    assert mapped["requires_confirmation"] is True
    assert mapped["permission_policy"] == {"type": "always_ask"}


def test_openai_stream_reasoning_maps_to_span_event():
    event = _run_item_event(
        "reasoning_item_created",
        {"type": "reasoning", "summary": [{"text": "checked constraints"}]},
    )

    mapped = _map_openai_stream_event(event)

    assert mapped["type"] == "span.reasoning"
    assert mapped["content"][0]["json"]["type"] == "reasoning"


def test_openai_agent_update_maps_to_agent_event():
    event = SimpleNamespace(
        type="agent_updated_stream_event",
        new_agent=SimpleNamespace(name="Researcher"),
    )

    mapped = _map_openai_stream_event(event)

    assert mapped == {
        "type": "agent.updated",
        "name": "Researcher",
        "source": "openai_agents_sdk",
    }


def test_explicit_confirmation_only_blocks_marked_events():
    result = RuntimeResult(
        final_text="",
        requires_action=True,
        tool_events=[
            {"type": "agent.tool_use", "name": "ordinary_tool"},
            {"type": "agent.mcp_tool_use", "name": "mcp_tool", "requires_confirmation": True},
        ],
    )

    ordinary, approval = result.tool_events

    assert _is_required_action_event(result, ordinary, explicit_confirmation_events=True) is False
    assert _is_required_action_event(result, approval, explicit_confirmation_events=True) is True


def test_implicit_local_required_action_keeps_existing_blocking_behavior():
    result = RuntimeResult(
        final_text="",
        requires_action=True,
        tool_events=[{"type": "agent.custom_tool_use", "name": "lookup"}],
    )

    assert _is_required_action_event(
        result,
        result.tool_events[0],
        explicit_confirmation_events=False,
    ) is True
