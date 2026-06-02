"""
Provider factory for creating AI provider instances.
"""

import logging
import os

from scribe.providers.base import AIProvider, ProviderConfig
from scribe.providers.ollama_provider import OLLAMA_PLACEHOLDER_KEY, OllamaProvider
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider
from scribe.utils.ollama_models import DEFAULT_OLLAMA_MODEL

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
    if api_key is None:
        if provider_name == "xai":
            api_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
        elif provider_name == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
        elif provider_name == "gemini":
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("SCRIBE_GEMINI_API_KEY")
        elif provider_name == "ollama":
            # Ollama runs locally and ignores the key, but the SDK needs a value.
            api_key = (
                os.getenv("OLLAMA_API_KEY")
                or os.getenv("SCRIBE_OLLAMA_API_KEY")
                or OLLAMA_PLACEHOLDER_KEY
            )
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    if not api_key:
        raise ValueError(f"No API key found for provider: {provider_name}")

    # Health check if enabled
    if enable_health_check:
        from scribe.providers.health import get_health_monitor

        monitor = get_health_monitor()
        status = monitor.check_provider_health(provider_name, api_key)

        if not status.is_healthy:
            logger.warning(f"Provider {provider_name} failed health check: {status.error_message}")
            # Try to get a fallback provider
            fallback = _get_fallback_provider(feature, provider_name, api_key)
            if fallback:
                logger.info(f"Using fallback provider: {fallback}")
                return get_provider(feature, provider_name=fallback, enable_health_check=False)
            else:
                logger.warning(f"No fallback available, proceeding with {provider_name}")

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
                "anthropic package not installed. Install with: pip install anthropic"
            )
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider_name == "gemini":
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-genai package not installed. Install with: pip install google-genai"
            )
        return GeminiProvider(config)
    elif provider_name == "ollama":
        return OllamaProvider(config)
    else:
        raise ValueError(f"Unsupported provider: {provider_name}")


def _get_default_model(provider_name: str, feature: str) -> str:
    """Get default model for a provider and feature."""

    defaults: dict[str, dict[str, str | None]] = {
        "openai": {
            "joke": "gpt-5.5",
            "meme": "gpt-5.5",
            "meme_image": "gpt-image-1",
            "notes": "gpt-5.5",
            "transcribe": "whisper-1",
        },
        "xai": {
            "joke": "grok-4.3",
            "meme": "grok-4.3",
            "meme_image": "grok-imagine-image",  # Note: XAI image gen can add watermarks, consider using OpenAI for images
            "notes": "grok-4.3",
            "transcribe": None,  # XAI doesn't support transcription yet
        },
        "anthropic": {
            "joke": "claude-3-5-sonnet-20241022",
            "meme": "claude-3-5-sonnet-20241022",
            "meme_image": None,  # Anthropic doesn't support image generation
            "notes": "claude-3-5-sonnet-20241022",
            "transcribe": None,  # Anthropic doesn't support transcription yet
        },
        "gemini": {
            "joke": "gemini-3-pro-preview",  # Gemini 3 for advanced reasoning
            "meme": "gemini-3-pro-preview",  # Gemini 3 for complex multimodal tasks
            "meme_image": "imagen-4.0-generate-001",
            "notes": "gemini-3-pro-preview",  # Gemini 3 for structured analysis
            "transcribe": None,  # Gemini doesn't support dedicated transcription yet
        },
        # Ollama models are machine-dependent; get_provider() picks the best
        # installed model by VRAM. These are only last-resort fallbacks.
        "ollama": {
            "joke": DEFAULT_OLLAMA_MODEL,
            "meme": DEFAULT_OLLAMA_MODEL,
            "meme_image": None,  # Ollama does not generate images
            "notes": DEFAULT_OLLAMA_MODEL,
            "transcribe": None,  # Ollama does not transcribe audio
        },
    }

    provider_defaults: dict[str, str | None] | None = defaults.get(provider_name)
    model = provider_defaults.get(feature) if provider_defaults is not None else None

    if model is None:
        raise ValueError(f"Provider '{provider_name}' does not support feature '{feature}'")

    return model


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
