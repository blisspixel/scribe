"""Unit tests for Ollama model discovery and VRAM-aware selection."""

import json
from io import BytesIO

from scribe.utils import ollama_models
from scribe.utils.ollama_models import (
    DEFAULT_OLLAMA_MODEL,
    OllamaModel,
    _tags_url,
    list_installed_models,
    select_ollama_model,
)


class _FakeCtx:
    """Minimal context manager standing in for urlopen's response."""

    def __init__(self, body: BytesIO):
        self._body = body

    def __enter__(self) -> BytesIO:
        return self._body

    def __exit__(self, *args: object) -> bool:
        return False


class TestOllamaModel:
    def test_general_model(self):
        assert OllamaModel("qwen3:30b", 17.0).is_general is True

    def test_coder_not_general(self):
        assert OllamaModel("qwen3-coder:30b", 17.0).is_general is False

    def test_uncensored_not_general(self):
        assert OllamaModel("llama2-uncensored:latest", 3.6).is_general is False

    def test_embed_not_general(self):
        assert OllamaModel("nomic-embed-text", 0.3).is_general is False


class TestTagsUrl:
    def test_default(self):
        assert _tags_url(None) == "http://localhost:11434/api/tags"

    def test_strips_v1_suffix(self):
        assert _tags_url("http://localhost:11434/v1") == "http://localhost:11434/api/tags"

    def test_custom_host(self):
        assert _tags_url("http://box:1234") == "http://box:1234/api/tags"


class TestSelectOllamaModel:
    def _installed(self) -> list[OllamaModel]:
        return [
            OllamaModel("llama3:70b", 37.2),
            OllamaModel("qwen3-coder:30b", 17.3),
            OllamaModel("qwen3:30b", 17.3),
            OllamaModel("gemma4:26b", 16.8),
            OllamaModel("qwen2.5:14b", 8.4),
            OllamaModel("mistral-openorca:7b", 3.8),
        ]

    def test_override_wins(self):
        assert select_ollama_model(self._installed(), 24.0, override="custom:1b") == "custom:1b"

    def test_empty_returns_default(self):
        assert select_ollama_model([], 24.0) == DEFAULT_OLLAMA_MODEL

    def test_picks_largest_general_that_fits_24gb(self):
        # 24 * 0.92 = 22.08 ceiling; coder excluded; llama3:70b too big.
        assert select_ollama_model(self._installed(), 24.0) == "qwen3:30b"

    def test_12gb_picks_smaller_model(self):
        # 12 * 0.92 = 11.04 ceiling; only qwen2.5:14b (8.4) and mistral (3.8) fit.
        assert select_ollama_model(self._installed(), 12.0) == "qwen2.5:14b"

    def test_8gb_picks_smallest_when_only_tiny_fits(self):
        # 8 * 0.92 = 7.36; only mistral 3.8 fits.
        assert select_ollama_model(self._installed(), 8.0) == "mistral-openorca:7b"

    def test_none_fit_returns_smallest(self):
        models = [OllamaModel("big:70b", 40.0), OllamaModel("medium:30b", 20.0)]
        assert select_ollama_model(models, 8.0) == "medium:30b"

    def test_unknown_budget_uses_cap(self):
        # budget 0 -> conservative: largest general under UNKNOWN_BUDGET_CAP_GB (9.0).
        assert select_ollama_model(self._installed(), 0.0) == "qwen2.5:14b"

    def test_specialized_only_falls_back_to_specialized(self):
        models = [OllamaModel("qwen3-coder:30b", 17.3), OllamaModel("starcoder:3b", 2.0)]
        # No general models; with a budget, largest that fits is chosen.
        assert select_ollama_model(models, 24.0) == "qwen3-coder:30b"


class TestListInstalledModels:
    def _patch_urlopen(self, monkeypatch, payload: dict | None, raise_exc: Exception | None = None):
        def fake_urlopen(url, timeout=5.0):
            if raise_exc is not None:
                raise raise_exc
            return _FakeCtx(BytesIO(json.dumps(payload).encode("utf-8")))

        monkeypatch.setattr(ollama_models.urllib.request, "urlopen", fake_urlopen)

    def test_parses_and_sorts_by_size_desc(self, monkeypatch):
        payload = {
            "models": [
                {"name": "small:7b", "size": 4 * 1024**3},
                {"name": "big:30b", "size": 17 * 1024**3},
            ]
        }
        self._patch_urlopen(monkeypatch, payload)
        models = list_installed_models()
        assert [m.name for m in models] == ["big:30b", "small:7b"]
        assert round(models[0].size_gb) == 17

    def test_skips_malformed_entries(self, monkeypatch):
        payload = {"models": [{"name": "ok:7b", "size": 1024**3}, {"size": 5}, {"name": "x"}]}
        self._patch_urlopen(monkeypatch, payload)
        models = list_installed_models()
        assert [m.name for m in models] == ["ok:7b"]

    def test_unreachable_returns_empty(self, monkeypatch):
        self._patch_urlopen(monkeypatch, None, raise_exc=ConnectionError("refused"))
        assert list_installed_models() == []
