# TODO

This file tracks Claude Managed Agents compatibility gaps after the MVP API pass.

Use [docs/claude-managed-agents-alignment.md](./docs/claude-managed-agents-alignment.md) as the official-doc-aligned engineering map for these gaps.

## Claude Compatibility Risk Register

These are not just route coverage gaps. They are semantic contracts that can become expensive to fix later if core data models or runtime state machines drift away from Claude Managed Agents.

- Keep exact workspace/API-key scoping semantics. Claude API keys are workspace-scoped; core resolves every request to `CurrentWorkspace` without putting workspace IDs in public `/v1` paths.
- Complete durable session state machine semantics: transient runtime failures now enter `rescheduling` with retry windows and capped attempts; real durable queue execution and OpenAI Agents SDK snapshot resume execution remain TODO.
- Wire `requires_action` pauses for custom tools, self-hosted tool results, and tool confirmations into real OpenAI Agents SDK HITL continuation, not only the MVP event contract.
- Keep session-local agent update runtime semantics aligned with the SDK-validated request/response shape.
- Preserve agent versioning semantics: agent updates require the current version, arrays replace wholesale, metadata merges/deletes intentionally, and delegated-agent rosters stay pinned rather than auto-updated.
- Map the full event protocol, including `user.*`, `system.*`, `session.*`, `span.*`, and `agent.*` events. `processed_at = null` for queued user/system input events and non-null processed timestamps for output events have local coverage.
- Keep uploaded-file session mounts creating session-scoped file resources and object-storage copies. Staged upload completion is workspace-scoped. The official 100 file resources per session limit is enforced locally. Memory-store session resources enforce the official 8 stores per session limit and cannot be added or removed after creation. Session-produced files should still become session-scoped file references.
- Implement permission policy semantics for built-in/MCP tools, including the boundary that custom tools are handled by the application continuation flow rather than normal permission policy enforcement.
- Implement MCP connector auth semantics: agent definitions reference MCP servers, while sessions supply credentials through validated workspace vault context. Runtime URL matching and non-terminal missing-auth session errors have local coverage; real MCP connection/OAuth refresh remains TODO.
- Implement vault credential lifecycle: enrollment, refresh, runtime resolution, revocation, and webhook emission. Response redaction, archive/delete secret purge, and persisted validation metadata have local coverage.
- Implement outcome/grader loops with separate grader context, max iterations, rubric inputs, and outcome evaluation events. A deterministic local `span.outcome_evaluation_end` MVP exists; real grader LLM loops remain TODO.
- Implement multiagent thread semantics: shared sandbox/filesystem/vault context, but separate persistent thread/context/event stream per agent. Delegated agent session threads are created from pinned rosters, and primary thread event listing includes unassigned session events; full delegated execution/routing remains TODO.
- Implement webhook delivery semantics: endpoint registration, event IDs, organization/workspace identifiers, retries, idempotency, and failure disabling. Standard Webhooks-compatible signing, verification, freshness checks, and event-envelope unwrap helpers have local coverage.
- Implement deployment scheduler semantics: autonomous scheduled session creation, retries, and lease-safe workers. Cron/timezone validation, required `user.message` deployment initial events, `upcoming_runs_at`/`last_run_at` bookkeeping, manual run session linkage, deployment `initial_events` delivery, deployment resource mounting, paused-manual-run behavior, terminal archive behavior, primary-agent archive auto-archive/no-run behavior, failed session-creation run records, and deployment-run vault validation have local coverage.
- Implement sandbox/environment policy enforcement through provider interfaces: network allowlists, MCP/package-manager exceptions, resource limits, and production cloud sandbox backends. Policy config validation and runtime sandbox-state summaries have local coverage.

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
- Keep the current passing SDK strict surface green: beta resource discovery, agent CRUD/versioned retrieve, agent versions, environment lifecycle/scope/work queue, session lifecycle/events/resources/threads, `user.tool_result`, files upload/list/download/delete, skill lifecycle/version lifecycle, vault/credential lifecycle including auth unions, memory store/memory/memory-version lifecycle and memory-version `api_key_id`/`session_id`/`view` filters, deployment/deployment-run lifecycle, and user profile lifecycle.
- Expand pagination/filter contract tests from representative SDK coverage to exhaustive per-route edge cases, especially less common filters. Invalid cursor handling, expired cursor handling, max limit clamping, timestamp aliases, and core SDK pagination paths have test coverage.
- Verify exact deleted-resource response shapes for future route families as they are added.

## Runtime Semantics

- Replace inline Postgres work-queue consumer with Cloud Tasks/PubSub deployment and fencing locks.
- Implement true resumable OpenAI Agents SDK `RunState` continuation. SDK `RunState.to_json()` snapshots are persisted when available, but reconstructing the agent and resuming through `RunState.from_json()` is still TODO.
- Keep expanding OpenAI Agents SDK stream mapping. Run-item events for messages, tool calls/results, MCP approvals, reasoning, handoffs, and agent updates have local coverage; raw response deltas and the exact full Claude event union remain TODO.
- Keep expanding runtime integration tests. API-level session turn coverage exists for a mocked OpenAI-compatible runtime and provider resolution/capability coverage exists for DeepSeek, MiniMax, and custom providers; wire-level mocked OpenAI SDK HTTP endpoint coverage remains TODO.
- Persist and resume real OpenAI Agents SDK HITL/tool confirmation run state.
- Keep session `rescheduling` behavior for transient failures covered, including retry windows and capped attempts. Durable retry execution still belongs to the production queue provider.
- Expand session state-machine tests for worker crashes and queued continuation batches. `user.interrupt` single-event handling while active has local coverage.

## Open-Core Hosted Layer

- Keep core resource tables scoped by `workspace_id`; do not add organization/billing/RBAC dependencies to core.
- Add service-account lifecycle APIs if needed. A DB-backed API key auth provider exists and resolves to `CurrentWorkspace`; hosted org/RBAC still belongs in the private layer.
- Add provider interfaces for quota, audit logging, secret manager, and hosted sandbox fleet.
- Keep cross-workspace isolation tests current for every new route group.
- Implement organizations, members, billing, SSO, and RBAC only in a hosted/private layer that imports core.

## Sandbox And Environments

- Map `cloud` environments to a real production sandbox provider.
- Replace the current Postgres-backed `self_hosted` worker queue with a production durable queue provider when deploying at scale.
- Add production retry execution and hosted worker identity/RBAC. Optional shared worker-token auth, HTTP/CLI worker lease ownership enforcement, automatic expired-lease recovery, and retry-at backoff gates have local coverage.
- Enforce network policies, package installation controls, and sandbox resource limits in real sandbox providers. Config validation and runtime policy summaries are covered locally.

## Skills

- Keep skill multipart upload compatibility covered through the official Anthropic SDK. The SDK sends `display_title` plus multipart `files` arrays to `/v1/skills?beta=true` and multipart `files` arrays to `/v1/skills/{skill_id}/versions?beta=true`; the strict contract test covers both create paths. Unsafe archive paths are rejected locally.
- Keep skill archive download shape covered. Zip response content-type, attachment header, and archive file paths are locally tested; official SDK binary download remains covered in contract tests.
- Keep official-compatible epoch-microsecond skill version identifiers and validated agent skill references covered. Exact skill archive/runtime semantics remain TODO.

## Files And Resources

- Add production malware scanning and object storage lifecycle policies. Direct file uploads, staged-upload completion, and skill uploads now pass through a local EICAR content-scan hook; file uploads also deduplicate by content hash within a workspace and keep shared objects until the last file reference is deleted. Session file mounts create session-scoped file resources and enforce the official 100 file resources per session limit; memory-store session resources enforce the official 8 stores per session limit and are not removable after creation.
- Implement production filesystem mount semantics for the SDK-validated session resource union. Uploaded file resources now create session-scoped file resources and object-storage copies.
- Keep session resource union coverage current if Anthropic adds resource kinds beyond `file`, `github_repository`, and `memory_store`.

## Vaults

- Store credentials in KMS/Vault instead of the generic resource table.
- Implement OAuth enrollment and real validation flows. The validation route persists last-validation metadata, but still does not perform real OAuth/MCP probing.
- Implement credential refresh and webhook events.
- Keep secret redaction in logs, API responses, and archive/delete purge paths covered. Secure secret storage still belongs in the KMS/Vault TODO above.

## Memory Stores

- Extract Memory Store routes into typed request/response models instead of the current generic-resource compatibility layer.
- Keep exact path and prefix lookups backed by indexed `managed_resources.name` as the stored `path_key`. SDK-compatible slash-prefixed path validation, `depth` rollups as `memory_prefix` items, memory content size, per-store count limits, memory-version `api_key_id`/`session_id`/`view` filters, deleted-version survival, live-head redact protection, and archived-store read-only behavior have local coverage.
- Add semantic search/vector indexing if memories need retrieval beyond exact path and prefix lookup.
- Keep mounted memory stores integrated into the runtime context builder. Session creation enforces the official 8 mounted stores limit and rejects new attachments to archived stores. Full semantic/vector retrieval tools remain TODO.

## Deployments

- Keep cron/timezone validation, required `user.message` deployment initial events, schedule timestamp bookkeeping, deployment-run session linkage, deployment `initial_events` delivery, deployment resource mounting, paused-manual-run behavior, terminal archive behavior, primary-agent archive auto-archive/no-run behavior, failed session-creation run records, and vault validation covered.
- Implement real scheduler execution, retries, and lease-safe deployment-run workers.
- Emit deployment and session webhook events.

## User Profiles

- Implement identity binding and trust grants. Enrollment URL tokens are generated, hashed, persisted, and expired locally; hosted delivery/verification remains TODO.
- Enforce access policy between user profiles, vaults, and sessions. Session `vault_ids` are validated and workspace-scoped; user-profile trust policy remains TODO.

## Webhooks

- Implement webhook endpoint registration when the official API exposes CRUD for it.
- Keep Standard Webhooks-compatible signature generation/verification covered against Anthropic SDK helper semantics.
- Emit all session, vault, credential, and deployment webhook event types.
