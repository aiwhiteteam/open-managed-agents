import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db.engine import get_engine, reset_engine_for_tests
from app.db.models import Base

TEST_HEADERS = {
    "anthropic-beta": "managed-agents-2026-04-01",
    "anthropic-version": "2023-06-01",
}

OPEN_MANAGED_AGENTS_HEADERS = {
    "open-managed-agents-beta": "open-managed-agents-2026-04-01",
    "anthropic-version": "2023-06-01",
}


@pytest.fixture(autouse=True)
async def test_database(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OMA_RUNTIME_BACKEND", "local")
    monkeypatch.setenv("OMA_STORAGE_BACKEND", "database")
    monkeypatch.setenv("OMA_REQUIRE_BETA_HEADER", "true")
    monkeypatch.setenv("OMA_REQUIRE_ANTHROPIC_VERSION_HEADER", "true")
    get_settings.cache_clear()
    await reset_engine_for_tests()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await reset_engine_for_tests()
    get_settings.cache_clear()
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
