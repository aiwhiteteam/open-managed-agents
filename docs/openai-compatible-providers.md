# OpenAI-Compatible Providers

The runtime uses OpenAI Agents SDK as the execution engine. Provider switching is handled by `app.runtime.providers`.

## Built-In Providers

| Provider | API key env | Base URL | Default model | Responses API |
| --- | --- | --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` or official default | `OMA_DEFAULT_OPENAI_MODEL` | `OPENAI_USE_RESPONSES` |
| `deepseek` | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` | `DEEPSEEK_DEFAULT_MODEL` | false |
| `minimax` | `MINIMAX_API_KEY` | `MINIMAX_BASE_URL` | `MINIMAX_DEFAULT_MODEL` | false |

DeepSeek and MiniMax are treated as OpenAI-compatible Chat Completions providers, so they run through `OpenAIProvider(..., use_responses=false)`.

## Capability Map

Provider behavior is not assumed to be identical. `app.runtime.providers` exposes a capability map used by the runtime:

| Provider | Streaming | Tool calls | Responses API | Hosted tools | Multimodal input | Reasoning traces |
| --- | --- | --- | --- | --- | --- | --- |
| `openai` | yes | yes | configurable | yes when Responses is enabled | yes | yes when Responses is enabled |
| `deepseek` | yes | yes | no | no | no by default | no |
| `minimax` | yes | yes | no | no | no by default | no |
| custom | yes by default | yes by default | no by default | no by default | no by default | no by default |

Custom providers can override `capabilities` in `OMA_OPENAI_COMPATIBLE_PROVIDERS`.

## Agent Model Shape

```json
{
  "model": {
    "provider": "deepseek",
    "id": "deepseek-v4-pro"
  }
}
```

The shorthand `provider/model-id` and `provider:model-id` forms are also accepted:

```json
{
  "model": "minimax/MiniMax-M3"
}
```

## Custom Providers

Set `OMA_OPENAI_COMPATIBLE_PROVIDERS` to a JSON object:

```json
{
  "moonshot": {
    "api_key_env": "MOONSHOT_API_KEY",
    "base_url": "https://api.moonshot.ai/v1",
    "default_model": "kimi-k2",
    "capabilities": {
      "streaming": true,
      "tool_calls": true,
      "multimodal_input": false
    }
  }
}
```

Then use:

```json
{
  "model": "moonshot/kimi-k2"
}
```
