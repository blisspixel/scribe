"""
AI Provider abstraction for Scribe.

Supports multiple AI providers (OpenAI, XAI/Grok, Anthropic, etc.) for:
- Transcription (cloud fallback)
- Joke generation
- Meme concept and QA
- Meeting notes
"""

from scribe.providers.base import AIProvider, ProviderConfig
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider
from scribe.providers.factory import get_provider

try:
    from scribe.providers.anthropic_provider import AnthropicProvider
    __all__ = [
        "AIProvider",
        "ProviderConfig",
        "OpenAIProvider",
        "XAIProvider",
        "AnthropicProvider",
        "get_provider",
    ]
except ImportError:
    __all__ = [
        "AIProvider",
        "ProviderConfig",
        "OpenAIProvider",
        "XAIProvider",
        "get_provider",
    ]
