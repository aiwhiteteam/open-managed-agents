# Open Managed Agents

An MVP compatibility layer for a Claude Managed Agents-shaped API backed by the OpenAI Agents SDK.

The first version is intentionally small:

- FastAPI service deployable to Google Cloud Run.
- SQLAlchemy async persistence for agents, environments, sessions, and append-only events.
- CMA-shaped `/v1/agents`, `/v1/environments`, `/v1/sessions`, and session event APIs.
- SSE replay/stream endpoint.
- Runtime adapter that uses OpenAI Agents SDK when configured, and a deterministic local runtime otherwise.
- Resource APIs for Skills, Files, Vaults, Memory Stores, Deployments, Deployment Runs, User Profiles, session resources, and self-hosted environment work queue stubs.

See [plan.md](./plan.md) for the research notes, compatibility boundaries, and implementation roadmap.

## Local Run

```bash
cp .env.example .env
bash run.sh --migrate
```

The API listens on `http://localhost:8080` by default. Override with `PORT=9000 bash run.sh`.

For local development without a real OpenAI key, leave `OPENAI_API_KEY` empty. The runtime falls back to a deterministic local response so the control plane and event stream can be tested.

## Model Providers

The runtime uses the OpenAI Agents SDK. It supports OpenAI and OpenAI-compatible providers through a provider registry:

- `openai`: official OpenAI provider, using `OPENAI_API_KEY`.
- `deepseek`: OpenAI-compatible Chat Completions provider, using `DEEPSEEK_API_KEY`.
- `minimax`: OpenAI-compatible Chat Completions provider, using `MINIMAX_API_KEY`.
- Custom providers from `OMA_OPENAI_COMPATIBLE_PROVIDERS`.

Use provider-qualified model config on an agent:

```json
{
  "model": {
    "provider": "deepseek",
    "id": "deepseek-v4-pro"
  }
}
```

Or shorthand:

```json
{
  "model": "minimax/MiniMax-M3"
}
```

OpenAI-compatible providers run with `use_responses=false`; they target Chat Completions-compatible APIs, so provider-specific capability gaps are expected for hosted tools, Responses-only state, and advanced tracing.

## Storage

This service follows the `votrix-backend` split:

- Supabase is used only through `DATABASE_URL` as relational Postgres for agents, sessions, events, resource metadata, and version pointers.
- Memory stores are relational data: memory paths, content, metadata, optimistic versions, and version history live in Postgres.
- Supabase Storage is not used.
- Cloudflare R2 stores object bytes: file uploads, skill zip archives, future session artifacts, bundle-like objects, and optional large memory attachments/snapshots if added later.
- Local development can leave R2 empty with `OMA_STORAGE_BACKEND=database`; in staging/production use `OMA_STORAGE_BACKEND=r2` plus all `R2_*` settings.

## Minimal Flow

All Managed Agents-shaped routes use `/v1` paths and expect:

- `anthropic-version: 2023-06-01`
- `anthropic-beta: managed-agents-2026-04-01`

Create an agent:

```bash
curl -s http://localhost:8080/v1/agents \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'anthropic-beta: managed-agents-2026-04-01' \
  -d '{
    "name": "Coding Assistant",
    "model": {"id": "gpt-5.5"},
    "system": "You are a helpful coding agent.",
    "tools": [{"type": "agent_toolset_20260401"}]
  }'
```

Publish a new agent version:

```bash
curl -s -X PATCH http://localhost:8080/v1/agents/$AGENT_ID \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'anthropic-beta: managed-agents-2026-04-01' \
  -d '{
    "version": 1,
    "system": "You are a helpful coding agent. Always write tests."
  }'
```

See [docs/agent-versioning.md](./docs/agent-versioning.md) for the versioning contract.

## API Compatibility

The implemented Managed Agents-shaped route groups are:

- `/v1/agents`
- `/v1/agents/{agent_id}/versions`
- `/v1/environments`
- `/v1/environments/{environment_id}/work`
- `/v1/sessions`
- `/v1/sessions/{session_id}/events`
- `/v1/sessions/{session_id}/resources`
- `/v1/sessions/{session_id}/threads`
- `/v1/files`
- `/v1/skills`
- `/v1/skills/{skill_id}/versions`
- `/v1/vaults`
- `/v1/vaults/{vault_id}/credentials`
- `/v1/memory_stores`
- `/v1/memory_stores/{memory_store_id}/memories`
- `/v1/memory_stores/{memory_store_id}/memory_versions`
- `/v1/deployments`
- `/v1/deployment_runs`
- `/v1/user_profiles`

Several route groups are metadata-compatible skeletons rather than complete Claude-equivalent behavior. See [TODO.md](./TODO.md).

## Cloud Run

The service follows the same deployment shape as `votrix-backend`:

- `Dockerfile`
- `entrypoint.sh`
- `cloudbuild.yaml`
- `service.staging.yaml`

Set `DATABASE_URL`, `OPENAI_API_KEY`, `OMA_API_KEYS`, `OMA_STORAGE_BACKEND=r2`, and all `R2_*` values as Cloud Run secrets or environment variables. `DATABASE_URL` should point at Supabase Postgres; object bytes should point at Cloudflare R2.
