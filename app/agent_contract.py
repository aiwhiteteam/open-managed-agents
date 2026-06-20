from fastapi import HTTPException


def normalize_agent_tools(tools: list[dict]) -> list[dict]:
    if not isinstance(tools, list):
        raise HTTPException(status_code=422, detail="tools must be an array")

    return [_normalize_agent_tool(tool) for tool in tools]


def _normalize_agent_tool(tool: dict) -> dict:
    if not isinstance(tool, dict):
        raise HTTPException(status_code=422, detail="tools entries must be objects")

    tool_type = tool.get("type")
    if tool_type == "agent_toolset_20260401":
        return _normalize_toolset(tool, default_policy_type="always_allow")
    if tool_type == "mcp_toolset":
        normalized = _normalize_toolset(tool, default_policy_type="always_ask")
        server_name = normalized.get("mcp_server_name")
        if not isinstance(server_name, str) or not server_name:
            raise HTTPException(status_code=422, detail="mcp_toolset entries require mcp_server_name")
        return normalized
    if tool_type == "custom":
        return _normalize_custom_tool(tool)

    return dict(tool)


def _normalize_toolset(tool: dict, *, default_policy_type: str) -> dict:
    normalized = dict(tool)
    default_config = _normalize_tool_config(
        normalized.get("default_config") if isinstance(normalized.get("default_config"), dict) else {},
        fallback_enabled=True,
        fallback_policy={"type": default_policy_type},
    )
    normalized["default_config"] = default_config
    normalized["configs"] = [
        _normalize_tool_config(
            config,
            fallback_enabled=default_config["enabled"],
            fallback_policy=default_config["permission_policy"],
            require_name=True,
        )
        for config in normalized.get("configs") or []
    ]
    return normalized


def _normalize_tool_config(
    config: dict,
    *,
    fallback_enabled: bool,
    fallback_policy: dict,
    require_name: bool = False,
) -> dict:
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="tool configs entries must be objects")

    normalized = dict(config)
    if require_name and not normalized.get("name"):
        raise HTTPException(status_code=422, detail="tool configs entries require name")
    if "enabled" not in normalized or normalized["enabled"] is None:
        normalized["enabled"] = fallback_enabled
    policy = normalized.get("permission_policy")
    if not isinstance(policy, dict) or not policy.get("type"):
        normalized["permission_policy"] = dict(fallback_policy)
    return normalized


def _normalize_custom_tool(tool: dict) -> dict:
    normalized = dict(tool)
    name = normalized.get("name")
    if not isinstance(name, str) or not name:
        raise HTTPException(status_code=422, detail="custom tools require name")
    if not isinstance(normalized.get("description"), str) or not normalized["description"]:
        normalized["description"] = f"Custom tool {name}."
    input_schema = normalized.get("input_schema")
    if not isinstance(input_schema, dict):
        normalized["input_schema"] = {"type": "object", "properties": {}}
    elif input_schema.get("type") != "object":
        raise HTTPException(status_code=422, detail='custom tool input_schema.type must be "object"')
    return normalized


def validate_mcp_bindings(mcp_servers: list[dict], tools: list[dict]) -> None:
    if len(mcp_servers) > 20:
        raise HTTPException(status_code=422, detail="mcp_servers supports at most 20 servers")

    server_names: set[str] = set()
    for server in mcp_servers:
        if not isinstance(server, dict):
            raise HTTPException(status_code=422, detail="mcp_servers entries must be objects")
        if server.get("type") != "url":
            raise HTTPException(status_code=422, detail='mcp_servers entries must have type "url"')
        name = server.get("name")
        url = server.get("url")
        if not isinstance(name, str) or not name:
            raise HTTPException(status_code=422, detail="mcp_servers entries require name")
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=422, detail="mcp_servers entries require url")
        if name in server_names:
            raise HTTPException(status_code=422, detail=f"Duplicate MCP server name: {name}")
        server_names.add(name)

    tool_refs: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "mcp_toolset":
            continue
        server_name = tool.get("mcp_server_name")
        if not isinstance(server_name, str) or not server_name:
            raise HTTPException(status_code=422, detail="mcp_toolset entries require mcp_server_name")
        if server_name not in server_names:
            raise HTTPException(status_code=422, detail=f"mcp_toolset references undeclared MCP server: {server_name}")
        tool_refs.add(server_name)

    unreferenced = server_names - tool_refs
    if unreferenced:
        names = ", ".join(sorted(unreferenced))
        raise HTTPException(status_code=422, detail=f"MCP servers must be referenced by mcp_toolset: {names}")
