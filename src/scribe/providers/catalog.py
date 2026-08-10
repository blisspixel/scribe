"""Provider capability and default-model catalog.

This module is intentionally dependency-light. Provider construction and live
health probes both depend on it, so keeping the catalog separate prevents those
two services from importing each other.
"""

from scribe.utils.ollama_models import DEFAULT_OLLAMA_MODEL

_DEFAULT_MODELS: dict[str, dict[str, str | None]] = {
    "openai": {
        "joke": "gpt-5.5",
        "meme": "gpt-5.5",
        "meme_image": "gpt-image-2",
        "notes": "gpt-5.5",
        "transcribe": "whisper-1",
    },
    "xai": {
        "joke": "grok-4.3",
        "meme": "grok-4.3",
        "meme_image": "grok-imagine-image",
        "notes": "grok-4.3",
        "transcribe": None,
    },
    "anthropic": {
        "joke": "claude-sonnet-5",
        "meme": "claude-sonnet-5",
        "meme_image": None,
        "notes": "claude-sonnet-5",
        "transcribe": None,
    },
    "gemini": {
        "joke": "gemini-3.5-flash",
        "meme": "gemini-3.5-flash",
        "meme_image": "gemini-3.1-flash-image",
        "notes": "gemini-3.5-flash",
        "transcribe": None,
    },
    # Ollama models are machine-dependent. These values are last-resort
    # fallbacks when runtime discovery cannot select an installed model.
    "ollama": {
        "joke": DEFAULT_OLLAMA_MODEL,
        "meme": DEFAULT_OLLAMA_MODEL,
        "meme_image": None,
        "notes": DEFAULT_OLLAMA_MODEL,
        "transcribe": None,
    },
}


def get_default_model(provider_name: str, feature: str) -> str:
    """Return the default model for a supported provider capability."""
    provider_defaults = _DEFAULT_MODELS.get(provider_name)
    model = provider_defaults.get(feature) if provider_defaults is not None else None
    if model is None:
        raise ValueError(f"Provider '{provider_name}' does not support feature '{feature}'")
    return model
