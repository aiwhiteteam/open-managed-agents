# Anthropic SDK Contract Tests

These tests use the official `anthropic` Python SDK against the local ASGI app with strict response validation enabled. They are meant to prevent API-shape guessing.

Install the contract test dependency:

```bash
uv sync --extra dev --extra contract
```

Run the contract suite:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/contract -p no:cacheprovider
```

Current passing coverage:

- Managed Agents beta SDK surface discovery.
- `client.beta.agents.create/retrieve/update/list/archive`.
- `client.beta.files.upload/retrieve_metadata/list/download/delete`.

Current expected failures are intentional compatibility gaps:

- `client.beta.agents.versions.list`: MVP returns `agent_version`; SDK expects agent-shaped snapshots.
- `client.beta.environments.create`: SDK requires `description`.
- `client.beta.sessions.create`: SDK requires the fuller session model, including agent/resources/stats/usage/vault fields.
- `client.beta.skills.create`: SDK multipart/source/version/directory shapes are not exact yet.

Reference sources:

- https://github.com/anthropics/anthropic-sdk-python
- https://github.com/anthropics/anthropic-sdk-python/blob/main/api.md
- https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python
