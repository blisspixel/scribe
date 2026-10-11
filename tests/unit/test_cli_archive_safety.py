"""Archives preserve recordings and distinct artifact sets when placement fails or collides."""

import json
import os
import socket
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from docx import Document
from typer.testing import CliRunner

from scribe.cli.main import _place_transcript_in_output_dir, app
from scribe.core.downloader import DownloadResult, URLDownloader
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils import safe_write


def _write_media(path: Path) -> bytes:
    """Create a small, valid WAV without a model, decoder, or network request."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 1600)
    return path.read_bytes()


@pytest.fixture
def archive_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[Path, str]]:
    """Keep real CLI/config/artifact/session code and replace inference boundaries."""
    archive = tmp_path / "archive"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[output]\nfolder = {json.dumps(str(archive))}\n"
        '[transcription]\nmodel = "tiny"\nmethod = "openai"\n'
        "[features]\ngenerate_notes = true\ngenerate_joke = false\ngenerate_meme = false\n",
        encoding="utf-8",
    )
    for name in os.environ:
        if name.startswith("SCRIBE_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr("scribe.config_file.CONFIG_PATH", config_path)
    monkeypatch.setitem(ScribeConfig.model_config, "env_file", None)
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(tmp_path / "logs"))
    monkeypatch.setenv("SCRIBE_ANIMATIONS", "off")
    monkeypatch.setenv("SCRIBE_KEEP_DOWNLOADS", "false")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.chdir(tmp_path)

    def reject_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Archive regressions must not make network requests")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    texts: dict[Path, str] = {}

    class SyntheticTranscriber:
        last_transcript: Transcript

        def choose_method(self, method: str) -> str:
            # Small media on this mocked provider route needs no FFmpeg dependency.
            assert method == "openai"
            return method

        def transcribe(
            self,
            audio_file: Path,
            *,
            method: str,
            session: TranscriptionSession,
            **_kwargs: object,
        ) -> Path:
            text = texts.get(audio_file, "ArchiveFixture preserves an important recording.")
            self.last_transcript = Transcript(
                segments=[TranscriptSegment(0, 0.1, text)],
                language="en",
                backend="synthetic",
                model="synthetic",
            )
            transcript_path = audio_file.with_name(f"{audio_file.stem}_transcription.txt")
            transcript_path.write_text(
                f"Meeting: {audio_file.stem}\n\n{'─' * 80}\n[00:00:00] {text}\n",
                encoding="utf-8",
            )
            session.add_file(transcript_path, "transcript")
            session.transcription_method = method
            session.model_used = "synthetic"
            return transcript_path

        def cleanup_intermediate_files(self, _folder: Path) -> list[Path]:
            return []

    monkeypatch.setattr(
        "scribe.cli.main.Transcriber", lambda *_args, **_kwargs: SyntheticTranscriber()
    )

    def generate_notes(transcript_path: Path, **_kwargs: object) -> Path:
        notes = transcript_path.with_name(f"{transcript_path.stem}_notes.md")
        notes.write_text(transcript_path.read_text(encoding="utf-8"), encoding="utf-8")
        return notes

    monkeypatch.setattr(
        "scribe.utils.notes_generator.NotesGenerator",
        lambda **_kwargs: SimpleNamespace(generate_notes=generate_notes),
    )
    return archive, texts


@pytest.mark.parametrize("copy_fails", [True, False], ids=["copy-fails", "normal-cleanup"])
def test_url_owned_download_retained_only_when_archiving_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive_cli: tuple[Path, dict[Path, str]],
    copy_fails: bool,
) -> None:
    archive, _texts = archive_cli
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    downloads: list[URLDownloader] = []
    downloaded_bytes: list[bytes] = []

    def download(downloader: URLDownloader, url: str) -> DownloadResult:
        downloads.append(downloader)
        media = downloader.output_dir / "clip.wav"
        downloaded_bytes.append(_write_media(media))
        return DownloadResult(media, "Archive fixture", 0.1, url)

    monkeypatch.setattr(URLDownloader, "download", download)
    if copy_fails:

        def fail_copy(_source: Path, _target: Path) -> None:
            raise OSError("Synthetic archive copy failure")

        monkeypatch.setattr(safe_write, "safe_copy", fail_copy)

    result = CliRunner().invoke(
        app,
        ["url", "https://8.8.8.8/synthetic.wav", "--method", "openai", "--format", "json,md"],
    )
    assert len(downloads) == 1, result.output
    downloader = downloads[0]
    assert downloader.owns_output_dir
    assert downloader.output_dir.parent == tmp_path
    assert downloader.output_dir.name.startswith("scribe_dl_")
    media = downloader.output_dir / "clip.wav"
    source_transcript = downloader.output_dir / "clip_transcription.txt"
    summaries = list(archive.glob("*_session_summary.json"))
    assert len(summaries) == 1, result.output
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    if copy_fails:
        assert result.exit_code == 1, result.output
        assert "Synthetic archive copy failure" in result.output
        assert downloader.output_dir.is_dir()
        assert media.read_bytes() == downloaded_bytes[0]
        assert "ArchiveFixture preserves" in source_transcript.read_text(encoding="utf-8")
        assert "recoverable transcription outputs were retained" in " ".join(result.output.split())
        assert summary["outcome"] == "failed"
        assert summary["transcript_file"] == str(source_transcript)
        assert str(source_transcript) in summary["files_created"]
        assert str(media) not in summary["files_cleaned"]
        assert str(source_transcript) not in summary["files_cleaned"]
        assert not list(archive.glob("clip_transcription*"))
    else:
        assert result.exit_code == 0, result.output
        assert not downloader.output_dir.exists()
        assert "recoverable transcription outputs were retained" not in result.output
        assert summary["outcome"] == "success"
        assert summary["transcript_file"] == str(archive / "clip_transcription.txt")
        assert str(media) in summary["files_cleaned"]
        assert str(source_transcript) not in summary["files_cleaned"]
        assert {
            "source": str(source_transcript),
            "destination": str(archive / source_transcript.name),
        } in summary["files_moved"]
        for suffix in ("txt", "json", "md", "docx"):
            assert (archive / f"clip_transcription.{suffix}").is_file()
        assert (archive / "clip_transcription_notes.md").is_file()


def test_batch_same_named_recordings_keep_both_complete_archives(
    tmp_path: Path, archive_cli: tuple[Path, dict[Path, str]]
) -> None:
    archive, texts = archive_cli
    first = tmp_path / "first" / "clip.wav"
    second = tmp_path / "second" / "clip.wav"
    original_media = {path: _write_media(path) for path in (first, second)}
    texts[first] = "AlphaArchive schedules a roof inspection."
    texts[second] = "BetaArchive approves a plumbing repair."
    runner = CliRunner()
    result = runner.invoke(
        app, ["batch", str(first), str(second), "--method", "openai", "--format", "json,md"]
    )
    assert result.exit_code == 0, result.output
    transcripts = list(archive.glob("clip_transcription*.txt"))
    assert len(transcripts) == 2
    assert len({path.stem for path in transcripts}) == 2
    summaries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in archive.glob("*_session_summary.json")
    ]
    assert len(summaries) == 2
    assert len({summary["session_id"] for summary in summaries}) == 2
    assert {summary["transcript_file"] for summary in summaries} == {
        str(path) for path in transcripts
    }
    for summary in summaries:
        source = Path(summary["source_file"])
        expected = texts[source]
        other = texts[second if source == first else first]
        transcript = Path(summary["transcript_file"])
        assert summary["outcome"] == "success"
        assert transcript.parent == archive
        assert expected in transcript.read_text(encoding="utf-8")
        assert other not in transcript.read_text(encoding="utf-8")
        sidecar = json.loads(transcript.with_suffix(".json").read_text(encoding="utf-8"))
        assert [segment["text"] for segment in sidecar["segments"]] == [expected]
        markdown = transcript.with_suffix(".md").read_text(encoding="utf-8")
        assert expected in markdown
        assert other not in markdown
        docx = transcript.with_suffix(".docx")
        document_text = "\n".join(paragraph.text for paragraph in Document(docx).paragraphs)
        assert expected in document_text
        assert other not in document_text
        notes = transcript.with_name(f"{transcript.stem}_notes.md")
        assert expected in notes.read_text(encoding="utf-8")
        expected_artifacts = {
            transcript.with_suffix(f".{suffix}") for suffix in ("txt", "json", "md", "docx")
        }
        expected_artifacts.add(notes)
        assert expected_artifacts <= {Path(path) for path in summary["files_created"]}
        assert summary["docx_file"] == str(docx)
        assert str(source.with_name("clip_transcription.txt")) not in summary["files_cleaned"]
        assert {
            "source": str(source.with_name("clip_transcription.txt")),
            "destination": str(transcript),
        } in summary["files_moved"]
        assert not list(source.parent.glob("clip_transcription*"))
        assert source.read_bytes() == original_media[source]
        query = runner.invoke(app, ["query", expected.split()[0]])
        assert query.exit_code == 0, query.output
        assert expected in " ".join(query.output.split())
        assert other not in " ".join(query.output.split())
        assert transcript.with_suffix(".json").name in query.output


@pytest.mark.parametrize("sidecar_suffix", [".json", ".docx", "_notes.md"])
def test_sidecar_without_transcript_reserves_its_artifact_stem(
    tmp_path: Path, sidecar_suffix: str
) -> None:
    source = tmp_path / "source" / "clip_transcription.txt"
    source.parent.mkdir()
    source.write_text("A newly transcribed recording.\n", encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    previous = archive / f"clip_transcription{sidecar_suffix}"
    previous.write_bytes(b"previous archive artifact")
    session = TranscriptionSession.create("clip")
    session.add_file(source, "transcript")

    target = _place_transcript_in_output_dir(source, archive, session)

    assert target.stem != source.stem
    assert target.parent == archive
    assert target.read_text(encoding="utf-8") == "A newly transcribed recording.\n"
    assert previous.read_bytes() == b"previous archive artifact"
    assert not source.exists()
    assert not (archive / "clip_transcription.txt").exists()
    assert session.transcript_file == target
    assert session.files_created == [target]
    assert session.files_cleaned == []
    assert session.files_moved == [{"source": str(source), "destination": str(target)}]
    assert set(archive.iterdir()) == {previous, target}


def test_parallel_archive_placements_reserve_distinct_artifact_stems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "archive"
    sources = []
    for name in ("first", "second"):
        source = tmp_path / name / "clip_transcription.txt"
        source.parent.mkdir()
        source.write_text(f"The {name} recording remains distinct.\n", encoding="utf-8")
        sources.append(source)
    both_reserved = Barrier(2)
    real_copy = safe_write.safe_copy

    def copy_after_both_reservations(source: Path, target: Path) -> None:
        both_reserved.wait(timeout=10)
        real_copy(source, target)

    monkeypatch.setattr(safe_write, "safe_copy", copy_after_both_reservations)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_place_transcript_in_output_dir, source, archive, None)
            for source in sources
        ]
        targets = [future.result(timeout=15) for future in futures]

    assert len(set(targets)) == 2
    assert {path.read_text(encoding="utf-8") for path in targets} == {
        "The first recording remains distinct.\n",
        "The second recording remains distinct.\n",
    }
    assert all(not source.exists() for source in sources)
    assert set(archive.iterdir()) == set(targets)
