"""Tests for the structured-output writers (utils/transcript_writers.py)."""

import json

from hypothesis import given
from hypothesis import strategies as st

from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils import transcript_writers as tw


def _sample() -> Transcript:
    return Transcript(
        segments=[
            TranscriptSegment(0.0, 1.5, "Hello there", speaker="SPEAKER_00"),
            TranscriptSegment(1.5, 3.25, "General Kenobi", speaker="SPEAKER_01"),
        ],
        language="en",
        duration=3.25,
        backend="faster-whisper",
        model="large-v3",
    )


def test_clock_formats_vtt_and_srt():
    assert tw._clock(3661.5, millis_sep=".") == "01:01:01.500"
    assert tw._clock(3661.5, millis_sep=",") == "01:01:01,500"
    assert tw._clock(-5.0, millis_sep=".") == "00:00:00.000"


# Bounded well under the 100-hour mark, where the HH field widens past two digits
# and string ordering no longer tracks time. Real transcripts never reach that.
@given(st.floats(min_value=0, max_value=86399, allow_nan=False, allow_infinity=False))
def test_clock_is_wellformed_and_monotonic(seconds):
    a = tw._clock(seconds, millis_sep=".")
    b = tw._clock(seconds + 1.0, millis_sep=".")
    assert len(a) == 12 and a[2] == ":" and a[5] == ":" and a[8] == "."
    assert b >= a  # one second later never sorts earlier


def test_json_round_trips(tmp_path):
    out = tw.write_json(_sample(), tmp_path / "t.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == tw.JSON_SCHEMA
    assert data["backend"] == "faster-whisper"
    assert data["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert len(data["segments"]) == 2
    assert data["segments"][0] == {
        "start": 0.0,
        "end": 1.5,
        "text": "Hello there",
        "speaker": "SPEAKER_00",
        "confidence": None,
    }


def test_vtt_has_header_cues_and_speaker_voice(tmp_path):
    text = tw.write_vtt(_sample(), tmp_path / "t.vtt").read_text(encoding="utf-8")
    assert text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in text
    assert "<v SPEAKER_00>Hello there" in text


def test_srt_is_numbered_with_comma_millis(tmp_path):
    text = tw.write_srt(_sample(), tmp_path / "t.srt").read_text(encoding="utf-8")
    assert text.startswith("1\n")
    assert "00:00:01,500 --> 00:00:03,250" in text
    assert "SPEAKER_01: General Kenobi" in text


def test_markdown_has_frontmatter_and_turns(tmp_path):
    text = tw.write_markdown(_sample(), tmp_path / "t.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "backend: faster-whisper" in text
    assert "speakers: [SPEAKER_00, SPEAKER_01]" in text
    assert "**SPEAKER_00:** Hello there" in text


def test_write_formats_writes_requested_and_skips_unknown(tmp_path):
    txt = tmp_path / "meeting.txt"
    txt.write_text("plain")
    written = tw.write_formats(_sample(), txt, ["json", "vtt", "txt", "bogus"])
    names = sorted(p.name for p in written)
    assert names == ["meeting.json", "meeting.vtt"]  # txt and bogus skipped
    assert all(p.exists() for p in written)
