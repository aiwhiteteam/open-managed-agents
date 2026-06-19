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
from app.session_state import (
    SESSION_IDLE,
    SESSION_RESCHEDULING,
    SESSION_RUNNING,
    SESSION_TERMINATED,
    can_start_work,
    is_waiting_for_action,
)

logger = structlog.get_logger()
_running_sessions: set[str] = set()
_running_lock = asyncio.Lock()


@dataclass
class RuntimeResult:
    final_text: str
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    requires_action: bool = False
    run_state: dict[str, Any] | None = None
    sandbox_state: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class EffectiveAgentVersion:
    id: str
    agent_id: str
    version: int
    name: str
    model: dict[str, Any]
    system: str | None
    description: str | None
    tools: list[dict[str, Any]]
    mcp_servers: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    multiagent: dict[str, Any] | None
    metadata_: dict[str, Any]
    runtime: dict[str, Any]


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
        if not can_start_work(session.status, session.stop_reason):
            return
        await sessions_q.update_session(db, session, status=SESSION_RUNNING, stop_reason={"type": "in_progress"})
        await events_q.append_event(
            db,
            session,
            event_type="session.status_running",
            payload={"type": "session.status_running", "status": SESSION_RUNNING},
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
            effective_version = _effective_agent_version(version, session.status_details)

        result = await _execute(effective_version, history, environment.config)

        async with session_scope() as db:
            session = await sessions_q.get_session(db, session_id)
            if session is None:
                return
            if session.status != SESSION_RUNNING or is_waiting_for_action(session.stop_reason):
                return
            blocking_event_ids: list[str] = []
            for tool_event in result.tool_events:
                event = await events_q.append_event(
                    db,
                    session,
                    event_type=tool_event["type"],
                    payload=tool_event,
                )
                if result.requires_action and tool_event["type"] in {
                    "agent.custom_tool_use",
                    "agent.tool_use",
                    "agent.mcp_tool_use",
                }:
                    blocking_event_ids.append(event.id)
            if result.requires_action:
                stop_reason = {"type": "requires_action", "event_ids": blocking_event_ids}
                await sessions_q.update_session(
                    db,
                    session,
                    status=SESSION_IDLE,
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
                        "status": SESSION_IDLE,
                        "stop_reason": stop_reason,
                        "usage": result.usage or {},
                    },
                )
                await db.commit()
                return
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
                status=SESSION_IDLE,
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
                    "status": SESSION_IDLE,
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
            await sessions_q.update_session(db, session, status=SESSION_TERMINATED, stop_reason=stop_reason)
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
            await events_q.append_event(
                db,
                session,
                event_type="session.status_terminated",
                payload={"type": "session.status_terminated", "status": SESSION_TERMINATED, "stop_reason": stop_reason},
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


def _effective_agent_version(version, status_details: dict[str, Any] | None) -> EffectiveAgentVersion:
    overlay = {}
    if isinstance(status_details, dict) and isinstance(status_details.get("agent"), dict):
        overlay = status_details["agent"]
    tools = overlay.get("tools", version.tools)
    mcp_servers = overlay.get("mcp_servers", version.mcp_servers)
    return EffectiveAgentVersion(
        id=version.id,
        agent_id=version.agent_id,
        version=version.version,
        name=version.name,
        model=version.model,
        system=version.system,
        description=version.description,
        tools=tools if isinstance(tools, list) else version.tools,
        mcp_servers=mcp_servers if isinstance(mcp_servers, list) else version.mcp_servers,
        skills=version.skills,
        multiagent=version.multiagent,
        metadata_=version.metadata_,
        runtime=version.runtime,
    )


async def _execute_openai(version, history, environment_config: dict[str, Any] | None = None) -> RuntimeResult:
    from agents import (
        Agent,
        CodeInterpreterTool,
        FileSearchTool,
        HostedMCPTool,
        ImageGenerationTool,
        ModelSettings,
        RunConfig,
        Runner,
        WebSearchTool,
    )
    from agents.models.openai_provider import OpenAIProvider
    from agents.sandbox import SandboxAgent
    from agents.tool import CodeInterpreter, ImageGeneration, Mcp

    provider = resolve_runtime_provider(version.model)
    model_settings, removed_model_settings = _model_settings_for_provider(
        version.runtime,
        version.model,
        provider.capabilities,
        ModelSettings,
    )
    sdk_tools, enabled_sdk_tools, filtered_tools = _sdk_tools_for_provider(
        version.tools,
        version.mcp_servers,
        provider.capabilities,
        {
            "WebSearchTool": WebSearchTool,
            "FileSearchTool": FileSearchTool,
            "CodeInterpreterTool": CodeInterpreterTool,
            "CodeInterpreter": CodeInterpreter,
            "HostedMCPTool": HostedMCPTool,
            "Mcp": Mcp,
            "ImageGenerationTool": ImageGenerationTool,
            "ImageGeneration": ImageGeneration,
        },
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
        tools=sdk_tools,
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
            "enabled_sdk_tools": enabled_sdk_tools,
            "filtered_tools": filtered_tools,
            "sdk_state": _safe_state(result),
        },
        sandbox_state=sandbox_plan.summary,
        usage=_safe_usage(result),
    )


async def _execute_local(version, history, environment_config: dict[str, Any] | None = None) -> RuntimeResult:
    await asyncio.sleep(0.05)
    sandbox_plan = sandbox_plan_from_environment(environment_config)
    latest_action = _latest_user_action_event(history)
    if latest_action is not None:
        return RuntimeResult(
            final_text=_local_action_result_text(latest_action),
            run_state={"backend": "local", "agent_version_id": version.id, "resumed_from": latest_action.type},
            sandbox_state={**sandbox_plan.summary, "runtime_backend": "local"},
        )

    latest = _latest_user_text(history)
    if latest:
        custom_tool = _first_custom_tool(version.tools)
        if custom_tool is not None:
            name = str(custom_tool.get("name") or "custom_tool")
            return RuntimeResult(
                final_text="",
                tool_events=[
                    {
                        "type": "agent.custom_tool_use",
                        "name": name,
                        "input": {"prompt": latest},
                        "tool": _public_tool_summary(custom_tool),
                    }
                ],
                requires_action=True,
                run_state={"backend": "local", "agent_version_id": version.id, "pending_action": "custom_tool"},
                sandbox_state={**sandbox_plan.summary, "runtime_backend": "local"},
            )

        confirmation_tool = _first_confirmation_tool(version.tools)
        if confirmation_tool is not None:
            return RuntimeResult(
                final_text="",
                tool_events=[
                    {
                        "type": confirmation_tool["event_type"],
                        "name": confirmation_tool["name"],
                        "input": {"prompt": latest},
                        "permission_policy": {"type": "always_ask"},
                        "tool": confirmation_tool["tool"],
                    }
                ],
                requires_action=True,
                run_state={"backend": "local", "agent_version_id": version.id, "pending_action": "tool_confirmation"},
                sandbox_state={**sandbox_plan.summary, "runtime_backend": "local"},
            )

        text = f"Open Managed Agents local runtime received: {latest}"
    else:
        text = "Open Managed Agents local runtime is idle."
    return RuntimeResult(
        final_text=text,
        run_state={"backend": "local", "agent_version_id": version.id},
        sandbox_state={**sandbox_plan.summary, "runtime_backend": "local"},
    )


def _latest_user_action_event(history):
    for event in reversed(history):
        if not event.type.startswith("user."):
            continue
        return event if event.type in {"user.custom_tool_result", "user.tool_confirmation"} else None
    return None


def _local_action_result_text(event) -> str:
    if event.type == "user.custom_tool_result":
        result = _text_from_payload(event.payload) or "custom tool result received"
        return f"Open Managed Agents local runtime received custom tool result: {result}"

    result = event.payload.get("result")
    if result == "deny":
        message = event.payload.get("deny_message") or "tool use denied"
        return f"Open Managed Agents local runtime received tool denial: {message}"
    return "Open Managed Agents local runtime received tool confirmation: allow"


def _first_custom_tool(tools: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for tool in tools or []:
        if isinstance(tool, dict) and _normalized_tool_type(tool) == "custom":
            return tool
    return None


def _first_confirmation_tool(tools: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        tool_type = _normalized_tool_type(tool)
        if tool_type == "custom":
            continue
        if tool_type == "mcp_toolset" and _permission_policy_type(tool, default="always_ask") == "always_ask":
            return {
                "event_type": "agent.mcp_tool_use",
                "name": str(tool.get("mcp_server_name") or tool.get("name") or "mcp_tool"),
                "tool": _public_tool_summary(tool),
            }
        if tool_type == "agent_toolset_20260401":
            config_tool = _first_configured_always_ask_tool(tool)
            if config_tool is not None:
                return {
                    "event_type": "agent.tool_use",
                    "name": config_tool,
                    "tool": _public_tool_summary(tool),
                }
            if _permission_policy_type(tool, default="always_allow") == "always_ask":
                return {
                    "event_type": "agent.tool_use",
                    "name": "bash",
                    "tool": _public_tool_summary(tool),
                }
    return None


def _first_configured_always_ask_tool(tool: dict[str, Any]) -> str | None:
    configs = tool.get("configs")
    if not isinstance(configs, list):
        return None
    for config in configs:
        if not isinstance(config, dict):
            continue
        if config.get("enabled") is False:
            continue
        if _permission_policy_type(config, default="") == "always_ask":
            name = config.get("name")
            return str(name) if name else "tool"
    return None


def _permission_policy_type(config: dict[str, Any], *, default: str) -> str:
    default_config = config.get("default_config")
    candidates = [config]
    if isinstance(default_config, dict):
        candidates.insert(0, default_config)
    for candidate in candidates:
        policy = candidate.get("permission_policy") if isinstance(candidate, dict) else None
        if isinstance(policy, dict) and policy.get("type"):
            return str(policy["type"])
    return default


def _public_tool_summary(tool: dict[str, Any]) -> dict[str, Any]:
    summary = dict(tool)
    for key in ("authorization", "headers"):
        if key in summary:
            summary[key] = "redacted"
    return summary


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


def _sdk_tools_for_provider(
    tools: list[dict[str, Any]] | None,
    mcp_servers: list[dict[str, Any]] | None,
    capabilities,
    sdk_classes: dict[str, Any],
) -> tuple[list[Any], list[dict[str, Any]], list[dict[str, Any]]]:
    specs = _tool_specs(tools, mcp_servers)
    if not specs:
        return [], [], []

    sdk_tools: list[Any] = []
    enabled: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []

    for index, spec in enumerate(specs):
        tool_type = _normalized_tool_type(spec)
        summary = _tool_summary(spec, index=index, tool_type=tool_type)
        if tool_type is None:
            filtered.append({**summary, "reason": "missing_tool_type"})
            continue
        if not capabilities.hosted_tools and _is_hosted_tool_type(tool_type):
            filtered.append({**summary, "reason": "provider_does_not_support_hosted_tools"})
            continue

        mapped = _map_hosted_tool(tool_type, spec, sdk_classes)
        if mapped is None:
            filtered.append({**summary, "reason": "unsupported_tool_type"})
            continue
        if isinstance(mapped, str):
            filtered.append({**summary, "reason": mapped})
            continue
        sdk_tools.append(mapped)
        enabled.append(summary)

    return sdk_tools, enabled, filtered


def _tool_specs(
    tools: list[dict[str, Any]] | None,
    mcp_servers: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for tool in tools or []:
        if isinstance(tool, dict):
            specs.append(dict(tool))
    for server in mcp_servers or []:
        if isinstance(server, dict):
            specs.append({"type": "mcp", **server})
    return specs


def _normalized_tool_type(spec: dict[str, Any]) -> str | None:
    raw = spec.get("type") or spec.get("tool_type") or spec.get("name")
    if raw is None:
        return None
    return str(raw).strip().lower().replace("-", "_")


def _is_hosted_tool_type(tool_type: str) -> bool:
    return tool_type in {
        "web_search",
        "web_search_preview",
        "file_search",
        "code_interpreter",
        "hosted_mcp",
        "mcp",
        "image_generation",
    }


def _map_hosted_tool(tool_type: str, spec: dict[str, Any], sdk_classes: dict[str, Any]) -> Any | str | None:
    if tool_type in {"web_search", "web_search_preview"}:
        kwargs: dict[str, Any] = {}
        context_size = spec.get("search_context_size") or spec.get("context_size")
        if context_size in {"low", "medium", "high"}:
            kwargs["search_context_size"] = context_size
        if isinstance(spec.get("user_location"), dict):
            kwargs["user_location"] = spec["user_location"]
        if isinstance(spec.get("filters"), dict):
            kwargs["filters"] = spec["filters"]
        if "external_web_access" in spec:
            kwargs["external_web_access"] = bool(spec["external_web_access"])
        return sdk_classes["WebSearchTool"](**kwargs)

    if tool_type == "file_search":
        vector_store_ids = spec.get("vector_store_ids") or spec.get("vector_store_id")
        if isinstance(vector_store_ids, str):
            vector_store_ids = [vector_store_ids]
        if not isinstance(vector_store_ids, list) or not vector_store_ids:
            return "missing_vector_store_ids"
        kwargs = {
            "vector_store_ids": [str(item) for item in vector_store_ids],
        }
        if spec.get("max_num_results") is not None:
            kwargs["max_num_results"] = int(spec["max_num_results"])
        if "include_search_results" in spec:
            kwargs["include_search_results"] = bool(spec["include_search_results"])
        if isinstance(spec.get("ranking_options"), dict):
            kwargs["ranking_options"] = spec["ranking_options"]
        if isinstance(spec.get("filters"), dict):
            kwargs["filters"] = spec["filters"]
        return sdk_classes["FileSearchTool"](**kwargs)

    if tool_type == "code_interpreter":
        config = sdk_classes["CodeInterpreter"](
            type="code_interpreter",
            container=spec.get("container") or {"type": "auto"},
        )
        return sdk_classes["CodeInterpreterTool"](config)

    if tool_type in {"hosted_mcp", "mcp"}:
        config = _mcp_tool_config(spec, sdk_classes["Mcp"])
        if isinstance(config, str):
            return config
        return sdk_classes["HostedMCPTool"](config)

    if tool_type == "image_generation":
        config = {"type": "image_generation"}
        for key in (
            "model",
            "quality",
            "size",
            "output_format",
            "output_compression",
            "background",
            "moderation",
            "partial_images",
            "input_fidelity",
            "action",
        ):
            if key in spec:
                config[key] = spec[key]
        return sdk_classes["ImageGenerationTool"](sdk_classes["ImageGeneration"](**config))

    return None


def _mcp_tool_config(spec: dict[str, Any], mcp_cls) -> Any | str:
    server_label = (
        spec.get("server_label")
        or spec.get("label")
        or spec.get("name")
        or spec.get("id")
    )
    if not server_label:
        return "missing_server_label"

    config: dict[str, Any] = {
        "type": "mcp",
        "server_label": str(server_label),
    }
    for key in (
        "server_url",
        "connector_id",
        "authorization",
        "headers",
        "allowed_tools",
        "require_approval",
        "server_description",
        "defer_loading",
        "tunnel_id",
    ):
        value = spec.get(key)
        if value is not None:
            config[key] = value
    if "server_url" not in config and spec.get("url"):
        config["server_url"] = spec["url"]
    if "server_url" not in config and "connector_id" not in config:
        return "missing_server_url_or_connector_id"
    return mcp_cls(**config)


def _tool_summary(spec: dict[str, Any], *, index: int, tool_type: str | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "index": index,
        "type": tool_type or "unknown",
    }
    label = spec.get("server_label") or spec.get("label") or spec.get("name") or spec.get("id")
    if label:
        summary["label"] = str(label)
    if spec.get("connector_id"):
        summary["connector_id"] = str(spec["connector_id"])
    return summary


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
