# Claude Code Instructions

This repo is the OSS core. It must remain self-hostable and tenant-ready, while a private hosted/enterprise repo can wrap it without rewriting it.

Follow these invariants:

- Do not put organization, billing, seats, SSO, invite, RBAC, usage metering, or hosted admin UI logic into core.
- Use `workspace_id` as the core tenant boundary. Do not add `organization_id` to core resources.
- Keep public Managed Agents APIs workspace-path-free: `/v1/agents`, `/v1/sessions`, `/v1/files`, etc.
- Resolve workspace through auth/provider context, then run workspace-scoped core queries.
- Every persisted Managed Agents resource must be workspace-scoped.
- Object storage keys must include `workspaces/{workspace_id}/...`.
- Private hosted code should compose core with `from open_managed_agents import create_app` and provider interfaces, not fork or rewrite core.
- Core must not import private hosted modules.
- Add cross-workspace non-visibility tests when adding or changing resource families.

See `docs/open-core-architecture.md` for the full architecture contract.
