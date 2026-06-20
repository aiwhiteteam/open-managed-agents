import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_access
from app.config import get_settings
from app.db.engine import get_session
from app.db.queries import resources as res_q
from app.models.common import FlexibleApiModel, ListResponse
from app.models.resources import deleted_response, resource_to_response
from app.pagination import paginate_by_id, sort_by_created_at
from app.storage import (
    StorageConfigurationError,
    copy_file,
    create_presigned_upload_url,
    delete_file as delete_stored_file,
    download_file_with_type,
    get_file_info,
    is_object_storage_backend,
    object_key,
    object_storage_backend_label,
    public_url_for_key,
    save_file_bytes,
    should_store_in_object_storage,
)
from app.workspace import workspace_id_or_default

router = APIRouter(
    prefix="/v1/files",
    tags=["files"],
    dependencies=[Depends(require_api_access)],
)


class PresignFileBody(FlexibleApiModel):
    filename: str
    mime_type: str = "application/octet-stream"
    namespace: str = "oma"
    expires_in: int = 900


class CompleteFileBody(FlexibleApiModel):
    key: str
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
):
    content = await file.read()
    _enforce_size_limit(
        len(content),
        get_settings().oma_max_file_upload_bytes,
        label="File upload",
    )
    mime_type = file.content_type or "application/octet-stream"
    sha256 = hashlib.sha256(content).hexdigest()
    existing = await _find_deduplicated_file(db, sha256=sha256)
    if existing is None:
        try:
            should_store_in_object_storage()
            stored = await save_file_bytes(
                content,
                mime_type,
                namespace="oma",
                filename=file.filename or "upload",
                category="files",
            )
        except StorageConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        storage_backend = stored.backend
        storage_key = stored.key
        storage_url = stored.url
        stored_size_bytes = stored.size_bytes
        stored_sha256 = stored.sha256 or sha256
        data = {
            "filename": file.filename,
            "mime_type": mime_type,
        }
    else:
        storage_backend = existing.storage_backend
        storage_key = existing.storage_key
        storage_url = existing.storage_url
        stored_size_bytes = existing.size_bytes
        stored_sha256 = existing.sha256 or sha256
        data = {
            "filename": file.filename,
            "mime_type": mime_type,
            "deduplicated_from_file_id": existing.id,
        }

    resource = await res_q.create_resource(
        db,
        resource_type="file",
        name=file.filename,
        filename=file.filename,
        content=None,
        content_type=mime_type,
        data=data,
        storage_backend=storage_backend,
        storage_key=storage_key,
        storage_url=storage_url,
        size_bytes=stored_size_bytes,
        sha256=stored_sha256,
    )
    await db.commit()
    return resource_to_response(resource, public_type="file")


@router.post("/presign")
async def presign_file_upload(body: PresignFileBody):
    try:
        if not should_store_in_object_storage():
            raise HTTPException(status_code=503, detail="Object storage is not configured")
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    key = object_key(
        namespace=body.namespace,
        category="staged-uploads",
        filename=body.filename,
    )
    upload_url = await create_presigned_upload_url(
        key,
        body.mime_type,
        expires_in=body.expires_in,
    )
    return {
        "type": "file_upload_url",
        "key": key,
        "upload_url": upload_url,
        "method": "PUT",
        "headers": {"content-type": body.mime_type},
        "expires_in": body.expires_in,
    }


@router.post("/complete", status_code=201)
async def complete_file_upload(body: CompleteFileBody, db: AsyncSession = Depends(get_session)):
    try:
        if not should_store_in_object_storage():
            raise HTTPException(status_code=503, detail="Object storage is not configured")
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _validate_staged_upload_key(body.key)
    info = await get_file_info(body.key)
    mime_type = body.mime_type or info.get("ContentType") or "application/octet-stream"
    size_bytes = body.size_bytes or info.get("ContentLength")
    if size_bytes is not None:
        _enforce_size_limit(
            int(size_bytes),
            get_settings().oma_max_file_upload_bytes,
            label="File upload",
        )
    filename = body.filename or body.key.split("/")[-1]
    existing = await _find_deduplicated_file(db, sha256=body.sha256)
    if existing is None:
        permanent_key = object_key(
            namespace="oma",
            category="files",
            filename=filename,
            content_sha256=body.sha256,
        )
        await copy_file(body.key, permanent_key, content_type=mime_type)
        storage_key = permanent_key
        storage_url = public_url_for_key(permanent_key)
        storage_backend = object_storage_backend_label()
        data = {
            "filename": filename,
            "mime_type": mime_type,
        }
    else:
        storage_key = existing.storage_key
        storage_url = existing.storage_url
        storage_backend = existing.storage_backend
        data = {
            "filename": filename,
            "mime_type": mime_type,
            "deduplicated_from_file_id": existing.id,
        }
    await delete_stored_file(body.key)
    resource = await res_q.create_resource(
        db,
        resource_type="file",
        name=filename,
        filename=filename,
        content_type=mime_type,
        data=data,
        storage_backend=storage_backend,
        storage_key=storage_key,
        storage_url=storage_url,
        size_bytes=int(size_bytes) if size_bytes is not None else None,
        sha256=body.sha256,
    )
    await db.commit()
    return resource_to_response(resource, public_type="file")


@router.get("")
async def list_files(
    limit: int = 50,
    after_id: str | None = None,
    before_id: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    files = await res_q.list_resources(db, resource_type="file", limit=1000)
    files = sort_by_created_at(files, order="desc")
    return paginate_by_id(
        [resource_to_response(f, public_type="file") for f in files],
        limit=limit,
        after_id=after_id,
        before_id=before_id,
    )


@router.get("/{file_id}")
async def retrieve_file_metadata(file_id: str, db: AsyncSession = Depends(get_session)):
    file = await res_q.get_resource(db, resource_id=file_id, resource_type="file")
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return resource_to_response(file, public_type="file")


@router.get("/{file_id}/content")
async def download_file(file_id: str, db: AsyncSession = Depends(get_session)):
    file = await res_q.get_resource(db, resource_id=file_id, resource_type="file")
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    if not (is_object_storage_backend(file.storage_backend) and file.storage_key):
        raise HTTPException(status_code=500, detail="File object is not stored in object storage")
    content, stored_content_type = await download_file_with_type(file.storage_key)
    content_type = stored_content_type or file.content_type or "application/octet-stream"
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{file.filename or file.id}"'},
    )


@router.delete("/{file_id}")
async def delete_file(file_id: str, db: AsyncSession = Depends(get_session)):
    file = await res_q.get_resource(db, resource_id=file_id, resource_type="file")
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    if is_object_storage_backend(file.storage_backend) and file.storage_key:
        active_references = await res_q.count_resources_by_storage_key(
            db,
            resource_type="file",
            storage_backend=file.storage_backend,
            storage_key=file.storage_key,
        )
        if active_references <= 1:
            await delete_stored_file(file.storage_key)
    await res_q.delete_resource(db, file)
    await db.commit()
    return deleted_response(file, public_type="file_deleted")


def _enforce_size_limit(size_bytes: int, max_bytes: int, *, label: str) -> None:
    if max_bytes > 0 and size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds maximum size of {max_bytes} bytes",
        )


async def _find_deduplicated_file(db: AsyncSession, *, sha256: str | None):
    if not sha256:
        return None
    existing = await res_q.get_resource_by_sha256(db, resource_type="file", sha256=sha256)
    if existing is None:
        return None
    if not (is_object_storage_backend(existing.storage_backend) and existing.storage_key):
        return None
    return existing


def _validate_staged_upload_key(key: str) -> None:
    workspace_prefix = f"workspaces/{workspace_id_or_default()}/"
    if not key.startswith(workspace_prefix) or "/staged-uploads/" not in key:
        raise HTTPException(
            status_code=422,
            detail="Only staged upload keys for the current workspace can be completed",
        )
