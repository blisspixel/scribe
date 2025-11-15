"""
Anthropic Claude provider implementation.
"""

import logging
import os
from typing import Dict, Any, List, Optional

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .base import AIProvider, ProviderConfig

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """Provider for Anthropic Claude models."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022", config: Optional[ProviderConfig] = None):
        """
        Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use (default: claude-3-5-sonnet-20241022)
            config: Provider configuration (optional)
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package not installed. Install with: pip install anthropic")
        
        # Handle both direct initialization and config-based initialization
        if config:
            super().__init__(config)
            self.api_key = config.api_key
            self.model = config.model
        else:
            self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not self.api_key:
                raise ValueError("Anthropic API key required")
            self.model = model
            # Create a minimal config for parent class
            self.config = ProviderConfig(
                provider_name="anthropic",
                api_key=self.api_key,
                model=self.model
            )
        
        self.client = Anthropic(api_key=self.api_key)
        logger.info(f"Initialized Anthropic provider with model: {self.model}")
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate chat completion using Claude.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional model-specific parameters
        
        Returns:
            Dict with 'content' and 'usage' keys
        """
        # Claude uses 'system' parameter separately from messages
        system_message = None
        user_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                # Claude uses 'user' and 'assistant' roles
                role = "user" if msg["role"] in ["user", "developer"] else "assistant"
                user_messages.append({"role": role, "content": msg["content"]})
        
        # Call Claude API
        params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages
        }
        
        if system_message:
            params["system"] = system_message
        
        response = self.client.messages.create(**params)
        
        # Extract content from response
        content = response.content[0].text if response.content else ""
        
        return {
            "content": content,
            "usage": {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens
            }
        }
    
    def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        **kwargs
    ) -> bytes:
        """
        Claude doesn't support image generation.
        
        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError("Anthropic Claude does not support image generation")
    
    def transcribe_audio(
        self,
        audio_path: str,
        language: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Claude doesn't support audio transcription.
        
        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError("Anthropic Claude does not support audio transcription")
    
    def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        **kwargs
    ) -> str:
        """
        Analyze an image using Claude's vision capabilities.
        
        Args:
            image_data: Image bytes
            prompt: Analysis prompt
            **kwargs: Additional parameters
        
        Returns:
            Analysis text
        """
        import base64
        
        # Convert image to base64
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        # Claude vision API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )
        
        return response.content[0].text if response.content else ""
