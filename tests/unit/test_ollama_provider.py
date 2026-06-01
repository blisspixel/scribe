"""Unit tests for the local Ollama provider."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scribe.providers.base import ProviderConfig
from scribe.providers.ollama_provider import (
    DEFAULT_OLLAMA_BASE_URL,
    OllamaProvider,
    _int_attr,
)


def _make_provider(model: str = "qwen2.5:14b") -> OllamaProvider:
    config = ProviderConfig(provider_name="ollama", api_key="", model=model)
    return OllamaProvider(config)


def _fake_response(content: str, prompt: int = 10, completion: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        ),
        model="qwen2.5:14b",
    )


class TestIntAttr:
    def test_reads_int(self):
        assert _int_attr(SimpleNamespace(x=7), "x") == 7

    def test_float_coerced(self):
        assert _int_attr(SimpleNamespace(x=7.0), "x") == 7

    def test_missing_is_zero(self):
        assert _int_attr(SimpleNamespace(), "x") == 0

    def test_bool_ignored(self):
        assert _int_attr(SimpleNamespace(x=True), "x") == 0


class TestOllamaDefaults:
    def test_placeholder_key_used_when_empty(self):
        provider = _make_provider()
        # The SDK requires a non-empty key; Ollama ignores it.
        assert provider.client.api_key == "ollama"

    def test_default_base_url(self):
        provider = _make_provider()
        assert str(provider.client.base_url).startswith(DEFAULT_OLLAMA_BASE_URL)


class TestChatCompletion:
    def test_returns_content_usage_and_free_cost(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = _fake_response('{"ok": 1}')

        result = provider.chat_completion([{"role": "user", "content": "hi"}], max_tokens=128)

        assert result["content"] == '{"ok": 1}'
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["total_tokens"] == 15
        # Local inference is always free.
        assert result["usage"]["cost_usd"] == 0.0
        assert result["usage"]["cost_source"] == "local"

    def test_passes_max_tokens_and_temperature(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = _fake_response("hi")

        provider.chat_completion(
            [{"role": "user", "content": "hi"}], max_tokens=64, temperature=0.3
        )

        _, kwargs = provider.client.chat.completions.create.call_args
        assert kwargs["max_tokens"] == 64
        assert kwargs["temperature"] == 0.3

    def test_total_tokens_derived_when_missing(self):
        provider = _make_provider()
        provider.client = MagicMock()
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="x"))],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=6),
            model="m",
        )
        provider.client.chat.completions.create.return_value = resp

        result = provider.chat_completion([{"role": "user", "content": "hi"}])
        assert result["usage"]["total_tokens"] == 10

    def test_wraps_connection_error(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.side_effect = ConnectionError("refused")

        with pytest.raises(RuntimeError, match="Ollama request failed"):
            provider.chat_completion([{"role": "user", "content": "hi"}])


class TestChatCompletionWithJson:
    def test_injects_schema_and_json_mode(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = _fake_response('{"a": 1}')

        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        provider.chat_completion_with_json(
            [{"role": "user", "content": "extract"}], json_schema=schema
        )

        _, kwargs = provider.client.chat.completions.create.call_args
        # Native JSON mode requested.
        assert kwargs["response_format"] == {"type": "json_object"}
        # Schema injected into the user message.
        assert "conforms to this schema" in kwargs["messages"][-1]["content"]

    def test_no_schema_still_requests_json_mode(self):
        provider = _make_provider()
        provider.client = MagicMock()
        provider.client.chat.completions.create.return_value = _fake_response("{}")

        provider.chat_completion_with_json([{"role": "user", "content": "x"}])
        _, kwargs = provider.client.chat.completions.create.call_args
        assert kwargs["response_format"] == {"type": "json_object"}


class TestFactoryIntegration:
    def test_factory_builds_ollama_without_api_key(self):
        from scribe.providers import OllamaProvider as ExportedOllama
        from scribe.providers.factory import get_provider

        # Model supplied -> no server probe; no API key required for local.
        provider = get_provider("notes", provider_name="ollama", model="qwen2.5:14b")
        assert isinstance(provider, ExportedOllama)
        assert provider.config.model == "qwen2.5:14b"

    def test_factory_gives_ollama_generous_timeout(self, monkeypatch):
        from scribe.providers.factory import get_provider

        monkeypatch.delenv("SCRIBE_OLLAMA_TIMEOUT", raising=False)
        provider = get_provider("notes", provider_name="ollama", model="m")
        # Local models need a long default timeout (cold loads / CPU offload).
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
