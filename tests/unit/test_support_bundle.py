from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from scribe.utils import support_bundle


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


def test_get_environment_config_redacts_api_key() -> None:
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
    assert config["OPENAI_API_KEY"].startswith("sk-test-12...")


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


def test_get_run_history_summary_uses_history_object() -> None:
    recent_run = Mock()
    recent_run.to_dict.return_value = {"id": "recent"}
    failed_run = Mock()
    failed_run.to_dict.return_value = {"id": "failed"}

    history = Mock()
    history.runs = [1, 2, 3]
    history.get_recent.return_value = [recent_run]
    history.get_failed_runs.return_value = [failed_run]

    with patch("scribe.utils.support_bundle.get_run_history", return_value=history):
        summary = support_bundle.get_run_history_summary(max_runs=5)

    assert summary["total_runs"] == 3
    assert summary["recent_runs"] == [{"id": "recent"}]
    assert summary["failed_runs"] == [{"id": "failed"}]
    assert summary["summary"] == {"total": 3, "recent_count": 1, "failed_count": 1}


def test_create_support_bundle_can_skip_run_history() -> None:
    with (
        patch("scribe.utils.support_bundle.get_system_info", return_value={"system": "ok"}),
        patch("scribe.utils.support_bundle.get_environment_config", return_value={"env": "ok"}),
        patch("scribe.utils.support_bundle.get_diagnostics_results", return_value={"diag": "ok"}),
        patch("scribe.utils.support_bundle.get_run_history_summary") as mock_history,
    ):
        bundle = support_bundle.create_support_bundle(include_run_history=False)

    assert bundle["system_info"] == {"system": "ok"}
    assert "run_history" not in bundle
    mock_history.assert_not_called()


def test_save_support_bundle_uses_pretty_writer(tmp_path: Path) -> None:
    output_path = tmp_path / "bundle.json"

    with patch("scribe.utils.safe_write.atomic_write") as mock_atomic_write:
        result = support_bundle.save_support_bundle({"ok": True}, output_path, pretty=True)

    assert result == output_path
    mock_atomic_write.assert_called_once()


def test_generate_support_bundle_cli_creates_timestamped_file(tmp_path: Path) -> None:
    saved_path = tmp_path / "scribe_support_bundle_20260508_000000.json"

    with (
        patch("scribe.utils.support_bundle.create_support_bundle", return_value={"ok": True}),
        patch("scribe.utils.support_bundle.save_support_bundle") as mock_save,
        patch("scribe.utils.support_bundle.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value.strftime.return_value = "20260508_000000"
        mock_save.return_value = saved_path
        result = support_bundle.generate_support_bundle_cli(tmp_path)

    assert result == saved_path
    mock_save.assert_called_once()
