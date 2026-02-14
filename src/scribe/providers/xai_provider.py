"""
XAI/Grok provider implementation.
"""

import base64
from typing import Any

from openai import OpenAI  # XAI API is OpenAI-compatible

from scribe.providers.base import AIProvider, ProviderConfig


class XAIProvider(AIProvider):
    """XAI/Grok API provider."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        # XAI uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url or "https://api.x.ai/v1",
            timeout=config.timeout,
            max_retries=config.max_retries
        )

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Create a chat completion using Grok."""

        params = {
            "model": self.config.model,
            "messages": messages,
        }

        # Grok 4 Fast uses max_completion_tokens and doesn't support temperature
        if max_tokens:
            params["max_completion_tokens"] = max_tokens

        # Add any additional kwargs
        params.update(kwargs)

        response = self.client.chat.completions.create(**params)

        return {
            "content": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "model": response.model,
        }

    def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        **kwargs
    ) -> str:
        """
        Transcribe audio using Grok.
        
        Note: XAI doesn't currently have a transcription API.
        This is a placeholder for future support.
        """
        raise NotImplementedError(
            "XAI/Grok does not currently support audio transcription. "
            "Use OpenAI provider for transcription."
        )

    def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        **kwargs
    ) -> bytes:
        """Generate an image using Grok."""
        import base64
        import logging

        import requests
        logger = logging.getLogger(__name__)

        # XAI uses grok-2-image-1212 model
        # Default to grok-2-image-1212, ignore any other model passed in kwargs
        model = "grok-2-image-1212"

        # Try b64_json format first (more reliable than URL)
        try:
            logger.debug(f"Attempting XAI image generation with b64_json format using {model}")
            response = self.client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                response_format="b64_json"
            )

            logger.debug(f"XAI response received: {type(response)}, data length: {len(response.data) if response.data else 0}")

            if not response.data or len(response.data) == 0:
                raise ValueError("XAI API returned no image data")

            # Get base64 data
            b64_data = response.data[0].b64_json
            logger.debug(f"b64_json data present: {b64_data is not None}, length: {len(b64_data) if b64_data else 0}")

            if not b64_data:
                raise ValueError("XAI API returned empty base64 data")

            logger.info("Successfully generated image with XAI b64_json format")
            return base64.b64decode(b64_data)

        except Exception as e:
            logger.warning(f"b64_json format failed: {e}, trying URL format")

            # Fallback to URL format
            try:
                logger.debug(f"Attempting XAI image generation with URL format using {model}")
                response = self.client.images.generate(
                    model=model,
                    prompt=prompt,
                    n=1,
                    response_format="url"
                )

                logger.debug(f"XAI URL response received: {type(response)}, data length: {len(response.data) if response.data else 0}")

                if not response.data or len(response.data) == 0:
                    raise ValueError("XAI API returned no image data")

                image_url = response.data[0].url
                logger.debug(f"Image URL: {image_url}")

                if not image_url:
                    # Log the full response for debugging
                    logger.error(f"XAI returned None URL. Response data[0] attributes: {dir(response.data[0])}")
                    raise ValueError("XAI API returned no URL")

                # Download the image
                logger.debug(f"Downloading image from: {image_url}")
                image_response = requests.get(image_url, timeout=30)
                image_response.raise_for_status()
                logger.info("Successfully generated image with XAI URL format")
                return image_response.content

            except Exception as url_error:
                logger.error(f"XAI image generation failed with both formats: {url_error}")
                raise

    def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        **kwargs
    ) -> str:
        """Analyze an image using Grok vision."""

        # Encode image to base64
        image_b64 = base64.b64encode(image_data).decode('utf-8')

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    }
                ]
            }
        ]

        response = self.chat_completion(messages, **kwargs)
        return response["content"]
