"""Tests for `scribe query` transcript search (cli/query.py)."""

from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.cli.query import search_transcripts
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.transcript_writers import write_json


def _make(tmp_path):
    write_json(
        Transcript(
            segments=[
                TranscriptSegment(0.0, 1.0, "the budget is tight", speaker="SPEAKER_00"),
                TranscriptSegment(1.0, 2.0, "agreed on the plan", speaker="SPEAKER_01"),
            ],
            backend="faster-whisper",
        ),
        tmp_path / "m1.json",
    )


def test_search_by_text(tmp_path):
    _make(tmp_path)
    results = search_transcripts(tmp_path, text="BUDGET")  # case-insensitive
    assert len(results) == 1
    _path, _start, speaker, text = results[0]
    assert speaker == "SPEAKER_00"
    assert "budget" in text


def test_search_by_speaker(tmp_path):
    _make(tmp_path)
    results = search_transcripts(tmp_path, speaker="SPEAKER_01")
    assert len(results) == 1
    assert "plan" in results[0][3]


def test_search_no_match_and_limit(tmp_path):
    _make(tmp_path)
    assert search_transcripts(tmp_path, text="zzz") == []
    assert len(search_transcripts(tmp_path, limit=1)) == 1


def test_search_ignores_foreign_json(tmp_path):
    (tmp_path / "other.json").write_text('{"foo": 1}', encoding="utf-8")
    assert search_transcripts(tmp_path, text="x") == []


def test_query_command_runs(tmp_path):
    _make(tmp_path)
    result = CliRunner().invoke(app, ["query", "plan", "--folder", str(tmp_path)])
    assert result.exit_code == 0
    assert "SPEAKER_01" in result.stdout
