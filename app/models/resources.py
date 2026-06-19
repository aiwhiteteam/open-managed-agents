import base64
from typing import Any

from app.db.models import ManagedResource
from app.models.common import FlexibleApiModel


class GenericBody(FlexibleApiModel):
    pass


def resource_to_response(resource: ManagedResource, *, public_type: str | None = None) -> dict[str, Any]:
    data = dict(resource.data or {})
    data.update(
        {
            "id": resource.id,
            "type": public_type or resource.resource_type,
            "created_at": resource.created_at,
            "updated_at": resource.updated_at,
            "archived_at": resource.archived_at,
        }
    )
    if resource.version is not None:
        data.setdefault("version", resource.version)
    if resource.name is not None:
        data.setdefault("name", resource.name)
    if resource.status:
        data.setdefault("status", resource.status)
    if resource.deleted_at is not None:
        data["deleted_at"] = resource.deleted_at
    if resource.filename is not None:
        data.setdefault("filename", resource.filename)
    if resource.content_type is not None:
        data.setdefault("mime_type", resource.content_type)
    if resource.size_bytes is not None:
        data.setdefault("size_bytes", resource.size_bytes)
    elif resource.content is not None:
        data.setdefault("size_bytes", len(resource.content))
    if resource.sha256 is not None:
        data.setdefault("sha256", resource.sha256)
    if resource.storage_backend is not None:
        data.setdefault(
            "storage",
            {
                "backend": resource.storage_backend,
                "key": resource.storage_key,
                "url": resource.storage_url,
            },
        )
    return data


def deleted_response(resource: ManagedResource, *, public_type: str | None = None) -> dict[str, Any]:
    return {
        "id": resource.id,
        "type": public_type or f"deleted_{resource.resource_type}",
        "deleted": True,
    }


def encode_content(content: bytes | None) -> str | None:
    if content is None:
        return None
    return base64.b64encode(content).decode("ascii")
