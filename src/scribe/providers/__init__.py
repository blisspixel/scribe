"""
AI Provider abstraction for Scribe.

Supports multiple AI providers (OpenAI, XAI/Grok, Anthropic, Google Gemini) for:
- Transcription (cloud fallback)
- Joke generation
- Meme concept and QA
- Meeting notes
- Image generation
"""

from scribe.providers.base import AIProvider, ProviderConfig
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider
from scribe.providers.factory import get_provider
from scribe.providers.health import ProviderHealthMonitor, HealthStatus, get_health_monitor

__all__ = [
    "AIProvider",
    "ProviderConfig",
    "OpenAIProvider",
    "XAIProvider",
    "get_provider",
    "ProviderHealthMonitor",
    "HealthStatus",
    "get_health_monitor",
]

# Optional providers
try:
    from scribe.providers.anthropic_provider import AnthropicProvider
    __all__.append("AnthropicProvider")
except ImportError:
    pass

try:
    from scribe.providers.gemini_provider import GeminiProvider
    __all__.append("GeminiProvider")
except ImportError:
    pass
