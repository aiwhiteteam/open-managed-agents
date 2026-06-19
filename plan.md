# Open Managed Agents MVP Plan

Date: 2026-06-19

## Decision

Use Python 3.12 for the first implementation.

Reasoning:

- Claude Managed Agents is a managed agent control plane plus execution plane, not just a thin REST proxy. The public docs describe four core resources: Agent, Environment, Session, and Events. Sessions are stateful, long-running, resume cleanly, and store conversation history, sandbox state, and outputs server-side.
- Claude Managed Agents requires the `managed-agents-2026-04-01` beta header, supports long-running asynchronous work, SSE event streaming, persisted event history, cloud or self-hosted sandboxes, built-in tools, MCP, and versioned reusable agents.
- OpenAI Agents SDK for Python already has the runtime primitives we need: Agent, Runner, tool execution, sessions, streaming, handoffs, guardrails, MCP, tracing, and beta sandbox agents with persistent workspaces and resumable sandbox sessions.
- `votrix-backend` is a Python FastAPI service with Pydantic settings, SQLAlchemy async models, Alembic, structured logging, `run.sh`, `scripts/entrypoint.sh`, Docker, Cloud Build, and Cloud Run service manifests. This repo should follow that deployment style without modifying `votrix-backend`.

Primary references:

- Claude Managed Agents overview: https://platform.claude.com/docs/en/managed-agents/overview
- Claude Managed Agents quickstart: https://platform.claude.com/docs/en/managed-agents/quickstart
- Claude Managed Agents reference: https://platform.claude.com/docs/en/managed-agents/reference
- Claude agent setup: https://platform.claude.com/docs/en/managed-agents/agent-setup
- Claude environments: https://platform.claude.com/docs/en/managed-agents/environments
- Claude sessions: https://platform.claude.com/docs/en/managed-agents/sessions
- Claude events and streaming: https://platform.claude.com/docs/en/managed-agents/events-and-streaming
- Claude Agent SDK hosting notes: https://code.claude.com/docs/en/agent-sdk/hosting
- Claude Agent SDK session storage: https://code.claude.com/docs/en/agent-sdk/session-storage
- OpenAI Agents SDK intro: https://openai.github.io/openai-agents-python/
- OpenAI Agents SDK agents: https://openai.github.io/openai-agents-python/agents/
- OpenAI Agents SDK running agents: https://openai.github.io/openai-agents-python/running_agents/
- OpenAI Agents SDK sessions: https://openai.github.io/openai-agents-python/sessions/
- OpenAI Agents SDK streaming: https://openai.github.io/openai-agents-python/streaming/
- OpenAI Agents SDK sandbox agents: https://openai.github.io/openai-agents-python/sandbox_agents/

## Compatibility Scope

P0 is a CMA-shaped service powered by OpenAI Agents SDK, not full behavioral parity with Claude.

Implement now:

- `POST /v1/agents`
- `GET /v1/agents`
- `GET /v1/agents/{agent_id}`
- `PATCH /v1/agents/{agent_id}`
- `POST /v1/agents/{agent_id}/archive`
- `GET /v1/agents/{agent_id}/versions`
- `POST /v1/environments`
- `GET /v1/environments`
- `GET /v1/environments/{environment_id}`
- `PATCH /v1/environments/{environment_id}`
- `POST /v1/environments/{environment_id}/archive`
- `DELETE /v1/environments/{environment_id}`
- `POST /v1/sessions`
- `GET /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `PATCH /v1/sessions/{session_id}`
- `POST /v1/sessions/{session_id}/archive`
- `DELETE /v1/sessions/{session_id}`
- `POST /v1/sessions/{session_id}/cancel`
- `POST /v1/sessions/{session_id}/resume`
- `POST /v1/sessions/{session_id}/events`
- `GET /v1/sessions/{session_id}/events`
- `GET /v1/sessions/{session_id}/events/stream`
- `GET /v1/sessions/{session_id}/stream`

P0 event types:

- User input: `user.message`, `user.interrupt`, `user.tool_confirmation`, `user.custom_tool_result`
- Runtime output: `agent.message`, `agent.tool_use`, `agent.tool_result`
- Session lifecycle: `session.status_running`, `session.status_idle`, `session.status_terminated`, `session.error`, `session.updated`, `session.deleted`
- System: `system.message`

Known P0 limitations:

- This MVP uses a process-local background task runner. It is enough for Cloud Run single-service MVP and local validation, but production-grade long-running execution should move to Cloud Tasks, Pub/Sub, Temporal, DBOS, or another durable worker.
- SSE polling is database-backed and process-local; production fanout should use Postgres LISTEN/NOTIFY, Redis Streams, NATS, or a dedicated event bus.
- Sandbox support is represented in the Environment schema and runtime metadata first. Full OpenAI SandboxAgent mapping is the next step after the core event/session contract is stable.
- Exact Anthropic SDK generated schemas are not vendored yet. Any unverified wire details should stay flexible and marked as compatibility gaps rather than overfit guesses.

## Architecture

```
Client / Anthropic-shaped SDK
        |
        | REST + JSON + SSE
        v
FastAPI compatibility layer
        |
        | append-only events
        v
Postgres via SQLAlchemy async
        |
        | background work claim
        v
OpenAI Agents SDK runtime adapter
        |
        | stable normalized events
        v
Session event log + SSE stream
```

Core tables:

- `agents`: mutable resource pointer with active version.
- `agent_versions`: immutable versioned runtime configuration.
- `environments`: sandbox configuration.
- `sessions`: session lifecycle, pinned agent version, environment, runtime checkpoint blobs.
- `session_events`: append-only event stream with monotonic `seq`.

Runtime rules:

- Never expose raw OpenAI SDK event objects as public API.
- Store the full append-only session event log separately from model context.
- Pin each session to an agent version at creation time.
- Use stable event IDs and monotonic sequence numbers.
- Map SDK streaming/tool/run events into our event catalog.
- Persist `run_state` and `sandbox_state` columns even if the first runtime only partially fills them.
- Accept CMA-shaped environment and agent configs; reject unsafe unsupported config explicitly.

## Implementation Checklist

1. Create Python/FastAPI project skeleton using `votrix-backend` conventions.
2. Add settings, logging, auth/beta header dependencies, Cloud Run entrypoints, Docker, and env examples.
3. Add SQLAlchemy async engine, models, Alembic config, and initial migration.
4. Add Pydantic API models with flexible CMA-shaped payload fields.
5. Add repository/query helpers for agents, environments, sessions, and events.
6. Add routers for `/health`, `/docs`, `/v1/agents`, `/v1/environments`, `/v1/sessions`, and session events.
7. Add runtime adapter with `auto` mode: OpenAI Agents SDK when installed/configured, local deterministic runtime otherwise.
8. Add SSE event streaming with replay from stored events and live polling.
9. Add focused tests for create/list/retrieve, version pinning, append-only event logs, and local runtime event generation.
10. Run formatting/compile/tests where dependencies are available.

## Next Production Steps

- Extract an exact API contract from Anthropic SDK generated resources and types.
- Add contract tests against the official Anthropic Python SDK pointed at this service.
- Replace process-local background execution with durable workers and fencing locks.
- Implement OpenAI SandboxAgent environment mapping.
- Add OpenTelemetry traces and per-session usage accounting.
- Extend workspace isolation tests across every resource family, and add hosted-provider hooks for quotas, audit logging, sandbox fleet, and secrets.
- Add per-workspace egress policy and credential proxying.
- Add webhook subscriptions and scheduled deployment resources.
