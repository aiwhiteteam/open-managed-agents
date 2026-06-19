from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.workspace import CurrentWorkspace
from open_managed_agents import AuthProvider, create_app
from tests.conftest import TEST_HEADERS


async def test_api_keys_scope_resources_to_workspaces(client, monkeypatch):
    monkeypatch.setenv("OMA_API_KEYS", "key-a,key-b")
    monkeypatch.setenv("OMA_API_KEY_WORKSPACES", '{"key-a":"ws_a","key-b":"ws_b"}')
    get_settings.cache_clear()

    headers_a = {**TEST_HEADERS, "x-api-key": "key-a"}
    headers_b = {**TEST_HEADERS, "x-api-key": "key-b"}

    response = await client.post(
        "/v1/agents",
        headers=headers_a,
        json={"name": "Scoped Agent", "model": {"id": "gpt-5.5"}},
    )
    assert response.status_code == 201, response.text
    agent = response.json()

    response = await client.get("/v1/agents", headers=headers_b)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == []

    response = await client.get(f"/v1/agents/{agent['id']}", headers=headers_b)
    assert response.status_code == 404

    response = await client.post(
        "/v1/environments",
        headers=headers_a,
        json={"name": "shared-name", "config": {"type": "cloud"}},
    )
    assert response.status_code == 201, response.text

    response = await client.post(
        "/v1/environments",
        headers=headers_b,
        json={"name": "shared-name", "config": {"type": "cloud"}},
    )
    assert response.status_code == 201, response.text


async def test_create_app_accepts_hosted_auth_provider(monkeypatch):
    class HostedAuthProvider:
        async def authenticate(self, request, credentials):
            return CurrentWorkspace(id="ws_hosted", slug="hosted", source="hosted_test")

    assert isinstance(HostedAuthProvider(), AuthProvider)

    monkeypatch.delenv("OMA_API_KEYS", raising=False)
    get_settings.cache_clear()

    app = create_app(auth_provider=HostedAuthProvider())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/agents",
            headers=TEST_HEADERS,
            json={"name": "Hosted Agent", "model": {"id": "gpt-5.5"}},
        )
        assert response.status_code == 201, response.text

        response = await client.get("/v1/agents", headers=TEST_HEADERS)
        assert response.status_code == 200, response.text
        assert [item["name"] for item in response.json()["data"]] == ["Hosted Agent"]
