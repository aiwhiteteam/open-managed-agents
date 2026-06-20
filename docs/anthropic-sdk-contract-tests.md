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
- `client.beta.agents.versions.list`.
- `client.beta.environments.create/retrieve/update/list/archive/delete`.
- `client.beta.sessions.create/retrieve/update/list/archive/delete`.
- `client.beta.sessions.create` resource union for `file`, `github_repository`, and `memory_store`, including GitHub token redaction.
- `client.beta.sessions.update` metadata/title patches and session-local agent `tools`/`mcp_servers` replacement.
- `client.beta.sessions.events.send/list`.
- `client.beta.sessions.resources.add/retrieve/update/list/delete`.
- `client.beta.sessions.threads.list/retrieve/archive`.
- `client.beta.sessions.threads.events.list`.
- `client.beta.files.upload/retrieve_metadata/list/download/delete`.
- `client.beta.skills.create/retrieve/list/delete`.
- `client.beta.skills.versions.create/retrieve/list/download/delete`.
- `client.beta.vaults.create/retrieve/update/list/archive/delete`.
- `client.beta.vaults.credentials.create/retrieve/update/list/archive/delete/mcp_oauth_validate`.
- `client.beta.memory_stores.create/retrieve/update/list/archive/delete`.
- `client.beta.memory_stores.memories.create/retrieve/update/list/delete`.
- `client.beta.memory_stores.memory_versions.retrieve/list/redact`.
- `client.beta.deployments.create/retrieve/update/list/archive/pause/unpause/run`.
- `client.beta.deployment_runs.retrieve/list`.
- `client.beta.user_profiles.create/retrieve/update/list/create_enrollment_url`.
- SDK `next_page` cursor pagination for agents, sessions, skills, credentials, memories, and user profiles.
- SDK `after_id` pagination for files.
- Representative list filters and sort options: `include_archived`, `source`, `path_prefix`, `order/order_by`, `deployment_id`, `trigger_type`, and `has_error`.
- Invalid page cursor handling, invalid file ID cursor handling, timestamp alias filtering, and high-limit clamping.

Important remaining coverage gaps:

- Exhaustive pagination edge cases across every route group, especially expired cursor behavior.
- Full filter semantics for every list endpoint, especially less common filters.
- Production runtime semantics behind the validated response shapes.

Reference sources:

- https://github.com/anthropics/anthropic-sdk-python
- https://github.com/anthropics/anthropic-sdk-python/blob/main/api.md
- https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python
