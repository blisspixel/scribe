"""Tests for the free-VRAM probe and the contended-GPU warning."""

import subprocess
from unittest.mock import patch

import pytest

from scribe.core.local_whisper import warn_if_gpu_memory_contended
from scribe.models.gpu import GPUConfig


def _smi(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_query_free_memory_parses_first_gpu() -> None:
    with patch("scribe.models.gpu.subprocess.run", return_value=_smi("5120\n2048\n")):
        assert GPUConfig.query_free_memory_gb() == pytest.approx(5.0)


@pytest.mark.parametrize(
    "result",
    [_smi("", 0), _smi("5120", 1), _smi("N/A", 0)],
)
def test_query_free_memory_unknown_is_none(result: subprocess.CompletedProcess[str]) -> None:
    with patch("scribe.models.gpu.subprocess.run", return_value=result):
        assert GPUConfig.query_free_memory_gb() is None


def test_query_free_memory_missing_tool_is_none() -> None:
    with patch("scribe.models.gpu.subprocess.run", side_effect=FileNotFoundError):
        assert GPUConfig.query_free_memory_gb() is None


def test_warns_when_free_memory_is_below_model_need() -> None:
    with (
        patch.object(GPUConfig, "query_free_memory_gb", return_value=2.0),
        patch("scribe.core.local_whisper.logger") as log,
    ):
        warn_if_gpu_memory_contended("large-v3")
    assert log.warning.called
    assert "ollama stop" in log.warning.call_args.args[0]


@pytest.mark.parametrize("free", [None, 12.0])
def test_no_warning_with_enough_or_unknown_memory(free: float | None) -> None:
    with (
        patch.object(GPUConfig, "query_free_memory_gb", return_value=free),
        patch("scribe.core.local_whisper.logger") as log,
    ):
        warn_if_gpu_memory_contended("large-v3")
    assert not log.warning.called


def test_small_models_need_less_memory() -> None:
    with (
        patch.object(GPUConfig, "query_free_memory_gb", return_value=2.0),
        patch("scribe.core.local_whisper.logger") as log,
    ):
        warn_if_gpu_memory_contended("base")
    assert not log.warning.called


@pytest.mark.parametrize(
    ("model", "free", "bytes_per_weight"),
    [("large-v3", 1.0, 1), ("large-v3", 2.0, 2), ("small", 0.1, 1)],
)
def test_known_memory_below_weights_stops_without_model_downgrade(model, free, bytes_per_weight):
    from scribe.core.local_whisper import check_model_memory
    from scribe.exceptions import TranscriptionError

    with pytest.raises(
        TranscriptionError, match="No smaller model or cloud service was selected"
    ) as error:
        check_model_memory(model, free, device="CPU", bytes_per_weight=bytes_per_weight)
    assert error.value.context["model"] == model


@pytest.mark.parametrize("free", [None, 16.0])
def test_unknown_memory_is_not_a_fit_guarantee_or_a_reason_to_shrink(free):
    from scribe.core.local_whisper import check_model_memory

    check_model_memory("large-v3", free, device="CPU", bytes_per_weight=1)
