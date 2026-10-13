"""
Unit tests for Transcriber orchestration logic.

Tests the core transcription orchestrator including method selection,
fallback logic, audio preparation, and session management.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.requires_ffmpeg

from scribe.core.transcriber import Transcriber
from scribe.exceptions import TranscriptionError, ValidationError
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession


@pytest.fixture
def temp_config(temp_config):
    """These legacy orchestration cases exercise the explicit one-pass workflow."""
    temp_config.transcription_quality = "accurate"
    return temp_config


class TestTranscriberInitialization:
    """Test Transcriber initialization and setup."""

    def test_init_with_config(self, temp_config: ScribeConfig):
        """Test transcriber initializes with config."""
        transcriber = Transcriber(temp_config)

        assert transcriber.config == temp_config
        assert transcriber.gpu_config is not None
        assert transcriber.converter is not None

    def test_init_detects_gpu(self, temp_config: ScribeConfig, mock_gpu):
        """Test transcriber detects GPU on initialization."""
        transcriber = Transcriber(temp_config)

        assert transcriber.gpu_config.has_gpu is True
        assert transcriber.gpu_config.gpu_name == "NVIDIA GeForce RTX 4090"

    def test_init_without_gpu(self, temp_config: ScribeConfig, mock_no_gpu):
        """Test transcriber handles no GPU gracefully."""
        transcriber = Transcriber(temp_config)

        assert transcriber.gpu_config.has_gpu is False
        assert transcriber.gpu_config.gpu_name is None


class TestMethodSelection:
    """Test intelligent method selection logic."""

    def test_choose_method_auto_with_gpu(self, temp_config: ScribeConfig, mock_gpu):
        """Test auto method selects local when GPU available."""
        transcriber = Transcriber(temp_config)

        method = transcriber.choose_method("auto")

        assert method == "local"

    def test_choose_method_auto_without_gpu(self, temp_config: ScribeConfig, mock_no_gpu):
        """$0-first: auto selects local even without a GPU (CPU floor works)."""
        transcriber = Transcriber(temp_config)

        method = transcriber.choose_method("auto")

        # Never silently spends on the paid API; the CPU path is always $0.
        assert method == "local"

    def test_choose_method_explicit_local(self, temp_config: ScribeConfig):
        """Test explicit local method selection."""
        transcriber = Transcriber(temp_config)

        method = transcriber.choose_method("local")

        assert method == "local"

    def test_choose_method_explicit_openai(self, temp_config: ScribeConfig):
        """Test explicit openai method selection."""
        transcriber = Transcriber(temp_config)

        method = transcriber.choose_method("openai")

        assert method == "openai"

    def test_choose_method_explicit_openrouter(self, temp_config: ScribeConfig):
        """OpenRouter is selected only when explicitly requested and configured."""
        temp_config.openrouter_api_key = "sk-or-v1-test-key-1234567890"
        transcriber = Transcriber(temp_config)

        assert transcriber.choose_method("openrouter") == "openrouter"

    def test_choose_method_openrouter_without_key_stays_local(self, temp_config: ScribeConfig):
        """A missing optional key never turns into an attempted network call."""
        temp_config.openrouter_api_key = None
        transcriber = Transcriber(temp_config)

        assert transcriber.choose_method("openrouter") == "local"

    def test_choose_method_auto_prefers_gpu_with_high_vram(
        self, temp_config: ScribeConfig, mock_gpu
    ):
        """Test auto method prefers GPU when VRAM is sufficient."""
        transcriber = Transcriber(temp_config)

        # Mock GPU with high VRAM
        transcriber.gpu_config.gpu_memory_gb = 24.0

        method = transcriber.choose_method("auto")

        assert method == "local"

    def test_choose_method_auto_is_zero_cost_first(self, temp_config: ScribeConfig, mock_no_gpu):
        """$0-first: even with an API key set, auto never auto-selects the paid API."""
        transcriber = Transcriber(temp_config)

        assert temp_config.openai_api_key is not None
        method = transcriber.choose_method("auto")

        # The paid API is opt-in only (--method openai), never a surprise charge.
        assert method == "local"

    def test_choose_method_local_only_forces_local(self, temp_config: ScribeConfig, mock_no_gpu):
        """local_only mode forces local even when a cloud method is requested."""
        temp_config.local_only = True
        temp_config.openrouter_api_key = "sk-or-v1-test-key-1234567890"
        transcriber = Transcriber(temp_config)

        assert transcriber.choose_method("openai") == "local"
        assert transcriber.choose_method("openrouter") == "local"
        assert transcriber.choose_method("auto") == "local"


class TestAudioPreparation:
    """Test audio format preparation for different methods."""

    def test_prepare_audio_for_local_converts_to_wav(
        self, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test audio is converted to WAV for local method when not already WAV."""
        transcriber = Transcriber(temp_config)

        # Create a non-WAV file path
        mp3_file = sample_audio.parent / "test.mp3"
        mp3_file.touch()

        with patch.object(transcriber.converter, "convert_to_wav") as mock_convert:
            mock_convert.return_value = sample_audio.parent / "converted.wav"

            result = transcriber._prepare_audio_for_method(mp3_file, "local")

            mock_convert.assert_called_once_with(mp3_file)
            assert result == sample_audio.parent / "converted.wav"

    def test_prepare_audio_for_local_keeps_wav_files(
        self, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test WAV files are kept as-is for local method."""
        transcriber = Transcriber(temp_config)

        # Create a WAV file path
        wav_file = sample_audio.parent / "test.wav"
        wav_file.touch()

        with patch.object(transcriber.converter, "convert_to_wav") as mock_convert:
            result = transcriber._prepare_audio_for_method(wav_file, "local")

            mock_convert.assert_not_called()
            assert result == wav_file

    def test_prepare_audio_for_openai_keeps_small_files(
        self, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test small files are kept as-is for OpenAI."""
        transcriber = Transcriber(temp_config)

        # Mock small file size
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 10 * 1024 * 1024  # 10 MB

            result = transcriber._prepare_audio_for_method(sample_audio, "openai")

            assert result == sample_audio

    def test_prepare_audio_for_openai_compresses_large_files(
        self, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test large files are compressed to MP3 for OpenAI."""
        transcriber = Transcriber(temp_config)

        # Mock large file size
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 30 * 1024 * 1024  # 30 MB

            with patch.object(transcriber.converter, "convert_to_mp3") as mock_convert:
                mock_convert.return_value = sample_audio.parent / "compressed.mp3"

                result = transcriber._prepare_audio_for_method(sample_audio, "openai")

                mock_convert.assert_called_once()
                assert result == sample_audio.parent / "compressed.mp3"

    def test_prepare_audio_for_openrouter_defers_bounded_chunking(
        self, temp_config: ScribeConfig, sample_audio: Path
    ):
        """OpenRouter receives the source so its backend can normalize exactly once."""
        transcriber = Transcriber(temp_config)
        with (
            patch.object(transcriber.converter, "convert_to_wav") as convert_wav,
            patch.object(transcriber.converter, "convert_to_mp3") as convert_mp3,
        ):
            result = transcriber._prepare_audio_for_method(sample_audio, "openrouter")

        assert result == sample_audio
        convert_wav.assert_not_called()
        convert_mp3.assert_not_called()


class TestTranscriptionMethods:
    """Test actual transcription execution."""

    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_transcribe_local_success(
        self, mock_local_class, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test successful local transcription."""
        transcriber = Transcriber(temp_config)

        # Mock local transcriber
        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        result = transcriber._transcribe_local(sample_audio, None, None, False)

        assert result == sample_audio.parent / "transcript.txt"
        mock_local.transcribe.assert_called_once()

    @patch("scribe.core.transcriber.OpenAITranscriber")
    def test_transcribe_openai_success(
        self, mock_api_class, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test successful OpenAI transcription."""
        transcriber = Transcriber(temp_config)

        # Mock OpenAI transcriber
        mock_api = Mock()
        mock_api.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_api_class.return_value = mock_api

        result = transcriber._transcribe_openai(sample_audio, None, None)

        assert result == sample_audio.parent / "transcript.txt"
        mock_api.transcribe.assert_called_once()

    @patch("scribe.core.transcriber.OpenRouterTranscriber")
    def test_transcribe_openrouter_success(
        self, mock_api_class, temp_config: ScribeConfig, sample_audio: Path
    ):
        """The orchestrator passes only OpenRouter-specific settings to the backend."""
        temp_config.openrouter_api_key = "sk-or-v1-test-key-1234567890"
        temp_config.openrouter_model = "openai/whisper-1"
        transcriber = Transcriber(temp_config)
        backend = Mock()
        backend.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_api_class.return_value = backend

        result = transcriber._transcribe_openrouter(sample_audio, None, None)

        assert result == sample_audio.parent / "transcript.txt"
        mock_api_class.assert_called_once_with(
            api_key="sk-or-v1-test-key-1234567890",
            model="openai/whisper-1",
            language=temp_config.default_language,
            max_attempts=temp_config.max_retries,
            timeout_seconds=temp_config.openrouter_timeout_seconds,
            max_spend_usd=temp_config.openrouter_max_spend_usd,
        )
        backend.transcribe.assert_called_once_with(
            sample_audio,
            cleanup_temp=not temp_config.keep_intermediate_files,
        )

    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_transcribe_local_keeps_full_large_v3_by_default(
        self,
        mock_local_class,
        temp_config: ScribeConfig,
        sample_audio: Path,
        mock_gpu,
    ):
        """Hardware suggestions cannot silently shrink the accurate file model."""
        transcriber = Transcriber(temp_config)
        transcriber.gpu_config.model_size = "medium"
        transcriber.gpu_config.recommendation = "local"

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        transcriber._transcribe_local(sample_audio, None, None, False)

        mock_local_class.assert_called_once()
        assert mock_local_class.call_args.kwargs["model_size"] == "large-v3"
        assert mock_local_class.call_args.kwargs["batch_size"] == 0

    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_six_gb_gpu_session_records_only_the_resolved_model(
        self,
        mock_local_class,
        temp_config: ScribeConfig,
        sample_audio: Path,
    ):
        """A 6 GB profile must not record a model other than the resolver's choice."""
        import json

        from scribe.models.gpu import GPUConfig
        from scribe.utils.model_selection import resolve_local_model

        transcriber = Transcriber(temp_config)
        gpu = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce GTX 1660",
            gpu_memory_gb=6.0,
            cuda_available=True,
        )
        gpu._configure_for_gpu()
        assert gpu.model_size == "medium"
        transcriber.gpu_config = gpu

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local.last_transcript = None
        mock_local_class.return_value = mock_local

        session = TranscriptionSession.create("six-gb")
        transcriber._transcribe_local(sample_audio, session, None, False)

        expected, _adjusted = resolve_local_model(
            temp_config.default_model,
            set(temp_config.model_fields_set),
            temp_config.transcription_quality,
        )
        assert session.model_used is not None
        assert session.model_used.endswith(f"-{expected}")
        assert expected != "medium"
        record = json.dumps(session.to_dict())
        remainder = record.replace(session.model_used, "")
        for identity in (
            "large-v3-turbo",
            "large-v3",
            "large-v2",
            "medium",
            "small",
            "tiny",
            "turbo",
            "base",
        ):
            assert identity not in remainder
        assert session.gpu_info is not None
        assert "model_size" not in session.gpu_info
        assert "smaller model" not in record

    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_transcribe_local_respects_explicit_model_override(
        self,
        mock_local_class,
        temp_config: ScribeConfig,
        sample_audio: Path,
        mock_gpu,
    ):
        """Explicit model selection should win over hardware auto-tuning."""
        temp_config.default_model = "small"
        transcriber = Transcriber(temp_config)
        transcriber.gpu_config.model_size = "medium"
        transcriber.gpu_config.recommendation = "local"

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        transcriber._transcribe_local(sample_audio, None, None, False)

        mock_local_class.assert_called_once()
        assert mock_local_class.call_args.kwargs["model_size"] == "small"


class TestFallbackLogic:
    """Test fallback behavior when primary method fails."""

    @patch.object(Transcriber, "_transcribe_openai")
    @patch.object(Transcriber, "_transcribe_local")
    @patch.object(Transcriber, "_prepare_audio_for_method")
    def test_local_failure_never_falls_back_to_openai(
        self,
        mock_prepare,
        mock_local,
        mock_api,
        temp_config: ScribeConfig,
        sample_audio: Path,
        mock_openai,
    ):
        """A local request never authorizes an audio upload after failure."""
        temp_config.openai_api_key = "sk-test"
        transcriber = Transcriber(temp_config)

        # Mock audio preparation
        mock_prepare.return_value = sample_audio

        # Mock local to fail with TranscriptionError
        mock_local.side_effect = TranscriptionError("CUDA out of memory")

        with pytest.raises(TranscriptionError, match="CUDA out of memory"):
            transcriber.transcribe(sample_audio, method="local")

        mock_local.assert_called_once()
        mock_api.assert_not_called()

    @patch.object(Transcriber, "_transcribe_local")
    @patch.object(Transcriber, "_transcribe_openai")
    @patch.object(Transcriber, "_prepare_audio_for_method")
    def test_fallback_openai_to_local(
        self,
        mock_prepare,
        mock_api,
        mock_local,
        temp_config: ScribeConfig,
        sample_audio: Path,
        mock_gpu,
    ):
        """Test fallback from OpenAI to local when API fails."""
        transcriber = Transcriber(temp_config)

        # Mock audio preparation
        mock_prepare.return_value = sample_audio

        # Mock OpenAI to fail with TranscriptionError
        mock_api.side_effect = TranscriptionError("API Error")

        # Mock local to succeed
        transcript_path = sample_audio.parent / "transcript.txt"
        transcript_path.write_text("Test transcript")
        mock_local.return_value = transcript_path

        # Should fallback to local
        result = transcriber.transcribe(sample_audio, method="openai")

        assert result is not None
        mock_api.assert_called_once()
        mock_local.assert_called_once()

    @patch.object(Transcriber, "_detect_language_for_music", return_value=(None, 0.0))
    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    @patch("scribe.core.transcriber.OpenAITranscriber")
    def test_no_fallback_in_music_mode(
        self,
        mock_api_class,
        mock_local_class,
        _detect_language,
        temp_config: ScribeConfig,
        sample_audio: Path,
    ):
        """Test no fallback attempted in music mode."""
        transcriber = Transcriber(temp_config)

        # Mock local to fail
        mock_local = Mock()
        mock_local.transcribe.side_effect = TranscriptionError("No speech detected")
        mock_local_class.return_value = mock_local

        # Should raise error without fallback
        with pytest.raises(TranscriptionError, match="No speech detected"):
            transcriber.transcribe(sample_audio, method="local", music_mode=True)


class TestSessionManagement:
    """Test session tracking and metadata."""

    def test_transcribe_updates_session(
        self, temp_config: ScribeConfig, sample_audio: Path, mock_openai
    ):
        """Test transcription updates session metadata."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("test_meeting")

        result = transcriber.transcribe(sample_audio, method="openai", session=session)

        assert session.transcript_file == result
        assert session.start_time is not None
        assert session.transcription_method == "openai"

    def test_transcribe_tracks_audio_file(
        self, temp_config: ScribeConfig, sample_audio: Path, mock_openai
    ):
        """Test transcription tracks audio file in session."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("test_meeting")

        transcriber.transcribe(sample_audio, method="openai", session=session)

        # Session should track the audio file
        assert len(session.files_created) > 0


class TestResourceValidation:
    """Test resource limit validation."""

    def test_validates_file_size_limit(self, temp_config: ScribeConfig, sample_audio: Path):
        """Test file size validation."""
        transcriber = Transcriber(temp_config)

        # Mock huge file - patch where it's used, not where it's defined
        with patch("scribe.core.transcriber.validate_audio_file") as mock_validate:
            mock_validate.side_effect = ValidationError("File too large")

            with pytest.raises(ValidationError, match="File too large"):
                transcriber.transcribe(sample_audio, method="auto")

    def test_validates_duration_limit(self, temp_config: ScribeConfig, sample_audio: Path):
        """Test duration validation."""
        transcriber = Transcriber(temp_config)

        # Mock very long audio - patch where it's used, not where it's defined
        with patch("scribe.core.transcriber.validate_audio_file") as mock_validate:
            mock_validate.side_effect = ValidationError("Audio too long")

            with pytest.raises(ValidationError, match="Audio too long"):
                transcriber.transcribe(sample_audio, method="auto")


class TestCleanup:
    """Test intermediate file cleanup."""

    def test_cleanup_intermediate_files(self, temp_config: ScribeConfig, temp_dir: Path):
        """Test cleanup removes intermediate files."""
        transcriber = Transcriber(temp_config)

        # Create fake intermediate files that match delete patterns but NOT keep patterns
        # The keep patterns include *.mp3, *.wav, etc. so we need to use other extensions
        # or patterns that are specifically deleted
        temp_file1 = temp_dir / "audio_temp.tmp"  # matches *_temp.* but not any keep pattern
        temp_file2 = temp_dir / "audio_tmp.dat"  # matches *_tmp.* but not any keep pattern
        temp_file1.write_text("fake")
        temp_file2.write_text("fake")

        transcriber.cleanup_intermediate_files(temp_dir)

        # Intermediate files should be deleted
        assert not temp_file1.exists()
        assert not temp_file2.exists()


class TestErrorHandling:
    """Test error handling and recovery."""

    def test_handles_missing_file(self, temp_config: ScribeConfig):
        """Test error when file doesn't exist."""
        transcriber = Transcriber(temp_config)
        fake_file = Path("/nonexistent/file.wav")

        with pytest.raises((TranscriptionError, ValidationError)):
            transcriber.transcribe(fake_file, method="auto")

    @patch.object(Transcriber, "_transcribe_openai")
    @patch.object(Transcriber, "_transcribe_local")
    @patch.object(Transcriber, "_prepare_audio_for_method")
    def test_handles_all_methods_failing(
        self, mock_prepare, mock_local, mock_api, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test error when all methods fail."""
        temp_config.openai_api_key = "sk-test"
        transcriber = Transcriber(temp_config)

        # Mock audio preparation
        mock_prepare.return_value = sample_audio

        # Mock both methods to fail with TranscriptionError
        mock_local.side_effect = TranscriptionError("GPU Error")
        mock_api.side_effect = TranscriptionError("API Error")

        with pytest.raises(TranscriptionError, match="All transcription methods failed"):
            transcriber.transcribe(sample_audio, method="openai")


class TestCustomVocabulary:
    """Test custom vocabulary support."""

    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_passes_vocabulary_to_local(
        self, mock_local_class, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test custom vocabulary is passed to local transcriber."""
        transcriber = Transcriber(temp_config)

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        # Create mock vocabulary
        from scribe.utils.vocabulary import CustomVocabulary

        vocab = CustomVocabulary(["test", "words"])

        transcriber.transcribe(sample_audio, method="local", custom_vocabulary=vocab)

        # Vocabulary should be passed to transcriber
        call_args = mock_local.transcribe.call_args
        assert call_args is not None


class TestMusicMode:
    """Test music mode transcription."""

    @patch.object(Transcriber, "_detect_language_for_music", return_value=(None, 0.0))
    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_music_mode_enabled(
        self, mock_local_class, _detect_language, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Test music mode is passed to transcriber."""
        transcriber = Transcriber(temp_config)

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        transcriber.transcribe(sample_audio, method="local", music_mode=True)

        # Music mode should be passed
        call_args = mock_local.transcribe.call_args
        assert call_args is not None

    @patch.object(Transcriber, "_detect_language_for_music")
    @patch("scribe.core.transcriber.LocalWhisperTranscriber")
    def test_music_mode_detected_language_is_per_call_only(
        self, mock_local_class, mock_detect_language, temp_config: ScribeConfig, sample_audio: Path
    ):
        """Detected music language should not mutate global config defaults."""
        temp_config.default_language = None
        mock_detect_language.return_value = ("es", 0.91)
        transcriber = Transcriber(temp_config)

        mock_local = Mock()
        mock_local.transcribe.return_value = sample_audio.parent / "transcript.txt"
        mock_local_class.return_value = mock_local

        transcriber.transcribe(sample_audio, method="local", music_mode=True)

        assert temp_config.default_language is None
        assert mock_local_class.call_args is not None
        assert mock_local_class.call_args.kwargs["language"] is None
        assert mock_local.language == "es"
        mock_detect_language.assert_called_once_with(sample_audio, mock_local)


class TestTermNormalization:
    """Glossary-driven term normalization applied after transcription."""

    def test_rewrites_txt_body_and_transcript(self, temp_config: ScribeConfig, tmp_path: Path):
        from scribe.models.transcript import Transcript, TranscriptSegment
        from scribe.utils.vocabulary import CustomVocabulary

        transcriber = Transcriber(temp_config)
        txt = tmp_path / "m_transcription.txt"
        txt.write_text(
            "Meeting: post gray sequel demo\nDate: x\n\n"
            + "─" * 80
            + "\n\nwe use post gray sequel here\n",
            encoding="utf-8",
        )
        transcriber.last_transcript = Transcript(
            segments=[TranscriptSegment(0.0, 1.0, "post gray sequel")], backend="x"
        )
        vocab = CustomVocabulary(["PostgreSQL"], {"PostgreSQL": ["post gray sequel"]})

        transcriber._apply_term_normalization(txt, vocab)

        body = txt.read_text(encoding="utf-8")
        assert "we use PostgreSQL here" in body
        # The header (meeting name) is left untouched.
        assert "Meeting: post gray sequel demo" in body
        assert transcriber.last_transcript.segments[0].text == "PostgreSQL"

    def test_noop_without_aliases_or_vocab(self, temp_config: ScribeConfig, tmp_path: Path):
        from scribe.utils.vocabulary import CustomVocabulary

        transcriber = Transcriber(temp_config)
        txt = tmp_path / "m.txt"
        txt.write_text("hello world", encoding="utf-8")

        transcriber._apply_term_normalization(txt, CustomVocabulary(["Term"]))  # no aliases
        assert txt.read_text(encoding="utf-8") == "hello world"
        transcriber._apply_term_normalization(txt, None)  # no vocab
        assert txt.read_text(encoding="utf-8") == "hello world"
