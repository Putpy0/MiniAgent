"""LLM provider registry with aliases and metadata."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderInfo:
    """Information about an LLM provider."""

    name: str
    display_name: str
    supports_streaming: bool = True
    requires_api_key: bool = True
    rate_limit_tier: str = "standard"  # free, standard, premium


class ProviderRegistry:
    """Registry of supported LLM providers with litellm-compatible identifiers."""

    # Provider aliases and metadata
    PROVIDERS: dict[str, ProviderInfo] = {
        # OpenRouter (aggregator for many models)
        "openrouter": ProviderInfo(
            name="openrouter",
            display_name="OpenRouter",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="standard",
        ),
        # Groq (fast inference)
        "groq": ProviderInfo(
            name="groq",
            display_name="Groq",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="free",
        ),
        # DeepSeek
        "deepseek": ProviderInfo(
            name="deepseek",
            display_name="DeepSeek",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="standard",
        ),
        # Anthropic (Claude)
        "anthropic": ProviderInfo(
            name="anthropic",
            display_name="Anthropic",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="premium",
        ),
        # OpenAI
        "openai": ProviderInfo(
            name="openai",
            display_name="OpenAI",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="premium",
        ),
        # Alibaba DashScope (Qwen)
        "dashscope": ProviderInfo(
            name="dashscope",
            display_name="DashScope (Alibaba)",
            supports_streaming=True,
            requires_api_key=True,
            rate_limit_tier="standard",
        ),
        # Ollama (local models)
        "ollama": ProviderInfo(
            name="ollama",
            display_name="Ollama (Local)",
            supports_streaming=True,
            requires_api_key=False,
            rate_limit_tier="free",
        ),
        # LM Studio (local)
        "lm_studio": ProviderInfo(
            name="lm_studio",
            display_name="LM Studio (Local)",
            supports_streaming=True,
            requires_api_key=False,
            rate_limit_tier="free",
        ),
        # vLLM (self-hosted)
        "vllm": ProviderInfo(
            name="vllm",
            display_name="vLLM (Self-hosted)",
            supports_streaming=True,
            requires_api_key=False,
            rate_limit_tier="free",
        ),
    }

    # Common model aliases for convenience
    MODEL_ALIASES: dict[str, str] = {
        # Qwen models
        "qwen-coder": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
        "qwen-chat": "openrouter/qwen/qwen-2.5-72b-instruct",
        "qwen-local": "ollama/qwen2.5-coder",
        # Llama models
        "llama-3.1-70b": "groq/llama-3.1-70b-versatile",
        "llama-3.3-70b": "groq/llama-3.3-70b-versatile",
        "llama-local": "ollama/llama3.1",
        # Claude models
        "claude-sonnet": "anthropic/claude-3-5-sonnet-20241022",
        "claude-haiku": "anthropic/claude-3-5-haiku-20241022",
        "claude-opus": "anthropic/claude-3-opus-20240229",
        # GPT models
        "gpt-4o": "openai/gpt-4o",
        "gpt-4-turbo": "openai/gpt-4-turbo-preview",
        "gpt-3.5-turbo": "openai/gpt-3.5-turbo",
        # DeepSeek models
        "deepseek-chat": "deepseek/deepseek-chat",
        "deepseek-coder": "deepseek/deepseek-coder",
    }

    @classmethod
    def get_provider_info(cls, model_identifier: str) -> Optional[ProviderInfo]:
        """
        Get provider information from a model identifier.

        Args:
            model_identifier: Full model identifier (e.g., 'openrouter/qwen/...')
                or alias (e.g., 'qwen-coder')

        Returns:
            ProviderInfo if found, None otherwise
        """
        # Resolve alias if provided
        if model_identifier in cls.MODEL_ALIASES:
            model_identifier = cls.MODEL_ALIASES[model_identifier]

        # Extract provider name from identifier
        parts = model_identifier.split("/")
        if len(parts) >= 1:
            provider_name = parts[0].lower()
            return cls.PROVIDERS.get(provider_name)
        return None

    @classmethod
    def resolve_model(cls, model_identifier: str) -> str:
        """
        Resolve a model alias to its full identifier.

        Args:
            model_identifier: Model alias or full identifier

        Returns:
            Full model identifier
        """
        return cls.MODEL_ALIASES.get(model_identifier, model_identifier)

    @classmethod
    def list_providers(cls) -> list[ProviderInfo]:
        """List all registered providers."""
        return list(cls.PROVIDERS.values())

    @classmethod
    def list_aliases(cls) -> dict[str, str]:
        """List all model aliases."""
        return cls.MODEL_ALIASES.copy()

    @classmethod
    def is_local_provider(cls, model_identifier: str) -> bool:
        """
        Check if a provider is local (doesn't require API key).

        Args:
            model_identifier: Model identifier or alias

        Returns:
            True if provider is local, False otherwise
        """
        info = cls.get_provider_info(model_identifier)
        return info is not None and not info.requires_api_key
