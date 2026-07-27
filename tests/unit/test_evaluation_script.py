"""Tests for the reproducible evaluation manifest command."""

import hashlib
import json

import pytest

import scripts.evaluate_transcripts as evaluation_cli


def test_build_report_records_manifest_provenance_and_micro_metrics(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    content = (
        '{"id":"one","reference":"hello world","hypothesis":"hello word",'
        '"audio_seconds":10,"processing_seconds":2,"metadata":{"backend":"local"}}\n'
        '{"id":"two","reference":"all good","hypothesis":"all good",'
        '"audio_seconds":5,"processing_seconds":1}\n'
    )
    manifest.write_text(content, encoding="utf-8")

    report = evaluation_cli.build_report(manifest, revision="abc123")

    assert report["schema"] == "scribe.evaluation/v1"
    assert report["source_revision"] == "abc123"
    assert report["manifest"]["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert report["results"]["word_error_rate"] == 0.25
    assert report["results"]["real_time_factor"] == 0.2


def test_main_writes_report_atomically(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"id":"one","reference":"hello","hypothesis":"hello",'
        '"audio_seconds":1,"processing_seconds":0.1}\n',
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    assert evaluation_cli.main([str(manifest), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["results"]["word_error_rate"] == 0.0


def test_main_reports_invalid_manifest(tmp_path, capsys) -> None:
    manifest = tmp_path / "bad.jsonl"
    manifest.write_text("not json\n", encoding="utf-8")

    assert evaluation_cli.main([str(manifest)]) == 2
    assert "line 1: invalid JSON" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reference", 42, "reference must be a string"),
        ("audio_seconds", True, "audio_seconds must be a number"),
    ],
)
def test_manifest_rejects_coerced_field_types(tmp_path, field, value, message) -> None:
    manifest = tmp_path / "bad-types.jsonl"
    record = {
        "id": "one",
        "reference": "hello",
        "hypothesis": "hello",
        "audio_seconds": 1,
        "processing_seconds": 0.1,
    }
    record[field] = value
    manifest.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        evaluation_cli.load_manifest(manifest)
