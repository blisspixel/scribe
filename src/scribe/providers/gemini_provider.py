"""
Google Gemini provider implementation.

Supports both Gemini 2.5 and Gemini 3 model families with automatic parameter adaptation.

Gemini 3 Features:
- Dynamic thinking with thinking_level (low/high) for reasoning control
- Optimized for temperature=1.0 (changing may degrade performance)
- 1M token context window, 64k output
- Knowledge cutoff: January 2025
- Media resolution control for images/video/PDFs
- Thought signatures for maintaining reasoning context

Gemini 2.5 Features:
- Legacy thinking_budget parameter (0 to disable)
- Flexible temperature tuning
- Flash models for speed, Pro for quality

Model Selection:
- gemini-3-pro-preview: Best for complex reasoning, broad knowledge, multimodal tasks
- gemini-2.5-flash: Fast, cost-effective for simple tasks
- gemini-2.5-pro: Balanced quality and speed
"""

import io
from typing import Any, cast

from scribe.providers.base import AIProvider, ProviderConfig


class GeminiProvider(AIProvider):
    """Google Gemini API provider."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError(
                "google-genai package not installed. " "Install with: pip install google-genai"
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
        """
        Create a chat completion using Gemini.

        Supports both Gemini 2.5 and Gemini 3 models with automatic parameter adaptation.
        """

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

        # Temperature handling
        # Gemini 3: Strongly recommend keeping at default 1.0
        # Gemini 2.5: Can be tuned
        is_gemini_3 = "gemini-3" in self.config.model.lower()

        if temperature is not None:
            if is_gemini_3 and temperature != 1.0:
                # Warn but allow override
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Gemini 3 is optimized for temperature=1.0. "
                    f"Using temperature={temperature} may degrade performance."
                )
            config_params["temperature"] = temperature

        if max_tokens:
            config_params["max_output_tokens"] = max_tokens

        # Thinking configuration for Gemini 3
        # Gemini 3 uses thinking_config with thinking_level: "low", "high" (Pro)
        # or "minimal", "low", "medium", "high" (Flash)
        # Default is "high" for maximum reasoning
        if is_gemini_3:
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
        """Generate an image using Imagen."""
        import logging

        logger = logging.getLogger(__name__)

        # Parse size to aspect ratio
        aspect_ratio = self._size_to_aspect_ratio(size)

        # Determine image size (1K or 2K) - only for Standard/Ultra models
        image_size = "1K"
        if "2048" in size or kwargs.get("quality") == "hd":
            image_size = "2K"

        # Build config
        config_params = {
            "number_of_images": 1,
            "aspect_ratio": aspect_ratio,
        }

        # Get model, but ignore non-Imagen models (e.g., gpt-image-1, dall-e-3)
        model = kwargs.get("model", "imagen-4.0-generate-001")
        if not model.startswith("imagen"):
            logger.warning(f"Non-Imagen model '{model}' specified, using imagen-4.0-generate-001")
            model = "imagen-4.0-generate-001"

        # Only add image_size for Standard/Ultra models
        if "ultra" in model.lower() or "standard" in model.lower():
            config_params["image_size"] = image_size

        # Person generation setting
        # Default to "allow_adult" (Imagen's default) for maximum flexibility
        # Options: "dont_allow", "allow_adult", "allow_all" (not available in EU/UK/CH/MENA)
        person_gen = kwargs.get("person_generation", "allow_adult")
        config_params["person_generation"] = person_gen

        config = cast(Any, self.types.GenerateImagesConfig)(**config_params)

        # Generate image
        response = self.client.models.generate_images(
            model=model,
            prompt=prompt,
            config=config,
        )

        if not response.generated_images:
            raise ValueError("Imagen API returned no images")

        # Get the first image
        generated_image = response.generated_images[0]
        image = generated_image.image
        if image is None:
            raise ValueError("Imagen API returned an empty image payload")

        # Convert PIL Image to bytes
        img_byte_arr = io.BytesIO()
        cast(Any, image).save(img_byte_arr, format="PNG")
        return img_byte_arr.getvalue()

    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """Analyze an image using Gemini vision."""
        from PIL import Image

        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_data))

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
