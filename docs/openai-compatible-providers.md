# OpenAI-Compatible Providers

The default runtime uses the OpenAI Agents SDK with the official OpenAI provider.
Most deployments should only configure:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` when intentionally pointing the SDK at a compatible endpoint
- `OMA_DEFAULT_OPENAI_MODEL`

## Advanced Custom Providers

OpenAI-compatible provider routing is an advanced escape hatch. It is configured
through `OMA_OPENAI_COMPATIBLE_PROVIDERS`, not through provider-specific built-ins.

Set `OMA_OPENAI_COMPATIBLE_PROVIDERS` to a JSON object:

```json
{
  "example": {
    "api_key_env": "EXAMPLE_API_KEY",
    "base_url": "https://api.example.com/v1",
    "default_model": "example-chat",
    "use_responses": false,
    "capabilities": {
      "streaming": true,
      "tool_calls": true,
      "hosted_tools": false,
      "multimodal_input": false,
      "reasoning_traces": false,
      "unsupported_parameters": ["previous_response_id", "conversation_id", "prompt"]
    }
  }
}
```

Then use provider-qualified model config on an agent:

```json
{
  "model": {
    "provider": "example",
    "id": "example-chat"
  }
}
```

The shorthand `provider/model-id` and `provider:model-id` forms are also accepted:

```json
{
  "model": "example/example-chat"
}
```

## Provider Examples

Providers such as DeepSeek and MiniMax should use the same generic registry instead
of provider-specific code paths:

```json
{
  "deepseek": {
    "api_key_env": "DEEPSEEK_API_KEY",
    "base_url": "https://api.deepseek.com/v1",
    "default_model": "deepseek-chat",
    "use_responses": false
  },
  "mini-max": {
    "base_url": "https://api.minimax.io/v1",
    "default_model": "MiniMax-M1",
    "capabilities": {
      "multimodal_input": true,
      "unsupported_parameters": ["previous_response_id", "prompt"]
    }
  }
}
```

When `api_key_env` is omitted, the provider name is normalized and uppercased.
For example, `mini-max` resolves credentials from `MINI_MAX_API_KEY`.

## Capability Map

Provider behavior is not assumed to be identical. `app.runtime.providers`
exposes a capability map used by the runtime.

| Provider | Streaming | Tool calls | Responses API | Hosted tools | Multimodal input | Reasoning traces |
| --- | --- | --- | --- | --- | --- | --- |
| `openai` | yes | yes | configurable | yes when Responses is enabled | yes | yes when Responses is enabled |
| custom | yes by default | yes by default | no by default | no by default | no by default | no by default |
