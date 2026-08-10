"""Unit tests for the local Ollama provider (native /api/chat API)."""

from unittest.mock import MagicMock

import pytest

from scribe.providers.base import ProviderConfig
from scribe.providers.ollama_provider import (
    DEFAULT_OLLAMA_BASE_URL,
    OllamaProvider,
    compute_num_ctx,
    estimate_input_tokens,
)


def _make_provider(model: str = "qwen2.5:14b", base_url: str | None = None) -> OllamaProvider:
    config = ProviderConfig(provider_name="ollama", api_key="", model=model, base_url=base_url)
    return OllamaProvider(config)


def _native_response(content: str, prompt: int = 10, completion: int = 5) -> dict:
    return {
        "model": "qwen2.5:14b",
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": prompt,
        "eval_count": completion,
    }


class TestEstimateInputTokens:
    def test_counts_string_content(self):
        # ~3 chars per token; 30 chars -> 10 tokens.
        assert estimate_input_tokens([{"role": "user", "content": "x" * 30}]) == 10

    def test_ignores_non_string_content(self):
        assert estimate_input_tokens([{"role": "user", "content": [{"k": "v"}]}]) == 0


class TestComputeNumCtx:
    def test_override_wins(self):
        assert compute_num_ctx([], 1000, override=12345) == 12345

    def test_small_input_floors_to_min(self):
        assert compute_num_ctx([{"role": "user", "content": "hi"}], 100) == 4096

    def test_caps_at_max(self):
        big = [{"role": "user", "content": "x" * 1_000_000}]
        assert compute_num_ctx(big, 1000, max_ctx=16384) == 16384

    def test_sizes_between_bounds(self):
        # ~12000 chars -> ~4000 input tokens; +1000 output +512 margin -> ~5512 -> 6144.
        msgs = [{"role": "user", "content": "x" * 12000}]
        ctx = compute_num_ctx(msgs, 1000, max_ctx=16384)
        assert 4096 <= ctx <= 16384
        assert ctx % 1024 == 0


class TestNormalizeBaseUrl:
    def test_default(self):
        assert _make_provider().base_url == DEFAULT_OLLAMA_BASE_URL

    def test_strips_v1_suffix(self):
        assert (
            _make_provider(base_url="http://localhost:11434/v1").base_url == DEFAULT_OLLAMA_BASE_URL
        )

    def test_strips_trailing_slash(self):
        assert _make_provider(base_url="http://box:1234/").base_url == "http://box:1234"


class TestChatCompletion:
    def test_parses_content_usage_and_free_cost(self, monkeypatch):
        monkeypatch.delenv("SCRIBE_OLLAMA_NUM_CTX", raising=False)
        provider = _make_provider()
        provider._post_chat = MagicMock(return_value=_native_response('{"ok": 1}'))

        result = provider.chat_completion([{"role": "user", "content": "hi"}], max_tokens=128)

        assert result["content"] == '{"ok": 1}'
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["total_tokens"] == 15
        assert result["usage"]["cost_usd"] == 0.0
        assert result["usage"]["cost_source"] == "local"

    def test_payload_includes_capped_context_and_predict(self, monkeypatch):
        monkeypatch.delenv("SCRIBE_OLLAMA_NUM_CTX", raising=False)
        monkeypatch.delenv("SCRIBE_OLLAMA_MAX_CTX", raising=False)
        provider = _make_provider()
        captured = {}

        def fake_post(payload):
            captured.update(payload)
            return _native_response("hi")

        provider._post_chat = fake_post
        provider.chat_completion(
            [{"role": "user", "content": "hi"}], max_tokens=64, temperature=0.3
        )

        assert captured["model"] == "qwen2.5:14b"
        assert captured["stream"] is False
        assert captured["options"]["num_ctx"] == 4096  # small prompt -> floor
        assert captured["options"]["num_predict"] == 64
        assert captured["options"]["temperature"] == 0.3

    def test_num_gpu_passed_when_env_set(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_OLLAMA_NUM_GPU", "999")
        provider = _make_provider()
        captured = {}
        provider._post_chat = lambda payload: captured.update(payload) or _native_response("x")
        provider.chat_completion([{"role": "user", "content": "hi"}])
        assert captured["options"]["num_gpu"] == 999

    def test_handles_missing_usage_counts(self):
        provider = _make_provider()
        provider._post_chat = MagicMock(return_value={"model": "m", "message": {"content": "x"}})
        result = provider.chat_completion([{"role": "user", "content": "hi"}])
        assert result["usage"]["total_tokens"] == 0


class TestChatCompletionWithJson:
    def test_schema_passed_as_format(self):
        provider = _make_provider()
        captured = {}
        provider._post_chat = lambda payload: captured.update(payload) or _native_response("{}")
        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}

        provider.chat_completion_with_json([{"role": "user", "content": "x"}], json_schema=schema)
        # Constrained decoding: the schema itself is the format.
        assert captured["format"] == schema

    def test_no_schema_uses_json_mode(self):
        provider = _make_provider()
        captured = {}
        provider._post_chat = lambda payload: captured.update(payload) or _native_response("{}")
        provider.chat_completion_with_json([{"role": "user", "content": "x"}])
        assert captured["format"] == "json"


class TestPostChatErrors:
    def test_connection_error_wrapped(self, monkeypatch):
        import scribe.providers.ollama_provider as mod

        def boom(*args, **kwargs):
            raise ConnectionError("refused")

        monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
        provider = _make_provider()
        with pytest.raises(RuntimeError, match="Is the Ollama server running"):
            provider.chat_completion([{"role": "user", "content": "hi"}])


class TestFactoryIntegration:
    def test_factory_builds_ollama_without_api_key(self):
        from scribe.providers import OllamaProvider as ExportedOllama
        from scribe.providers.factory import get_provider

        provider = get_provider("notes", provider_name="ollama", model="qwen2.5:14b")
        assert isinstance(provider, ExportedOllama)
        assert provider.config.model == "qwen2.5:14b"

    def test_factory_gives_ollama_generous_timeout(self, monkeypatch):
        from scribe.providers.factory import get_provider

        monkeypatch.delenv("SCRIBE_OLLAMA_TIMEOUT", raising=False)
        provider = get_provider("notes", provider_name="ollama", model="m")
        assert provider.config.timeout == 600

    def test_ollama_timeout_env_override(self, monkeypatch):
        from scribe.providers.factory import get_provider

        monkeypatch.setenv("SCRIBE_OLLAMA_TIMEOUT", "1200")
        provider = get_provider("notes", provider_name="ollama", model="m")
        assert provider.config.timeout == 1200


class TestUnsupportedFeatures:
    def test_transcribe_not_implemented(self):
        with pytest.raises(NotImplementedError):
            _make_provider().transcribe_audio("a.wav")

    def test_generate_image_not_implemented(self):
        with pytest.raises(NotImplementedError):
            _make_provider().generate_image("a cat")

    def test_analyze_image_not_implemented(self):
        with pytest.raises(NotImplementedError):
            _make_provider().analyze_image(b"\x00", "describe")
