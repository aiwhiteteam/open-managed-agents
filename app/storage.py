"""Cloudflare R2 object storage.

Relational state lives in Postgres/SQLite. Object bytes live in R2 when
configured, with DB blob storage kept only as the local development fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.ids import new_id

_session: Any | None = None
_lock = asyncio.Lock()


@dataclass(frozen=True)
class StoredObject:
    backend: str
    key: str
    url: str
    content_type: str
    size_bytes: int
    sha256: str


class StorageConfigurationError(RuntimeError):
    pass


def r2_configured() -> bool:
    s = get_settings()
    return all(
        [
            s.r2_account_id,
            s.r2_access_key_id,
            s.r2_secret_access_key,
            s.r2_files_bucket_name,
            s.r2_files_url,
        ]
    )


def should_store_in_r2() -> bool:
    backend = get_settings().oma_storage_backend.lower()
    if backend == "r2":
        if not r2_configured():
            raise StorageConfigurationError("OMA_STORAGE_BACKEND=r2 requires all R2_* settings")
        return True
    if backend == "auto":
        return r2_configured()
    return False


def public_url_for_key(key: str) -> str:
    base = get_settings().r2_files_url.rstrip("/")
    return f"{base}/{key}"


def key_from_public_url(url: str) -> str:
    base = f"{get_settings().r2_files_url.rstrip('/')}/"
    return url[len(base) :] if url.startswith(base) else url


def object_key(
    *,
    namespace: str,
    category: str,
    filename: str,
    content_sha256: str | None = None,
) -> str:
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    safe_namespace = _safe_path_part(namespace or "oma")
    safe_category = _safe_path_part(category or "general")
    safe_filename = _safe_filename(filename)
    unique = content_sha256[:16] if content_sha256 else new_id("obj")
    return f"{safe_namespace}/{safe_category}/{date_str}/{unique}_{safe_filename}"


async def save_file_bytes(
    data: bytes,
    mime_type: str | None,
    *,
    namespace: str,
    filename: str,
    category: str = "general",
) -> StoredObject:
    """Upload bytes to R2 and return object metadata."""
    if not r2_configured():
        raise StorageConfigurationError("R2 is not fully configured")
    content_type = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    sha256 = hashlib.sha256(data).hexdigest()
    key = object_key(
        namespace=namespace,
        category=category,
        filename=filename,
        content_sha256=sha256,
    )
    s = get_settings()
    async with _get_session().client(**_client_kwargs()) as client:
        await client.put_object(
            Bucket=s.r2_files_bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    return StoredObject(
        backend="r2",
        key=key,
        url=public_url_for_key(key),
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256,
    )


async def download_file(key: str) -> bytes:
    data, _content_type = await download_file_with_type(key)
    return data


async def download_file_with_type(key: str) -> tuple[bytes, str | None]:
    s = get_settings()
    async with _get_session().client(**_client_kwargs()) as client:
        resp = await client.get_object(Bucket=s.r2_files_bucket_name, Key=key)
        data = await resp["Body"].read()
        return data, resp.get("ContentType")


async def create_presigned_upload_url(
    key: str,
    mime_type: str,
    *,
    expires_in: int = 900,
) -> str:
    s = get_settings()
    async with _get_session().client(**_client_kwargs()) as client:
        return await client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": s.r2_files_bucket_name,
                "Key": key,
                "ContentType": mime_type,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )


async def get_file_info(key: str) -> dict[str, Any]:
    s = get_settings()
    async with _get_session().client(**_client_kwargs()) as client:
        return await client.head_object(Bucket=s.r2_files_bucket_name, Key=key)


async def copy_file(
    source_key: str,
    destination_key: str,
    *,
    content_type: str | None = None,
) -> None:
    s = get_settings()
    params: dict[str, Any] = {
        "Bucket": s.r2_files_bucket_name,
        "Key": destination_key,
        "CopySource": {"Bucket": s.r2_files_bucket_name, "Key": source_key},
    }
    if content_type:
        params["ContentType"] = content_type
        params["MetadataDirective"] = "REPLACE"
    async with _get_session().client(**_client_kwargs()) as client:
        await client.copy_object(**params)


async def delete_file(key: str) -> None:
    s = get_settings()
    async with _get_session().client(**_client_kwargs()) as client:
        await client.delete_object(Bucket=s.r2_files_bucket_name, Key=key)


def _get_session() -> Any:
    global _session
    if _session is None:
        import aioboto3

        _session = aioboto3.Session()
    return _session


def _client_kwargs() -> dict[str, str]:
    s = get_settings()
    return {
        "service_name": "s3",
        "endpoint_url": f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
        "aws_access_key_id": s.r2_access_key_id,
        "aws_secret_access_key": s.r2_secret_access_key,
        "region_name": "auto",
    }


def _safe_filename(value: str | None) -> str:
    candidate = (value or "object").split("/")[-1].strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    return candidate[:180] or "object"


def _safe_path_part(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._=-]+", "_", value.strip())
    return candidate[:120] or "oma"
