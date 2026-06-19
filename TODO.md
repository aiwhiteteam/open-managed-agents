# TODO

This file tracks Claude Managed Agents compatibility gaps after the MVP API pass.

Use [docs/claude-managed-agents-alignment.md](./docs/claude-managed-agents-alignment.md) as the official-doc-aligned engineering map for these gaps.

## Claude Compatibility Risk Register

These are not just route coverage gaps. They are semantic contracts that can become expensive to fix later if core data models or runtime state machines drift away from Claude Managed Agents.

- Keep exact workspace/API-key scoping semantics. Claude API keys are workspace-scoped; core resolves every request to `CurrentWorkspace` without putting workspace IDs in public `/v1` paths.
- Complete durable session state machine semantics: real `rescheduling`, retry windows, and persisted OpenAI Agents SDK resume state.
- Wire `requires_action` pauses for custom tools and tool confirmations into real OpenAI Agents SDK HITL continuation, not only the MVP event contract.
- Verify session-local agent configuration update request/response shapes against the official SDK.
- Preserve agent versioning semantics: agent updates require the current version, arrays replace wholesale, metadata merges/deletes intentionally, and delegated-agent rosters stay pinned rather than auto-updated.
- Map the full event protocol, including `user.*`, `system.*`, `session.*`, `span.*`, and `agent.*` events, with `processed_at = null` for queued input events.
- Implement file/resource copy semantics. Uploaded files can be mounted into sessions, and session-produced files should become session-scoped file references.
- Implement permission policy semantics for built-in/MCP tools, including the boundary that custom tools are handled by the application continuation flow rather than normal permission policy enforcement.
- Implement MCP connector auth semantics: agent definitions reference MCP servers, while sessions supply credentials through vault/profile context.
- Implement vault credential lifecycle: enrollment, refresh, resolution, revocation/archive purge, secret redaction, and webhook emission.
- Implement outcome/grader loops with separate grader context, max iterations, rubric inputs, and outcome evaluation events.
- Implement multiagent thread semantics: shared sandbox/filesystem/vault context, but separate persistent thread/context/event stream per agent.
- Implement webhook delivery semantics: event IDs, organization/workspace identifiers, signatures, freshness window, retries, idempotency, and failure disabling.
- Implement deployment scheduler semantics: cron/timezone validation, upcoming runs, autonomous session creation, retries, and lease-safe workers.
- Implement sandbox/environment policy enforcement through provider interfaces: network allowlists, MCP/package-manager exceptions, resource limits, and production cloud sandbox backends.

## Design Invariants / Do Not Break

- OSS core only knows `workspace_id`; organization, billing, seats, SSO, invites, RBAC, hosted admin UI, and metering belong in a private hosted layer.
- Public Managed Agents routes remain workspace-path-free, for example `/v1/agents`, not `/v1/workspaces/{workspace_id}/agents`.
- Hosted SaaS should wrap core through `create_app(...)` and provider interfaces, not fork core or rely on an HTTP-proxy-only wrapper.
- Core must never import private hosted modules.
- Every persisted Managed Agents resource must be scoped by `workspace_id`.
- Object storage keys must include `workspaces/{workspace_id}/...`.
- Provider interfaces should stay narrow and replaceable: auth, quota, audit logging, secret manager, sandbox, queue, webhook delivery, and object storage.
- Default OSS providers should remain self-hosted friendly and usable with a single default workspace.
- Add cross-workspace non-visibility tests for every new major resource family.

## Contract Extraction

- Extract exact request/response schemas from `anthropic-sdk-python` generated types for every Managed Agents resource.
- Add contract tests using the official Anthropic Python SDK with `base_url` pointed at this service.
- Verify pagination parameter names and envelopes against the SDK for every list endpoint.
- Verify exact deleted-resource response shapes.

## Runtime Semantics

- Replace inline Postgres work-queue consumer with Cloud Tasks/PubSub deployment and fencing locks.
- Implement true resumable OpenAI Agents SDK `RunState` persistence.
- Map OpenAI Agents SDK streaming events into the full Claude Managed Agents event union.
- Add integration tests with mocked OpenAI-compatible endpoints for DeepSeek, MiniMax, and at least one custom provider.
- Persist and resume real OpenAI Agents SDK HITL/tool confirmation run state.
- Implement session `rescheduling` behavior for transient failures.
- Expand session state-machine tests for worker crashes, queued continuation batches, and `user.interrupt`.

## Open-Core Hosted Layer

- Keep core resource tables scoped by `workspace_id`; do not add organization/billing/RBAC dependencies to core.
- Add DB-backed API keys/service accounts as an optional provider, still resolving to `CurrentWorkspace`.
- Add provider interfaces for quota, audit logging, secret manager, and hosted sandbox fleet.
- Add cross-workspace isolation tests for every new route group.
- Implement organizations, members, billing, SSO, and RBAC only in a hosted/private layer that imports core.

## Sandbox And Environments

- Map `cloud` environments to a real production sandbox provider.
- Map `self_hosted` environments to a real worker queue.
- Add self-hosted worker auth, retry backoff, and automatic heartbeat timeout recovery.
- Enforce network policies, package installation controls, and sandbox resource limits.

## Skills

- Verify the zip archive response shape against Claude skill downloads and official SDK clients.
- Implement exact SDK multipart field compatibility for `files`.

## Files And Resources

- Add content deduplication, malware/content scanning, and object storage lifecycle policies.
- Implement exact session resource union types for file, GitHub repository, and future resource kinds.

## Vaults

- Store credentials in KMS/Vault instead of the generic resource table.
- Implement OAuth enrollment and validation flows.
- Implement credential refresh and webhook events.
- Add secret redaction in logs.

## Memory Stores

- Extract Memory Store routes into typed request/response models matching the official SDK.
- Add indexed Postgres columns or expression indexes for memory `path_key` lookups before production scale.
- Add semantic search/vector indexing if memories need retrieval beyond exact path and prefix lookup.
- Integrate memory tools into the runtime context builder.

## Deployments

- Implement real scheduler execution, retries, and lease-safe deployment-run workers.
- Emit deployment and session webhook events.

## User Profiles

- Implement real enrollment URLs, identity binding, and trust grants.
- Enforce access policy between user profiles, vaults, and sessions.

## Webhooks

- Implement webhook endpoint registration when the official API exposes CRUD for it.
- Implement signature generation/verification compatible with Anthropic SDK helpers.
- Emit all session, vault, credential, and deployment webhook event types.
