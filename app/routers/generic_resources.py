from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.db.engine import get_session
from app.db.queries import resources as res_q
from app.models.common import ListResponse, utcnow
from app.models.resources import GenericBody, deleted_response, resource_to_response

router = APIRouter(tags=["managed resources"], dependencies=[Depends(require_api_access)])


RESOURCE_CONFIG = {
    "vaults": ("vault", "vault"),
    "memory_stores": ("memory_store", "memory_store"),
    "deployments": ("deployment", "deployment"),
    "deployment_runs": ("deployment_run", "deployment_run"),
    "user_profiles": ("user_profile", "user_profile"),
}


@router.post("/v1/vaults", status_code=201)
async def create_vault(body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _create_top_level(db, "vault", body.model_dump(mode="json"))


@router.get("/v1/vaults")
async def list_vaults(limit: int = 50, db: AsyncSession = Depends(get_session)):
    return await _list_top_level(db, "vault", limit)


@router.get("/v1/vaults/{vault_id}")
async def retrieve_vault(vault_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, vault_id, "vault")


@router.post("/v1/vaults/{vault_id}")
async def update_vault(vault_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _update(db, vault_id, "vault", body.model_dump(mode="json"))


@router.delete("/v1/vaults/{vault_id}")
async def delete_vault(vault_id: str, db: AsyncSession = Depends(get_session)):
    return await _delete(db, vault_id, "vault", "deleted_vault")


@router.post("/v1/vaults/{vault_id}/archive")
async def archive_vault(vault_id: str, db: AsyncSession = Depends(get_session)):
    return await _archive(db, vault_id, "vault")


@router.post("/v1/vaults/{vault_id}/credentials", status_code=201)
async def create_credential(vault_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    await _must_exist(db, vault_id, "vault")
    return await _create_child(db, "credential", vault_id, body.model_dump(mode="json"))


@router.get("/v1/vaults/{vault_id}/credentials")
async def list_credentials(vault_id: str, limit: int = 50, db: AsyncSession = Depends(get_session)):
    await _must_exist(db, vault_id, "vault")
    return await _list_child(db, "credential", vault_id, limit)


@router.get("/v1/vaults/{vault_id}/credentials/{credential_id}")
async def retrieve_credential(vault_id: str, credential_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, credential_id, "credential", parent_id=vault_id)


@router.post("/v1/vaults/{vault_id}/credentials/{credential_id}")
async def update_credential(
    vault_id: str,
    credential_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    return await _update(db, credential_id, "credential", body.model_dump(mode="json"), parent_id=vault_id)


@router.delete("/v1/vaults/{vault_id}/credentials/{credential_id}")
async def delete_credential(vault_id: str, credential_id: str, db: AsyncSession = Depends(get_session)):
    return await _delete(db, credential_id, "credential", "deleted_credential", parent_id=vault_id)


@router.post("/v1/vaults/{vault_id}/credentials/{credential_id}/archive")
async def archive_credential(vault_id: str, credential_id: str, db: AsyncSession = Depends(get_session)):
    return await _archive(db, credential_id, "credential", parent_id=vault_id)


@router.post("/v1/vaults/{vault_id}/credentials/{credential_id}/mcp_oauth_validate")
async def validate_credential(vault_id: str, credential_id: str, db: AsyncSession = Depends(get_session)):
    credential = await _must_exist(db, credential_id, "credential", parent_id=vault_id)
    return {
        "id": f"validation_{credential.id}",
        "type": "credential_validation",
        "credential_id": credential.id,
        "status": "not_validated",
        "message": "OAuth validation is not implemented in the local compatibility runtime.",
    }


@router.post("/v1/memory_stores", status_code=201)
async def create_memory_store(body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _create_top_level(db, "memory_store", body.model_dump(mode="json"))


@router.get("/v1/memory_stores")
async def list_memory_stores(limit: int = 50, db: AsyncSession = Depends(get_session)):
    return await _list_top_level(db, "memory_store", limit)


@router.get("/v1/memory_stores/{memory_store_id}")
async def retrieve_memory_store(memory_store_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, memory_store_id, "memory_store")


@router.post("/v1/memory_stores/{memory_store_id}")
async def update_memory_store(memory_store_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _update(db, memory_store_id, "memory_store", body.model_dump(mode="json"))


@router.delete("/v1/memory_stores/{memory_store_id}")
async def delete_memory_store(memory_store_id: str, db: AsyncSession = Depends(get_session)):
    return await _delete(db, memory_store_id, "memory_store", "deleted_memory_store")


@router.post("/v1/memory_stores/{memory_store_id}/archive")
async def archive_memory_store(memory_store_id: str, db: AsyncSession = Depends(get_session)):
    return await _archive(db, memory_store_id, "memory_store")


@router.post("/v1/memory_stores/{memory_store_id}/memories", status_code=201)
async def create_memory(memory_store_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    await _must_exist(db, memory_store_id, "memory_store")
    data = _memory_payload(body.model_dump(mode="json"))
    existing = await _find_memory_by_path(db, memory_store_id, data["path_key"])
    if existing is not None:
        raise HTTPException(status_code=409, detail="Memory path already exists in this memory store")
    memory = await res_q.create_resource(
        db,
        resource_type="memory",
        parent_id=memory_store_id,
        name=data.get("name") or data["path_key"],
        data=data,
    )
    await _create_memory_version(db, memory, version=1, actor=data["updated_by"], operation="create")
    await db.commit()
    return resource_to_response(memory, public_type="memory")


@router.get("/v1/memory_stores/{memory_store_id}/memories")
async def list_memories(
    memory_store_id: str,
    limit: int = 50,
    path: str | None = None,
    path_prefix: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_store_id, "memory_store")
    resources = await res_q.list_resources(db, resource_type="memory", parent_id=memory_store_id, limit=1000)
    if path is not None:
        path_key = _path_key(_normalize_memory_path(path))
        resources = [memory for memory in resources if memory.data.get("path_key") == path_key]
    if path_prefix is not None:
        prefix = _path_key(_normalize_memory_path(path_prefix))
        resources = [
            memory
            for memory in resources
            if memory.data.get("path_key") == prefix or str(memory.data.get("path_key", "")).startswith(f"{prefix}/")
        ]
    return ListResponse[dict].from_items(
        [resource_to_response(memory, public_type="memory") for memory in resources[:limit]]
    )


@router.get("/v1/memory_stores/{memory_store_id}/memories/by_path")
async def retrieve_memory_by_path(
    memory_store_id: str,
    path: str = Query(...),
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_store_id, "memory_store")
    memory = await _find_memory_by_path(db, memory_store_id, _path_key(_normalize_memory_path(path)))
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return resource_to_response(memory, public_type="memory")


@router.get("/v1/memory_stores/{memory_store_id}/memories/{memory_id}")
async def retrieve_memory(memory_store_id: str, memory_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, memory_id, "memory", parent_id=memory_store_id)


@router.post("/v1/memory_stores/{memory_store_id}/memories/{memory_id}")
async def update_memory(
    memory_store_id: str,
    memory_id: str,
    body: GenericBody,
    db: AsyncSession = Depends(get_session),
):
    memory = await _must_exist(db, memory_id, "memory", parent_id=memory_store_id)
    update = body.model_dump(mode="json")
    expected_version = update.pop("if_version", update.pop("expected_version", None))
    current_version = int(memory.data.get("version") or 1)
    if expected_version is not None and int(expected_version) != current_version:
        raise HTTPException(status_code=409, detail="Memory version precondition failed")
    data = _merge_memory_data(memory.data, update)
    if data["path_key"] != memory.data.get("path_key"):
        existing = await _find_memory_by_path(db, memory_store_id, data["path_key"])
        if existing is not None and existing.id != memory.id:
            raise HTTPException(status_code=409, detail="Memory path already exists in this memory store")
    await res_q.update_resource(db, memory, data=data)
    version = int(data["version"])
    await _create_memory_version(db, memory, version=version, actor=data["updated_by"], operation="update")
    await db.commit()
    return resource_to_response(memory, public_type="memory")


@router.delete("/v1/memory_stores/{memory_store_id}/memories/{memory_id}")
async def delete_memory(memory_store_id: str, memory_id: str, db: AsyncSession = Depends(get_session)):
    return await _delete(db, memory_id, "memory", "deleted_memory", parent_id=memory_store_id)


@router.get("/v1/memory_stores/{memory_store_id}/memories/{memory_id}/versions")
async def list_memory_versions_for_memory(
    memory_store_id: str,
    memory_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_id, "memory", parent_id=memory_store_id)
    versions = await res_q.list_resources(db, resource_type="memory_version", parent_id=memory_id, limit=limit)
    return ListResponse[dict].from_items(
        [resource_to_response(version, public_type="memory_version") for version in versions]
    )


@router.get("/v1/memory_stores/{memory_store_id}/memories/{memory_id}/versions/{version}")
async def retrieve_memory_version_for_memory(
    memory_store_id: str,
    memory_id: str,
    version: int,
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_id, "memory", parent_id=memory_store_id)
    memory_version = await res_q.get_resource_version(
        db,
        resource_type="memory_version",
        parent_id=memory_id,
        version=version,
    )
    if memory_version is None:
        raise HTTPException(status_code=404, detail="Memory version not found")
    return resource_to_response(memory_version, public_type="memory_version")


@router.get("/v1/memory_stores/{memory_store_id}/memory_versions")
async def list_memory_versions(memory_store_id: str, limit: int = 50, db: AsyncSession = Depends(get_session)):
    await _must_exist(db, memory_store_id, "memory_store")
    memories = await res_q.list_resources(db, resource_type="memory", parent_id=memory_store_id, limit=1000)
    versions = []
    for memory in memories:
        versions.extend(
            await res_q.list_resources(db, resource_type="memory_version", parent_id=memory.id, limit=limit)
        )
    return ListResponse[dict].from_items(
        [resource_to_response(v, public_type="memory_version") for v in versions[:limit]]
    )


@router.get("/v1/memory_stores/{memory_store_id}/memory_versions/{memory_version_id}")
async def retrieve_memory_version(
    memory_store_id: str,
    memory_version_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_store_id, "memory_store")
    version = await res_q.get_resource(db, resource_id=memory_version_id, resource_type="memory_version")
    if version is None:
        raise HTTPException(status_code=404, detail="Memory version not found")
    return resource_to_response(version, public_type="memory_version")


@router.post("/v1/memory_stores/{memory_store_id}/memory_versions/{memory_version_id}/redact")
async def redact_memory_version(
    memory_store_id: str,
    memory_version_id: str,
    db: AsyncSession = Depends(get_session),
):
    await _must_exist(db, memory_store_id, "memory_store")
    version = await res_q.get_resource(db, resource_id=memory_version_id, resource_type="memory_version")
    if version is None:
        raise HTTPException(status_code=404, detail="Memory version not found")
    memory = await _must_exist(db, version.parent_id, "memory", parent_id=memory_store_id)
    data = dict(version.data)
    snapshot = dict(data.get("snapshot") or {})
    snapshot.pop("content", None)
    snapshot["redacted"] = True
    data["snapshot"] = snapshot
    data["redacted"] = True
    data["redacted_at"] = utcnow().isoformat()
    await res_q.update_resource(db, version, data=data)
    if memory.data.get("version") == data.get("memory_version"):
        memory_data = dict(memory.data)
        memory_data.pop("content", None)
        memory_data["redacted"] = True
        memory_data["redacted_at"] = data["redacted_at"]
        await res_q.update_resource(db, memory, data=memory_data)
    await db.commit()
    return resource_to_response(version, public_type="memory_version")


@router.post("/v1/deployments", status_code=201)
async def create_deployment(body: GenericBody, db: AsyncSession = Depends(get_session)):
    data = body.model_dump(mode="json")
    data.setdefault("status", "active")
    return await _create_top_level(db, "deployment", data, status=data["status"])


@router.get("/v1/deployments")
async def list_deployments(limit: int = 50, db: AsyncSession = Depends(get_session)):
    return await _list_top_level(db, "deployment", limit)


@router.get("/v1/deployments/{deployment_id}")
async def retrieve_deployment(deployment_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, deployment_id, "deployment")


@router.post("/v1/deployments/{deployment_id}")
async def update_deployment(deployment_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _update(db, deployment_id, "deployment", body.model_dump(mode="json"))


@router.post("/v1/deployments/{deployment_id}/archive")
async def archive_deployment(deployment_id: str, db: AsyncSession = Depends(get_session)):
    return await _archive(db, deployment_id, "deployment")


@router.post("/v1/deployments/{deployment_id}/pause")
async def pause_deployment(deployment_id: str, db: AsyncSession = Depends(get_session)):
    deployment = await _must_exist(db, deployment_id, "deployment")
    data = dict(deployment.data)
    data["status"] = "paused"
    await res_q.update_resource(db, deployment, data=data, status="paused")
    await db.commit()
    return resource_to_response(deployment, public_type="deployment")


@router.post("/v1/deployments/{deployment_id}/unpause")
async def unpause_deployment(deployment_id: str, db: AsyncSession = Depends(get_session)):
    deployment = await _must_exist(db, deployment_id, "deployment")
    data = dict(deployment.data)
    data["status"] = "active"
    await res_q.update_resource(db, deployment, data=data, status="active")
    await db.commit()
    return resource_to_response(deployment, public_type="deployment")


@router.post("/v1/deployments/{deployment_id}/run")
async def run_deployment(deployment_id: str, db: AsyncSession = Depends(get_session)):
    deployment = await _must_exist(db, deployment_id, "deployment")
    run = await res_q.create_resource(
        db,
        resource_type="deployment_run",
        parent_id=deployment.id,
        status="queued",
        data={"deployment_id": deployment.id, "status": "queued"},
    )
    await db.commit()
    return resource_to_response(run, public_type="deployment_run")


@router.get("/v1/deployment_runs")
async def list_deployment_runs(limit: int = 50, db: AsyncSession = Depends(get_session)):
    return await _list_top_level(db, "deployment_run", limit)


@router.get("/v1/deployment_runs/{deployment_run_id}")
async def retrieve_deployment_run(deployment_run_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, deployment_run_id, "deployment_run")


@router.post("/v1/user_profiles", status_code=201)
async def create_user_profile(body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _create_top_level(db, "user_profile", body.model_dump(mode="json"))


@router.get("/v1/user_profiles")
async def list_user_profiles(limit: int = 50, db: AsyncSession = Depends(get_session)):
    return await _list_top_level(db, "user_profile", limit)


@router.get("/v1/user_profiles/{user_profile_id}")
async def retrieve_user_profile(user_profile_id: str, db: AsyncSession = Depends(get_session)):
    return await _retrieve(db, user_profile_id, "user_profile")


@router.post("/v1/user_profiles/{user_profile_id}")
async def update_user_profile(user_profile_id: str, body: GenericBody, db: AsyncSession = Depends(get_session)):
    return await _update(db, user_profile_id, "user_profile", body.model_dump(mode="json"))


@router.post("/v1/user_profiles/{user_profile_id}/enrollment_url")
async def create_user_profile_enrollment_url(user_profile_id: str, db: AsyncSession = Depends(get_session)):
    profile = await _must_exist(db, user_profile_id, "user_profile")
    return {
        "id": f"enroll_{profile.id}",
        "type": "user_profile_enrollment_url",
        "user_profile_id": profile.id,
        "url": f"https://example.invalid/managed-agents/user-profiles/{profile.id}/enroll",
    }


async def _create_top_level(
    db: AsyncSession,
    resource_type: str,
    data: dict[str, Any],
    *,
    status: str = "active",
) -> dict[str, Any]:
    resource = await res_q.create_resource(
        db,
        resource_type=resource_type,
        name=data.get("name") or data.get("display_name") or data.get("display_title"),
        data=data,
        status=status,
    )
    await db.commit()
    return resource_to_response(resource, public_type=resource_type)


async def _create_child(
    db: AsyncSession,
    resource_type: str,
    parent_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    resource = await res_q.create_resource(
        db,
        resource_type=resource_type,
        parent_id=parent_id,
        name=data.get("name") or data.get("display_name") or data.get("display_title"),
        data=data,
    )
    await db.commit()
    return resource_to_response(resource, public_type=resource_type)


async def _list_top_level(db: AsyncSession, resource_type: str, limit: int) -> ListResponse[dict]:
    resources = await res_q.list_resources(db, resource_type=resource_type, limit=limit)
    return ListResponse[dict].from_items([resource_to_response(r, public_type=resource_type) for r in resources])


async def _list_child(db: AsyncSession, resource_type: str, parent_id: str, limit: int) -> ListResponse[dict]:
    resources = await res_q.list_resources(db, resource_type=resource_type, parent_id=parent_id, limit=limit)
    return ListResponse[dict].from_items([resource_to_response(r, public_type=resource_type) for r in resources])


async def _retrieve(
    db: AsyncSession,
    resource_id: str,
    resource_type: str,
    *,
    parent_id: str | None = None,
) -> dict[str, Any]:
    resource = await _must_exist(db, resource_id, resource_type, parent_id=parent_id)
    return resource_to_response(resource, public_type=resource_type)


async def _update(
    db: AsyncSession,
    resource_id: str,
    resource_type: str,
    data: dict[str, Any],
    *,
    parent_id: str | None = None,
) -> dict[str, Any]:
    resource = await _must_exist(db, resource_id, resource_type, parent_id=parent_id)
    await res_q.update_resource(
        db,
        resource,
        data=_merge_data(resource.data, data),
        name=data.get("name") or data.get("display_name") or data.get("display_title") or resource.name,
    )
    await db.commit()
    return resource_to_response(resource, public_type=resource_type)


async def _archive(
    db: AsyncSession,
    resource_id: str,
    resource_type: str,
    *,
    parent_id: str | None = None,
) -> dict[str, Any]:
    resource = await _must_exist(db, resource_id, resource_type, parent_id=parent_id)
    await res_q.archive_resource(db, resource)
    await db.commit()
    return resource_to_response(resource, public_type=resource_type)


async def _delete(
    db: AsyncSession,
    resource_id: str,
    resource_type: str,
    public_type: str,
    *,
    parent_id: str | None = None,
) -> dict[str, Any]:
    resource = await _must_exist(db, resource_id, resource_type, parent_id=parent_id)
    await res_q.delete_resource(db, resource)
    await db.commit()
    return deleted_response(resource, public_type=public_type)


async def _must_exist(
    db: AsyncSession,
    resource_id: str,
    resource_type: str,
    *,
    parent_id: str | None = None,
):
    resource = await res_q.get_resource(
        db,
        resource_id=resource_id,
        resource_type=resource_type,
        parent_id=parent_id,
    )
    if resource is None:
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")
    return resource


def _merge_data(existing: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in update.items():
        if value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _memory_payload(data: dict[str, Any]) -> dict[str, Any]:
    path = _normalize_memory_path(data.get("path"))
    now = utcnow().isoformat()
    actor = str(data.get("actor") or data.get("updated_by") or "api")
    memory = dict(data)
    memory["path"] = path
    memory["path_key"] = _path_key(path)
    memory["version"] = 1
    memory["created_by"] = actor
    memory["updated_by"] = actor
    memory["created_at"] = now
    memory["updated_at"] = now
    memory.setdefault("metadata", {})
    memory.setdefault("redacted", False)
    memory.pop("actor", None)
    return memory


def _merge_memory_data(existing: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    actor = str(update.pop("actor", update.pop("updated_by", merged.get("updated_by", "api"))))
    if "path" in update:
        path = _normalize_memory_path(update["path"])
        merged["path"] = path
        merged["path_key"] = _path_key(path)
    for key, value in update.items():
        if key in {"path_key", "version", "created_at", "created_by"}:
            continue
        if value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    merged["version"] = int(merged.get("version") or 1) + 1
    merged["updated_by"] = actor
    merged["updated_at"] = utcnow().isoformat()
    merged.setdefault("metadata", {})
    return merged


async def _find_memory_by_path(db: AsyncSession, memory_store_id: str, path_key: str):
    memories = await res_q.list_resources(db, resource_type="memory", parent_id=memory_store_id, limit=1000)
    for memory in memories:
        if memory.data.get("path_key") == path_key:
            return memory
    return None


async def _create_memory_version(
    db: AsyncSession,
    memory,
    *,
    version: int,
    actor: str,
    operation: str,
):
    await res_q.create_resource(
        db,
        resource_type="memory_version",
        parent_id=memory.id,
        version=version,
        data={
            "memory_store_id": memory.parent_id,
            "memory_id": memory.id,
            "memory_version": version,
            "path": memory.data.get("path"),
            "path_key": memory.data.get("path_key"),
            "snapshot": _memory_snapshot(memory.data),
            "actor": actor,
            "operation": operation,
            "redacted": False,
        },
    )


def _memory_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in {"path_key"}
    }


def _normalize_memory_path(value: Any) -> list[str]:
    if value is None:
        raise HTTPException(status_code=422, detail="Memory path is required")
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace("\\", "/").split("/") if part.strip()]
    elif isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise HTTPException(status_code=422, detail="Memory path must be a string or array")
    if not parts:
        raise HTTPException(status_code=422, detail="Memory path cannot be empty")
    if any("/" in part for part in parts):
        raise HTTPException(status_code=422, detail="Memory path array items cannot contain '/'")
    return parts


def _path_key(path: list[str]) -> str:
    return "/".join(path)
