from app.config import get_settings
from app.runtime.providers import provider_capabilities, resolve_runtime_provider, runtime_provider_configured
from app.runtime.runner import _model_settings_for_provider, _sdk_tools_for_provider


def test_openai_provider_resolution(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()

    config = resolve_runtime_provider({"provider": "openai", "id": "gpt-5.5"})

    assert config.provider == "openai"
    assert config.model_id == "gpt-5.5"
    assert config.api_key == "test-openai-key"
    assert config.use_responses is True
    assert config.capabilities.responses_api is True
    assert config.capabilities.tool_calls is True


def test_custom_openai_compatible_provider_resolution(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-moonshot-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"moonshot":{"api_key_env":"MOONSHOT_API_KEY","base_url":"https://api.moonshot.ai/v1","default_model":"kimi-k2"}}',
    )
    get_settings.cache_clear()

    config = resolve_runtime_provider({"id": "moonshot/kimi-k2-turbo"})

    assert config.provider == "moonshot"
    assert config.model_id == "kimi-k2-turbo"
    assert config.base_url == "https://api.moonshot.ai/v1"
    assert config.api_key == "test-moonshot-key"
    assert config.use_responses is False


def test_deepseek_openai_compatible_provider_resolution(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"deepseek":{"api_key_env":"DEEPSEEK_API_KEY","base_url":"https://api.deepseek.com/v1","default_model":"deepseek-chat"}}',
    )
    get_settings.cache_clear()

    config = resolve_runtime_provider({"provider_id": "deepseek", "id": "deepseek-reasoner"})

    assert config.provider == "deepseek"
    assert config.model_id == "deepseek-reasoner"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key == "test-deepseek-key"
    assert config.use_responses is False
    assert config.capabilities.hosted_tools is False


def test_minimax_openai_compatible_provider_resolution(monkeypatch):
    monkeypatch.setenv("MINI_MAX_API_KEY", "test-minimax-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"mini-max":{"base_url":"https://api.minimax.io/v1","default_model":"MiniMax-M1","capabilities":{"multimodal_input":true,"unsupported_parameters":["previous_response_id","prompt"]}}}',
    )
    get_settings.cache_clear()

    config = resolve_runtime_provider({"model": "mini-max/MiniMax-Text-01"})

    assert config.provider == "mini_max"
    assert config.model_id == "MiniMax-Text-01"
    assert config.base_url == "https://api.minimax.io/v1"
    assert config.api_key == "test-minimax-key"
    assert config.capabilities.multimodal_input is True
    assert "previous_response_id" in config.capabilities.unsupported_parameters


def test_provider_capability_map(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_USE_RESPONSES", "true")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"example":{"api_key_env":"EXAMPLE_API_KEY","base_url":"https://api.example.com/v1","default_model":"example-chat"}}',
    )
    get_settings.cache_clear()

    openai = provider_capabilities("openai")
    example = provider_capabilities("example")

    assert openai.responses_api is True
    assert openai.hosted_tools is True
    assert example.responses_api is False
    assert example.hosted_tools is False


def test_provider_capability_map_filters_model_settings(monkeypatch):
    from agents import ModelSettings

    monkeypatch.setenv("EXAMPLE_API_KEY", "test-example-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"example":{"api_key_env":"EXAMPLE_API_KEY","base_url":"https://api.example.com/v1","default_model":"example-chat","capabilities":{"unsupported_parameters":["presence_penalty","reasoning"]}}}',
    )
    get_settings.cache_clear()
    config = resolve_runtime_provider({"provider": "example", "id": "example-chat"})

    model_settings, removed = _model_settings_for_provider(
        {"model_settings": {"temperature": 0.2, "presence_penalty": 1.0, "reasoning": {"effort": "low"}}},
        {},
        config.capabilities,
        ModelSettings,
    )

    assert model_settings.temperature == 0.2
    assert "presence_penalty" in removed
    assert "reasoning" in removed


def test_provider_capability_map_filters_hosted_tools(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "test-example-key")
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"example":{"api_key_env":"EXAMPLE_API_KEY","base_url":"https://api.example.com/v1","default_model":"example-chat"}}',
    )
    get_settings.cache_clear()
    config = resolve_runtime_provider({"provider": "example", "id": "example-chat"})

    sdk_tools, enabled, filtered = _sdk_tools_for_provider(
        [{"type": "web_search"}, {"type": "agent_toolset_20260401"}],
        [],
        config.capabilities,
        _sdk_tool_classes(),
    )

    assert sdk_tools == []
    assert enabled == []
    assert filtered[0]["reason"] == "provider_does_not_support_hosted_tools"
    assert filtered[1]["reason"] == "unsupported_tool_type"


def test_openai_hosted_tools_are_mapped(monkeypatch):
    monkeypatch.setenv("OPENAI_USE_RESPONSES", "true")
    get_settings.cache_clear()
    capabilities = provider_capabilities("openai")

    sdk_tools, enabled, filtered = _sdk_tools_for_provider(
        [
            {"type": "web_search", "search_context_size": "low"},
            {"type": "file_search", "vector_store_ids": ["vs_123"]},
        ],
        [{"name": "docs", "server_url": "https://mcp.example.com"}],
        capabilities,
        _sdk_tool_classes(),
    )

    assert [tool.name for tool in sdk_tools] == ["web_search", "file_search", "hosted_mcp"]
    assert [tool["type"] for tool in enabled] == ["web_search", "file_search", "mcp"]
    assert filtered == []


def test_unconfigured_provider_falls_back_in_auto(monkeypatch):
    monkeypatch.delenv("EXAMPLE_API_KEY", raising=False)
    monkeypatch.setenv(
        "OMA_OPENAI_COMPATIBLE_PROVIDERS",
        '{"example":{"api_key_env":"EXAMPLE_API_KEY","base_url":"https://api.example.com/v1","default_model":"example-chat"}}',
    )
    get_settings.cache_clear()

    assert runtime_provider_configured({"provider": "example", "id": "example-chat"}) is False


def test_claude_model_id_falls_back_to_default_openai_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OMA_DEFAULT_OPENAI_MODEL", "gpt-5.5")
    get_settings.cache_clear()

    config = resolve_runtime_provider({"id": "claude-opus-4-8"})

    assert config.provider == "openai"
    assert config.model_id == "gpt-5.5"


def _sdk_tool_classes():
    from agents import (
        CodeInterpreterTool,
        FileSearchTool,
        HostedMCPTool,
        ImageGenerationTool,
        WebSearchTool,
    )
    from agents.tool import CodeInterpreter, ImageGeneration, Mcp

    return {
        "WebSearchTool": WebSearchTool,
        "FileSearchTool": FileSearchTool,
        "CodeInterpreterTool": CodeInterpreterTool,
        "CodeInterpreter": CodeInterpreter,
        "HostedMCPTool": HostedMCPTool,
        "Mcp": Mcp,
        "ImageGenerationTool": ImageGenerationTool,
        "ImageGeneration": ImageGeneration,
    }
