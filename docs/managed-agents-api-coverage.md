# Managed Agents API Coverage

Source basis:

- Official docs navigation and guides under `https://platform.claude.com/docs/en/managed-agents`
- Official `anthropic-sdk-python` `api.md` on `main`, checked on 2026-06-19

Status legend:

- `implemented`: route and basic lifecycle behavior are implemented.
- `partial`: route exists and persists data, but exact schema or production semantics are incomplete.
- `stub`: route exists as a compatibility placeholder.
- `todo`: not implemented.

## Agents

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/agents` | implemented |
| retrieve | `GET /v1/agents/{agent_id}` | implemented |
| update | `POST /v1/agents/{agent_id}` | implemented |
| update alias | `PATCH /v1/agents/{agent_id}` | implemented |
| list | `GET /v1/agents` | implemented |
| archive | `POST /v1/agents/{agent_id}/archive` | implemented |
| list versions | `GET /v1/agents/{agent_id}/versions` | implemented |

## Environments

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/environments` | implemented |
| retrieve | `GET /v1/environments/{environment_id}` | implemented |
| update | `POST /v1/environments/{environment_id}` | implemented |
| update alias | `PATCH /v1/environments/{environment_id}` | implemented |
| list | `GET /v1/environments` | implemented |
| delete | `DELETE /v1/environments/{environment_id}` | implemented |
| archive | `POST /v1/environments/{environment_id}/archive` | implemented |
| work retrieve | `GET /v1/environments/{environment_id}/work/{work_id}` | stub |
| work update | `POST /v1/environments/{environment_id}/work/{work_id}` | stub |
| work list | `GET /v1/environments/{environment_id}/work` | stub |
| work ack | `POST /v1/environments/{environment_id}/work/{work_id}/ack` | stub |
| work heartbeat | `POST /v1/environments/{environment_id}/work/{work_id}/heartbeat` | stub |
| work poll | `GET /v1/environments/{environment_id}/work/poll` | stub |
| work stats | `GET /v1/environments/{environment_id}/work/stats` | stub |
| work stop | `POST /v1/environments/{environment_id}/work/{work_id}/stop` | stub |

## Sessions

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/sessions` | implemented |
| retrieve | `GET /v1/sessions/{session_id}` | implemented |
| update | `POST /v1/sessions/{session_id}` | implemented |
| update alias | `PATCH /v1/sessions/{session_id}` | implemented |
| list | `GET /v1/sessions` | implemented |
| delete | `DELETE /v1/sessions/{session_id}` | implemented |
| archive | `POST /v1/sessions/{session_id}/archive` | implemented |
| cancel compatibility helper | `POST /v1/sessions/{session_id}/cancel` | implemented |
| resume compatibility helper | `POST /v1/sessions/{session_id}/resume` | implemented |

## Session Events

| Operation | Route | Status |
| --- | --- | --- |
| list | `GET /v1/sessions/{session_id}/events` | implemented |
| send | `POST /v1/sessions/{session_id}/events` | implemented |
| stream | `GET /v1/sessions/{session_id}/events/stream` | partial |
| stream alias | `GET /v1/sessions/{session_id}/stream` | partial |

## Session Resources

| Operation | Route | Status |
| --- | --- | --- |
| add | `POST /v1/sessions/{session_id}/resources` | partial |
| retrieve | `GET /v1/sessions/{session_id}/resources/{resource_id}` | partial |
| update | `POST /v1/sessions/{session_id}/resources/{resource_id}` | partial |
| list | `GET /v1/sessions/{session_id}/resources` | partial |
| delete | `DELETE /v1/sessions/{session_id}/resources/{resource_id}` | partial |

## Session Threads

| Operation | Route | Status |
| --- | --- | --- |
| retrieve | `GET /v1/sessions/{session_id}/threads/{thread_id}` | stub |
| list | `GET /v1/sessions/{session_id}/threads` | stub |
| archive | `POST /v1/sessions/{session_id}/threads/{thread_id}/archive` | stub |
| list events | `GET /v1/sessions/{session_id}/threads/{thread_id}/events` | stub |
| stream events | `GET /v1/sessions/{session_id}/threads/{thread_id}/stream` | stub |

## Deployments

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/deployments` | partial |
| retrieve | `GET /v1/deployments/{deployment_id}` | partial |
| update | `POST /v1/deployments/{deployment_id}` | partial |
| list | `GET /v1/deployments` | partial |
| archive | `POST /v1/deployments/{deployment_id}/archive` | partial |
| pause | `POST /v1/deployments/{deployment_id}/pause` | partial |
| run | `POST /v1/deployments/{deployment_id}/run` | partial |
| unpause | `POST /v1/deployments/{deployment_id}/unpause` | partial |

## Deployment Runs

| Operation | Route | Status |
| --- | --- | --- |
| retrieve | `GET /v1/deployment_runs/{deployment_run_id}` | partial |
| list | `GET /v1/deployment_runs` | partial |

## Vaults

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/vaults` | partial |
| retrieve | `GET /v1/vaults/{vault_id}` | partial |
| update | `POST /v1/vaults/{vault_id}` | partial |
| list | `GET /v1/vaults` | partial |
| delete | `DELETE /v1/vaults/{vault_id}` | partial |
| archive | `POST /v1/vaults/{vault_id}/archive` | partial |
| credential create | `POST /v1/vaults/{vault_id}/credentials` | partial |
| credential retrieve | `GET /v1/vaults/{vault_id}/credentials/{credential_id}` | partial |
| credential update | `POST /v1/vaults/{vault_id}/credentials/{credential_id}` | partial |
| credential list | `GET /v1/vaults/{vault_id}/credentials` | partial |
| credential delete | `DELETE /v1/vaults/{vault_id}/credentials/{credential_id}` | partial |
| credential archive | `POST /v1/vaults/{vault_id}/credentials/{credential_id}/archive` | partial |
| credential OAuth validate | `POST /v1/vaults/{vault_id}/credentials/{credential_id}/mcp_oauth_validate` | stub |

## Memory Stores

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/memory_stores` | partial |
| retrieve | `GET /v1/memory_stores/{memory_store_id}` | partial |
| update | `POST /v1/memory_stores/{memory_store_id}` | partial |
| list | `GET /v1/memory_stores` | partial |
| delete | `DELETE /v1/memory_stores/{memory_store_id}` | partial |
| archive | `POST /v1/memory_stores/{memory_store_id}/archive` | partial |
| memory create | `POST /v1/memory_stores/{memory_store_id}/memories` | partial |
| memory retrieve | `GET /v1/memory_stores/{memory_store_id}/memories/{memory_id}` | partial |
| memory update | `POST /v1/memory_stores/{memory_store_id}/memories/{memory_id}` | partial |
| memory list | `GET /v1/memory_stores/{memory_store_id}/memories` | partial |
| memory delete | `DELETE /v1/memory_stores/{memory_store_id}/memories/{memory_id}` | partial |
| memory version retrieve | `GET /v1/memory_stores/{memory_store_id}/memory_versions/{memory_version_id}` | partial |
| memory version list | `GET /v1/memory_stores/{memory_store_id}/memory_versions` | partial |
| memory version redact | `POST /v1/memory_stores/{memory_store_id}/memory_versions/{memory_version_id}/redact` | stub |

## Files

| Operation | Route | Status |
| --- | --- | --- |
| list | `GET /v1/files` | partial |
| delete | `DELETE /v1/files/{file_id}` | partial |
| download | `GET /v1/files/{file_id}/content` | partial |
| retrieve metadata | `GET /v1/files/{file_id}` | partial |
| upload | `POST /v1/files` | partial |

## Skills

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/skills` | partial |
| retrieve | `GET /v1/skills/{skill_id}` | partial |
| list | `GET /v1/skills` | partial |
| delete | `DELETE /v1/skills/{skill_id}` | partial |
| version create | `POST /v1/skills/{skill_id}/versions` | partial |
| version retrieve | `GET /v1/skills/{skill_id}/versions/{version}` | partial |
| version list | `GET /v1/skills/{skill_id}/versions` | partial |
| version delete | `DELETE /v1/skills/{skill_id}/versions/{version}` | partial |
| version download | `GET /v1/skills/{skill_id}/versions/{version}/content` | partial |

## Webhooks

The current SDK exposes webhook event types and unwrap helpers in beta, but this API pass did not find beta webhook CRUD routes in `api.md`.

| Operation | Route | Status |
| --- | --- | --- |
| unwrap/verify helpers | SDK local helper | todo |

## User Profiles

| Operation | Route | Status |
| --- | --- | --- |
| create | `POST /v1/user_profiles` | partial |
| retrieve | `GET /v1/user_profiles/{user_profile_id}` | partial |
| update | `POST /v1/user_profiles/{user_profile_id}` | partial |
| list | `GET /v1/user_profiles` | partial |
| create enrollment URL | `POST /v1/user_profiles/{user_profile_id}/enrollment_url` | stub |

