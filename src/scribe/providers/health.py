"""
Provider health check utilities.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health status for a provider."""

    provider_name: str
    is_healthy: bool
    last_check: datetime
    error_message: str | None = None
    response_time_ms: float | None = None
    consecutive_failures: int = 0


class ProviderHealthMonitor:
    """Monitor health status of AI providers."""

    def __init__(self, check_interval_seconds: int = 300) -> None:
        """
        Initialize health monitor.

        Args:
            check_interval_seconds: How often to check provider health (default: 5 minutes)
        """
        self.check_interval = timedelta(seconds=check_interval_seconds)
        self.health_status: dict[str, HealthStatus] = {}
        self.max_consecutive_failures = 3

    def check_provider_health(
        self, provider_name: str, api_key: str, force: bool = False
    ) -> HealthStatus:
        """
        Check health of a provider.

        Args:
            provider_name: Name of provider ("openai", "xai", "anthropic", "gemini")
            api_key: API key for the provider
            force: Force check even if recently checked

        Returns:
            HealthStatus object
        """
        # Check if we need to run health check
        if not force and provider_name in self.health_status:
            status = self.health_status[provider_name]
            time_since_check = datetime.now() - status.last_check

            if time_since_check < self.check_interval:
                logger.debug(f"Using cached health status for {provider_name}")
                return status

        # Run health check
        logger.info(f"Checking health of {provider_name} provider")

        try:
            start_time = datetime.now()

            # Perform lightweight test based on provider
            if provider_name == "openai":
                self._check_openai(api_key)
            elif provider_name == "xai":
                self._check_xai(api_key)
            elif provider_name == "anthropic":
                self._check_anthropic(api_key)
            elif provider_name == "gemini":
                self._check_gemini(api_key)
            elif provider_name == "ollama":
                self._check_ollama()
            else:
                raise ValueError(f"Unknown provider: {provider_name}")

            response_time = (datetime.now() - start_time).total_seconds() * 1000

            status = HealthStatus(
                provider_name=provider_name,
                is_healthy=True,
                last_check=datetime.now(),
                response_time_ms=response_time,
                consecutive_failures=0,
            )

            logger.info(f"{provider_name} is healthy (response time: {response_time:.0f}ms)")

        except Exception as e:
            # Get previous failure count
            prev_failures = 0
            if provider_name in self.health_status:
                prev_failures = self.health_status[provider_name].consecutive_failures

            status = HealthStatus(
                provider_name=provider_name,
                is_healthy=False,
                last_check=datetime.now(),
                error_message=str(e),
                consecutive_failures=prev_failures + 1,
            )

            logger.warning(
                f"{provider_name} health check failed (attempt {status.consecutive_failures}): {e}"
            )

        # Cache status
        self.health_status[provider_name] = status
        return status

    def get_healthy_providers(self, feature: str, api_keys: dict[str, str]) -> list[str]:
        """
        Get list of healthy providers for a feature.

        Args:
            feature: Feature name ("joke", "meme", "notes", "transcribe")
            api_keys: Dict of provider_name -> api_key

        Returns:
            List of healthy provider names
        """
        # Define which providers support which features
        feature_support = {
            "joke": ["openai", "xai", "anthropic", "gemini", "ollama"],
            "meme": ["openai", "xai", "anthropic", "gemini", "ollama"],
            "meme_image": ["openai", "xai", "gemini"],
            "notes": ["openai", "xai", "anthropic", "gemini", "ollama"],
            "transcribe": ["openai"],
        }

        supported_providers = feature_support.get(feature, [])
        healthy = []

        for provider_name in supported_providers:
            if provider_name not in api_keys:
                continue

            status = self.check_provider_health(provider_name, api_keys[provider_name])

            if status.is_healthy:
                healthy.append(provider_name)
            elif status.consecutive_failures >= self.max_consecutive_failures:
                logger.error(
                    f"{provider_name} has failed {status.consecutive_failures} "
                    f"consecutive health checks, marking as unavailable"
                )

        return healthy

    def _check_openai(self, api_key: str) -> None:
        """Check OpenAI API health."""
        from openai import OpenAI

        from scribe.providers.factory import _get_default_model

        model = _get_default_model("openai", "joke")
        client = OpenAI(api_key=api_key, timeout=10)

        # Simple completion test
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "test"}],
            max_completion_tokens=5,
        )

        if not response.choices:
            raise ValueError("No response from OpenAI")

    def _check_xai(self, api_key: str) -> None:
        """Check XAI API health."""
        from openai import OpenAI

        from scribe.providers.factory import _get_default_model

        model = _get_default_model("xai", "joke")
        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=10)

        # Simple completion test
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "test"}],
            max_completion_tokens=5,
        )

        if not response.choices:
            raise ValueError("No response from XAI")

    def _check_anthropic(self, api_key: str) -> None:
        """Check Anthropic API health."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed")

        from scribe.providers.factory import _get_default_model

        model = _get_default_model("anthropic", "joke")

        client = anthropic.Anthropic(api_key=api_key, timeout=10)

        # Simple completion test
        response = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "test"}],
        )

        if not response.content:
            raise ValueError("No response from Anthropic")

    def _check_gemini(self, api_key: str) -> None:
        """Check Gemini API health."""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai package not installed")

        # Get the default model from factory
        from scribe.providers.factory import _get_default_model

        model = _get_default_model("gemini", "joke")

        client = genai.Client(api_key=api_key)

        # Test with actual model we use
        # Use higher max_output_tokens because Gemini 3 thinking uses tokens
        thinking_config_factory = cast(Any, types.ThinkingConfig)
        config_factory = cast(Any, types.GenerateContentConfig)
        response = client.models.generate_content(
            model=model,
            contents="test",
            config=config_factory(
                max_output_tokens=200,
                thinking_config=thinking_config_factory(thinking_level="low"),
            ),
        )

        if not response.text:
            raise ValueError("No response from Gemini")

    def _check_ollama(self) -> None:
        """Check that a local Ollama server is reachable and has a model installed."""
        import os

        from scribe.utils.ollama_models import list_installed_models

        base_url = os.getenv("SCRIBE_OLLAMA_BASE_URL")
        models = list_installed_models(base_url)
        if not models:
            raise ValueError(
                "Ollama server not reachable or no models installed. "
                "Start Ollama and run e.g. `ollama pull llama3.2`."
            )


# Global health monitor instance
_health_monitor = ProviderHealthMonitor()


def get_health_monitor() -> ProviderHealthMonitor:
    """Get the global health monitor instance."""
    return _health_monitor
