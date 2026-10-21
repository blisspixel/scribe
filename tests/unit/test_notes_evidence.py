"""Source-linked next-step evidence."""

import json
from pathlib import Path

import pytest

from scribe.utils.notes_evidence import (
    EvidenceError,
    assert_same_source,
    load_snapshot,
    merge_step_objects,
    resolve_next_steps,
    sidecar_document,
)


def _transcript(tmp_path: Path, segments: list[dict]) -> Path:
    path = tmp_path / "meeting.json"
    path.write_text(
        json.dumps(
            {
                "schema": "scribe.transcript/v1",
                "language": "en",
                "metadata": {},
                "segments": segments,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_valid_quote_resolves_and_uses_source_time(tmp_path: Path):
    path = _transcript(
        tmp_path,
        [
            {
                "start": 12.5,
                "end": 18.0,
                "text": "Alex will send the report on Friday.",
                "speaker": "A",
            }
        ],
    )
    snapshot = load_snapshot(path)
    steps = resolve_next_steps(
        snapshot,
        [
            {
                "text": "Alex sends the report on Friday.",
                "source_id": "s0001",
                "quote": "send the report",
            }
        ],
    )
    assert steps[0].status == "referenced"
    assert steps[0].start == 12.5
    assert steps[0].end == 18.0
    document = sidecar_document(snapshot, steps)
    assert "owner" not in document["steps"][0]
    assert document["steps"][0]["source_ids"] == ["s0001"]


def test_invented_id_fabricated_quote_and_malformed_item_are_unverified(tmp_path: Path):
    path = _transcript(tmp_path, [{"start": 0, "end": 1, "text": "We paused the migration."}])
    snapshot = load_snapshot(path)
    steps = resolve_next_steps(
        snapshot,
        [
            {"text": "Continue.", "source_id": "s9999", "quote": "We paused"},
            {"text": "Continue.", "source_id": "s0001", "quote": "ship it tomorrow"},
            {"text": "no quote"},
            "plain string",
        ],
    )
    assert [step.status for step in steps] == ["unverified"] * 4
    assert sidecar_document(snapshot, steps)["omitted_unverified"] == 4


def test_empty_actions_and_withdrawn_proposal(tmp_path: Path):
    path = _transcript(tmp_path, [{"start": 1, "end": 2, "text": "The proposal was withdrawn."}])
    snapshot = load_snapshot(path)
    assert resolve_next_steps(snapshot, []) == []
    steps = resolve_next_steps(
        snapshot,
        [
            {
                "text": "The migration proposal was withdrawn.",
                "source_id": "s0001",
                "quote": "proposal was withdrawn",
            }
        ],
    )
    assert steps[0].status == "not-a-commitment"
    assert "deadline" not in sidecar_document(snapshot, steps)["steps"][0]


def test_chunk_merge_keeps_both_spans(tmp_path: Path):
    path = _transcript(
        tmp_path,
        [
            {"start": 1, "end": 2, "text": "Send the notes."},
            {"start": 9, "end": 10, "text": "Send the notes after lunch."},
        ],
    )
    snapshot = load_snapshot(path)
    merged = merge_step_objects(
        [
            [{"text": "Send the notes.", "source_id": "s0001", "quote": "Send the notes."}],
            [{"text": "Send the notes.", "source_id": "s0002", "quote": "Send the notes"}],
        ]
    )
    steps = resolve_next_steps(snapshot, merged)
    assert steps[0].status == "referenced"
    assert steps[0].source_ids == ("s0001", "s0002")


def test_text_snapshot_has_no_audio_timing(tmp_path: Path):
    path = tmp_path / "reading.txt"
    path.write_text("Line one stays.\n\nLine three is later.\n", encoding="utf-8")
    snapshot = load_snapshot(path)
    assert snapshot.kind == "text"
    assert snapshot.timing_available is False
    assert [span.source_id for span in snapshot.spans] == ["l0001", "l0003"]
    steps = resolve_next_steps(
        snapshot,
        [{"text": "Keep line one.", "source_id": "l0001", "quote": "Line one stays."}],
    )
    assert steps[0].status == "referenced"
    assert steps[0].start is None


def test_review_warning_is_not_labeled_verified(tmp_path: Path):
    path = _transcript(
        tmp_path,
        [
            {
                "start": 3,
                "end": 4,
                "text": "Ship the patch.",
                "review_warning": "acoustic disagreement",
            }
        ],
    )
    steps = resolve_next_steps(
        load_snapshot(path),
        [{"text": "Ship the patch.", "source_id": "s0001", "quote": "Ship the patch."}],
    )
    assert steps[0].status == "source-review"
    assert steps[0].review_warning == "acoustic disagreement"


def test_relocated_copy_matches_and_changed_bytes_do_not(tmp_path: Path):
    path = _transcript(tmp_path, [{"start": 0, "end": 1, "text": "Original words."}])
    snapshot = load_snapshot(path)
    moved = tmp_path / "archive" / "other-name.json"
    moved.parent.mkdir()
    moved.write_bytes(path.read_bytes())
    assert_same_source(snapshot, moved)
    moved.write_text(
        moved.read_text(encoding="utf-8").replace("Original", "Different"), encoding="utf-8"
    )
    with pytest.raises(EvidenceError):
        assert_same_source(snapshot, moved)


def test_missing_source_fails_visibly(tmp_path: Path):
    path = _transcript(tmp_path, [{"start": 0, "end": 1, "text": "Here."}])
    snapshot = load_snapshot(path)
    path.unlink()
    with pytest.raises(EvidenceError, match="missing"):
        assert_same_source(snapshot, path)
