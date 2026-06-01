"""
Ollama provider implementation.

Talks to a locally running Ollama server through its OpenAI-compatible API
(default ``http://localhost:11434/v1``), so it reuses the ``openai`` SDK exactly
like the XAI provider. This makes local, fully offline note generation a
first-class provider that runs identically on Linux, macOS, and Windows —
Ollama abstracts the GPU (CUDA/Metal/ROCm) for us.

Local inference has no per-token cost, so every response is tagged
``cost_usd=0.0`` / ``cost_source="local"``.
"""

import base64
from typing import Any, cast

from openai import OpenAI  # Ollama exposes an OpenAI-compatible API

from scribe.providers.base import AIProvider, ProviderConfig

# Default endpoint for a local Ollama server's OpenAI-compatible API.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Ollama ignores the API key, but the OpenAI SDK requires a non-empty value.
OLLAMA_PLACEHOLDER_KEY = "ollama"


def _int_attr(obj: Any, name: str) -> int:
    """Read an integer usage field, tolerating missing/non-numeric values."""
    value = getattr(obj, name, None)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


class OllamaProvider(AIProvider):
    """Local Ollama provider (OpenAI-compatible, free, offline)."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = OpenAI(
            api_key=config.api_key or OLLAMA_PLACEHOLDER_KEY,
            base_url=config.base_url or DEFAULT_OLLAMA_BASE_URL,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a chat completion using a local Ollama model."""

        params: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }

        # Ollama's OpenAI-compatible endpoint uses the standard max_tokens field.
        if max_tokens:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature

        params.update(kwargs)

        try:
            response = cast(Any, self.client.chat.completions).create(**params)
        except Exception as exc:  # pragma: no cover - exercised via wrapper message test
            raise RuntimeError(
                f"Ollama request failed (model '{self.config.model}'). Is the Ollama "
                f"server running at {self.config.base_url or DEFAULT_OLLAMA_BASE_URL}? "
                f"Original error: {exc}"
            ) from exc

        usage_obj = getattr(response, "usage", None)
        prompt_tokens = _int_attr(usage_obj, "prompt_tokens")
        completion_tokens = _int_attr(usage_obj, "completion_tokens")
        total_tokens = _int_attr(usage_obj, "total_tokens") or (prompt_tokens + completion_tokens)

        usage: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            # Local inference is free; record it explicitly so cost reporting and
            # the notes eval can treat Ollama as the $0 baseline.
            "cost_usd": 0.0,
            "cost_source": "local",
        }

        return {
            "content": response.choices[0].message.content or "",
            "usage": usage,
            "model": getattr(response, "model", self.config.model),
        }

    def chat_completion_with_json(
        self,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Request JSON output from a local model.

        Combines two reliability levers that local models benefit from:
        Ollama's native JSON mode (``response_format={"type": "json_object"}``)
        plus the schema injected into the prompt (the base-class behaviour).
        """
        modified_messages = messages
        if json_schema:
            schema_instruction = (
                "\n\nIMPORTANT: Return ONLY valid JSON that conforms to this schema:\n"
                f"{json_schema}\n"
                "Do not include any explanations, markdown, or code fences. Only the JSON object."
            )
            modified_messages = [dict(m) for m in messages]
            for i in range(len(modified_messages) - 1, -1, -1):
                if modified_messages[i]["role"] == "user":
                    modified_messages[i]["content"] += schema_instruction
                    break

        kwargs.setdefault("response_format", {"type": "json_object"})
        return self.chat_completion(
            modified_messages, max_tokens=max_tokens, temperature=temperature, **kwargs
        )

    def transcribe_audio(self, audio_path: str, language: str | None = None, **kwargs: Any) -> str:
        """Ollama does not provide audio transcription; use the OpenAI/local Whisper paths."""
        raise NotImplementedError(
            "Ollama does not support audio transcription. Use local Whisper or the OpenAI provider."
        )

    def generate_image(self, prompt: str, size: str = "1024x1024", **kwargs: Any) -> bytes:
        """Ollama does not provide image generation."""
        raise NotImplementedError(
            "Ollama does not support image generation. Use the OpenAI or XAI provider."
        )

    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """Analyze an image with a multimodal Ollama model (e.g. a vision-capable Gemma/Llama)."""
        image_b64 = base64.b64encode(image_data).decode("utf-8")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ]
        response = self.chat_completion(messages, **kwargs)
        return str(response["content"])
