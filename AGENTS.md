# Agent Instructions

This repo is the open-source core for Open Managed Agents. Keep it usable as a self-hosted service while preserving a clean extension boundary for a private hosted/enterprise repo.

## Open-Core Boundary

- Do not add organization, billing, seats, SSO, invite, RBAC, usage metering, or hosted admin UI logic to OSS core.
- Core owns Managed Agents behavior: `/v1` route shape, SQLAlchemy models/query helpers, runtime adapter, object storage adapter, workspace-scoped resources, and default self-hosted operation.
- Hosted/private code should import core with `from open_managed_agents import create_app` and compose it through provider interfaces. Do not assume hosted SaaS is implemented by forking core or by an HTTP proxy-only wrapper.
- Core must never import private hosted modules.

## Tenant Model

- `workspace_id` is the only tenant boundary inside core.
- OSS defaults to `wrkspc_default`; self-hosted users should not need to understand multi-tenancy.
- Public Managed Agents routes must stay workspace-path-free, for example `/v1/agents`, not `/v1/workspaces/{workspace_id}/agents`.
- Auth resolves a request to `CurrentWorkspace`; every persisted Managed Agents resource must be scoped to that workspace.
- Object storage keys must include `workspaces/{workspace_id}/...`.

## Provider Interfaces

- Hosted-only behavior belongs behind replaceable providers such as auth, quota, secret manager, sandbox, webhook delivery, and audit logging.
- Default OSS providers should be simple and self-hosted friendly.
- New provider interfaces should be narrow, typed, and usable without importing hosted code.

## Tests

- Add cross-workspace non-visibility tests for every new major resource family.
- Keep tests for default single-workspace behavior so OSS remains easy to run locally.
