# Open Managed Agents

An MVP compatibility layer for a Claude Managed Agents-shaped API backed by the OpenAI Agents SDK.

The first version is intentionally small:

- FastAPI service deployable as a portable Docker container on Cloud Run, Render, Railway, Fly.io, or AWS ECS/Fargate.
- SQLAlchemy async persistence for agents, environments, sessions, and append-only events.
- CMA-shaped `/v1/agents`, `/v1/environments`, `/v1/sessions`, and session event APIs.
- SSE replay/stream endpoint.
- Runtime adapter that uses OpenAI Agents SDK when configured, and a deterministic local runtime otherwise.
- Resource APIs for Skills, Files, Vaults, Memory Stores, Deployments, Deployment Runs, User Profiles, session resources, and self-hosted environment work queue stubs.
- Workspace-scoped core design: self-hosted defaults to one workspace, while hosted/org SaaS can wrap the core through provider injection.

See [plan.md](./plan.md) for the research notes, compatibility boundaries, and implementation roadmap.
For the official Claude Managed Agents semantic alignment map, see [docs/claude-managed-agents-alignment.md](./docs/claude-managed-agents-alignment.md).

For the open-core boundary and hosted SaaS compatibility contract, see [docs/open-core-architecture.md](./docs/open-core-architecture.md). Hosted/private layers should compose the core through the stable package import:

```python
from open_managed_agents import create_app

app = create_app(auth_provider=HostedOrgAuthProvider())
```

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

## Sandbox Runtime

Environment sandbox config can be mapped into OpenAI Agents SDK sandbox execution through `SandboxAgent` and `RunConfig.sandbox`. The MVP supports a local SDK-backed `unix_local` sandbox plan for development; production cloud/self-hosted sandbox execution still needs a real sandbox provider and durable worker lifecycle.

See [docs/sandbox-runtime.md](./docs/sandbox-runtime.md).

Session execution is queued as Postgres-backed environment work before it runs. See [docs/work-queue.md](./docs/work-queue.md).

Run a local worker for queued self-hosted work:

```bash
oma-worker --poll-interval 1
```

## Portable Runtime

The application is platform-neutral. All deployment targets use the same Dockerfile and the same process commands:

- Web: `scripts/start-web.sh`
- Worker: `scripts/start-worker.sh`
- Migration: `scripts/migrate.sh`

The default container command starts only the web process. Run migrations as a release/pre-deploy step or one-shot job before traffic is shifted. Set `RUN_MIGRATIONS=true` only for single-instance development or explicit one-off migration runs.

## Storage

This service follows the `votrix-backend` split:

- Relational state uses `DATABASE_URL` and can point at any compatible Postgres deployment.
- Core resources are scoped by `workspace_id`. OSS self-hosted defaults to `wrkspc_default`; hosted/private layers should resolve callers to a workspace through an injected auth provider.
- Memory stores are relational data: memory paths, content, metadata, optimistic versions, and version history live in Postgres.
- S3-compatible object storage stores object bytes under `workspaces/{workspace_id}/...`: file uploads, skill zip archives, future session artifacts, bundle-like objects, and optional large memory attachments/snapshots if added later.
- Local, staging, and production deployments should use `OMA_STORAGE_BACKEND=s3` plus `S3_*` settings for object bytes.
- Cloudflare R2 works through the same S3-compatible path. `R2_*` settings are kept as backward-compatible aliases, not the preferred deployment surface.

## Minimal Flow

Open Managed Agents routes use `/v1` paths and the native beta header:

- `open-managed-agents-beta: open-managed-agents-2026-04-01`

Claude Managed Agents compatibility headers are also accepted:

- `anthropic-version: 2023-06-01`
- `anthropic-beta: managed-agents-2026-04-01`

When using `anthropic-beta`, the Anthropic version header is required. Native clients should use `open-managed-agents-beta`.

Create an agent:

```bash
curl -s http://localhost:8080/v1/agents \
  -H 'content-type: application/json' \
  -H 'open-managed-agents-beta: open-managed-agents-2026-04-01' \
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
  -H 'open-managed-agents-beta: open-managed-agents-2026-04-01' \
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

Official Anthropic Python SDK compatibility checks live in [docs/anthropic-sdk-contract-tests.md](./docs/anthropic-sdk-contract-tests.md).

## License

MIT. See [LICENSE](./LICENSE).

## Deployment Targets

The root `Dockerfile` is the source of truth for every platform. Provider-specific files live under `deploy/`:

- `deploy/gcp`: Google Cloud Run and Cloud Build.
- `deploy/render`: Render Blueprint with web, worker, managed Postgres, and pre-deploy migration.
- `deploy/railway`: Railway web and worker config-as-code templates.
- `deploy/fly`: Fly.io app config with web, worker, and release migration.
- `deploy/aws`: AWS ECS/Fargate Terraform reference for web and worker services.
- `deploy/docker-compose`: Docker Compose for local integration, simple VPS, and self-hosted smoke tests.

Set `DATABASE_URL`, `OPENAI_API_KEY`, `OMA_API_KEYS`, `OMA_STORAGE_BACKEND=s3`, and all `S3_*` values as platform secrets or environment variables. `DATABASE_URL` can point at Render/Railway/Fly Postgres, Cloud SQL, RDS, or any compatible Postgres deployment. Object bytes should point at S3-compatible object storage.
