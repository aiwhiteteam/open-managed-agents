from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.db.engine import get_session
from app.db.queries import agents as agents_q
from app.models.agents import (
    AgentCreateRequest,
    AgentResponse,
    AgentUpdateRequest,
    AgentVersionResponse,
    agent_to_response,
    version_to_response,
)
from app.models.common import ListResponse

router = APIRouter(
    prefix="/v1/agents",
    tags=["agents"],
    dependencies=[Depends(require_api_access)],
)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreateRequest,
    db: AsyncSession = Depends(get_session),
):
    agent, version = await agents_q.create_agent(
        db,
        name=body.name,
        model=body.model,
        system=body.system,
        description=body.description,
        tools=body.tools,
        mcp_servers=body.mcp_servers,
        skills=body.skills,
        multiagent=body.multiagent,
        metadata=body.metadata,
        runtime=body.runtime,
    )
    await db.commit()
    return agent_to_response(agent, version)


@router.get("", response_model=ListResponse[AgentResponse])
async def list_agents(
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    agents = await agents_q.list_agents(db, limit=limit)
    responses: list[AgentResponse] = []
    for agent in agents:
        version = await agents_q.get_active_agent_version(db, agent)
        if version is not None:
            responses.append(agent_to_response(agent, version))
    return ListResponse[AgentResponse].from_items(responses)


@router.get("/{agent_id}/versions", response_model=ListResponse[AgentVersionResponse])
async def list_agent_versions(
    agent_id: str,
    db: AsyncSession = Depends(get_session),
):
    agent = await agents_q.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    result = await db.execute(agents_q.agent_versions_query(agent_id))
    versions = [version_to_response(v) for v in result.scalars().all()]
    return ListResponse[AgentVersionResponse].from_items(versions)


@router.get("/{agent_id}", response_model=AgentResponse)
async def retrieve_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_session),
):
    agent = await agents_q.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = await agents_q.get_active_agent_version(db, agent)
    if version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    return agent_to_response(agent, version)


@router.post("/{agent_id}", response_model=AgentResponse)
@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    db: AsyncSession = Depends(get_session),
):
    agent = await agents_q.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived agents cannot be updated")

    active = await agents_q.get_active_agent_version(db, agent)
    if active is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    if body.version != agent.active_version:
        raise HTTPException(
            status_code=409,
            detail=f"Version mismatch: expected {agent.active_version}, got {body.version}",
        )

    update = body.model_dump(exclude_unset=True)
    update.pop("version", None)
    next_config = _merge_agent_update(active, agent, update)
    version, _created = await agents_q.update_agent(
        db,
        agent,
        **next_config,
    )
    await db.commit()
    return agent_to_response(agent, version)


@router.post("/{agent_id}/archive", response_model=AgentResponse)
async def archive_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_session),
):
    agent = await agents_q.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = await agents_q.get_active_agent_version(db, agent)
    if version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    await agents_q.archive_agent(db, agent)
    await db.commit()
    return agent_to_response(agent, version)


def _merge_agent_update(active, agent, update: dict) -> dict:
    name = active.name
    model = active.model
    system = active.system
    description = active.description
    tools = active.tools
    mcp_servers = active.mcp_servers
    skills = active.skills
    multiagent = active.multiagent
    metadata = dict(active.metadata_)
    runtime = active.runtime

    if "name" in update:
        if update["name"] is None:
            raise HTTPException(status_code=422, detail="name cannot be null")
        name = update["name"]
    if "model" in update:
        if update["model"] is None:
            raise HTTPException(status_code=422, detail="model cannot be null")
        model = update["model"] if isinstance(update["model"], dict) else {"id": update["model"]}
    if "system" in update:
        system = update["system"]
    if "description" in update:
        description = update["description"]
    if "tools" in update:
        tools = update["tools"] or []
    if "mcp_servers" in update:
        mcp_servers = update["mcp_servers"] or []
    if "skills" in update:
        skills = update["skills"] or []
    if "multiagent" in update:
        multiagent = update["multiagent"]
    if "metadata" in update:
        for key, value in (update["metadata"] or {}).items():
            if value == "":
                metadata.pop(key, None)
            else:
                metadata[key] = value
    if "runtime" in update:
        runtime = update["runtime"] or {}

    return {
        "name": name,
        "model": model,
        "system": system,
        "description": description,
        "tools": tools,
        "mcp_servers": mcp_servers,
        "skills": skills,
        "multiagent": multiagent,
        "metadata": metadata,
        "runtime": runtime,
    }
