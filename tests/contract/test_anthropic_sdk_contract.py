from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

anthropic = pytest.importorskip("anthropic")

from anthropic import APIResponseValidationError, AsyncAnthropic  # noqa: E402

from tests.conftest import TEST_HEADERS

pytestmark = pytest.mark.contract


MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
BETA_KWARG = {"betas": [MANAGED_AGENTS_BETA]}


@asynccontextmanager
async def anthropic_client():
    from app.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as http_client:
        sdk = AsyncAnthropic(
            api_key="test-contract-key",
            base_url="http://testserver",
            default_headers={
                "anthropic-beta": MANAGED_AGENTS_BETA,
                "anthropic-version": "2023-06-01",
            },
            http_client=http_client,
            max_retries=0,
            _strict_response_validation=True,
        )
        yield sdk, http_client


def test_anthropic_sdk_exposes_expected_managed_agents_surface():
    client = AsyncAnthropic(api_key="test-contract-key")

    expected = {
        "agents": {"create", "retrieve", "update", "list", "archive", "versions"},
        "environments": {"create", "retrieve", "update", "list", "delete", "archive", "work"},
        "sessions": {"create", "retrieve", "update", "list", "delete", "archive", "events", "resources", "threads"},
        "skills": {"create", "retrieve", "list", "delete", "versions"},
        "files": {"upload", "retrieve_metadata", "list", "download", "delete"},
        "vaults": {"create", "retrieve", "update", "list", "delete", "archive", "credentials"},
        "memory_stores": {"create", "retrieve", "update", "list", "delete", "archive"},
        "deployments": {"create", "retrieve", "update", "list", "archive", "pause", "unpause", "run"},
        "deployment_runs": {"retrieve", "list"},
        "user_profiles": {"create", "retrieve", "update", "list", "create_enrollment_url"},
    }

    for resource_name, methods in expected.items():
        resource = getattr(client.beta, resource_name)
        missing = methods - set(dir(resource))
        assert not missing, f"{resource_name} missing SDK methods: {sorted(missing)}"


async def test_anthropic_sdk_agent_crud_contract():
    async with anthropic_client() as (client, _):
        agent = await client.beta.agents.create(
            name="SDK Contract Agent",
            model={"id": "gpt-5.5"},
            system="Be precise.",
            tools=[
                {
                    "type": "agent_toolset_20260401",
                    "configs": [],
                    "default_config": {
                        "enabled": True,
                        "permission_policy": {"type": "always_allow"},
                    },
                }
            ],
            **BETA_KWARG,
        )
        assert agent.type == "agent"
        assert agent.version == 1
        assert agent.model.id == "gpt-5.5"

        retrieved = await client.beta.agents.retrieve(agent.id, **BETA_KWARG)
        assert retrieved.id == agent.id

        updated = await client.beta.agents.update(
            agent.id,
            version=agent.version,
            metadata={"team": "contract"},
            **BETA_KWARG,
        )
        assert updated.version == 2
        assert updated.metadata["team"] == "contract"

        listed = [item async for item in client.beta.agents.list(limit=20, **BETA_KWARG)]
        assert any(item.id == agent.id for item in listed)

        archived = await client.beta.agents.archive(agent.id, **BETA_KWARG)
        assert archived.archived_at is not None


async def test_anthropic_sdk_files_contract():
    async with anthropic_client() as (client, _):
        uploaded = await client.beta.files.upload(
            file=("hello.txt", b"hello world", "text/plain"),
            **BETA_KWARG,
        )
        assert uploaded.type == "file"
        assert uploaded.filename == "hello.txt"
        assert uploaded.mime_type == "text/plain"
        assert uploaded.size_bytes == 11

        metadata = await client.beta.files.retrieve_metadata(uploaded.id, **BETA_KWARG)
        assert metadata.id == uploaded.id

        listed = [item async for item in client.beta.files.list(limit=20, **BETA_KWARG)]
        assert any(item.id == uploaded.id for item in listed)

        download = await client.beta.files.download(uploaded.id, **BETA_KWARG)
        assert await download.read() == b"hello world"

        deleted = await client.beta.files.delete(uploaded.id, **BETA_KWARG)
        assert deleted.id == uploaded.id
        assert deleted.type == "file_deleted"


@pytest.mark.xfail(
    raises=APIResponseValidationError,
    strict=True,
    reason="Agent versions endpoint returns MVP `agent_version` objects; official SDK expects agent-shaped snapshots.",
)
async def test_anthropic_sdk_agent_versions_contract_currently_xfail():
    async with anthropic_client() as (client, _):
        agent = await client.beta.agents.create(name="SDK Versions Agent", model={"id": "gpt-5.5"}, **BETA_KWARG)
        await client.beta.agents.update(agent.id, version=agent.version, system="v2", **BETA_KWARG)
        [item async for item in client.beta.agents.versions.list(agent.id, limit=20, **BETA_KWARG)]


@pytest.mark.xfail(
    raises=APIResponseValidationError,
    strict=True,
    reason="Environment responses are missing official SDK-required `description`.",
)
async def test_anthropic_sdk_environment_contract_currently_xfail():
    async with anthropic_client() as (client, _):
        await client.beta.environments.create(
            name="SDK Contract Environment",
            config={"type": "cloud"},
            **BETA_KWARG,
        )


@pytest.mark.xfail(
    raises=APIResponseValidationError,
    strict=True,
    reason="Session responses are still MVP-shaped and miss official SDK fields like agent/resources/stats/usage/vault_ids.",
)
async def test_anthropic_sdk_session_contract_currently_xfail():
    async with anthropic_client() as (client, http_client):
        agent = await client.beta.agents.create(name="SDK Session Agent", model={"id": "gpt-5.5"}, **BETA_KWARG)
        response = await http_client.post(
            "/v1/environments",
            headers=TEST_HEADERS,
            json={"name": "raw-env-for-session-contract", "config": {"type": "cloud"}},
        )
        assert response.status_code == 201, response.text
        environment = response.json()

        await client.beta.sessions.create(
            agent={"type": "agent", "id": agent.id, "version": agent.version},
            environment_id=environment["id"],
            **BETA_KWARG,
        )


@pytest.mark.xfail(
    raises=APIResponseValidationError,
    strict=True,
    reason="Skill responses do not yet match official SDK source/version/directory shapes exactly.",
)
async def test_anthropic_sdk_skills_contract_currently_xfail():
    async with anthropic_client() as (client, _):
        await client.beta.skills.create(
            display_title="Contract Skill",
            files=[
                (
                    "skill/SKILL.md",
                    b"---\nname: contract\ndescription: Contract skill.\n---\nUse the contract.",
                    "text/markdown",
                )
            ],
            **BETA_KWARG,
        )
