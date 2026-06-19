import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import get_settings
from app.db.engine import session_scope
from app.db.queries import agents as agents_q
from app.db.queries import environments as env_q
from app.db.queries import events as events_q
from app.db.queries import sessions as sessions_q
from app.runtime.providers import resolve_runtime_provider, runtime_provider_configured
from app.runtime.sandbox import sandbox_plan_from_environment

logger = structlog.get_logger()
_running_sessions: set[str] = set()
_running_lock = asyncio.Lock()


@dataclass
class RuntimeResult:
    final_text: str
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    run_state: dict[str, Any] | None = None
    sandbox_state: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


def schedule_session_run(session_id: str) -> None:
    asyncio.create_task(run_session_turn(session_id))


async def run_session_turn(session_id: str) -> None:
    async with _running_lock:
        if session_id in _running_sessions:
            logger.info("session_already_running", session_id=session_id)
            return
        _running_sessions.add(session_id)

    try:
        await _run_session_turn(session_id)
    finally:
        async with _running_lock:
            _running_sessions.discard(session_id)


async def _run_session_turn(session_id: str) -> None:
    async with session_scope() as db:
        session = await sessions_q.get_session(db, session_id)
        if session is None or session.deleted_at is not None:
            return
        if session.status == "terminated":
            return
        await sessions_q.update_session(db, session, status="running", stop_reason={"type": "in_progress"})
        await events_q.append_event(
            db,
            session,
            event_type="session.status_running",
            payload={"type": "session.status_running", "status": "running"},
        )
        await db.commit()

    try:
        async with session_scope() as db:
            session = await sessions_q.get_session(db, session_id)
            if session is None:
                return
            agent = await agents_q.get_agent(db, session.agent_id)
            if agent is None:
                raise RuntimeError(f"Agent {session.agent_id} not found")
            version = await agents_q.get_agent_version(
                db,
                agent_id=session.agent_id,
                version=session.agent_version,
            )
            if version is None:
                raise RuntimeError(f"Agent version {session.agent_version} not found")
            environment = await env_q.get_environment(db, session.environment_id)
            if environment is None or environment.deleted_at is not None:
                raise RuntimeError(f"Environment {session.environment_id} not found")
            history = await events_q.list_events(db, session_id=session.id, after_seq=0, limit=500)

        result = await _execute(version, history, environment.config)

        async with session_scope() as db:
            session = await sessions_q.get_session(db, session_id)
            if session is None:
                return
            for tool_event in result.tool_events:
                await events_q.append_event(
                    db,
                    session,
                    event_type=tool_event["type"],
                    payload=tool_event,
                )
            if result.final_text:
                await events_q.append_event(
                    db,
                    session,
                    event_type="agent.message",
                    payload={
                        "type": "agent.message",
                        "content": [{"type": "text", "text": result.final_text}],
                    },
                )
            stop_reason = {"type": "end_turn"}
            await sessions_q.update_session(
                db,
                session,
                status="idle",
                stop_reason=stop_reason,
                run_state=result.run_state,
                sandbox_state=result.sandbox_state,
            )
            await events_q.append_event(
                db,
                session,
                event_type="session.status_idle",
                payload={
                    "type": "session.status_idle",
                    "status": "idle",
                    "stop_reason": stop_reason,
                    "usage": result.usage or {},
                },
            )
            await db.commit()
    except Exception as exc:
        logger.exception("session_run_failed", session_id=session_id)
        async with session_scope() as db:
            session = await sessions_q.get_session(db, session_id)
            if session is None:
                return
            stop_reason = {"type": "error"}
            await sessions_q.update_session(db, session, status="error", stop_reason=stop_reason)
            await events_q.append_event(
                db,
                session,
                event_type="session.error",
                payload={
                    "type": "session.error",
                    "message": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )
            await db.commit()


async def _execute(version, history, environment_config: dict[str, Any] | None = None) -> RuntimeResult:
    settings = get_settings()
    backend = settings.oma_runtime_backend
    if backend == "auto":
        backend = "openai" if runtime_provider_configured(version.model) else "local"
    if backend in {"openai", "openai_compatible"}:
        try:
            return await _execute_openai(version, history, environment_config)
        except ImportError:
            if settings.oma_runtime_backend == "openai":
                raise
            logger.warning("openai_agents_sdk_unavailable_falling_back_to_local")
    return await _execute_local(version, history, environment_config)


async def _execute_openai(version, history, environment_config: dict[str, Any] | None = None) -> RuntimeResult:
    from agents import Agent, ModelSettings, RunConfig, Runner
    from agents.models.openai_provider import OpenAIProvider
    from agents.sandbox import SandboxAgent

    provider = resolve_runtime_provider(version.model)
    model_settings, removed_model_settings = _model_settings_for_provider(
        version.runtime,
        version.model,
        provider.capabilities,
        ModelSettings,
    )
    sandbox_plan = sandbox_plan_from_environment(environment_config)
    agent_class = SandboxAgent if sandbox_plan.enabled and sandbox_plan.sdk_supported else Agent
    agent_kwargs: dict[str, Any] = {}
    if agent_class is SandboxAgent:
        agent_kwargs["default_manifest"] = sandbox_plan.run_config.manifest
    agent = agent_class(
        name=version.name,
        instructions=version.system or "You are a helpful managed agent.",
        model=provider.model_id,
        model_settings=model_settings,
        **agent_kwargs,
    )
    sdk_input = _history_to_openai_input(history)
    model_provider = OpenAIProvider(
        api_key=provider.api_key,
        base_url=provider.base_url,
        use_responses=provider.use_responses,
    )
    run_config_kwargs: dict[str, Any] = {}
    if sandbox_plan.run_config is not None:
        run_config_kwargs["sandbox"] = sandbox_plan.run_config
    run_config = RunConfig(
        model_provider=model_provider,
        trace_metadata={
            "managed_agent_id": version.agent_id,
            "managed_agent_version": version.version,
            "model_provider": provider.provider,
            "model": provider.model_id,
            "sandbox_backend": sandbox_plan.backend,
            "sandbox_enabled": sandbox_plan.enabled,
        },
        **run_config_kwargs,
    )
    result = Runner.run_streamed(agent, input=sdk_input, run_config=run_config)

    tool_events: list[dict[str, Any]] = []
    async for event in result.stream_events():
        maybe_tool = _map_openai_stream_event(event)
        if maybe_tool:
            tool_events.append(maybe_tool)

    final_output = getattr(result, "final_output", None)
    return RuntimeResult(
        final_text=str(final_output or ""),
        tool_events=tool_events,
        run_state={
            "backend": "openai_agents_sdk",
            "provider": provider.provider,
            "model": provider.model_id,
            "provider_capabilities": {
                "chat_completions": provider.capabilities.chat_completions,
                "responses_api": provider.capabilities.responses_api,
                "streaming": provider.capabilities.streaming,
                "tool_calls": provider.capabilities.tool_calls,
                "hosted_tools": provider.capabilities.hosted_tools,
                "multimodal_input": provider.capabilities.multimodal_input,
                "reasoning_traces": provider.capabilities.reasoning_traces,
                "unsupported_parameters": list(provider.capabilities.unsupported_parameters),
            },
            "filtered_model_settings": removed_model_settings,
            "sdk_state": _safe_state(result),
        },
        sandbox_state=sandbox_plan.summary,
        usage=_safe_usage(result),
    )


async def _execute_local(version, history, environment_config: dict[str, Any] | None = None) -> RuntimeResult:
    await asyncio.sleep(0.05)
    sandbox_plan = sandbox_plan_from_environment(environment_config)
    latest = _latest_user_text(history)
    if latest:
        text = f"Open Managed Agents local runtime received: {latest}"
    else:
        text = "Open Managed Agents local runtime is idle."
    return RuntimeResult(
        final_text=text,
        run_state={"backend": "local", "agent_version_id": version.id},
        sandbox_state={**sandbox_plan.summary, "runtime_backend": "local"},
    )


def _history_to_openai_input(history) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in history:
        text = _text_from_payload(event.payload)
        if not text:
            continue
        if event.type == "user.message":
            items.append({"role": "user", "content": text})
        elif event.type == "agent.message":
            items.append({"role": "assistant", "content": text})
    if not items:
        items.append({"role": "user", "content": ""})
    return items


def _model_settings_for_provider(
    runtime: dict[str, Any] | None,
    model: dict[str, Any] | None,
    capabilities,
    model_settings_cls,
):
    raw_settings: dict[str, Any] = {}
    if isinstance(model, dict) and isinstance(model.get("settings"), dict):
        raw_settings.update(model["settings"])
    if isinstance(runtime, dict) and isinstance(runtime.get("model_settings"), dict):
        raw_settings.update(runtime["model_settings"])
    if not raw_settings:
        return model_settings_cls(), {}

    allowed_fields = set(getattr(model_settings_cls, "__annotations__", {}).keys())
    unsupported = set(capabilities.unsupported_parameters)
    if not capabilities.reasoning_traces:
        unsupported.add("reasoning")
    if not capabilities.responses_api:
        unsupported.update({"store", "prompt_cache_retention", "response_include", "context_management"})

    filtered = {
        key: value
        for key, value in raw_settings.items()
        if key in allowed_fields and key not in unsupported
    }
    removed = {
        key: value
        for key, value in raw_settings.items()
        if key not in filtered
    }
    return model_settings_cls(**filtered), removed


def _latest_user_text(history) -> str:
    for event in reversed(history):
        if event.type == "user.message":
            return _text_from_payload(event.payload)
    return ""


def _text_from_payload(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    text = payload.get("text") or payload.get("message")
    return text if isinstance(text, str) else ""


def _map_openai_stream_event(event) -> dict[str, Any] | None:
    event_type = getattr(event, "type", "")
    if event_type != "run_item_stream_event":
        return None
    name = getattr(event, "name", "")
    item = getattr(event, "item", None)
    if name == "tool_called":
        return {
            "type": "agent.tool_use",
            "name": getattr(item, "name", "tool"),
            "input": _jsonish(getattr(item, "arguments", None)),
        }
    if name == "tool_output":
        return {
            "type": "agent.tool_result",
            "name": getattr(item, "name", "tool"),
            "content": [{"type": "text", "text": str(getattr(item, "output", ""))}],
        }
    return None


def _safe_state(result) -> dict[str, Any] | None:
    try:
        state = result.to_state()
        if hasattr(state, "model_dump"):
            return state.model_dump(mode="json")
        return {"repr": repr(state)}
    except Exception:
        return None


def _safe_usage(result) -> dict[str, Any] | None:
    usage = getattr(result, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    return {"repr": repr(usage)}


def _jsonish(value) -> Any:
    if value is None or isinstance(value, str | int | float | bool | list | dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return repr(value)
