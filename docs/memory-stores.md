# Memory Stores

Memory Store data lives in the relational database. In production this means a Postgres-compatible database through `DATABASE_URL`.

Object storage is not the source of truth for memory records. S3-compatible storage should only be used for optional large binary memory attachments, exported snapshots, or artifact bundles.

## Current MVP Semantics

- `memory_store` rows store store-level metadata.
- `memory` rows store structured records with `path`, `path_key`, `content`, metadata, and the current optimistic `version`.
- `memory_version` rows store version snapshots with actor and operation metadata.
- Paths are unique inside a memory store.
- Individual memory content is capped at 100KB, and each store is capped at 2000 live memories.
- Updates may pass `if_version` or `expected_version`; stale values return `409`.
- Every create, update, and delete creates an immutable memory version; versions survive after their memory is deleted.
- Redaction removes the snapshot `content` from the targeted memory version. The current live head version cannot be redacted.
- Archived stores remain readable, but reject writes and cannot be attached to new sessions.

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
