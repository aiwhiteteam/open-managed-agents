from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeProviderCapabilities:
    chat_completions: bool
    responses_api: bool
    streaming: bool
    tool_calls: bool
    hosted_tools: bool
    multimodal_input: bool
    reasoning_traces: bool
    unsupported_parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeProviderConfig:
    provider: str
    model_id: str
    api_key: str | None
    base_url: str | None
    use_responses: bool
    openai_compatible: bool = True
    capabilities: RuntimeProviderCapabilities = RuntimeProviderCapabilities(
        chat_completions=True,
        responses_api=False,
        streaming=True,
        tool_calls=True,
        hosted_tools=False,
        multimodal_input=False,
        reasoning_traces=False,
    )


def runtime_provider_configured(model: dict[str, Any]) -> bool:
    try:
        config = resolve_runtime_provider(model)
    except ProviderConfigurationError as exc:
        if "requires an API key" in str(exc):
            return False
        raise
    return bool(config.api_key)


def resolve_runtime_provider(model: dict[str, Any]) -> RuntimeProviderConfig:
    settings = get_settings()
    provider, explicit_model_id = _provider_and_model(model, settings)
    registry = _provider_registry(settings)
    provider_config = registry.get(provider)
    if provider_config is None:
        raise ProviderConfigurationError(f"Unknown model provider: {provider}")

    model_id = explicit_model_id or str(provider_config.get("default_model") or "")
    if provider == "openai" and model_id.startswith("claude-"):
        model_id = str(provider_config.get("default_model") or model_id)
    if not model_id:
        raise ProviderConfigurationError(f"Provider {provider} requires a model id")

    api_key = _resolve_api_key(provider_config)
    if not api_key:
        key_hint = provider_config.get("api_key_env") or f"{provider.upper()}_API_KEY"
        raise ProviderConfigurationError(f"Provider {provider} requires an API key in {key_hint}")

    base_url = _clean_optional_str(provider_config.get("base_url"))
    use_responses = bool(provider_config.get("use_responses", False))
    return RuntimeProviderConfig(
        provider=provider,
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        use_responses=use_responses,
        capabilities=_provider_capabilities(provider, use_responses, provider_config),
    )


def provider_capabilities(provider: str) -> RuntimeProviderCapabilities:
    settings = get_settings()
    registry = _provider_registry(settings)
    normalized = _normalize_provider_name(provider)
    config = registry.get(normalized)
    if config is None:
        raise ProviderConfigurationError(f"Unknown model provider: {provider}")
    return _provider_capabilities(normalized, bool(config.get("use_responses", False)), config)


def _provider_registry(settings: Settings) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {
        "openai": {
            "api_key": settings.openai_api_key or os.getenv("OPENAI_API_KEY", ""),
            "api_key_env": "OPENAI_API_KEY",
            "base_url": settings.openai_base_url or os.getenv("OPENAI_BASE_URL", ""),
            "default_model": settings.oma_default_openai_model,
            "use_responses": settings.openai_use_responses,
            "capabilities": {
                "chat_completions": True,
                "responses_api": settings.openai_use_responses,
                "streaming": True,
                "tool_calls": True,
                "hosted_tools": settings.openai_use_responses,
                "multimodal_input": True,
                "reasoning_traces": settings.openai_use_responses,
            },
        },
    }
    for raw_name, raw_config in settings.oma_openai_compatible_providers.items():
        name = _normalize_provider_name(raw_name)
        if not name:
            continue
        config = dict(raw_config or {})
        config.setdefault("api_key_env", f"{name.upper()}_API_KEY")
        config.setdefault("use_responses", False)
        config.setdefault(
            "capabilities",
            {
                "chat_completions": True,
                "responses_api": False,
                "streaming": True,
                "tool_calls": True,
                "hosted_tools": False,
                "multimodal_input": False,
                "reasoning_traces": False,
                "unsupported_parameters": ("previous_response_id", "conversation_id", "prompt"),
            },
        )
        registry[name] = config
    return registry


def _provider_and_model(model: dict[str, Any], settings: Settings) -> tuple[str, str | None]:
    raw_model_id = _clean_optional_str(model.get("id") or model.get("model"))
    raw_provider = _clean_optional_str(
        model.get("provider")
        or model.get("provider_id")
        or model.get("vendor")
        or model.get("source")
    )
    if raw_provider:
        return _normalize_provider_name(raw_provider), raw_model_id

    if raw_model_id and "/" in raw_model_id:
        candidate_provider, candidate_model = raw_model_id.split("/", 1)
        if candidate_provider and candidate_model:
            return _normalize_provider_name(candidate_provider), candidate_model

    if raw_model_id and ":" in raw_model_id:
        candidate_provider, candidate_model = raw_model_id.split(":", 1)
        if candidate_provider and candidate_model:
            return _normalize_provider_name(candidate_provider), candidate_model

    return _normalize_provider_name(settings.oma_default_model_provider), raw_model_id


def _resolve_api_key(config: dict[str, Any]) -> str | None:
    direct = _clean_optional_str(config.get("api_key"))
    if direct:
        return direct
    env_name = _clean_optional_str(config.get("api_key_env"))
    return os.getenv(env_name, "") if env_name else None


def _provider_capabilities(
    provider: str,
    use_responses: bool,
    config: dict[str, Any],
) -> RuntimeProviderCapabilities:
    raw = dict(config.get("capabilities") or {})
    raw.setdefault("chat_completions", True)
    raw.setdefault("responses_api", bool(use_responses))
    raw.setdefault("streaming", True)
    raw.setdefault("tool_calls", True)
    raw.setdefault("hosted_tools", provider == "openai" and bool(use_responses))
    raw.setdefault("multimodal_input", provider == "openai")
    raw.setdefault("reasoning_traces", provider == "openai" and bool(use_responses))
    unsupported = raw.get("unsupported_parameters") or ()
    return RuntimeProviderCapabilities(
        chat_completions=bool(raw["chat_completions"]),
        responses_api=bool(raw["responses_api"]),
        streaming=bool(raw["streaming"]),
        tool_calls=bool(raw["tool_calls"]),
        hosted_tools=bool(raw["hosted_tools"]),
        multimodal_input=bool(raw["multimodal_input"]),
        reasoning_traces=bool(raw["reasoning_traces"]),
        unsupported_parameters=tuple(str(item) for item in unsupported),
    )


def _normalize_provider_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
