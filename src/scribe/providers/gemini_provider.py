"""
Google Gemini provider implementation.

Current text default is ``gemini-3.8-flash``. The flagship is ``gemini-4-argon``
and the budget model is ``gemini-3.5-flash-lite``. Image generation defaults to
``gemini-nano-banana-2.1``. Retired ids fail with the replacement name.
"""

from __future__ import annotations

import io
from typing import Any, cast

from scribe.providers.base import AIProvider, ProviderConfig

RETIRED_GEMINI_MODELS = {
    "gemini-3.5-flash": "gemini-3.8-flash",
    "gemini-3.6-flash": "gemini-3.8-flash",
    "gemini-3.7-flash": "gemini-3.8-flash",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.5-pro": "gemini-4-argon",
    "gemini-2.0-flash": "gemini-3.8-flash",
}


def reject_retired_gemini_model(model: str) -> None:
    """Fail closed when a configured id is a retired model or a silent alias."""
    replacement = RETIRED_GEMINI_MODELS.get(model.strip())
    if replacement is not None:
        raise ValueError(f"{model} is retired and is not used. Use {replacement} instead.")


class GeminiProvider(AIProvider):
    """Google Gemini API provider."""

    def __init__(self, config: ProviderConfig) -> None:
        reject_retired_gemini_model(config.model)
        super().__init__(config)

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError(
                'Gemini support is not installed. Install Scribe with its "providers" extra.'
            )

        self.genai: Any = genai
        self.types: Any = types
        self.client: Any = genai.Client(api_key=config.api_key)

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a chat completion using the configured Gemini model."""

        # Convert OpenAI-style messages to Gemini format
        # Gemini uses system_instruction separately and contents for user/assistant
        system_instruction: str | None = None
        contents: list[str] = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                system_instruction = content
            elif role == "user":
                contents.append(content)
            elif role == "assistant":
                # Gemini doesn't have explicit assistant role in contents
                # We'll add it as a user message with context
                contents.append(f"[Previous response: {content}]")

        # Build config
        config_params: dict[str, Any] = {}

        if system_instruction:
            config_params["system_instruction"] = system_instruction

        # Gemini 3 and later reject deprecated sampling parameters. Known Gemini 2
        # ids are retired before this method runs; an unrecognized Gemini 2 id
        # still accepts explicit temperature tuning.
        model_name = self.config.model.lower()
        legacy_sampling = "gemini-2" in model_name or "gemini-1" in model_name

        if temperature is not None and legacy_sampling:
            config_params["temperature"] = temperature

        if max_tokens:
            config_params["max_output_tokens"] = max_tokens

        # Thinking configuration for Gemini 3
        # Gemini 3 uses thinking_config with thinking_level: "low", "high" (Pro)
        # or "minimal", "low", "medium", "high" (Flash)
        # Default is "high" for maximum reasoning
        if not legacy_sampling:
            thinking_level = kwargs.get("thinking_level", "high")
            if kwargs.get("disable_thinking", False):
                # Use "low" for Pro, "minimal" for Flash
                thinking_level = "minimal" if "flash" in self.config.model.lower() else "low"

            config_params["thinking_config"] = cast(Any, self.types.ThinkingConfig)(
                thinking_level=thinking_level
            )
        else:
            # Gemini 2.5: Use thinking_budget (0 to disable)
            if kwargs.get("disable_thinking", False):
                config_params["thinking_config"] = cast(Any, self.types.ThinkingConfig)(
                    thinking_budget=0
                )

        # Create config object if we have params
        config = None
        if config_params:
            config = cast(Any, self.types.GenerateContentConfig)(**config_params)

        # Generate content
        response = self.client.models.generate_content(
            model=self.config.model,
            contents=contents,
            config=config,
        )

        # Extract text from response
        # Gemini may return None for response.text if there's a safety filter or error
        response_text = response.text

        # Check for safety ratings or blocked content
        if response_text is None:
            import logging

            logger = logging.getLogger(__name__)

            # Check if response was blocked
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "finish_reason"):
                    logger.warning(f"Gemini response blocked: {candidate.finish_reason}")
                if hasattr(candidate, "safety_ratings"):
                    logger.warning(f"Safety ratings: {candidate.safety_ratings}")

            # Return empty string instead of None
            response_text = ""

        # Extract usage info (Gemini provides token counts)
        usage = {
            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
            "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
        }

        return {
            "content": response_text,
            "usage": usage,
            "model": self.config.model,
        }

    def transcribe_audio(self, audio_path: str, language: str | None = None, **kwargs: Any) -> str:
        """
        Transcribe audio using Gemini.

        Note: Gemini supports audio understanding but not dedicated transcription.
        This is a placeholder for future support.
        """
        raise NotImplementedError(
            "Gemini does not currently support dedicated audio transcription. "
            "Use OpenAI provider for transcription."
        )

    def generate_image(self, prompt: str, size: str = "1024x1024", **kwargs: Any) -> bytes:
        """Generate an image using a current Gemini image model."""

        # Parse size to aspect ratio
        aspect_ratio = self._size_to_aspect_ratio(size)

        # Determine image size for the Gemini response format.
        image_size = "1K"
        if "2048" in size or kwargs.get("quality") == "hd":
            image_size = "2K"

        requested_model = str(kwargs.get("model", "gemini-nano-banana-2.1"))
        reject_retired_gemini_model(requested_model)
        model = (
            requested_model if requested_model.startswith("gemini-") else "gemini-nano-banana-2.1"
        )
        config = cast(Any, self.types.GenerateContentConfig)(
            response_modalities=["IMAGE"],
            response_format={"image": {"aspect_ratio": aspect_ratio, "image_size": image_size}},
        )

        response = self.client.models.generate_content(
            model=model,
            contents=[prompt],
            config=config,
        )

        for part in getattr(response, "parts", []) or []:
            as_image = getattr(part, "as_image", None)
            image = as_image() if callable(as_image) else None
            if image is not None:
                img_byte_arr = io.BytesIO()
                cast(Any, image).save(img_byte_arr, format="PNG")
                return img_byte_arr.getvalue()
        raise ValueError("Gemini image API returned no images")

    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """Analyze an image using Gemini vision."""
        from scribe.utils.images import open_provider_image

        image = open_provider_image(image_data)

        # Generate content with image and text
        response = cast(Any, self.client.models).generate_content(
            model=self.config.model,
            contents=[image, prompt],
        )

        return str(response.text or "")

    def _size_to_aspect_ratio(self, size: str) -> str:
        """
        Convert size string to Imagen aspect ratio.

        Supported aspect ratios: "1:1", "3:4", "4:3", "9:16", "16:9"
        """
        size_map = {
            "1024x1024": "1:1",
            "1024x1536": "3:4",  # Portrait
            "1536x1024": "4:3",  # Landscape
            "1024x1792": "9:16",  # Tall portrait
            "1792x1024": "16:9",  # Wide landscape
            # 2K variants
            "2048x2048": "1:1",
            "2048x3072": "3:4",
            "3072x2048": "4:3",
            "2048x3584": "9:16",
            "3584x2048": "16:9",
        }

        return size_map.get(size, "1:1")  # Default to square
