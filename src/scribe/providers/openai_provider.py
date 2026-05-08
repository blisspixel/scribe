"""
OpenAI provider implementation.
"""

import base64
import urllib.request
from typing import Any, cast

from openai import OpenAI

from scribe.providers.base import AIProvider, ProviderConfig


class OpenAIProvider(AIProvider):
    """OpenAI API provider."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
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
        """Create a chat completion using OpenAI."""

        params: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }

        # Handle GPT-5 vs GPT-4 parameter differences
        if "gpt-5" in self.config.model.lower():
            if max_tokens:
                params["max_completion_tokens"] = max_tokens
            # GPT-5 doesn't support custom temperature
        else:
            if max_tokens:
                params["max_tokens"] = max_tokens
            if temperature is not None:
                params["temperature"] = temperature

        # Add any additional kwargs
        params.update(kwargs)

        response = cast(Any, self.client.chat.completions).create(**params)

        return {
            "content": response.choices[0].message.content or "",
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "model": response.model,
        }

    def transcribe_audio(self, audio_path: str, language: str | None = None, **kwargs: Any) -> str:
        """Transcribe audio using OpenAI Whisper."""

        with open(audio_path, "rb") as audio_file:
            params: dict[str, Any] = {
                "model": "whisper-1",
                "file": audio_file,
            }

            if language:
                params["language"] = language

            params.update(kwargs)

            transcript = cast(Any, self.client.audio.transcriptions).create(**params)
            return str(getattr(transcript, "text", ""))

    def generate_image(self, prompt: str, size: str = "1024x1024", **kwargs: Any) -> bytes:
        """Generate an image using GPT Image 1 (or DALL-E as fallback)."""
        import base64

        # Use gpt-image-1 by default (best text rendering)
        # Falls back to dall-e-3 if model is explicitly specified
        model = kwargs.get("model", "gpt-image-1")

        # gpt-image-1 uses different quality values than DALL-E
        quality = kwargs.get("quality", "standard")
        if model == "gpt-image-1":
            # gpt-image-1 uses: low, medium, high, auto
            if quality == "hd":
                quality = "high"
            elif quality == "standard":
                quality = "auto"
        else:
            # dall-e-3 uses: standard, hd
            if quality in ["low", "medium"]:
                quality = "standard"
            elif quality == "high":
                quality = "hd"

        response = self.client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )

        # gpt-image-1 returns base64, dall-e returns URL
        data = response.data or []
        if not data:
            raise ValueError("OpenAI image generation returned no data")

        first_image = data[0]
        b64_json = getattr(first_image, "b64_json", None)
        if b64_json:
            return base64.b64decode(b64_json)
        else:
            # Download from URL (dall-e-3)
            image_url = getattr(first_image, "url", None)
            if not image_url:
                raise ValueError("OpenAI image generation returned no image URL")
            try:
                import requests  # Optional dependency

                image_response = requests.get(image_url)
                image_response.raise_for_status()
                return image_response.content
            except ImportError:
                with urllib.request.urlopen(image_url) as resp:
                    return bytes(resp.read())

    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """Analyze an image using GPT-4 Vision."""

        # Encode image to base64
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
