# Compatibility Matrix

This MVP targets Claude Managed Agents-shaped wire and lifecycle compatibility, not identical Claude behavior.

| Area | Status | Notes |
| --- | --- | --- |
| `/v1` URL shape | Implemented | Matches Anthropic-style stable root path. |
| Native beta header | Implemented | `open-managed-agents-beta: open-managed-agents-2026-04-01` is accepted without Anthropic headers. |
| Claude compatibility headers | Implemented | `anthropic-beta: managed-agents-2026-04-01` is accepted; `anthropic-version: 2023-06-01` is required when using `anthropic-beta`. |
| Agent create/list/retrieve | Implemented | Flexible JSON config fields. |
| Agent update version guard | Implemented | Requires current `version`; stale writes return 409. |
| Agent no-op update detection | Implemented | Existing version is returned. |
| Agent metadata merge/delete | Implemented | Empty string deletes a key. |
| Multiagent roster pinning | Implemented | Coordinator rosters resolve unversioned agent references to the referenced agent's active version at create/update time. |
| MCP server/toolset declaration validation | Implemented | Rejects unreferenced MCP servers and dangling `mcp_toolset` references. Runtime MCP auth is still partial. |
| Agent archive | Implemented | Blocks new sessions; existing sessions can continue. |
| Environment CRUD | Implemented | Create/retrieve/update/list/archive/delete pass official SDK strict validation for the covered lifecycle. Sandbox backend mapping is not complete. |
| Session create/list/retrieve/update/archive/delete | Implemented | Covered lifecycle passes official SDK strict validation. Sessions pin agent version at creation. Running/rescheduling sessions reject update/archive/delete. |
| Session state machine | Partial | Core states are `idle`, `running`, `rescheduling`, and `terminated`; `requires_action` is represented as an idle `stop_reason`. Durable retry/rescheduling semantics are still TODO. |
| Session-local agent update | Partial | `agent.tools` and `agent.mcp_servers` replacement passes official SDK strict validation and does not mutate the persisted agent version. Full runtime semantics are TODO. |
| Session events append/list | Implemented | Append-only event log with monotonic `seq`. Basic official SDK strict validation passes for send/list. Full event union mapping is still partial. |
| Session resources | Partial | Official SDK strict validation passes for session-create resource union (`file`, `github_repository`, `memory_store`), file add, GitHub token rotation, retrieve/list/delete, memory-store snapshots, and GitHub token redaction. Uploaded file mounts create session-scoped object-storage copies. Real filesystem mount semantics and session-produced file references are still TODO. |
| Requires action continuation | Partial | Local/runtime contract supports `agent.custom_tool_use` + `user.custom_tool_result` and tool confirmation through `user.tool_confirmation`. Full OpenAI Agents SDK HITL persistence is TODO. |
| SSE stream | Implemented | DB polling-based replay and live polling. |
| OpenAI Agents SDK runtime | Partial | Uses SDK with OpenAI by default. Deterministic local runtime is explicit test-only configuration. Advanced OpenAI-compatible providers can be registered through `OMA_OPENAI_COMPATIBLE_PROVIDERS`. |
| SandboxAgent mapping | Partial | Environment sandbox config maps to OpenAI Agents SDK `SandboxAgent` + `RunConfig.sandbox` for explicit `unix_local` tests. Production cloud/self-hosted sandbox lifecycle is TODO. |
| Exact Anthropic Python SDK contract tests | Partial | `tests/contract/test_anthropic_sdk_contract.py` points the official Anthropic Python SDK at this ASGI app with strict response validation. Current coverage includes SDK surface, agents, agent versions, environments, sessions, session events/resources/threads, files, skills, skill versions, vaults, credentials, memory stores, memories, memory versions, deployments, deployment runs, user profiles, representative SDK cursor pagination, and key list filters. Exhaustive pagination edge cases and production runtime semantics are still TODO. |
| Workspace isolation | Implemented | API-key-to-workspace scoping is covered for agents, environments, files, skills, vaults, credentials, memory stores, memories, deployments, deployment runs, and user profiles. Hosted org/RBAC semantics remain private-layer work. |
| Skills API | Partial | Create/list/retrieve/delete plus versions and zip content download. Basic official SDK strict validation passes for skill and skill version lifecycle. Custom skill versions use official-compatible epoch-microsecond identifiers. S3-compatible object storage is supported through `S3_*` settings. Uploads require one top-level directory and `SKILL.md` frontmatter with `name` and `description`; exact Claude archive/runtime semantics are TODO. |
| Files API | Partial | Upload/list/retrieve/download/delete with S3-compatible object storage. Basic official SDK strict response validation passes. Session file resource mount response shape passes, and uploaded file mounts create session-scoped object-storage copies. Real filesystem mount semantics are still TODO. |
| Vaults and credentials | Partial | Basic lifecycle response shapes pass official SDK strict validation. Secure secret storage, OAuth enrollment/refresh, permission enforcement, and webhook emission are TODO. |
| Memory stores | Partial | Postgres-backed path memories with indexed exact/prefix path lookup, unique path, content hashes, optimistic version checks, version history with actor attribution, redaction, and official SDK strict response validation. Runtime memory tools and semantic/vector indexes are TODO. |
| Deployments and runs | Partial | Basic lifecycle response shapes pass official SDK strict validation, including cron schedule shape, pause/unpause, manual run, and deployment-run session linkage. Real scheduler/retry worker semantics are TODO. |
| User profiles | Partial | Basic lifecycle and enrollment URL response shapes pass official SDK strict validation. Real identity binding, trust grants, and access policy are TODO. |
| Self-hosted environment work | Partial | Optional hidden/advanced path with Postgres-backed work items, poll lease, lease owner enforcement, expired-lease recovery, ack, heartbeat, stop, stats, and `oma-worker`. Worker token auth, retry backoff, and external worker deployment are TODO. |
