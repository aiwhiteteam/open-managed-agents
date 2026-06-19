from fastapi import HTTPException


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

