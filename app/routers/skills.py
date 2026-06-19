import hashlib
import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.config import get_settings
from app.db.engine import get_session
from app.db.queries import resources as res_q
from app.models.common import ListResponse
from app.models.resources import deleted_response, resource_to_response
from app.storage import (
    StorageConfigurationError,
    download_file_with_type,
    is_object_storage_backend,
    save_file_bytes,
    should_store_in_object_storage,
)

router = APIRouter(
    prefix="/v1/skills",
    tags=["skills"],
    dependencies=[Depends(require_api_access)],
)


@router.post("", status_code=201)
async def create_skill(request: Request, db: AsyncSession = Depends(get_session)):
    data, content = await _skill_payload_from_request(request)
    skill = await res_q.create_resource(
        db,
        resource_type="skill",
        name=data.get("display_title") or data.get("name"),
        data={
            "display_title": data.get("display_title"),
            "name": data.get("name"),
            "description": data.get("description"),
            "top_level_directory": data.get("top_level_directory"),
            "latest_version": 1,
        },
    )
    version = await _create_skill_version_resource(db, skill.id, 1, data, content)
    await db.commit()
    response = resource_to_response(skill, public_type="skill")
    response["latest_version"] = 1
    response["version"] = resource_to_response(version, public_type="skill_version")
    return response


@router.get("")
async def list_skills(limit: int = 50, db: AsyncSession = Depends(get_session)):
    skills = await res_q.list_resources(db, resource_type="skill", limit=limit)
    return ListResponse[dict].from_items([resource_to_response(skill, public_type="skill") for skill in skills])


@router.get("/{skill_id}")
async def retrieve_skill(skill_id: str, db: AsyncSession = Depends(get_session)):
    skill = await res_q.get_resource(db, resource_id=skill_id, resource_type="skill")
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return resource_to_response(skill, public_type="skill")


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_session)):
    skill = await res_q.get_resource(db, resource_id=skill_id, resource_type="skill")
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    await res_q.delete_resource(db, skill)
    await db.commit()
    return deleted_response(skill, public_type="deleted_skill")


@router.post("/{skill_id}/versions", status_code=201)
async def create_skill_version(
    skill_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    skill = await res_q.get_resource(db, resource_id=skill_id, resource_type="skill")
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    data, content = await _skill_payload_from_request(request)
    version_number = await res_q.next_version(db, resource_type="skill_version", parent_id=skill.id)
    version = await _create_skill_version_resource(db, skill.id, version_number, data, content)
    skill_data = dict(skill.data)
    skill_data["latest_version"] = version_number
    await res_q.update_resource(db, skill, data=skill_data)
    await db.commit()
    return resource_to_response(version, public_type="skill_version")


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    skill = await res_q.get_resource(db, resource_id=skill_id, resource_type="skill")
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    versions = await res_q.list_resources(db, resource_type="skill_version", parent_id=skill_id, limit=limit)
    return ListResponse[dict].from_items([resource_to_response(v, public_type="skill_version") for v in versions])


@router.get("/{skill_id}/versions/{version}")
async def retrieve_skill_version(
    skill_id: str,
    version: int,
    db: AsyncSession = Depends(get_session),
):
    skill_version = await res_q.get_resource_version(
        db,
        resource_type="skill_version",
        parent_id=skill_id,
        version=version,
    )
    if skill_version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return resource_to_response(skill_version, public_type="skill_version")


@router.delete("/{skill_id}/versions/{version}")
async def delete_skill_version(skill_id: str, version: int, db: AsyncSession = Depends(get_session)):
    skill_version = await res_q.get_resource_version(
        db,
        resource_type="skill_version",
        parent_id=skill_id,
        version=version,
    )
    if skill_version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    await res_q.delete_resource(db, skill_version)
    await db.commit()
    return deleted_response(skill_version, public_type="deleted_skill_version")


@router.get("/{skill_id}/versions/{version}/content")
async def download_skill_version(skill_id: str, version: int, db: AsyncSession = Depends(get_session)):
    skill_version = await res_q.get_resource_version(
        db,
        resource_type="skill_version",
        parent_id=skill_id,
        version=version,
    )
    if skill_version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    if not (is_object_storage_backend(skill_version.storage_backend) and skill_version.storage_key):
        raise HTTPException(status_code=500, detail="Skill version object is not stored in object storage")
    content, stored_content_type = await download_file_with_type(skill_version.storage_key)
    content_type = stored_content_type or skill_version.content_type or "application/zip"
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{skill_version.filename or skill_version.id}.zip"'},
    )


async def _create_skill_version_resource(
    db: AsyncSession,
    skill_id: str,
    version_number: int,
    data: dict[str, Any],
    content: bytes,
):
    _enforce_skill_archive_size(content)
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        should_store_in_object_storage()
        stored = await save_file_bytes(
            content,
            "application/zip",
            namespace=f"skills/{skill_id}",
            filename=f"skill-v{version_number}-{sha256}.zip",
            category="versions",
        )
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return await res_q.create_resource(
        db,
        resource_type="skill_version",
        parent_id=skill_id,
        version=version_number,
        content=None,
        content_type="application/zip",
        filename=f"skill-v{version_number}.zip",
        data={
            "version": version_number,
            "files": data.get("files", []),
            "archive_format": "zip",
            "name": data.get("name"),
            "description": data.get("description"),
            "top_level_directory": data.get("top_level_directory"),
            "manifest": data.get("manifest"),
        },
        storage_backend=stored.backend,
        storage_key=stored.key,
        storage_url=stored.url,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256 or sha256,
    )


async def _skill_payload_from_request(request: Request) -> tuple[dict[str, Any], bytes]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        display_title = form.get("display_title")
        uploaded_files = []
        file_records = []
        for key, value in form.multi_items():
            if hasattr(value, "read"):
                raw = await value.read()
                filename = _normalize_zip_path(getattr(value, "filename", key))
                uploaded_files.append((filename, raw, getattr(value, "content_type", None)))
                file_records.append(
                    {
                        "filename": filename,
                        "mime_type": getattr(value, "content_type", None),
                        "size_bytes": len(raw),
                    }
                )
        manifest = _validate_skill_files(uploaded_files) if uploaded_files else {}
        content = _zip_uploaded_files(uploaded_files)
        return {
            "display_title": display_title,
            "name": manifest.get("name"),
            "description": manifest.get("description"),
            "files": file_records,
            "top_level_directory": manifest.get("top_level_directory"),
            "manifest": manifest,
        }, content

    body = await request.json()
    files = body.get("files")
    if isinstance(files, list) and files:
        uploaded_files = []
        file_records = []
        for item in files:
            if not isinstance(item, dict):
                continue
            filename = _normalize_zip_path(str(item.get("filename") or item.get("path") or "file"))
            raw_value = item.get("content", "")
            raw = raw_value.encode("utf-8") if isinstance(raw_value, str) else bytes(raw_value)
            mime_type = item.get("mime_type")
            uploaded_files.append((filename, raw, mime_type))
            file_records.append({"filename": filename, "mime_type": mime_type, "size_bytes": len(raw)})
        manifest = _validate_skill_files(uploaded_files)
        return {
            **body,
            "name": body.get("name") or manifest.get("name"),
            "description": body.get("description") or manifest.get("description"),
            "files": file_records,
            "top_level_directory": manifest.get("top_level_directory"),
            "manifest": manifest,
        }, _zip_uploaded_files(uploaded_files)

    manifest = json.dumps(body, separators=(",", ":")).encode("utf-8")
    content = _zip_uploaded_files([("manifest.json", manifest, "application/json")])
    return body, content


def _zip_uploaded_files(uploaded_files: list[tuple[str, bytes, str | None]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for filename, raw, _mime_type in uploaded_files:
            archive.writestr(_normalize_zip_path(filename), raw)
    return buffer.getvalue()


def _enforce_skill_archive_size(content: bytes) -> None:
    max_bytes = get_settings().oma_max_skill_archive_bytes
    if max_bytes > 0 and len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Skill archive exceeds maximum size of {max_bytes} bytes",
        )


def _normalize_zip_path(filename: str) -> str:
    parts = [part for part in filename.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or "file"


def _validate_skill_files(uploaded_files: list[tuple[str, bytes, str | None]]) -> dict[str, Any]:
    if not uploaded_files:
        raise HTTPException(status_code=422, detail="Skill uploads must include files")

    normalized_paths = [_normalize_zip_path(filename) for filename, _raw, _mime_type in uploaded_files]
    path_parts = [path.split("/") for path in normalized_paths]
    if any(len(parts) < 2 for parts in path_parts):
        raise HTTPException(status_code=422, detail="Skill files must live under one top-level directory")

    top_level = path_parts[0][0]
    if any(parts[0] != top_level for parts in path_parts):
        raise HTTPException(status_code=422, detail="Skill files must share one top-level directory")

    skill_path = f"{top_level}/SKILL.md"
    skill_file = next(
        (raw for filename, raw, _mime_type in uploaded_files if _normalize_zip_path(filename) == skill_path),
        None,
    )
    if skill_file is None:
        raise HTTPException(status_code=422, detail="Skill uploads must include root SKILL.md")

    frontmatter = _parse_skill_frontmatter(skill_file)
    missing = [field for field in ("name", "description") if not frontmatter.get(field)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"SKILL.md frontmatter is missing required field(s): {', '.join(missing)}",
        )
    return {**frontmatter, "top_level_directory": top_level}


def _parse_skill_frontmatter(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise HTTPException(status_code=422, detail="SKILL.md must start with YAML frontmatter")
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise HTTPException(status_code=422, detail="SKILL.md frontmatter must be closed with ---")

    frontmatter: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise HTTPException(status_code=422, detail="SKILL.md frontmatter must use key: value lines")
        key, value = stripped.split(":", 1)
        clean_value = value.strip().strip('"').strip("'")
        frontmatter[key.strip()] = clean_value
    return frontmatter
