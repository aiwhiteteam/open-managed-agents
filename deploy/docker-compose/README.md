# Docker Compose

This target is for local integration, simple VPS deployments, and customer
self-hosted smoke tests. It uses the same root Dockerfile and process scripts as
the cloud targets.

Start Postgres and the web service:

```bash
docker compose -f deploy/docker-compose/compose.yaml up --build web
```

Run migrations once:

```bash
docker compose -f deploy/docker-compose/compose.yaml --profile migrate run --rm migrate
```

Run the worker too:

```bash
docker compose -f deploy/docker-compose/compose.yaml --profile worker up --build web worker
```

The compose file defaults to DB-backed object storage for local use. Configure
`OMA_STORAGE_BACKEND=s3` and `S3_*` values in `.env` if you want to test
S3-compatible object storage.
