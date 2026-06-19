# Sandbox Runtime

The sandbox layer is designed to map Claude Managed Agents `Environment` resources onto OpenAI Agents SDK sandbox execution.

## OpenAI Agents SDK Integration

The integration points are:

- `agents.sandbox.SandboxAgent` instead of a plain `Agent` when sandbox execution is enabled.
- `RunConfig(sandbox=SandboxRunConfig(...))` for the runtime sandbox session/client/manifest/snapshot config.
- `Manifest` for workspace root, files, mounts, users, groups, and environment configuration.
- SDK sandbox clients such as `UnixLocalSandboxClient` for local development. Other extension modules exist in the SDK package, but provider-specific clients require their own dependencies and credentials.

## Current MVP

Enable a local SDK sandbox in an Environment:

```json
{
  "type": "local",
  "sandbox": {
    "enabled": true,
    "backend": "unix_local",
    "root": "/workspace",
    "capabilities": ["filesystem", "shell", "compaction"]
  }
}
```

When the OpenAI runtime backend is active, this maps to `SandboxAgent` and `RunConfig.sandbox`.

When the local deterministic runtime is active, the sandbox plan is recorded in `session.sandbox_state` but no commands are executed.

## Production Gap

Claude Managed Agents cloud environments provide a durable remote sandbox. This project still needs a production sandbox provider, queue/worker lifecycle, lease/heartbeat handling, and persisted sandbox session state before it is equivalent.
