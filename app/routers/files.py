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

    resource = await res_q.create_resource(
        db,
        resource_type="file",
        name=file.filename,
        filename=file.filename,
        content=None,
        content_type=mime_type,
        data={
            "filename": file.filename,
            "mime_type": mime_type,
        },
        storage_backend=stored.backend,
        storage_key=stored.key,
        storage_url=stored.url,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256 or sha256,
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
    if not body.key.startswith("oma/staged-uploads/") and "/staged-uploads/" not in body.key:
        raise HTTPException(status_code=422, detail="Only staged upload keys can be completed")
    info = await get_file_info(body.key)
    mime_type = body.mime_type or info.get("ContentType") or "application/octet-stream"
    size_bytes = body.size_bytes or info.get("ContentLength")
    if size_bytes is not None:
        _enforce_size_limit(
            int(size_bytes),
            get_settings().oma_max_file_upload_bytes,
            label="File upload",
        )
    permanent_key = object_key(
        namespace="oma",
        category="files",
        filename=body.filename or body.key.split("/")[-1],
        content_sha256=body.sha256,
    )
    await copy_file(body.key, permanent_key, content_type=mime_type)
    await delete_stored_file(body.key)
    resource = await res_q.create_resource(
        db,
        resource_type="file",
        name=body.filename or body.key.split("/")[-1],
        filename=body.filename or body.key.split("/")[-1],
        content_type=mime_type,
        data={
            "filename": body.filename or body.key.split("/")[-1],
            "mime_type": mime_type,
        },
        storage_backend=object_storage_backend_label(),
        storage_key=permanent_key,
        storage_url=public_url_for_key(permanent_key),
        size_bytes=int(size_bytes) if size_bytes is not None else None,
        sha256=body.sha256,
    )
    await db.commit()
    return resource_to_response(resource, public_type="file")


@router.get("")
async def list_files(limit: int = 50, db: AsyncSession = Depends(get_session)):
    files = await res_q.list_resources(db, resource_type="file", limit=limit)
    return ListResponse[dict].from_items([resource_to_response(f, public_type="file") for f in files])


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
