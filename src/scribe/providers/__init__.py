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
from scribe.providers.factory import get_provider
from scribe.providers.health import HealthStatus, ProviderHealthMonitor, get_health_monitor
from scribe.providers.ollama_provider import OllamaProvider
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider

__all__ = [
    "AIProvider",
    "HealthStatus",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderConfig",
    "ProviderHealthMonitor",
    "XAIProvider",
    "get_health_monitor",
    "get_provider",
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
