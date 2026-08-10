"""Tests for AIProvider.chat_completion_with_json (the shared default)."""

from typing import Any

from scribe.providers.base import AIProvider, ProviderConfig


class _FakeProvider(AIProvider):
    """Minimal concrete provider that records the messages it is handed."""

    def __init__(self) -> None:
        super().__init__(ProviderConfig(provider_name="fake", api_key="k", model="m"))
        self.seen: list[dict[str, Any]] = []

    def chat_completion(self, messages, max_tokens=None, temperature=None, **kwargs):
        self.seen = messages
        return {"content": "{}", "usage": {}}

    def transcribe_audio(self, audio_path, language=None, **kwargs):
        return ""

    def generate_image(self, prompt, size="1024x1024", **kwargs):
        return b""

    def analyze_image(self, image_data, prompt, **kwargs):
        return ""


def test_schema_instruction_appended_to_text_message() -> None:
    provider = _FakeProvider()
    provider.chat_completion_with_json(
        [{"role": "user", "content": "summarize this"}], json_schema={"type": "object"}
    )
    content = provider.seen[0]["content"]
    assert isinstance(content, str)
    assert content.startswith("summarize this")
    assert "JSON" in content


def test_schema_instruction_appended_to_image_message_without_crash() -> None:
    # Regression: multimodal messages carry a list of parts, and the old code did
    # `list += str`, raising TypeError. The schema must be added as a text part.
    provider = _FakeProvider()
    image_message = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:img"}}]}
    ]
    provider.chat_completion_with_json(image_message, json_schema={"type": "object"})
    content = provider.seen[0]["content"]
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[-1]["type"] == "text"
    assert "JSON" in content[-1]["text"]
