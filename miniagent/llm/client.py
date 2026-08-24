"""LLM client with multi-provider support and automatic fallback."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import litellm
from litellm import completion as litellm_completion

from miniagent.config import LLMConfig
from miniagent.llm.providers import ProviderRegistry

logger = logging.getLogger(__name__)
@dataclass
class LLMResponse:
    """Response from an LLM request."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Optional[Any] = None
    error: Optional[str] = None
class LLMClient:
    """
    Multi-provider LLM client using LiteLLM.

    Features:
    - Automatic fallback to backup providers on failure
    - Environment variable resolution for API keys
    - Retry logic with exponential backoff
    - Unified interface across all providers
    """

    def __init__(self, config: LLMConfig):
        """
        Initialize the LLM client.

        Args:
            config: LLM configuration with provider settings
        """
        self.config = config
        # No longer sets API keys globally in os.environ
        # Instead, we pass them directly to litellm_completion

    def _get_all_providers(self) -> list[str]:
        """Get list of all providers to try (primary + fallbacks)."""
        providers = [self.config.primary]
        providers.extend(self.config.fallback)
        return providers

    def _extract_provider_name(self, model: str) -> str:
        """Extract provider name from model identifier."""
        parts = model.split("/")
        return parts[0] if parts else "unknown"

    def complete(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a completion request to the LLM with automatic fallback.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt (prepended to messages)
            temperature: Override default temperature
            max_tokens: Override default max tokens
            stream: Whether to stream the response
            **kwargs: Additional arguments passed to litellm.completion

        Returns:
            LLMResponse with content and metadata

        Raises:
            RuntimeError: If all providers fail
        """
        # Prepare messages with system prompt
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        # Get settings
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        # Try each provider in order
        providers_to_try = self._get_all_providers()
        last_error: Optional[str] = None

        for i, model in enumerate(providers_to_try):
            is_primary = i == 0
            provider_name = self._extract_provider_name(model)

            try:
                logger.info(
                    f"Attempting LLM request with {provider_name} "
                    f"{'(primary)' if is_primary else '(fallback)'}"
                )

                # Get API key for this provider from config
                api_key = self.config.api_keys.get(provider_name)
                
                # Pass API key directly to litellm_completion
                response = litellm_completion(
                    model=model,
                    messages=all_messages,
                    temperature=temp,
                    max_tokens=tokens,
                    stream=stream,
                    timeout=self.config.timeout,
                    api_key=api_key,
                    **kwargs,
                )

                # Handle streaming response
                if stream:
                    # For streaming, we collect chunks and return as single response
                    # This is a simplification; full streaming would yield chunks
                    collected_content = []
                    for chunk in response:
                        if hasattr(chunk, "choices") and chunk.choices:
                            delta = chunk.choices[0].delta
                            if hasattr(delta, "content") and delta.content:
                                collected_content.append(delta.content)
                    content = "".join(collected_content)
                    usage = {}
                else:
                    # Handle non-streaming response
                    content = response.choices[0].message.content or ""
                    usage = {
                        "prompt_tokens": getattr(
                            response.usage, "prompt_tokens", 0
                        ),
                        "completion_tokens": getattr(
                            response.usage, "completion_tokens", 0
                        ),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    }

                logger.info(f"Successfully got response from {provider_name}")

                return LLMResponse(
                    content=content,
                    model=model,
                    provider=provider_name,
                    usage=usage,
                    raw_response=response if not stream else None,
                )

            except Exception as e:
                error_msg = f"{provider_name}: {str(e)}"
                logger.warning(f"Provider {provider_name} failed: {error_msg}")
                last_error = error_msg

                # Continue to next provider
                continue

        # All providers failed
        error_msg = f"All providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    def complete_with_retry(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a completion request with retry logic for transient errors.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Override default temperature
            max_tokens: Override default max tokens
            **kwargs: Additional arguments for completion

        Returns:
            LLMResponse with content and metadata

        Raises:
            RuntimeError: If all retries fail
        """
        import time

        last_exception: Optional[Exception] = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return self.complete(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    # Exponential backoff
                    wait_time = 2**attempt
                    logger.warning(
                        f"Retry {attempt + 1}/{self.config.max_retries} "
                        f"after {wait_time}s due to: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"All retries exhausted. Last error: {e}")

        raise RuntimeError(f"All retries failed") from last_exception

    def chat(
        self,
        user_message: str,
        conversation_history: Optional[list[dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Convenience method for chat conversations.

        Args:
            user_message: The user's message
            conversation_history: Optional list of previous messages
            system_prompt: Optional system prompt
            **kwargs: Additional arguments for completion

        Returns:
            LLMResponse with assistant's reply
        """
        messages = conversation_history or []
        messages.append({"role": "user", "content": user_message})

        return self.complete_with_retry(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        )

    def generate_json(
        self,
        prompt: str,
        schema_description: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Generate a JSON response from the LLM.

        Args:
            prompt: The user prompt
            schema_description: Description of expected JSON structure
            system_prompt: Optional additional system prompt
            **kwargs: Additional arguments for completion

        Returns:
            Parsed JSON response as dict

        Raises:
            ValueError: If response is not valid JSON
        """
        import json

        json_system_prompt = (
            "You must respond ONLY with valid JSON. "
            f"Expected structure: {schema_description}. "
            "Do not include any text outside the JSON object."
        )

        full_system = (
            f"{system_prompt}\n\n{json_system_prompt}"
            if system_prompt
            else json_system_prompt
        )

        response = self.complete_with_retry(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=full_system,
            temperature=0.1,  # Lower temperature for more deterministic JSON
            **kwargs,
        )

        # Extract JSON from response (handle potential markdown code blocks)
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {e}") from e