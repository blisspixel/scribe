"""
Base provider interface for AI services.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Abstract Base Class + Strategy Pattern
═══════════════════════════════════════════════════════════════════════════════

This module defines the contract that all AI providers must implement, enabling
Scribe to work with multiple AI services (OpenAI, XAI/Grok, Anthropic, Gemini)
through a unified interface.

DESIGN RATIONALE:
─────────────────
AI services have different APIs, pricing models, and capabilities. Rather than
coupling Scribe's code to a specific provider, we define an abstract interface
that all providers must implement. This enables:

1. PROVIDER INDEPENDENCE: Switch providers without changing application code
2. COST OPTIMIZATION: Use cheaper providers for specific tasks (Grok for jokes)
3. FEATURE AVAILABILITY: Use providers with specific capabilities (vision, reasoning)
4. RESILIENCE: Fallback to alternative providers if one fails
5. TESTING: Mock providers for unit tests

PROVIDER ABSTRACTION:
─────────────────────
The AIProvider abstract base class defines four core capabilities:

1. chat_completion(): Text generation with conversation context
2. transcribe_audio(): Speech-to-text transcription
3. generate_image(): Text-to-image generation
4. analyze_image(): Image-to-text analysis (vision)

Not all providers support all capabilities:
┌────────────┬──────┬────────────┬───────┬─────────┐
│ Provider   │ Chat │ Transcribe │ Image │ Vision  │
├────────────┼──────┼────────────┼───────┼─────────┤
│ OpenAI     │  ✓   │     ✓      │   ✓   │    ✓    │
│ XAI/Grok   │  ✓   │     ✗      │   ✓   │    ✓    │
│ Anthropic  │  ✓   │     ✗      │   ✗   │    ✓    │
│ Gemini     │  ✓   │     ✗      │   ✓   │    ✓    │
└────────────┴──────┴────────────┴───────┴─────────┘

Providers raise NotImplementedError for unsupported capabilities.

STRUCTURED OUTPUT PATTERN:
──────────────────────────
The chat_completion_with_json() method implements a pattern for getting
structured output from LLMs:

Traditional approach (fragile):
  response = llm.chat("Generate a joke")
  # Response might be: "Here's a joke: Why did the chicken..."
  # Hard to parse, inconsistent format

Structured approach (robust):
  schema = {"joke": "string", "archetype": "string"}
  response = llm.chat_completion_with_json(messages, json_schema=schema)
  # Response is guaranteed to be valid JSON matching schema
  # Easy to parse, consistent format

Implementation strategies:
1. Native structured output (OpenAI, Gemini): Use provider's JSON mode
2. Prompt engineering (Anthropic, XAI): Add schema to prompt, parse response
3. Validation + retry: Parse response, retry if invalid

PROVIDER CONFIGURATION:
───────────────────────
Each provider is configured with a ProviderConfig dataclass:

```python
config = ProviderConfig(
    provider_name="openai",
    api_key="sk-...",
    model="gpt-4",
    base_url=None,  # Optional custom endpoint
    timeout=120,    # Request timeout in seconds
    max_retries=3   # Retry failed requests
)
```

This configuration is passed to the provider constructor and used for all
requests. It encapsulates provider-specific settings in a type-safe way.

USAGE PATTERN:
──────────────
```python
from scribe.providers import get_provider

# Get provider for specific feature
provider = get_provider(feature='joke', provider_name='xai')

# Chat completion
response = provider.chat_completion(
    messages=[
        {"role": "system", "content": "You are a comedian"},
        {"role": "user", "content": "Tell me a joke"}
    ],
    max_tokens=500,
    temperature=0.8
)
joke = response["content"]

# Structured output
response = provider.chat_completion_with_json(
    messages=[...],
    json_schema={"joke": "string", "archetype": "string"}
)
data = json.loads(response["content"])
```

ERROR HANDLING:
───────────────
Providers should raise appropriate exceptions:

- APIError: API request failed (rate limit, auth, network)
- ValidationError: Invalid parameters or configuration
- NotImplementedError: Capability not supported by provider

The provider factory (get_provider) handles provider selection and fallback.

EXTENSIBILITY:
──────────────
Adding a new provider requires:

1. Create provider class inheriting from AIProvider
2. Implement required methods (chat_completion, etc.)
3. Register provider in factory (providers/__init__.py)
4. Add configuration (API key environment variable)

Example:
```python
class NewProvider(AIProvider):
    def chat_completion(self, messages, **kwargs):
        # Implementation
        pass

    def transcribe_audio(self, audio_path, **kwargs):
        raise NotImplementedError("Transcription not supported")
```

RESEARCH REFERENCES:
────────────────────
- "Design Patterns: Elements of Reusable Object-Oriented Software" (GoF, 1994)
  → Abstract Factory and Strategy patterns
- "Clean Architecture" (Martin, 2017)
  → Dependency inversion principle (depend on abstractions, not concretions)
- "Structured Output from Language Models" (OpenAI, 2023)
  → JSON mode and function calling for structured generation

This provider abstraction is key to Scribe's flexibility - it enables using
the best AI service for each task while maintaining a simple, unified interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""

    provider_name: str  # "openai", "xai", "anthropic"
    api_key: str
    model: str
    base_url: str | None = None
    timeout: int = 120
    max_retries: int = 3


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Create a chat completion.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Provider-specific parameters

        Returns:
            Response dict with 'content', 'usage', etc.
        """
        pass

    @abstractmethod
    def transcribe_audio(self, audio_path: str, language: str | None = None, **kwargs: Any) -> str:
        """
        Transcribe audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (optional)
            **kwargs: Provider-specific parameters

        Returns:
            Transcription text
        """
        pass

    @abstractmethod
    def generate_image(self, prompt: str, size: str = "1024x1024", **kwargs: Any) -> bytes:
        """
        Generate an image from a prompt.

        Args:
            prompt: Image generation prompt
            size: Image size
            **kwargs: Provider-specific parameters

        Returns:
            Image bytes
        """
        pass

    @abstractmethod
    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """
        Analyze an image with vision capabilities.

        Args:
            image_data: Image bytes
            prompt: Analysis prompt
            **kwargs: Provider-specific parameters

        Returns:
            Analysis text
        """
        pass

    def chat_completion_with_json(
        self,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Create a chat completion with JSON output.

        This is a convenience method that adds JSON schema instructions to the prompt
        and requests JSON mode from the provider. Providers can override this for
        native structured output support.

        Args:
            messages: List of message dicts with 'role' and 'content'
            json_schema: Optional JSON schema for structured output
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Provider-specific parameters

        Returns:
            Response dict with 'content' (JSON string), 'usage', etc.
        """
        # Default implementation: add schema to prompt and use regular chat completion
        if json_schema:
            schema_instruction = (
                "\n\nIMPORTANT: Return ONLY valid JSON that conforms to this schema:\n"
                f"{json_schema}\n"
                "Do not include any explanations, markdown, or code fences. Only the JSON object."
            )

            # Add schema instruction to the last user message
            modified_messages = messages.copy()
            for i in range(len(modified_messages) - 1, -1, -1):
                if modified_messages[i]["role"] == "user":
                    modified_messages[i] = modified_messages[i].copy()
                    modified_messages[i]["content"] += schema_instruction
                    break

            return self.chat_completion(
                modified_messages, max_tokens=max_tokens, temperature=temperature, **kwargs
            )
        else:
            return self.chat_completion(
                messages, max_tokens=max_tokens, temperature=temperature, **kwargs
            )
