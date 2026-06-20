# Sandbox Runtime

The sandbox layer is designed to map Claude Managed Agents `Environment` resources onto OpenAI Agents SDK sandbox execution.

## Default Path

The default product path is:

```text
API process -> OpenAI Agents SDK runtime -> external model/sandbox provider
```

Do not require `oma-worker` for this path. The API process can enqueue visible Postgres work and consume it inline for normal local development and hosted-provider testing.

`oma-worker` is only for optional `self_hosted` queue execution or direct queue lifecycle testing. It is not an OpenAI sandbox worker and it does not replace an external sandbox provider.

## OpenAI Agents SDK Integration

The integration points are:

- `agents.sandbox.SandboxAgent` instead of a plain `Agent` when sandbox execution is enabled.
- `RunConfig(sandbox=SandboxRunConfig(...))` for the runtime sandbox session/client/manifest/snapshot config.
- `Manifest` for workspace root, files, mounts, users, groups, and environment configuration.
- SDK sandbox clients. Local clients such as `UnixLocalSandboxClient` are development escape hatches; provider-backed clients should be used for the normal product path once wired.

## Current MVP

The default runtime backend is `openai`, so session execution expects an external provider key such as `OPENAI_API_KEY`.

The local deterministic runtime and SDK-backed `unix_local` sandbox are explicit test options, not the default path. Enable `unix_local` only when intentionally testing SDK sandbox mapping:

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

Claude Managed Agents cloud environments provide a durable remote sandbox. This project still needs a production cloud sandbox provider, durable queue lifecycle, lease/heartbeat handling, and persisted sandbox session state before it is equivalent.

The optional self-hosted worker remains an extension point for users who deliberately want their own environment to claim queued work. It should stay out of the default setup flow.
