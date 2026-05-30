"""
Unit tests for provider health monitoring.
"""

import sys
from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from scribe.providers.health import HealthStatus, ProviderHealthMonitor


class TestProviderHealthMonitor:
    """Test suite for ProviderHealthMonitor."""

    def test_init(self):
        """Test health monitor initialization."""
        monitor = ProviderHealthMonitor(check_interval_seconds=60)

        assert monitor.check_interval == timedelta(seconds=60)
        assert monitor.health_status == {}
        assert monitor.max_consecutive_failures == 3

    def test_health_status_dataclass(self):
        """Test HealthStatus dataclass."""
        status = HealthStatus(
            provider_name="test",
            is_healthy=True,
            last_check=datetime.now(),
            response_time_ms=100.0,
            consecutive_failures=0,
        )

        assert status.provider_name == "test"
        assert status.is_healthy
        assert status.response_time_ms == 100.0
        assert status.consecutive_failures == 0

    def test_check_unknown_provider(self):
        """Test health check with unknown provider."""
        monitor = ProviderHealthMonitor()

        status = monitor.check_provider_health("unknown", "test-key")

        assert not status.is_healthy
        assert "Unknown provider" in status.error_message

    def test_consecutive_failures_tracking(self):
        """Test that consecutive failures are tracked."""
        monitor = ProviderHealthMonitor()

        # Mock the check method to always fail
        with patch.object(monitor, "_check_openai", side_effect=Exception("Error")):
            # First failure
            status1 = monitor.check_provider_health("openai", "test-key", force=True)
            assert status1.consecutive_failures == 1

            # Second failure
            status2 = monitor.check_provider_health("openai", "test-key", force=True)
            assert status2.consecutive_failures == 2

    def test_cached_health_status(self):
        """Test that health status is cached."""
        monitor = ProviderHealthMonitor(check_interval_seconds=300)

        # Mock successful check
        with patch.object(monitor, "_check_openai"):
            # First check
            status1 = monitor.check_provider_health("openai", "test-key")
            first_check_time = status1.last_check

            # Second check (should use cache)
            status2 = monitor.check_provider_health("openai", "test-key")

            # Should be the same cached status
            assert status2.last_check == first_check_time

    def test_force_health_check_bypasses_cache(self):
        """Test that force flag bypasses cache."""
        monitor = ProviderHealthMonitor(check_interval_seconds=300)

        call_count = 0

        def mock_check(api_key):
            nonlocal call_count
            call_count += 1

        with patch.object(monitor, "_check_openai", side_effect=mock_check):
            # First check
            monitor.check_provider_health("openai", "test-key")

            # Force second check
            monitor.check_provider_health("openai", "test-key", force=True)

            # Should have called twice
            assert call_count == 2

    def test_get_healthy_providers_filters_by_feature(self):
        """Test that get_healthy_providers filters by feature support."""
        monitor = ProviderHealthMonitor()

        # Mock all checks to succeed
        with patch.object(monitor, "_check_openai"), patch.object(monitor, "_check_xai"):
            api_keys = {
                "openai": "key1",
                "xai": "key2",
            }

            # Transcription only supports OpenAI
            healthy = monitor.get_healthy_providers("transcribe", api_keys)

            assert "openai" in healthy
            assert "xai" not in healthy  # XAI doesn't support transcription

    def test_get_healthy_providers_excludes_unhealthy(self):
        """Test that unhealthy providers are excluded."""
        monitor = ProviderHealthMonitor()

        # OpenAI succeeds, XAI fails
        with (
            patch.object(monitor, "_check_openai"),
            patch.object(monitor, "_check_xai", side_effect=Exception("Error")),
        ):
            api_keys = {
                "openai": "key1",
                "xai": "key2",
            }

            healthy = monitor.get_healthy_providers("joke", api_keys)

            assert "openai" in healthy
            assert "xai" not in healthy

    def test_max_consecutive_failures_threshold(self):
        """Test that providers are marked unavailable after max failures."""
        monitor = ProviderHealthMonitor()
        monitor.max_consecutive_failures = 2

        # Mock to always fail
        with patch.object(monitor, "_check_openai", side_effect=Exception("Error")):
            api_keys = {"openai": "key1"}

            # First failure
            monitor.check_provider_health("openai", "key1", force=True)
            healthy = monitor.get_healthy_providers("joke", api_keys)
            assert "openai" not in healthy  # Excluded because unhealthy

            # Second failure (reaches threshold)
            monitor.check_provider_health("openai", "key1", force=True)
            healthy = monitor.get_healthy_providers("joke", api_keys)
            assert "openai" not in healthy  # Still excluded

    def test_check_openai_success_and_empty_response(self):
        monitor = ProviderHealthMonitor()
        create = patch("scribe.providers.factory._get_default_model", return_value="gpt-test")

        class FakeOpenAI:
            def __init__(self, *, api_key, timeout, base_url=None):
                assert api_key == "key"
                assert timeout == 10
                assert base_url is None
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **kwargs: SimpleNamespace(choices=[kwargs["model"]])
                    )
                )

        with create, patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeOpenAI)}):
            monitor._check_openai("key")

        class EmptyOpenAI(FakeOpenAI):
            def __init__(self, *, api_key, timeout, base_url=None):
                super().__init__(api_key=api_key, timeout=timeout, base_url=base_url)

                def create_empty(**_kwargs):
                    return SimpleNamespace(choices=[])

                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create_empty))

        with create, patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=EmptyOpenAI)}):
            with pytest.raises(ValueError, match="No response from OpenAI"):
                monitor._check_openai("key")

    def test_check_xai_success(self):
        monitor = ProviderHealthMonitor()

        class FakeOpenAI:
            def __init__(self, *, api_key, timeout, base_url=None):
                assert api_key == "key"
                assert timeout == 10
                assert base_url == "https://api.x.ai/v1"
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **kwargs: SimpleNamespace(choices=[kwargs["model"]])
                    )
                )

        with (
            patch("scribe.providers.factory._get_default_model", return_value="grok-test"),
            patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeOpenAI)}),
        ):
            monitor._check_xai("key")

    def test_check_anthropic_import_and_success_paths(self):
        monitor = ProviderHealthMonitor()

        class FakeAnthropicClient:
            def __init__(self, *, api_key, timeout):
                assert api_key == "key"
                assert timeout == 10
                self.messages = SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(content=[kwargs["model"]])
                )

        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic package not installed"):
                monitor._check_anthropic("key")

        with (
            patch("scribe.providers.factory._get_default_model", return_value="claude-test"),
            patch.dict(sys.modules, {"anthropic": SimpleNamespace(Anthropic=FakeAnthropicClient)}),
        ):
            monitor._check_anthropic("key")

    def test_check_gemini_import_and_success_paths(self):
        monitor = ProviderHealthMonitor()

        with patch.dict(
            sys.modules, {"google": None, "google.genai": None, "google.genai.types": None}
        ):
            with pytest.raises(ImportError, match="google-genai package not installed"):
                monitor._check_gemini("key")

        google_module = ModuleType("google")
        genai_module = ModuleType("google.genai")
        types_module = ModuleType("google.genai.types")
        types_module.ThinkingConfig = lambda **kwargs: {"thinking": kwargs}
        types_module.GenerateContentConfig = lambda **kwargs: {"config": kwargs}

        class FakeClient:
            def __init__(self, *, api_key):
                assert api_key == "key"
                self.models = SimpleNamespace(
                    generate_content=lambda **kwargs: SimpleNamespace(text=f"ok:{kwargs['model']}")
                )

        genai_module.Client = FakeClient
        genai_module.types = types_module
        google_module.genai = genai_module

        with (
            patch("scribe.providers.factory._get_default_model", return_value="gemini-test"),
            patch.dict(
                sys.modules,
                {
                    "google": google_module,
                    "google.genai": genai_module,
                    "google.genai.types": types_module,
                },
            ),
        ):
            monitor._check_gemini("key")

    def test_get_health_monitor_returns_global_singleton(self):
        from scribe.providers.health import get_health_monitor

        assert get_health_monitor() is get_health_monitor()
