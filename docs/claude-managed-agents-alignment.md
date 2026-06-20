# Claude Managed Agents Alignment

Last checked: 2026-06-19

This document is the engineering alignment contract between Claude Managed Agents official semantics and Open Managed Agents architecture. Treat official Claude docs and official SDK-generated contracts as the source of truth. Do not rely on removed research notes or informal analysis when implementing compatibility behavior.

## Source Policy

Before changing a Managed Agents-shaped semantic contract, check the relevant official docs:

- Agent definition and versioning: https://platform.claude.com/docs/en/managed-agents/agent-setup
- Tools: https://platform.claude.com/docs/en/managed-agents/tools
- MCP connector: https://platform.claude.com/docs/en/managed-agents/mcp-connector
- Permission policies: https://platform.claude.com/docs/en/managed-agents/permission-policies
- Skills on agents: https://platform.claude.com/docs/en/managed-agents/skills
- Cloud environments: https://platform.claude.com/docs/en/managed-agents/environments
- Cloud sandbox reference: https://platform.claude.com/docs/en/managed-agents/cloud-sandboxes-reference
- Self-hosted sandboxes: https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes
- Sessions: https://platform.claude.com/docs/en/managed-agents/sessions
- Session operations: https://platform.claude.com/docs/en/managed-agents/session-operations
- Events and streaming: https://platform.claude.com/docs/en/managed-agents/events-and-streaming
- Files in sessions: https://platform.claude.com/docs/en/managed-agents/files
- Files API: https://platform.claude.com/docs/en/build-with-claude/files
- Vaults: https://platform.claude.com/docs/en/managed-agents/vaults
- Memory stores: https://platform.claude.com/docs/en/managed-agents/memory
- Multiagent sessions: https://platform.claude.com/docs/en/managed-agents/multi-agent
- Outcomes: https://platform.claude.com/docs/en/managed-agents/define-outcomes
- Scheduled deployments: https://platform.claude.com/docs/en/managed-agents/scheduled-deployments
- Webhooks: https://platform.claude.com/docs/en/managed-agents/webhooks
- Reference catalog: https://platform.claude.com/docs/en/managed-agents/reference

## Product Shape

Claude Managed Agents is not only a REST wrapper around a model call. It is a versioned control plane plus a durable execution plane:

- Reusable agent definitions.
- Environment resources that configure sandbox execution.
- Sessions that provision a sandbox first, then run from appended events.
- Append-only event history and SSE streaming.
- Built-in tools, custom tool continuation, MCP, vaults, skills, files, memory, outcomes, multiagent threads, webhooks, and scheduled deployments.

Open Managed Agents should mirror the public shape while using OpenAI Agents SDK and provider interfaces under the hood.

## Compatibility Matrix

| Claude semantic | Open Managed Agents architecture | Current status |
| --- | --- | --- |
| Managed Agents beta header | Accept native `open-managed-agents-beta` and Claude compatibility `anthropic-beta`/`anthropic-version` headers. | Implemented |
| Workspace-scoped API keys | Core resolves each request to `CurrentWorkspace`; public paths stay `/v1/...`. Hosted org/user/RBAC resolution stays outside core. | Implemented for core resources |
| Agent resource | `agents` is the mutable pointer; `agent_versions` stores immutable snapshots. | Implemented |
| Agent update semantics | Current version required; omitted fields preserved; scalars replace; arrays replace; metadata merges with empty-string delete; no-op returns current version. | Implemented |
| Multiagent roster pinning | Coordinator `multiagent.agents` entries without `version` are resolved to the referenced agent's current active version at create/update time. | Implemented |
| MCP server/toolset declaration | Agent `mcp_servers` and `mcp_toolset` entries must match. Secrets stay out of agent definitions and are supplied through session vaults. | Validation implemented; runtime MCP auth still partial |
| Tools | Built-in toolset, MCP toolset, and custom tools are stored in agent versions. | Stored; runtime semantics partial |
| Permission policies | Server-executed tools may require confirmation through `requires_action`; custom tools use application continuation through `user.custom_tool_result`. | MVP event contract implemented; full runtime enforcement still partial |
| Skills | Skills are separate filesystem-based resources referenced by agents; custom skill versions are pinned or `latest`. | Partial |
| Environments | Environment config is not versioned; each session gets its own sandbox instance. Network and package policies are environment config. | Partial |
| Cloud sandbox | Requires a production remote sandbox provider with network/package policy enforcement and filesystem state. | TODO |
| Self-hosted sandbox | `self_hosted` environment acts as a work queue claimed by external workers. | Partial |
| Session lifecycle | Session creation provisions the sandbox and starts `idle`; user/system events drive work. Valid states are `idle`, `running`, `rescheduling`, `terminated`. | Partial; core state guards implemented |
| Session-local agent update | Session `agent.tools` and `agent.mcp_servers` can be fully replaced while idle without mutating agent versions. | Partial; SDK strict response contract verified, runtime semantics still partial |
| Event protocol | User/system events are inputs; session/span/agent events are outputs; queued input events may have `processed_at = null`. | Partial |
| Custom tool continuation | `agent.custom_tool_use` pauses with `requires_action`; caller sends `user.custom_tool_result`. | Partial; MVP continuation contract implemented |
| Tool confirmation | `agent.tool_use` or `agent.mcp_tool_use` may pause; caller sends `user.tool_confirmation`. | Partial; MVP continuation contract implemented |
| File resources | Uploaded files can be mounted into sessions; session mounts create session-scoped file references; mounts are read-only copies. | Partial |
| Memory stores | Workspace-scoped text stores mount into a session as directories; memory changes produce immutable versions. | Partial |
| Vault credentials | Vaults are workspace-scoped; secret values are write-only; runtime resolves and refreshes credentials. | Metadata only |
| Outcomes | `user.define_outcome` starts autonomous work; separate grader context evaluates rubric and emits outcome span events. | Stub/partial |
| Multiagent threads | Threads share sandbox/filesystem/vault context but keep isolated event streams and context. | Stub |
| Deployments | Cron schedule plus initial events autonomously create sessions and deployment run records. | Partial |
| Webhooks | Deliver compact event identifiers with signatures, retry, freshness, idempotency, and disable behavior. | TODO |

## Architecture Contracts

### Core and hosted boundary

Core only owns workspace-scoped Managed Agents resources. Organization, membership, billing, RBAC, SSO, usage metering, and hosted admin tables belong in a private hosted layer that imports:

```python
from open_managed_agents import create_app

app = create_app(auth_provider=HostedOrgAuthProvider())
```

The hosted layer maps user/session/API key identity to organization, workspace, roles, quotas, and audit policy. Core receives only `CurrentWorkspace`.

### Agent definitions

Agent definitions are JSON resources, not standalone manifest uploads. Skills may contain filesystem packages and metadata files, but agent version publication is an update to the agent resource plus optimistic version checking.

Implementation rules:

- Preserve agent version immutability.
- Resolve unversioned multiagent roster entries at create/update time.
- Keep arrays as replacement fields.
- Keep metadata key-level merge/delete behavior.
- Validate MCP server/toolset consistency before persisting a version.

### Session runtime

The public session contract should be event-sourced:

- Create session in `idle`.
- Append user/system events.
- Claim durable work.
- Transition to `running`.
- Map OpenAI Agents SDK streaming events into public session/span/agent events.
- Transition to `idle`, `rescheduling`, or `terminated`.
- Store resumable SDK run state and sandbox state.

Process-local background tasks are acceptable only for MVP/local mode. Cloud Run production needs a durable queue provider with lease, heartbeat, retry, stop, and worker auth.

### Sandbox providers

Environment config is a control-plane resource. Sandbox execution must be provider-backed:

- `cloud`: remote sandbox provider such as E2B, Daytona, Modal, Runloop, or a self-managed worker fleet.
- `self_hosted`: work queue claimed by user-operated workers.
- `local`: development-only local/unix sandbox path.

Provider interfaces must enforce network allowlists, package manager exceptions, MCP endpoint exceptions, filesystem mounts, resource limits, and artifact capture.

### Tooling and MCP

Permission policies apply to server-executed tools only. Custom tools are application-owned; the runtime must stop on `agent.custom_tool_use` and resume only after `user.custom_tool_result`.

MCP auth is deliberately split:

- Agent definitions declare MCP servers by name and URL.
- Session creation supplies `vault_ids`.
- Runtime matches credentials by URL and emits session errors for connection or auth failures without preventing the session from existing.

### Files, skills, memory, and vaults

Relational metadata lives in Postgres-compatible storage. Object bytes live in S3-compatible object storage.

- Files: uploaded once, then copied or mounted into sessions.
- Skills: versioned filesystem packages referenced by agents.
- Memory stores: Postgres-backed path documents with immutable versions; runtime mounts them into sandbox context.
- Vaults: metadata in Postgres, secret values in an injected secret manager provider, not generic resource JSON.

### Webhooks and deployments

Webhooks and scheduled deployments are production semantics, not just CRUD:

- Webhooks need stable event IDs, signatures, freshness windows, retries, idempotency, and endpoint disabling.
- Deployments need cron/timezone correctness, upcoming run calculation, jitter, session creation, run records, and retry-safe workers.

## Implementation Order

Prefer this order when closing compatibility gaps:

1. Official Anthropic SDK contract tests for every changed surface.
2. Agent/version contract and multiagent roster pinning.
3. Complete session state machine edge cases and durable `rescheduling`.
4. Complete event protocol, including processed input updates and full event unions.
5. Wire custom tool continuation and tool confirmation into persisted OpenAI Agents SDK run state.
6. File/session resource copy semantics.
7. Durable queue/worker provider and Cloud Run-safe execution.
8. Sandbox provider abstraction and cloud/self-hosted implementations.
9. MCP runtime auth and permission enforcement.
10. Vault secret manager provider and credential lifecycle.
11. Memory runtime tools and mounts.
12. Multiagent threads.
13. Outcomes/grader loop.
14. Webhooks and deployment scheduler.
