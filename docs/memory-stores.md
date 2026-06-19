# Memory Stores

Memory Store data lives in the relational database. In production this means a Postgres-compatible database through `DATABASE_URL`.

Object storage is not the source of truth for memory records. S3-compatible storage should only be used for optional large binary memory attachments, exported snapshots, or artifact bundles.

## Current MVP Semantics

- `memory_store` rows store store-level metadata.
- `memory` rows store structured records with `path`, `path_key`, `content`, metadata, and the current optimistic `version`.
- `memory_version` rows store version snapshots with actor and operation metadata.
- Paths are unique inside a memory store.
- Updates may pass `if_version` or `expected_version`; stale values return `409`.
- Redaction removes the snapshot `content` from the targeted memory version. If the latest version is redacted, the current memory content is removed too.

## Path Examples

```json
{
  "path": ["customers", "acme"],
  "content": "ACME prefers email.",
  "actor": "api"
}
```

The string shorthand is also accepted:

```json
{
  "path": "customers/acme",
  "content": "ACME prefers email."
}
```

## Storage Boundary

Use Postgres for the memory store itself. Use S3-compatible object storage only for optional large binary artifacts related to a memory, such as an exported archive or external attachment.
