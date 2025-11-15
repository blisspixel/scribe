"""
Provider factory for creating AI provider instances.
"""

import os
from typing import Optional

from scribe.providers.base import AIProvider, ProviderConfig
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider

try:
    from scribe.providers.anthropic_provider import AnthropicProvider
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


def get_provider(
    feature: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> AIProvider:
    """
    Get an AI provider for a specific feature.
    
    Args:
        feature: Feature name ("joke", "meme", "notes", "transcribe")
        api_key: API key (optional, will check env vars)
        model: Model name (optional, will use defaults)
        provider_name: Provider name (optional, will check env vars)
        
    Returns:
        AIProvider instance
        
    Environment Variables:
        SCRIBE_JOKE_PROVIDER: Provider for jokes (default: xai)
        SCRIBE_MEME_PROVIDER: Provider for memes (default: openai)
        SCRIBE_NOTES_PROVIDER: Provider for notes (default: openai)
        SCRIBE_TRANSCRIBE_PROVIDER: Provider for transcription (default: openai)
        
        XAI_API_KEY: XAI API key
        OPENAI_API_KEY: OpenAI API key
    """
    
    # Determine provider with feature-specific defaults
    if provider_name is None:
        env_var = f"SCRIBE_{feature.upper()}_PROVIDER"
        # Default to XAI for jokes (cheaper and faster), OpenAI for everything else
        default_provider = "xai" if feature == "joke" else "openai"
        provider_name = os.getenv(env_var, default_provider).lower()
    
    # Get API key
    if api_key is None:
        if provider_name == "xai":
            api_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
        elif provider_name == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
        else:
            raise ValueError(f"Unknown provider: {provider_name}")
    
    if not api_key:
        raise ValueError(f"No API key found for provider: {provider_name}")
    
    # Determine model
    if model is None:
        model = _get_default_model(provider_name, feature)
    
    # Create config
    config = ProviderConfig(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        timeout=int(os.getenv("SCRIBE_API_TIMEOUT", "120")),
    )
    
    # Create provider
    if provider_name == "openai":
        return OpenAIProvider(config)
    elif provider_name == "xai":
        return XAIProvider(config)
    elif provider_name == "anthropic":
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package not installed. Install with: pip install anthropic")
        return AnthropicProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unsupported provider: {provider_name}")


def _get_default_model(provider_name: str, feature: str) -> str:
    """Get default model for a provider and feature."""
    
    defaults = {
        "openai": {
            "joke": "gpt-5",
            "meme": "gpt-5",
            "meme_image": "gpt-image-1",
            "notes": "gpt-5",
            "transcribe": "whisper-1",
        },
        "xai": {
            "joke": "grok-4-fast-reasoning",
            "meme": "grok-4-fast-reasoning",
            "meme_image": "grok-2-image",
            "notes": "grok-4-fast-reasoning",
            "transcribe": None,  # XAI doesn't support transcription yet
        },
        "anthropic": {
            "joke": "claude-3-5-sonnet-20241022",
            "meme": "claude-3-5-sonnet-20241022",
            "meme_image": None,  # Anthropic doesn't support image generation
            "notes": "claude-3-5-sonnet-20241022",
            "transcribe": None,  # Anthropic doesn't support transcription yet
        },
    }
    
    model = defaults.get(provider_name, {}).get(feature)
    
    if model is None:
        raise ValueError(
            f"Provider '{provider_name}' does not support feature '{feature}'"
        )
    
    return model
