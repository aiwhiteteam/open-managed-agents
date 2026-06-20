# TODO

This file tracks Claude Managed Agents compatibility gaps after the MVP API pass.

Use [docs/claude-managed-agents-alignment.md](./docs/claude-managed-agents-alignment.md) as the official-doc-aligned engineering map for these gaps.

## Claude Compatibility Risk Register

These are not just route coverage gaps. They are semantic contracts that can become expensive to fix later if core data models or runtime state machines drift away from Claude Managed Agents.

- Keep exact workspace/API-key scoping semantics. Claude API keys are workspace-scoped; core resolves every request to `CurrentWorkspace` without putting workspace IDs in public `/v1` paths.
- Complete durable session state machine semantics: real `rescheduling`, retry windows, and persisted OpenAI Agents SDK resume state.
- Wire `requires_action` pauses for custom tools and tool confirmations into real OpenAI Agents SDK HITL continuation, not only the MVP event contract.
- Keep session-local agent update runtime semantics aligned with the SDK-validated request/response shape.
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
- Keep cross-workspace non-visibility tests green for every major resource family, including agents, environments, files, skills, vaults, credentials, memory stores, memories, deployments, deployment runs, and user profiles.

## Contract Extraction

- Maintain `tests/contract/test_anthropic_sdk_contract.py`, which points the official Anthropic Python SDK at this service with strict response validation.
- Keep the current passing SDK strict surface green: beta resource discovery, agent CRUD, agent versions, environment lifecycle, session lifecycle/events/resources/threads, files upload/list/download/delete, skill lifecycle/version lifecycle, vault/credential lifecycle, memory store/memory/memory-version lifecycle, deployment/deployment-run lifecycle, and user profile lifecycle.
- Expand pagination/filter contract tests from representative SDK coverage to exhaustive per-route edge cases, especially expired cursor behavior and less common filters. Invalid cursor handling, max limit clamping, timestamp aliases, and core SDK pagination paths have test coverage.
- Verify exact deleted-resource response shapes for future route families as they are added.

## Runtime Semantics

- Replace inline Postgres work-queue consumer with Cloud Tasks/PubSub deployment and fencing locks.
- Implement true resumable OpenAI Agents SDK `RunState` persistence.
- Map OpenAI Agents SDK streaming events into the full Claude Managed Agents event union.
- Add HTTP-level runtime integration tests with mocked OpenAI-compatible endpoints. Provider resolution/capability coverage exists for DeepSeek, MiniMax, and custom providers.
- Persist and resume real OpenAI Agents SDK HITL/tool confirmation run state.
- Implement session `rescheduling` behavior for transient failures.
- Expand session state-machine tests for worker crashes, queued continuation batches, and `user.interrupt`.

## Open-Core Hosted Layer

- Keep core resource tables scoped by `workspace_id`; do not add organization/billing/RBAC dependencies to core.
- Add service-account lifecycle APIs if needed. A DB-backed API key auth provider exists and resolves to `CurrentWorkspace`; hosted org/RBAC still belongs in the private layer.
- Add provider interfaces for quota, audit logging, secret manager, and hosted sandbox fleet.
- Keep cross-workspace isolation tests current for every new route group.
- Implement organizations, members, billing, SSO, and RBAC only in a hosted/private layer that imports core.

## Sandbox And Environments

- Map `cloud` environments to a real production sandbox provider.
- Map `self_hosted` environments to a real worker queue.
- Add self-hosted worker auth, retry backoff, and automatic heartbeat timeout recovery.
- Enforce network policies, package installation controls, and sandbox resource limits.

## Skills

- Keep skill archive download shape covered. Zip response content-type, attachment header, and archive file paths are locally tested; official SDK binary download remains covered in contract tests.
- Implement exact SDK multipart field compatibility for `files`.
- Replace MVP sequential skill version strings (`"1"`, `"2"`) with official-compatible version identifiers and lifecycle semantics.

## Files And Resources

- Add content deduplication, malware/content scanning, and object storage lifecycle policies.
- Implement production filesystem copy/mount semantics for the SDK-validated session resource union.
- Keep session resource union coverage current if Anthropic adds resource kinds beyond `file`, `github_repository`, and `memory_store`.

## Vaults

- Store credentials in KMS/Vault instead of the generic resource table.
- Implement OAuth enrollment and validation flows.
- Implement credential refresh and webhook events.
- Add secret redaction in logs.

## Memory Stores

- Extract Memory Store routes into typed request/response models instead of the current generic-resource compatibility layer.
- Add production-scale prefix/search indexes for Memory Store queries. Exact path lookup uses indexed `managed_resources.name` as the stored `path_key`.
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
