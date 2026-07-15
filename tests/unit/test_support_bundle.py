import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.utils import support_bundle

_REDACTED = "[" + "REDACTED]"


def test_get_system_info_includes_gpu_details() -> None:
    mock_torch = MagicMock()
    mock_torch.__spec__ = Mock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.device_count.return_value = 1
    mock_torch.cuda.get_device_name.return_value = "RTX Test"
    mock_torch.version.cuda = "12.4"
    mock_props = Mock(total_memory=24 * 1024**3, major=8, minor=9)
    mock_torch.cuda.get_device_properties.return_value = mock_props

    with patch.dict("sys.modules", {"torch": mock_torch}):
        info = support_bundle.get_system_info()

    assert info["gpu"]["cuda_available"] is True
    assert info["gpu"]["cuda_version"] == "12.4"
    assert info["gpu"]["devices"][0]["name"] == "RTX Test"


def test_get_system_info_handles_missing_torch() -> None:
    import builtins

    original_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "torch":
            raise ImportError("missing torch")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        info = support_bundle.get_system_info()

    assert info["gpu"] == {"available": False, "reason": "PyTorch not installed"}


def test_get_environment_config_fully_redacts_api_key() -> None:
    with patch.dict(
        "os.environ",
        {
            "SCRIBE_OUTPUT_FOLDER": "C:\\output",
            "SCRIBE_DEFAULT_MODEL": "large-v3",
            "OPENAI_API_KEY": "sk-test-1234567890abcd",
        },
        clear=True,
    ):
        config = support_bundle.get_environment_config()

    assert config["SCRIBE_OUTPUT_FOLDER"] == "C:\\output"
    assert config["SCRIBE_DEFAULT_MODEL"] == "large-v3"
    assert config["OPENAI_API_KEY"] == "[CONFIGURED]"
    assert "sk-test-1234567890abcd" not in str(config)


def test_get_environment_config_fully_redacts_short_api_key() -> None:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-short"}, clear=True):
        config = support_bundle.get_environment_config()

    assert config["OPENAI_API_KEY"] == "[CONFIGURED]"
    assert "sk-short" not in str(config)


def test_recursive_sanitizer_removes_nested_paths_and_credentials() -> None:
    home = Path.home()
    configured_secret = "-".join(("configured", "secret", "123"))
    value = {
        "diagnostics": {
            "details": [
                str(home / "private" / "meeting.wav"),
                "Authorization: Bearer bearer-token-123456",
                "api_key=sk-inline-secret-123456",
            ],
            "token": "nested-token-123456",
        }
    }

    with patch.dict("os.environ", {"SERVICE_PASSWORD": configured_secret}, clear=True):
        value["diagnostics"]["details"].append(configured_secret)
        sanitized = support_bundle._sanitize_for_sharing(value)

    serialized = json.dumps(sanitized)
    assert str(home) not in serialized
    assert home.name not in serialized
    assert configured_secret not in serialized
    assert "bearer-token-123456" not in serialized
    assert "sk-inline-secret-123456" not in serialized
    assert "nested-token-123456" not in serialized
    assert sanitized["diagnostics"]["token"] == _REDACTED


def test_recursive_sanitizer_handles_camel_case_basic_auth_and_quoted_values() -> None:
    first_value = "-".join(("camel", "credential", "123456"))
    second_value = "".join(("QmFzaWM", "xMjM0NTY="))
    third_value = "-".join(("quoted", "credential", "123456"))
    value = {
        "apiKey": first_value,
        "authHeader": f"Basic {second_value}",
        "nested": {"clientSecret": third_value},
        "message": (
            f'Authorization: Basic {second_value}; password="{third_value}"; '
            f"token='{first_value}'"
        ),
    }

    sanitized = support_bundle._sanitize_for_sharing(value)
    serialized = json.dumps(sanitized)

    assert first_value not in serialized
    assert second_value not in serialized
    assert third_value not in serialized
    assert sanitized["apiKey"] == _REDACTED
    assert sanitized["authHeader"] == _REDACTED
    assert sanitized["nested"]["clientSecret"] == _REDACTED


def test_get_diagnostics_results_summarizes_statuses() -> None:
    fake_results = [
        SimpleNamespace(
            name="GPU",
            status="pass",
            message="OK",
            details={"gpu": True},
            fix_suggestion=None,
        ),
        SimpleNamespace(
            name="API",
            status="warn",
            message="Missing key",
            details=None,
            fix_suggestion="Set OPENAI_API_KEY",
        ),
        SimpleNamespace(
            name="OBS",
            status="fail",
            message="Offline",
            details=None,
            fix_suggestion="Start OBS",
        ),
    ]

    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = fake_results

    with patch("scribe.utils.support_bundle.SystemDiagnostics", return_value=diagnostics):
        result = support_bundle.get_diagnostics_results()

    assert result["summary"] == {"pass": 1, "warn": 1, "fail": 1}
    assert result["checks"][2]["name"] == "OBS"


def _write_session_summary(
    path: Path,
    *,
    session_id: str,
    success: bool,
    error_message: str | None = None,
    log_file: Path | None = None,
    outcome: str | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "meeting_name": "Private Board Meeting",
                "start_time": "2026-07-15T12:00:00",
                "end_time": "2026-07-15T12:01:00",
                "success": success,
                **({"outcome": outcome} if outcome is not None else {}),
                "error_message": error_message,
                "transcription_method": "local",
                "model_used": "large-v3",
                "source_file": str(path.parent / "private-recording.wav"),
                "transcript_file": str(path.parent / "private-transcript.txt") if success else None,
                "log_file": str(log_file) if log_file else None,
                "files_created": [str(path.parent / "private-transcript.txt")] if success else [],
                "files_cleaned": [],
            }
        ),
        encoding="utf-8",
    )


def test_get_run_history_summary_reads_durable_sessions_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "older_session_summary.json"
    newer = tmp_path / "newer_session_summary.json"
    older_id = "session_20260715_120000_deadbeef"
    newer_id = "session_20260715_120001_feedface"
    _write_session_summary(older, session_id=older_id, success=True)
    _write_session_summary(
        newer,
        session_id=newer_id,
        success=False,
        error_message="backend failed",
    )
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    summary = support_bundle.get_run_history_summary(max_runs=5, output_dir=tmp_path)

    assert summary["total_runs"] == 2
    assert [run["session_id"] for run in summary["recent_runs"]] == [
        newer_id,
        older_id,
    ]
    assert summary["failed_runs"][0]["error_message"] == "backend failed"
    serialized = json.dumps(summary)
    assert "Private Board Meeting" not in serialized
    assert "private-recording.wav" not in serialized
    assert "private-transcript.txt" not in serialized


def test_run_history_preserves_precise_terminal_outcomes(tmp_path: Path) -> None:
    cases = [
        ("success", True),
        ("instrumental", True),
        ("partial", False),
        ("failed", False),
    ]
    for index, (outcome, success) in enumerate(cases):
        path = tmp_path / f"{outcome}_session_summary.json"
        _write_session_summary(
            path,
            session_id=f"session_20260715_12000{index}_deadbee{index}",
            success=success,
            error_message="incomplete" if not success else None,
            outcome=outcome,
        )
        os.utime(path, (index + 1, index + 1))

    history = support_bundle.get_run_history_summary(max_runs=10, output_dir=tmp_path)

    assert {run["outcome"] for run in history["recent_runs"]} == {
        "success",
        "instrumental",
        "partial",
        "failed",
    }
    assert [run["outcome"] for run in history["failed_runs"]] == ["failed"]
    assert [run["outcome"] for run in history["partial_runs"]] == ["partial"]
    assert [run["outcome"] for run in history["instrumental_runs"]] == ["instrumental"]
    assert history["summary"] == {
        "total": 4,
        "recent_count": 4,
        "failed_count": 1,
        "partial_count": 1,
        "instrumental_count": 1,
    }


def test_shareable_session_hashes_legacy_ids_and_removes_local_error_paths() -> None:
    private_path = Path.home() / "Private Board" / "secret meeting.wav"
    record = support_bundle._shareable_session_record(
        {
            "session_id": "session_legacy_private_board_20260715",
            "success": False,
            "error_message": f"Could not open {private_path}",
        }
    )

    serialized = json.dumps(record)
    assert record["session_id"].startswith("legacy_session_")
    assert "legacy_private_board" not in serialized
    assert "Private Board" not in serialized
    assert "secret meeting.wav" not in serialized
    assert record["error_message"] == "Could not open [LOCAL_PATH]"


def test_get_run_history_summary_skips_unsafe_or_invalid_files(tmp_path: Path, monkeypatch) -> None:
    valid = tmp_path / "valid_session_summary.json"
    malformed = tmp_path / "malformed_session_summary.json"
    oversized = tmp_path / "oversized_session_summary.json"
    valid_id = "session_20260715_120002_cafebabe"
    _write_session_summary(valid, session_id=valid_id, success=True)
    malformed.write_text("{not json", encoding="utf-8")
    size_limit = valid.stat().st_size
    oversized.write_text("x" * (size_limit + 1), encoding="utf-8")
    monkeypatch.setattr(support_bundle, "_MAX_SUMMARY_BYTES", size_limit)

    summary = support_bundle.get_run_history_summary(max_runs=5, output_dir=tmp_path)

    assert [run["session_id"] for run in summary["recent_runs"]] == [valid_id]
    assert summary["skipped_count"] == 2


def test_get_run_history_summary_rechecks_size_on_open(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "grown_session_summary.json"
    path.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(support_bundle, "_MAX_SUMMARY_BYTES", 50)
    monkeypatch.setattr(
        support_bundle,
        "_discover_local_files",
        lambda *_args: ([(path.stat().st_mtime, 1, path)], 0, False),
    )

    summary = support_bundle.get_run_history_summary(max_runs=5, output_dir=tmp_path)

    assert summary["recent_runs"] == []
    assert summary["skipped_count"] == 1


def test_get_run_history_summary_skips_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    link = tmp_path / "linked_session_summary.json"
    _write_session_summary(target, session_id="session_outside", success=False)
    try:
        link.symlink_to(target)
    except OSError:
        return

    summary = support_bundle.get_run_history_summary(max_runs=5, output_dir=tmp_path)

    assert summary["total_runs"] == 0
    assert summary["recent_runs"] == []


def test_recent_log_metadata_is_bounded_and_excludes_names_and_contents(tmp_path: Path) -> None:
    first = tmp_path / "scribe_private-meeting_20260715_120000.log"
    second = tmp_path / "scribe_private-meeting_20260715_120001.log"
    first.write_text("private transcript contents", encoding="utf-8")
    second.write_text("Bearer secret-token-123456", encoding="utf-8")
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))

    metadata = support_bundle.get_recent_log_metadata(max_logs=1, log_dir=tmp_path)

    assert metadata["listed_count"] == 1
    assert metadata["contents_included"] is False
    assert metadata["files"][0]["size_bytes"] == second.stat().st_size
    serialized = json.dumps(metadata)
    assert "private-meeting" not in serialized
    assert "secret-token" not in serialized
    assert "private transcript" not in serialized


def test_create_support_bundle_can_skip_run_history() -> None:
    with (
        patch("scribe.utils.support_bundle.get_system_info", return_value={"system": "ok"}),
        patch("scribe.utils.support_bundle.get_environment_config", return_value={"env": "ok"}),
        patch("scribe.utils.support_bundle.get_diagnostics_results", return_value={"diag": "ok"}),
        patch("scribe.utils.support_bundle.get_run_history_summary") as mock_history,
        patch("scribe.utils.support_bundle.get_recent_log_metadata", return_value={"files": []}),
    ):
        bundle = support_bundle.create_support_bundle(include_run_history=False)

    assert bundle["system_info"] == {"system": "ok"}
    assert "run_history" not in bundle
    mock_history.assert_not_called()


def test_create_support_bundle_sanitizes_all_sections() -> None:
    secret = "-".join(("sk", "bundle", "secret", "123456"))
    with (
        patch(
            "scribe.utils.support_bundle.get_system_info", return_value={"path": str(Path.home())}
        ),
        patch(
            "scribe.utils.support_bundle.get_environment_config",
            return_value={"SERVICE_TOKEN": secret},
        ),
        patch(
            "scribe.utils.support_bundle.get_diagnostics_results",
            return_value={"details": f"Bearer {secret}"},
        ),
        patch(
            "scribe.utils.support_bundle.get_run_history_summary",
            return_value={"recent_runs": [{"error_message": f"api_key={secret}"}]},
        ),
        patch("scribe.utils.support_bundle.get_recent_log_metadata", return_value={"files": []}),
    ):
        bundle = support_bundle.create_support_bundle()

    serialized = json.dumps(bundle)
    assert secret not in serialized
    assert str(Path.home()) not in serialized
    assert bundle["privacy"]["log_contents_included"] is False


def test_save_support_bundle_uses_pretty_writer(tmp_path: Path) -> None:
    output_path = tmp_path / "bundle.json"

    with patch("scribe.utils.safe_write.atomic_write") as mock_atomic_write:
        result = support_bundle.save_support_bundle({"ok": True}, output_path, pretty=True)

    assert result == output_path
    mock_atomic_write.assert_called_once()


def test_generate_support_bundle_cli_avoids_same_second_collisions(tmp_path: Path) -> None:
    with (
        patch(
            "scribe.utils.support_bundle.create_support_bundle",
            side_effect=[{"sequence": 1}, {"sequence": 2}],
        ),
        patch("scribe.utils.support_bundle.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value.strftime.return_value = "20260508_000000"
        first = support_bundle.generate_support_bundle_cli(tmp_path)
        second = support_bundle.generate_support_bundle_cli(tmp_path)

    assert first != second
    assert first.name.startswith("scribe_support_bundle_20260508_000000_")
    assert second.name.startswith("scribe_support_bundle_20260508_000000_")
    assert json.loads(first.read_text(encoding="utf-8"))["sequence"] == 1
    assert json.loads(second.read_text(encoding="utf-8"))["sequence"] == 2
    assert len(list(tmp_path.glob("scribe_support_bundle_*.json"))) == 2


def test_generate_support_bundle_cli_cleans_reservation_on_failure(tmp_path: Path) -> None:
    with patch(
        "scribe.utils.support_bundle.create_support_bundle",
        side_effect=RuntimeError("diagnostics unavailable"),
    ):
        with pytest.raises(RuntimeError, match="diagnostics unavailable"):
            support_bundle.generate_support_bundle_cli(tmp_path)

    assert list(tmp_path.glob("scribe_support_bundle_*.json")) == []


def test_generate_support_bundle_cli_close_failure_cleans_reservation(tmp_path: Path) -> None:
    with patch("scribe.utils.support_bundle.os.close", side_effect=OSError("close failed")):
        with pytest.raises(OSError, match="close failed"):
            support_bundle.generate_support_bundle_cli(tmp_path)

    assert list(tmp_path.glob("scribe_support_bundle_*.json")) == []


def test_generate_support_bundle_cli_cleanup_failure_is_logged(tmp_path: Path) -> None:
    with (
        patch(
            "scribe.utils.support_bundle.create_support_bundle",
            side_effect=RuntimeError("diagnostics unavailable"),
        ),
        patch.object(Path, "unlink", side_effect=OSError("cleanup denied")),
        patch("scribe.utils.support_bundle.logger.warning") as warning_log,
    ):
        with pytest.raises(RuntimeError, match="diagnostics unavailable"):
            support_bundle.generate_support_bundle_cli(tmp_path)

    reservations = list(tmp_path.glob("scribe_support_bundle_*.json"))
    assert len(reservations) == 1
    assert any(
        "Could not remove incomplete support-bundle reservation" in str(call)
        for call in warning_log.call_args_list
    )
    reservations[0].unlink()
