import pytest

from app.config import get_settings
from app.storage import (
    StorageConfigurationError,
    is_object_storage_backend,
    object_storage_backend_label,
    object_storage_configured,
    object_key,
    public_url_for_key,
    r2_configured,
    should_store_in_object_storage,
    should_store_in_r2,
)


def _clear_s3_env(monkeypatch):
    for key in (
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET_NAME",
        "S3_PUBLIC_URL",
        "S3_REGION",
    ):
        monkeypatch.delenv(key, raising=False)


def test_s3_object_storage_configuration(monkeypatch):
    monkeypatch.setenv("OMA_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://storage.example.com")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("S3_BUCKET_NAME", "oma-files")
    monkeypatch.setenv("S3_PUBLIC_URL", "https://cdn.example.com/oma-files")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    get_settings.cache_clear()

    assert object_storage_configured() is True
    assert should_store_in_object_storage() is True
    assert object_storage_backend_label() == "s3"
    assert public_url_for_key("agents/file.txt") == "https://cdn.example.com/oma-files/agents/file.txt"
    assert is_object_storage_backend("s3") is True
    assert object_key(
        namespace="oma",
        category="files",
        filename="file.txt",
        content_sha256="abcdef1234567890",
        workspace_id="ws_test",
    ).startswith("workspaces/ws_test/oma/files/")


def test_r2_legacy_alias_configuration(monkeypatch):
    _clear_s3_env(monkeypatch)
    monkeypatch.setenv("OMA_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "account-id")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_FILES_BUCKET_NAME", "oma-files")
    monkeypatch.setenv("R2_FILES_URL", "https://pub.example.com")
    get_settings.cache_clear()

    assert r2_configured() is True
    assert should_store_in_r2() is True
    assert object_storage_backend_label() == "r2"
    assert public_url_for_key("skills/archive.zip") == "https://pub.example.com/skills/archive.zip"
    assert is_object_storage_backend("r2") is True


def test_database_storage_backend_is_not_supported(monkeypatch):
    monkeypatch.setenv("OMA_STORAGE_BACKEND", "database")
    get_settings.cache_clear()

    with pytest.raises(StorageConfigurationError):
        should_store_in_object_storage()


def test_forced_object_storage_requires_configuration(monkeypatch):
    _clear_s3_env(monkeypatch)
    monkeypatch.setenv("OMA_STORAGE_BACKEND", "s3")
    get_settings.cache_clear()

    with pytest.raises(StorageConfigurationError):
        should_store_in_object_storage()
