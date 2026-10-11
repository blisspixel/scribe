"""Synthetic transcript and loopback transport regressions for note generation."""

import io
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rich.console import Console
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.cli.notes_progress import notes_progress
from scribe.providers.base import ProviderConfig
from scribe.providers.ollama_provider import OllamaProvider
from scribe.utils.notes_content import (
    BREAKDOWN_KEYS,
    BREAKDOWN_SCHEMA,
    breakdown_prompt,
    format_notes,
    refinement_prompt,
    summary_prompt,
    summary_prose,
    transcript_body,
)
from scribe.utils.notes_generator import NotesGenerationError, NotesGenerator, ValidationError

STORY = (
    "This is a fictional reading. The traveler explains to the narrator that a cube has "
    "length, breadth, and thickness, and that a real object must also exist in time. "
    "The narrator listens as the traveler compares movement in space with movement "
    "through time. Their conversation concerns the dimensions of imagined objects. "
    "The traveler draws a line on a piece of paper and asks whether it could exist "
    "without thickness. The narrator considers the question before the traveler "
    "returns to his explanation. The story describes a conversation about geometry "
    "and the possibility of time travel. No workplace project or business meeting "
    "is taking place in this fictional scene."
)
SUMMARY = (
    "In this fictional reading, the traveler argues that objects exist in time as well "
    "as in three spatial dimensions. The narrator considers his explanation of geometry "
    "and the possibility of time travel."
)
EMPTY_BREAKDOWN = {key: [] for key in BREAKDOWN_KEYS}


@pytest.fixture
def fake_ollama(monkeypatch):
    requests = []
    responses = [SUMMARY, json.dumps(EMPTY_BREAKDOWN), json.dumps(EMPTY_BREAKDOWN)]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/chat"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            index = len(requests) - 1
            response = {
                "model": "synthetic-notes-model",
                "message": {"content": responses[index]},
                "prompt_eval_count": 100,
                "eval_count": 25,
            }
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = server.server_address
    original_connect = socket.socket.connect

    def local_connect(sock, target):
        if target != address:
            raise AssertionError(f"Unexpected connection outside fake Ollama: {target}")
        return original_connect(sock, target)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    # Avoid a workstation's proxy configuration changing this loopback test.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    try:
        yield f"http://127.0.0.1:{address[1]}", requests, responses
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_http_summary_is_prose_other_phases_keep_schema(fake_ollama, tmp_path):
    base_url, requests, _ = fake_ollama
    transcript = tmp_path / "fiction.txt"
    transcript.write_text(
        f"Meeting: fiction\nDate: October 10, 2026\nDuration: 2 minutes\n\n{STORY}"
    )
    phases = []
    provider = OllamaProvider(
        ProviderConfig("ollama", "local-placeholder", "synthetic-notes-model", base_url=base_url)
    )
    with patch("scribe.providers.get_provider", return_value=provider):
        generator = NotesGenerator(provider_name="ollama", model="synthetic-notes-model")
    output = generator.generate_notes(transcript, progress_callback=phases.append)
    markdown = output.read_text()
    assert len(requests) == 3
    assert "format" not in requests[0]
    assert requests[1]["format"] == BREAKDOWN_SCHEMA
    assert requests[2]["format"] == BREAKDOWN_SCHEMA
    assert all(request["stream"] is False for request in requests)
    assert phases == ["Summary 1/3", "Breakdown 2/3", "Polish 3/3"]
    assert markdown.startswith("# Transcript Notes: fiction\n")
    assert SUMMARY in markdown
    assert "October 10, 2026" not in markdown
    assert "## Current State" not in markdown
    assert "## Future State" not in markdown
    assert "## Next Steps" not in markdown
    assert '"Meeting Purpose' not in markdown
    for request in requests:
        prompt = request["messages"][0]["content"]
        assert "Do not assume that a meeting took place" in prompt
        assert "October 10, 2026" not in prompt
        assert "The traveler draws a line" in prompt


def test_real_http_accidental_summary_json_is_rendered_as_prose(fake_ollama, tmp_path):
    base_url, requests, responses = fake_ollama
    responses[0] = json.dumps({"overview": SUMMARY, "details": ["The scene concerns geometry."]})
    transcript = tmp_path / "story.txt"
    transcript.write_text(STORY)
    provider = OllamaProvider(
        ProviderConfig("ollama", "local-placeholder", "synthetic-notes-model", base_url=base_url)
    )
    with patch("scribe.providers.get_provider", return_value=provider):
        output = NotesGenerator(provider_name="ollama").generate_notes(transcript)
    markdown = output.read_text()
    assert SUMMARY + "\n\nThe scene concerns geometry." in markdown
    assert '"overview"' not in markdown
    assert "format" not in requests[0]


@pytest.mark.parametrize(
    ("explicit", "env", "configured", "expected"),
    [
        (None, None, None, "ollama"),
        (None, None, "xai", "xai"),
        (None, "openai", "xai", "openai"),
        ("anthropic", "openai", "xai", "anthropic"),
        ("ollama", "openai", "xai", "ollama"),
    ],
)
def test_notes_provider_precedence(monkeypatch, explicit, env, configured, expected):
    monkeypatch.delenv("SCRIBE_NOTES_PROVIDER", raising=False)
    if env:
        monkeypatch.setenv("SCRIBE_NOTES_PROVIDER", env)
    provider = Mock(
        config=SimpleNamespace(provider_name=expected, model="chosen-model", api_key="test")
    )
    with (
        patch("scribe.providers.factory._config_provider", return_value=configured),
        patch("scribe.providers.get_provider", return_value=provider) as factory,
    ):
        NotesGenerator(provider_name=explicit, model="chosen-model")
    assert factory.call_args.kwargs["provider_name"] == expected
    assert factory.call_args.kwargs["model"] == "chosen-model"


def test_legacy_explicit_key_does_not_change_provider_selection():
    provider = Mock(
        config=SimpleNamespace(provider_name="openai", model="chosen-model", api_key="test")
    )
    with patch("scribe.providers.get_provider", return_value=provider) as factory:
        NotesGenerator(api_key="explicit-legacy-key", model="chosen-model")
    assert factory.call_args.kwargs["provider_name"] is None
    assert factory.call_args.kwargs["api_key"] == "explicit-legacy-key"


def test_unhealthy_local_notes_never_fall_back_to_cloud(monkeypatch):
    from scribe.providers.factory import get_provider

    monkeypatch.setenv("SCRIBE_ENABLE_HEALTH_CHECKS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-cloud-key")
    monitor = Mock()
    monitor.check_provider_health.return_value = Mock(is_healthy=False, error_message="offline")
    with (
        patch("scribe.providers.health.get_health_monitor", return_value=monitor),
        patch("scribe.providers.factory.OpenAIProvider") as cloud,
        patch("scribe.providers.factory._get_fallback_provider") as fallback,
    ):
        provider = get_provider("notes", provider_name="ollama", model="chosen-model")
    assert isinstance(provider, OllamaProvider)
    fallback.assert_not_called()
    cloud.assert_not_called()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Plain prose.", "Plain prose."),
        (
            '{"summary": "First.", "details": ["Second.", {"extra": "Third."}]}',
            "First.\n\nSecond.\n\nThird.",
        ),
        ('```json\n{"summary": "First."}\n```', "First."),
        ('["First.", "Second.", 3, null]', "First.\n\nSecond."),
        ('"First."', "First."),
        ("{malformed prose}", "{malformed prose}"),
    ],
)
def test_summary_prose(value, expected):
    assert summary_prose(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "  ", "{}", "[]", "null", "42", "false", '{"empty": null}', "```\n```", "```json\n```"],
)
def test_empty_or_nontext_json_summary_fails(value):
    with pytest.raises(ValueError, match="no prose"):
        summary_prose(value)


@given(
    st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz .", min_size=1).filter(str.strip),
        min_size=1,
        max_size=8,
    )
)
def test_accidental_json_preserves_all_text_values(paragraphs):
    expected = "\n\n".join(paragraph.strip() for paragraph in paragraphs)
    assert summary_prose(json.dumps({"summary": paragraphs})) == expected


def test_header_date_is_not_evidence_but_spoken_date_is_retained():
    text = "Meeting: story\nDate: October 10, 2026\nDuration: 2 minutes\n\nOn May 3, the narrator arrived."
    body = transcript_body(text)
    assert "October" not in body
    assert "On May 3" in body
    assert transcript_body("On May 3, the narrator arrived.") == "On May 3, the narrator arrived."


def test_grounding_rules_apply_to_every_prompt():
    for prompt in (
        summary_prompt(STORY),
        breakdown_prompt(STORY, SUMMARY),
        refinement_prompt(STORY, EMPTY_BREAKDOWN),
    ):
        assert "Use only facts explicitly supported" in prompt
        assert "recording date" in prompt
        assert "Fictional events" in prompt
    assert "empty array" in breakdown_prompt(STORY, SUMMARY)
    assert "Remove unsupported claims" in refinement_prompt(STORY, EMPTY_BREAKDOWN)


def test_empty_sections_are_omitted_and_explicit_actions_are_kept():
    breakdown = {**EMPTY_BREAKDOWN, "next_steps": ["Alex will send the review on May 3."]}
    markdown = format_notes(SUMMARY, breakdown, {})
    assert "## Next Steps\n\n- Alex will send the review on May 3." in markdown
    assert "## Current State" not in markdown
    assert "## Drivers" not in markdown
    assert "## Blockers" not in markdown
    assert "## Future State" not in markdown


def test_invalid_refinement_items_preserve_original_notes():
    generator = NotesGenerator.__new__(NotesGenerator)
    malformed = {**EMPTY_BREAKDOWN, "next_steps": [3]}
    with patch.object(generator, "_call_gpt5_api", return_value=(json.dumps(malformed), {})):
        assert generator._refine_and_polish(STORY, EMPTY_BREAKDOWN) == EMPTY_BREAKDOWN
    with pytest.raises(ValidationError, match="list of strings"):
        generator._validate_breakdown_keys(malformed)


def test_empty_json_summary_is_a_visible_failure():
    generator = NotesGenerator.__new__(NotesGenerator)
    with patch.object(generator, "_call_gpt5_api", return_value=("{}", {})):
        with pytest.raises(NotesGenerationError, match="no prose"):
            generator._generate_detailed_summary(STORY)


def test_redirected_progress_emits_one_elapsed_line_per_phase(monkeypatch):
    output = io.StringIO()
    console = Console(file=output, force_terminal=False)
    clock = iter([100.0, 100.0, 112.0, 120.0])
    monkeypatch.setattr("scribe.cli.notes_progress.time.monotonic", lambda: next(clock))
    with notes_progress(console) as report:
        report("Summary 1/3")
        report("Breakdown 2/3")
        report("Polish 3/3")
    lines = output.getvalue().splitlines()
    assert lines == [
        "Notes: Summary 1/3 | elapsed 0s",
        "Notes: Breakdown 2/3 | elapsed 12s",
        "Notes: Polish 3/3 | elapsed 20s",
    ]


def test_terminal_progress_uses_one_task_with_elapsed_column():
    console = Console(file=io.StringIO(), force_terminal=True)
    with patch("scribe.cli.notes_progress.Progress") as progress_class:
        progress = progress_class.return_value.__enter__.return_value
        with notes_progress(console) as report:
            report("Summary 1/3")
            report("Breakdown 2/3")
            report("Polish 3/3")
    progress.add_task.assert_called_once_with("Preparing notes", total=None)
    assert progress.update.call_count == 3
    assert any(
        type(column).__name__ == "TimeElapsedColumn" for column in progress_class.call_args.args
    )
    assert progress_class.call_args.kwargs["refresh_per_second"] == 4


def test_notes_cli_connects_phase_display_to_generator(tmp_path: Path):
    transcript = tmp_path / "fiction.txt"
    transcript.write_text(STORY)
    output = tmp_path / "fiction_notes.md"
    output.write_text(SUMMARY)

    def generate(path, destination, *, progress_callback):
        assert path == transcript
        for phase in ("Summary 1/3", "Breakdown 2/3", "Polish 3/3"):
            progress_callback(phase)
        return output

    with patch("scribe.utils.notes_generator.NotesGenerator") as generator:
        generator.return_value.generate_notes.side_effect = generate
        result = CliRunner().invoke(app, ["notes", str(transcript)], color=False)
    assert result.exit_code == 0, result.output
    assert result.output.count("Summary 1/3") == 1
    assert result.output.count("Breakdown 2/3") == 1
    assert result.output.count("Polish 3/3") == 1
    assert "elapsed" in result.output


@pytest.mark.parametrize("command", ["notes", "transcribe", "url", "record", "batch"])
def test_help_describes_notes_as_local_by_default(command):
    result = CliRunner().invoke(app, [command, "--help"], env={"COLUMNS": "240"}, color=False)
    assert result.exit_code == 0
    normalized = " ".join(result.output.split())
    assert "local Ollama" in normalized
    assert "cloud requires explicit" in normalized or "Cloud use requires" in normalized
    assert "notes this run (paid text API)" not in normalized


def test_notes_help_preserves_example_paragraphs_and_lines():
    result = CliRunner().invoke(app, ["notes", "--help"], env={"COLUMNS": "240"}, color=False)
    assert result.exit_code == 0
    lines = [line.strip() for line in result.output.splitlines()]
    assert "Examples:" in lines
    assert "scribe notes transcript.txt" in lines
    assert "scribe notes transcript.txt --output ./notes/reading.md" in lines
    assert "Explicit cloud use (paid, sends transcript):" in lines
    assert "scribe notes transcript.txt --provider openai" in lines
    assert "\b" not in result.output
