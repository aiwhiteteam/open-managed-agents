# Work Queue

Session execution now writes a durable `environment_work` resource before execution.

## Current MVP

- User events enqueue a work item with `session_id`, trigger, attempt count, and queued timestamp.
- `cloud` and `local` environments are consumed inline by the API process for local development.
- `self_hosted` environments only enqueue work. Workers use the environment work routes to lease and report progress.
- `GET /v1/environments/{environment_id}/work/poll` leases one queued item.
- `POST /work/{work_id}/ack` marks it running.
- `POST /work/{work_id}/heartbeat` records progress and extends the lease.
- `POST /work/{work_id}/stop` marks it stopped.

This makes pending work visible in Postgres, but it is not yet equivalent to a production queue. Production should move inline execution to Cloud Tasks, Pub/Sub, or a dedicated worker service with fencing locks and retry backoff.
