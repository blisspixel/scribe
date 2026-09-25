"""
Ollama provider implementation (native API).

Talks to a locally running Ollama server through its **native** ``/api/chat``
endpoint (not the OpenAI-compat shim) so we get full control over the knobs that
matter for running well on real hardware:

- ``options.num_ctx`` - the context window is sized dynamically to the actual
  transcript and capped, so the KV cache never balloons and forces a CPU spill.
  (Some models ship a huge default context, e.g. 262K, which alone is ~28GB of
  KV cache and pushes the model half onto the CPU. Capping it keeps the whole
  model on the GPU, where Ollama places it automatically once it fits.)
- ``format`` = the JSON schema - constrained decoding guarantees schema-valid
  JSON in ``content``. This is also what makes *thinking* models (Gemma 4,
  Qwen3) reliable: without it their JSON can land in the reasoning channel and
  ``content`` comes back empty.

Cross-platform (stdlib ``urllib`` only) and free: every response is tagged
``cost_usd=0.0`` / ``cost_source="local"``.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from scribe.providers.base import AIProvider, ProviderConfig

logger = logging.getLogger(__name__)

# Root of a local Ollama server (the native API lives here, not under /v1).
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# Ollama needs no API key; kept so the factory's key handling stays uniform.
OLLAMA_PLACEHOLDER_KEY = "ollama"

# Context-window sizing. Notes transcripts are small (and long ones are
# segmented upstream), so we never need a huge window. Capping it is what keeps
# big models fully on the GPU instead of spilling KV cache to the CPU.
_DEFAULT_MAX_CTX = 16384
_MIN_CTX = 4096
_CHARS_PER_TOKEN = 3  # conservative estimate for budgeting context
_CTX_MARGIN_TOKENS = 512


def _int(value: Any) -> int:
    """Coerce a usage count to int, tolerating None/odd types."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def estimate_input_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token count for the prompt, for context budgeting."""
    chars = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            chars += len(content)
    return chars // _CHARS_PER_TOKEN


def compute_num_ctx(
    messages: list[dict[str, Any]],
    max_output_tokens: int | None,
    *,
    override: int | None = None,
    max_ctx: int = _DEFAULT_MAX_CTX,
) -> int:
    """
    Size the context window to the actual request, then clamp.

    Large enough to hold the transcript plus the response, rounded up, but never
    larger than ``max_ctx`` - the cap is what prevents the KV cache from forcing
    a CPU spill on big models.
    """
    if override and override > 0:
        return override
    needed = estimate_input_tokens(messages) + (max_output_tokens or 1024) + _CTX_MARGIN_TOKENS
    rounded = ((needed + 1023) // 1024) * 1024
    return max(_MIN_CTX, min(rounded, max_ctx))


class OllamaProvider(AIProvider):
    """Local Ollama provider via the native /api/chat API (free, offline, GPU-aware)."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.base_url = self._normalize_base_url(config.base_url)
        self.max_ctx = int(os.getenv("SCRIBE_OLLAMA_MAX_CTX", str(_DEFAULT_MAX_CTX)))
        # 0 / unset -> auto-size; a positive value pins the context window.
        self.ctx_override = int(os.getenv("SCRIBE_OLLAMA_NUM_CTX", "0"))
        # Optional: pin GPU layers (e.g. 999 to force all layers on GPU).
        raw_num_gpu = os.getenv("SCRIBE_OLLAMA_NUM_GPU")
        self.num_gpu = int(raw_num_gpu) if raw_num_gpu else None
        self.keep_alive = os.getenv("SCRIBE_OLLAMA_KEEP_ALIVE", "5m")

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str:
        """Return the server root, tolerating a .../v1 or trailing-slash URL."""
        base = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return base

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to /api/chat and return the parsed JSON response."""
        url = f"{self.base_url}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - localhost Ollama server
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - localhost Ollama server
                request, timeout=self.config.timeout
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
            raise RuntimeError(
                f"Ollama request failed (model '{self.config.model}', HTTP {exc.code}): {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise RuntimeError(
                f"Ollama request failed (model '{self.config.model}'). Is the Ollama server "
                f"running at {self.base_url}? Original error: {exc}"
            ) from exc

        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected Ollama response for model '{self.config.model}'")
        return parsed

    def _build_options(
        self, messages: list[dict[str, Any]], max_tokens: int | None, temperature: float | None
    ) -> dict[str, Any]:
        """Assemble Ollama generation options, including the GPU-safe context size."""
        options: dict[str, Any] = {
            "num_ctx": compute_num_ctx(
                messages, max_tokens, override=self.ctx_override, max_ctx=self.max_ctx
            ),
        }
        if max_tokens:
            options["num_predict"] = max_tokens
        if temperature is not None:
            options["temperature"] = temperature
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        return options

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a chat completion using a local Ollama model."""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "keep_alive": kwargs.get("keep_alive", self.keep_alive),
            "options": self._build_options(messages, max_tokens, temperature),
        }
        # `format` carries either "json" or a full JSON schema for constrained
        # decoding; callers pass it through kwargs (see chat_completion_with_json).
        if kwargs.get("format") is not None:
            payload["format"] = kwargs["format"]
        # Ollama's top-level switch for reasoning models' thinking phase.
        if kwargs.get("think") is not None:
            payload["think"] = bool(kwargs["think"])

        data = self._post_chat(payload)
        message = data.get("message") or {}
        content = message.get("content", "") if isinstance(message, dict) else ""

        prompt_tokens = _int(data.get("prompt_eval_count"))
        completion_tokens = _int(data.get("eval_count"))
        usage: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": 0.0,
            "cost_source": "local",
        }
        return {
            "content": content or "",
            "usage": usage,
            "model": data.get("model", self.config.model),
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
        Request structured JSON via constrained decoding.

        Passing the schema to Ollama's ``format`` constrains generation to
        schema-valid JSON in ``content`` - reliable even for thinking models
        (Gemma 4, Qwen3) whose JSON would otherwise land in the reasoning channel.
        Falls back to plain JSON mode when no schema is given.
        """
        kwargs["format"] = json_schema if json_schema else "json"
        return self.chat_completion(
            messages, max_tokens=max_tokens, temperature=temperature, **kwargs
        )

    def transcribe_audio(self, audio_path: str, language: str | None = None, **kwargs: Any) -> str:
        """Ollama does not provide audio transcription; use local Whisper or OpenAI."""
        raise NotImplementedError(
            "Ollama does not support audio transcription. Use local Whisper or the OpenAI provider."
        )

    def generate_image(self, prompt: str, size: str = "1024x1024", **kwargs: Any) -> bytes:
        """Ollama does not provide image generation."""
        raise NotImplementedError(
            "Ollama does not support image generation. Use the OpenAI or XAI provider."
        )

    def analyze_image(self, image_data: bytes, prompt: str, **kwargs: Any) -> str:
        """Vision is out of scope for the notes-focused Ollama provider."""
        raise NotImplementedError("Image analysis is not implemented for the Ollama provider.")
