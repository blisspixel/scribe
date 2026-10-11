"""Capability-gap receipts retain exact primary text through archive and cleanup."""

import json
import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from scribe.cli.main import _place_transcript_in_output_dir
from scribe.core.transcription_review import unavailable_review
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession
from scribe.utils.review_audio import source_hash
from scribe.utils.safe_write import atomic_write
from tests.unit.test_transcription_review import audio_file, transcript


@pytest.fixture
def no_decoding(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Publishing capability-gap evidence must not decode or use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr("faster_whisper.WhisperModel", forbidden)
    decoder = Mock(side_effect=forbidden)
    monkeypatch.setattr("scribe.core.transcription_review.bounded_pass", decoder)
    yield decoder
    decoder.assert_not_called()


@pytest.mark.parametrize("typed_primary", [False, True])
@pytest.mark.parametrize("disposition", ["archive", "music_cleanup"])
def test_capability_gap_snapshot_survives_primary_archive_or_cleanup(
    tmp_path: Path, monkeypatch, no_decoding, typed_primary, disposition
) -> None:
    source = audio_file(tmp_path / "source.wav")
    raw = tmp_path / "workspace" / "primary.txt"
    raw.parent.mkdir()
    payload = "\ufeffExact primary wording: español, 日本語.\r\n\r\n".encode()
    raw.write_bytes(payload)
    config = ScribeConfig(
        _env_file=None,
        output_folder=tmp_path / "archive",
        log_folder=tmp_path / "logs",
        transcription_verification="best-effort",
    )
    session = TranscriptionSession.create("Synthetic")
    session.add_file(source, "source")
    session.add_file(raw, "transcript")
    manifest_writes = []

    def publish_last(path, content, *args, **kwargs):
        if path.name == "review.json":
            governing = json.loads(content)
            snapshot = Path(governing["primary_options"]["primary_text_path"])
            assert snapshot.read_bytes() == payload
            assert all(Path(name).is_file() for name in governing["artifacts"] if name != str(path))
            manifest_writes.append(path)
        return atomic_write(path, content, *args, **kwargs)

    monkeypatch.setattr("scribe.utils.transcript_review.atomic_write", publish_last)
    receipt, artifacts = unavailable_review(
        config, source, transcript() if typed_primary else None, raw, "Capability unavailable"
    )
    for path in artifacts:
        session.add_file(path, "acoustic_review")
    assert len(manifest_writes) == 1 and artifacts[-1] == manifest_writes[0]
    if disposition == "archive":
        final = _place_transcript_in_output_dir(raw, config.output_folder, session)
        assert final.read_bytes() == payload and final == session.transcript_file
    else:
        raw.unlink()  # The music owner removes transient segment transcripts.
    assert not raw.exists() and source.is_file()
    governing = json.loads(artifacts[-1].read_text())
    assert governing == receipt.to_dict()
    snapshot = Path(governing["primary_options"]["primary_text_path"])
    assert snapshot.name == "primary-text.txt" and snapshot.read_bytes() == payload
    assert snapshot in session.files_created and str(snapshot) in governing["artifacts"]
    assert governing["primary_options"]["primary_text_sha256"] == source_hash(snapshot)
    assert governing["primary_options"]["original_primary_text_path"] == str(raw.resolve())
    assert governing["primary_options"]["timed_primary_available"] is typed_primary
    assert governing["source_sha256"] == source_hash(source)
    assert governing["status"] == "partial" and governing["requires_review"] is True


@pytest.mark.parametrize("failure", ["snapshot", "manifest"])
def test_snapshot_or_receipt_failure_retains_original_primary_and_source(
    tmp_path: Path, monkeypatch, no_decoding, failure
) -> None:
    source = audio_file(tmp_path / "source.wav")
    raw = tmp_path / "primary.txt"
    payload = b"Exact retained primary\r\n"
    raw.write_bytes(payload)
    archive = tmp_path / "archive"
    if failure == "snapshot":
        monkeypatch.setattr(
            "scribe.utils.transcript_review.safe_copy", Mock(side_effect=OSError("Disk full"))
        )
    else:

        def fail_manifest(path, content, *args, **kwargs):
            if path.name == "review.json":
                raise OSError("Disk full")
            return atomic_write(path, content, *args, **kwargs)

        monkeypatch.setattr("scribe.utils.transcript_review.atomic_write", fail_manifest)
    receipt, paths = unavailable_review(
        ScribeConfig(_env_file=None, output_folder=archive, log_folder=tmp_path / "logs"),
        source,
        None,
        raw,
        "Capability unavailable",
    )
    assert not paths and not list(archive.rglob("review.json"))
    assert receipt.status == "partial" and receipt.requires_review and "Disk full" in receipt.error
    assert source.is_file() and raw.read_bytes() == payload
    assert receipt.primary_options["original_primary_text_path"] == str(raw.resolve())
    if failure == "manifest":
        assert Path(receipt.primary_options["primary_text_path"]).read_bytes() == payload
