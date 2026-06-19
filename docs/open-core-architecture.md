# Open-Core Architecture

This repo is the open-source core. It must remain usable as a self-hosted service while also being easy for a private hosted/enterprise repo to import and extend.

This follows the common open-core pattern used by products like PostHog and Cal.com: keep the self-hosted core usable, keep enterprise/hosted product concerns in a separate layer, and avoid rewriting the core for hosted SaaS.

## Boundary

Core owns Managed Agents behavior:

- FastAPI route shape for `/v1/agents`, `/v1/sessions`, resources, skills, files, environments, and work queue APIs.
- SQLAlchemy models and query helpers for core resources.
- OpenAI Agents SDK runtime adapter.
- S3-compatible object storage adapter.
- Workspace-scoped resource isolation.
- Default single-workspace self-hosted experience.

Hosted/private layer owns SaaS behavior:

- Organizations, members, invitations, RBAC, SSO, billing, seats, quotas, usage metering, audit logs, support tooling, and admin UI.
- Hosted sandbox fleet and provider-specific cloud credentials.
- Secret manager policy and enterprise credential lifecycle.

Do not put organization, billing, seat, SSO, or hosted-only product concepts into core tables or core query logic.

## Tenant Model

Core uses `workspace_id` as the only tenant boundary. It does not use `organization_id`.

```text
Hosted/private:
  user/api_key/session -> organization -> workspace -> permissions

OSS core:
  CurrentWorkspace(id=...) -> workspace-scoped core resources
```

Self-hosted OSS defaults to:

```text
workspace_id = wrkspc_default
workspace_slug = default
```

Public Managed Agents routes must stay workspace-path-free:

```text
/v1/agents
/v1/sessions
/v1/files
```

Do not introduce public paths like `/v1/workspaces/{workspace_id}/agents` for core Managed Agents APIs. The workspace is resolved from auth context, matching the platform pattern where API keys are scoped to a workspace.

## Extension Contract

Private hosted code should import core in-process:

```python
from open_managed_agents import create_app

app = create_app(auth_provider=HostedOrgAuthProvider())
```

The hosted auth provider resolves the caller to `CurrentWorkspace`. Core routers and query helpers then operate on that workspace scope.

Prefer provider injection over forking or placing an HTTP proxy in front of core. A separate HTTP wrapper service should only be introduced if core is intentionally operated as a standalone internal platform service.

The private hosted repo should own app composition, not core behavior:

```text
open-managed-agents:
  create_app(...)
  core routes
  workspace-scoped query/runtime/storage behavior

open-managed-agents-hosted:
  HostedOrgAuthProvider
  BillingQuotaProvider
  HostedSecretProvider
  HostedSandboxProvider
  organization/member/billing/admin tables
```

The hosted repo may run the same database deployment as core, but tables should remain layered:

```text
Core tables:
  workspaces
  agents
  sessions
  session_events
  managed_resources
  environments

Hosted tables:
  organizations
  organization_members
  workspace_members
  service_accounts
  billing_accounts
  usage_metering
  audit_logs
  sso_connections
```

Core tables must not require hosted tables to exist.

## Deployment Files

This repo is allowed to contain production-ready self-hosting and reference deployment files:

```text
Dockerfile
entrypoint.sh
scripts/start-web.sh
scripts/start-worker.sh
deploy/gcp
deploy/render
deploy/railway
deploy/fly
deploy/aws
deploy/docker-compose
```

These files are the OSS distribution surface. They do not mean core must only run as a standalone web service.

Hosted/private deployments may ignore these files and import core directly:

```python
from open_managed_agents import create_app

app = create_app(auth_provider=HostedOrgAuthProvider())
```

Keep this boundary clear:

- Deployment templates may depend on cloud platforms.
- Core business logic must not depend on a specific hosting platform.
- Platform-specific secrets, URLs, queues, and managed services should be injected through settings or providers.
- Hosted/private repos should compose core with hosted providers instead of editing deploy templates in this repo.

## Invariants

- Every core persistent resource must have `workspace_id`.
- Every core query/list/get helper must scope by current workspace unless it is an explicitly named internal/unscoped helper.
- Object storage keys must include `workspaces/{workspace_id}/...`.
- Core may expose provider interfaces, but it must not import private hosted modules.
- Hosted/private code may add organization tables that reference workspaces, but core must not require them.
- New routers should use `require_api_access` or another injected auth provider path before touching scoped resources.
- Tests should cover cross-workspace non-visibility for every new major resource family.
