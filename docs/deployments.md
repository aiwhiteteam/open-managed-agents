# Deployments

Deployments are stored in Postgres as managed resources.

## Current MVP

- `POST /v1/deployments` accepts metadata plus optional `agent`, `environment_id`, and `schedule`.
- Schedule support validates cron fields and IANA timezone names.
- Scheduled deployments return up to five computed `upcoming_runs_at` timestamps.
- Scheduled runs update `last_run_at` and refresh `upcoming_runs_at`.
- `pause` and `unpause` update both resource status and deployment metadata.
- `run` creates a `deployment_run`.
- If the deployment has `agent` and `environment_id`, `run` also creates a session and links `deployment_run.session_id`.

## Example

```json
{
  "name": "Daily report",
  "agent": {"id": "agt_...", "version": 1},
  "environment_id": "env_...",
  "schedule": {
    "type": "cron",
    "cron": "0 9 * * *",
    "timezone": "America/New_York"
  }
}
```

## Remaining Production Work

The MVP does not yet execute schedules by itself. Production deployment execution should use a durable scheduler plus a worker queue with retries, leases, and idempotency.
