"""
Provider factory for creating AI provider instances.
"""

import logging
import os

from scribe.providers.base import AIProvider, ProviderConfig
from scribe.providers.catalog import get_default_model as _get_default_model
from scribe.providers.ollama_provider import OLLAMA_PLACEHOLDER_KEY, OllamaProvider
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider

try:
    from scribe.providers.anthropic_provider import AnthropicProvider

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from scribe.providers.gemini_provider import GeminiProvider

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)


def _config_provider(feature: str) -> str | None:
    """Provider chosen in ~/.scribe/config.toml [providers] for a feature, if set.

    Bridges the setup wizard's vendor choice (written as ``<feature>_provider``)
    to provider selection. Env vars still win; this sits between the env var and
    the built-in default, so precedence is env > config.toml > default. Any
    failure reading the config (missing home, unreadable file) falls back to None.
    """
    try:
        from scribe.config_file import load_config_file

        providers = load_config_file().get("providers", {})
        value = providers.get(f"{feature}_provider")
        return str(value).lower() if value else None
    except Exception:
        return None


def _local_only_enabled() -> bool:
    """Whether $0 local-only mode is on (env SCRIBE_LOCAL_ONLY or config.toml).

    Mirrors ``ScribeConfig.local_only`` for the provider layer, which does not
    receive the config object. Env wins over the config file, matching the rest
    of the settings precedence. Any failure reading the config falls back to off.
    """
    env = os.getenv("SCRIBE_LOCAL_ONLY")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        from scribe.config_file import load_config_file

        transcription = load_config_file().get("transcription", {})
        return bool(transcription.get("local_only")) if isinstance(transcription, dict) else False
    except Exception:
        return False


def _resolve_api_key(provider_name: str, api_key: str | None) -> str:
    """Resolve API key from environment variables if not explicitly provided."""
    if api_key is not None:
        return api_key

    if provider_name == "xai":
        api_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
    elif provider_name == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
    elif provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("SCRIBE_GEMINI_API_KEY")
    elif provider_name == "ollama":
        api_key = (
            os.getenv("OLLAMA_API_KEY")
            or os.getenv("SCRIBE_OLLAMA_API_KEY")
            or OLLAMA_PLACEHOLDER_KEY
        )
    else:
        raise ValueError(f"Unknown provider: {provider_name}")

    if not api_key:
        raise ValueError(f"No API key found for provider: {provider_name}")

    return api_key


def _handle_unhealthy_provider(feature: str, provider_name: str, api_key: str) -> str | None:
    """Check health and return a fallback provider if unhealthy."""
    from scribe.providers.health import get_health_monitor

    monitor = get_health_monitor()
    status = monitor.check_provider_health(provider_name, api_key)

    if status.is_healthy:
        return None

    logger.warning(f"Provider {provider_name} failed health check: {status.error_message}")
    fallback = _get_fallback_provider(feature, provider_name, api_key)
    if fallback:
        logger.warning(
            f"Provider {provider_name} is unhealthy; failing over to {fallback}. "
            f"Your request will be sent to {fallback} instead."
        )
        return fallback
    else:
        logger.warning(f"No fallback available, proceeding with {provider_name}")
        return None


def get_provider(
    feature: str,
    api_key: str | None = None,
    model: str | None = None,
    provider_name: str | None = None,
    enable_health_check: bool = False,
) -> AIProvider:
    """
    Get an AI provider for a specific feature.

    Args:
        feature: Feature name ("joke", "meme", "notes", "transcribe")
        api_key: API key (optional, will check env vars)
        model: Model name (optional, will use defaults)
        provider_name: Provider name (optional, will check env vars)
        enable_health_check: Check provider health before returning (default: False)

    Returns:
        AIProvider instance

    Environment Variables:
        SCRIBE_JOKE_PROVIDER: Provider for jokes (default: xai)
        SCRIBE_MEME_PROVIDER: Provider for memes (default: openai)
        SCRIBE_NOTES_PROVIDER: Provider for notes (default: openai)
        SCRIBE_TRANSCRIBE_PROVIDER: Provider for transcription (default: openai)
        SCRIBE_ENABLE_HEALTH_CHECKS: Enable automatic health checks (default: false)

        XAI_API_KEY: XAI API key
        OPENAI_API_KEY: OpenAI API key
        ANTHROPIC_API_KEY: Anthropic API key
        GEMINI_API_KEY: Google Gemini API key
    """

    # Check if health checks are enabled globally
    if not enable_health_check:
        enable_health_check = os.getenv("SCRIBE_ENABLE_HEALTH_CHECKS", "false").lower() == "true"

    # Local-only mode ($0): route text features to local Ollama and refuse the paid
    # cloud image API, regardless of any configured/explicit provider.
    if _local_only_enabled():
        if feature == "meme_image":
            raise ValueError(
                "Local-only mode ($0, SCRIBE_LOCAL_ONLY) is enabled, but meme image "
                "generation has no local backend. Disable memes or unset SCRIBE_LOCAL_ONLY."
            )
        if provider_name and provider_name.lower() != "ollama":
            logger.warning(
                "Local-only mode is enabled; using local Ollama for %s instead of %s.",
                feature,
                provider_name,
            )
        provider_name = "ollama"

    # Determine provider with feature-specific defaults
    if provider_name is None:
        # Special handling for meme_image - check dedicated env var first
        if feature == "meme_image":
            # Env var, then config.toml, then the SCRIBE_MEME_PROVIDER fallbacks.
            provider_name = (
                os.getenv("SCRIBE_MEME_IMAGE_PROVIDER")
                or _config_provider("meme_image")
                or os.getenv("SCRIBE_MEME_PROVIDER")
                or _config_provider("meme")
                or "xai"
            )
        else:
            env_var = f"SCRIBE_{feature.upper()}_PROVIDER"
            # Default to XAI for jokes and memes (cheaper, faster, less restrictive)
            # OpenAI for everything else. Honor a wizard choice in config.toml between
            # the env var and the default so `scribe init` actually takes effect.
            default_provider = "xai" if feature in ["joke", "meme"] else "openai"
            provider_name = os.getenv(env_var) or _config_provider(feature) or default_provider

        provider_name = provider_name.lower()

    # Get API key
    api_key = _resolve_api_key(provider_name, api_key)

    # Health check if enabled
    if enable_health_check:
        fallback = _handle_unhealthy_provider(feature, provider_name, api_key)
        if fallback:
            return get_provider(feature, provider_name=fallback, enable_health_check=False)

    # Determine model
    if model is None or model == "":
        if provider_name == "ollama":
            # Pick the best installed local model for this machine's memory budget.
            from scribe.utils.ollama_models import select_default_ollama_model

            model = select_default_ollama_model(os.getenv("SCRIBE_OLLAMA_BASE_URL"))
        else:
            model = _get_default_model(provider_name, feature)

    # Create config. Local models can be much slower than cloud APIs (cold
    # loads, CPU offload on modest hardware), so Ollama gets a generous default
    # timeout that keeps notes generation working on "any machine".
    if provider_name == "ollama":
        timeout = int(os.getenv("SCRIBE_OLLAMA_TIMEOUT", "600"))
    else:
        timeout = int(os.getenv("SCRIBE_API_TIMEOUT", "120"))

    config = ProviderConfig(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        base_url=os.getenv("SCRIBE_OLLAMA_BASE_URL") if provider_name == "ollama" else None,
        timeout=timeout,
    )

    # Create provider
    if provider_name == "openai":
        return OpenAIProvider(config)
    elif provider_name == "xai":
        return XAIProvider(config)
    elif provider_name == "anthropic":
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                'Anthropic support is not installed. Install Scribe with its "providers" extra.'
            )
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider_name == "gemini":
        if not GEMINI_AVAILABLE:
            raise ImportError(
                'Gemini support is not installed. Install Scribe with its "providers" extra.'
            )
        return GeminiProvider(config)
    elif provider_name == "ollama":
        return OllamaProvider(config)
    else:
        raise ValueError(f"Unsupported provider: {provider_name}")


def _get_fallback_provider(feature: str, failed_provider: str, original_api_key: str) -> str | None:
    """
    Get a fallback provider when the primary fails.

    Args:
        feature: Feature name
        failed_provider: Provider that failed
        original_api_key: API key of failed provider

    Returns:
        Fallback provider name or None
    """
    # Define fallback chains
    fallbacks = {
        "joke": ["xai", "gemini", "openai", "anthropic"],
        "meme": ["xai", "gemini", "openai", "anthropic"],
        "meme_image": ["openai", "gemini", "xai"],
        "notes": ["gemini", "xai", "openai", "anthropic"],
        "transcribe": ["openai"],  # Only OpenAI supports transcription
    }

    chain = fallbacks.get(feature, [])

    # Remove the failed provider from the chain
    if failed_provider in chain:
        chain = [p for p in chain if p != failed_provider]

    # Try to find a provider with an API key
    for provider in chain:
        api_key = None
        if provider == "xai":
            api_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
        elif provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
        elif provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("SCRIBE_GEMINI_API_KEY")

        if api_key:
            return provider

    return None
