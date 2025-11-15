"""
Base provider interface for AI services.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""
    
    provider_name: str  # "openai", "xai", "anthropic"
    api_key: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 120
    max_retries: int = 3


class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
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
    def transcribe_audio(
        self,
        audio_path: str,
        language: Optional[str] = None,
        **kwargs
    ) -> str:
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
    def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        **kwargs
    ) -> bytes:
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
    def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        **kwargs
    ) -> str:
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
        messages: List[Dict[str, Any]],
        json_schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
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
                modified_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
        else:
            return self.chat_completion(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
