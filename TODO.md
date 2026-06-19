# TODO

This file tracks Claude Managed Agents compatibility gaps after the MVP API pass.

## Contract Extraction

- Extract exact request/response schemas from `anthropic-sdk-python` generated types for every Managed Agents resource.
- Add contract tests using the official Anthropic Python SDK with `base_url` pointed at this service.
- Verify pagination parameter names and envelopes against the SDK for every list endpoint.
- Verify exact deleted-resource response shapes.

## Runtime Semantics

- Replace inline Postgres work-queue consumer with Cloud Tasks/PubSub/worker deployment and fencing locks.
- Implement true resumable OpenAI Agents SDK `RunState` persistence.
- Map OpenAI Agents SDK streaming events into the full Claude Managed Agents event union.
- Add integration tests with mocked OpenAI-compatible endpoints for DeepSeek, MiniMax, and at least one custom provider.
- Implement tool confirmation and custom tool result continuation semantics.
- Implement session `rescheduling` behavior for transient failures.
- Enforce session archive/delete restrictions while running.

## Sandbox And Environments

- Map `cloud` environments to a real production sandbox provider.
- Map `self_hosted` environments to a real worker queue.
- Add self-hosted worker auth, retry backoff, and automatic heartbeat timeout recovery.
- Enforce network policies, package installation controls, and sandbox resource limits.

## Skills

- Verify the zip archive response shape against Claude skill downloads and official SDK clients.
- Implement exact SDK multipart field compatibility for `files`.

## Files And Resources

- Add content deduplication, malware/content scanning, and R2 lifecycle policies.
- Add a migration command to move legacy DB-backed local blobs into R2.
- Implement exact session resource union types for file, GitHub repository, and future resource kinds.

## Vaults

- Store credentials in KMS/Vault instead of the generic resource table.
- Implement OAuth enrollment and validation flows.
- Implement credential refresh and webhook events.
- Add secret redaction in responses and logs.

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
