from app.config import get_settings
from app.runtime.providers import provider_capabilities, resolve_runtime_provider, runtime_provider_configured
from app.runtime.runner import _model_settings_for_provider, _sdk_tools_for_provider


def test_deepseek_provider_resolution(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    get_settings.cache_clear()

    config = resolve_runtime_provider({"provider": "deepseek", "id": "deepseek-v4-pro"})

    assert config.provider == "deepseek"
    assert config.model_id == "deepseek-v4-pro"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key == "test-deepseek-key"
    assert config.use_responses is False
    assert config.capabilities.responses_api is False
    assert config.capabilities.tool_calls is True


def test_minimax_provider_resolution(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    get_settings.cache_clear()

    config = resolve_runtime_provider({"provider": "minimax"})

    assert config.provider == "minimax"
    assert config.model_id == "MiniMax-M3"
    assert config.base_url == "https://api.minimaxi.com/v1"
    assert config.api_key == "test-minimax-key"
    assert config.use_responses is False
    assert "presence_penalty" in config.capabilities.unsupported_parameters


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


def test_provider_capability_map(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_USE_RESPONSES", "true")
    get_settings.cache_clear()

    openai = provider_capabilities("openai")
    deepseek = provider_capabilities("deepseek")

    assert openai.responses_api is True
    assert openai.hosted_tools is True
    assert deepseek.responses_api is False
    assert deepseek.hosted_tools is False


def test_provider_capability_map_filters_model_settings(monkeypatch):
    from agents import ModelSettings

    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    get_settings.cache_clear()
    config = resolve_runtime_provider({"provider": "minimax", "id": "MiniMax-M3"})

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
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    get_settings.cache_clear()
    config = resolve_runtime_provider({"provider": "minimax", "id": "MiniMax-M3"})

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
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    get_settings.cache_clear()

    assert runtime_provider_configured({"provider": "deepseek", "id": "deepseek-v4-pro"}) is False


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
