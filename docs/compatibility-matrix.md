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
| Agent archive | Implemented | Blocks new sessions; existing sessions can continue. |
| Environment CRUD | Implemented | P0 schema validation only; sandbox backend mapping is not complete. |
| Session create/list/retrieve/update/archive/delete | Implemented | Sessions pin agent version at creation. |
| Session events append/list | Implemented | Append-only event log with monotonic `seq`. |
| SSE stream | Implemented | DB polling-based replay and live polling. |
| OpenAI Agents SDK runtime | Partial | Uses SDK when configured; deterministic local backend otherwise. OpenAI-compatible provider registry supports OpenAI, DeepSeek, MiniMax, custom providers, and capability maps. |
| SandboxAgent mapping | Partial | Environment sandbox config maps to OpenAI Agents SDK `SandboxAgent` + `RunConfig.sandbox` for `unix_local`. Production cloud/self-hosted sandbox lifecycle is TODO. |
| Exact Anthropic Python SDK contract tests | Planned | Requires extracting generated SDK types and route shapes. |
| Skills API | Partial | Create/list/retrieve/delete plus versions and zip content download. R2 object storage is supported. Uploads require one top-level directory and `SKILL.md` frontmatter with `name` and `description`; exact Claude archive contract tests are TODO. |
| Files API | Partial | Upload/list/retrieve/download/delete with R2 object storage when configured and DB blob fallback for local development. |
| Vaults and credentials | Partial | Metadata CRUD only. Secure secret storage and OAuth flows are TODO. |
| Memory stores | Partial | Postgres-backed path memories with unique path, optimistic version checks, version history with actor attribution, and redaction. Typed SDK schema parity and runtime memory tools are TODO. |
| Deployments and runs | Partial | Metadata CRUD, cron/timezone validation, pause/unpause, manual run, and deployment-run session linkage. Real scheduler/retry worker semantics are TODO. |
| User profiles | Partial | Metadata CRUD and placeholder enrollment URL. Identity/trust semantics are TODO. |
| Self-hosted environment work | Partial | Postgres-backed work items, poll lease, ack, heartbeat, stop, and stats are implemented. Worker auth, retry backoff, and external worker deployment are TODO. |
