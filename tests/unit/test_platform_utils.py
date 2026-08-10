import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scribe.utils.platform import (
    check_disk_space,
    get_default_output_directory,
    get_ffmpeg_path,
    get_ffprobe_path,
    get_home_directory,
    get_obs_executable_path,
    get_path_separator,
    get_platform,
    get_platform_info,
    get_temp_directory,
    normalize_path,
    open_file_with_default_app,
)


def test_get_platform_and_output_directories_cover_all_platforms(tmp_path):
    with patch("scribe.utils.platform.platform.system", return_value="Windows"):
        assert get_platform() == "windows"

    with patch("scribe.utils.platform.platform.system", return_value="Darwin"):
        assert get_platform() == "macos"

    with patch("scribe.utils.platform.platform.system", return_value="Linux"):
        assert get_platform() == "linux"

    with patch("scribe.utils.platform.platform.system", return_value="Plan9"):
        assert get_platform() == "unknown"

    with (
        patch("scribe.utils.platform.get_home_directory", return_value=tmp_path),
        patch("scribe.utils.platform.is_windows", return_value=True),
    ):
        assert get_default_output_directory() == tmp_path / "Videos" / "Transcriptions"

    with (
        patch("scribe.utils.platform.get_home_directory", return_value=tmp_path),
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("scribe.utils.platform.is_macos", return_value=True),
    ):
        assert get_default_output_directory() == tmp_path / "Movies" / "Transcriptions"

    with (
        patch("scribe.utils.platform.get_home_directory", return_value=tmp_path),
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("scribe.utils.platform.is_macos", return_value=False),
    ):
        assert get_default_output_directory() == tmp_path / "Videos" / "Transcriptions"


def test_ffmpeg_and_ffprobe_detection_use_path_env_and_common_locations(tmp_path):
    ffmpeg_file = tmp_path / "bin" / "ffmpeg.exe"
    ffmpeg_file.parent.mkdir(parents=True)
    ffmpeg_file.write_text("binary", encoding="utf-8")

    with patch("shutil.which", return_value=str(ffmpeg_file)):
        assert get_ffmpeg_path() == ffmpeg_file

    with (
        patch("shutil.which", return_value=None),
        patch.dict(os.environ, {"FFMPEG_DIR": str(tmp_path)}, clear=True),
    ):
        env_file = tmp_path / "ffmpeg.exe"
        env_file.write_text("binary", encoding="utf-8")
        with patch("scribe.utils.platform.is_windows", return_value=True):
            assert get_ffmpeg_path() == env_file

    with (
        patch("shutil.which", return_value=None),
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("scribe.utils.platform.is_macos", return_value=False),
        # Candidates are now accepted only if they are executable files; mock that
        # predicate so the first common Linux dir matches.
        patch("scribe.utils.platform._is_executable_file", side_effect=[True, False, False]),
    ):
        detected_path = str(get_ffmpeg_path()).lower()
    assert "usr" in detected_path
    assert detected_path.endswith("ffmpeg")

    ffprobe_path = ffmpeg_file.parent / "ffprobe.exe"
    ffprobe_path.write_text("binary", encoding="utf-8")
    with (
        patch("shutil.which", return_value=None),
        patch("scribe.utils.platform.get_ffmpeg_path", return_value=ffmpeg_file),
        # Pin Windows so the sibling lookup targets ffprobe.exe deterministically;
        # on POSIX runners the code would otherwise search for bare "ffprobe".
        patch("scribe.utils.platform.is_windows", return_value=True),
    ):
        assert get_ffprobe_path() == ffprobe_path


def test_obs_and_open_file_helpers_cover_all_platforms(tmp_path):
    obs_file = tmp_path / "obs64.exe"
    obs_file.write_text("binary", encoding="utf-8")

    with patch.dict(os.environ, {"OBS_EXE": str(obs_file)}, clear=True):
        assert get_obs_executable_path() == obs_file

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("scribe.utils.platform.is_windows", return_value=True),
        # OBS candidates are now accepted only if they are executable files.
        patch("scribe.utils.platform._is_executable_file", side_effect=[True, False, False]),
    ):
        assert str(get_obs_executable_path()).endswith("obs64.exe")

    with (
        patch("scribe.utils.platform.is_windows", return_value=True),
        patch("os.startfile", create=True) as mock_start,
    ):
        assert open_file_with_default_app(obs_file) is True
    mock_start.assert_called_once_with(str(obs_file))

    with (
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("scribe.utils.platform.is_macos", return_value=True),
        patch("subprocess.run") as mock_run,
    ):
        assert open_file_with_default_app(obs_file) is True
    mock_run.assert_called_once()

    with (
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("scribe.utils.platform.is_macos", return_value=False),
        patch("subprocess.run", side_effect=RuntimeError("open failed")),
    ):
        assert open_file_with_default_app(obs_file) is False


def test_platform_info_temp_directory_disk_space_and_normalize_path(tmp_path):
    assert get_home_directory() == Path.home()
    assert get_path_separator() == os.sep

    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        assert get_temp_directory() == tmp_path

    with (
        patch("scribe.utils.platform.platform.system", return_value="Linux"),
        patch("scribe.utils.platform.platform.release", return_value="1"),
        patch("scribe.utils.platform.platform.version", return_value="2"),
        patch("scribe.utils.platform.platform.machine", return_value="x86_64"),
        patch("scribe.utils.platform.platform.processor", return_value="cpu"),
        patch("scribe.utils.platform.platform.python_version", return_value="3.10"),
    ):
        info = get_platform_info()
    assert info["system"] == "Linux"
    assert info["python_version"] == "3.10"

    fake_stat = SimpleNamespace(f_bavail=5 * 1024**3, f_frsize=1)
    with (
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("os.statvfs", return_value=fake_stat, create=True),
    ):
        assert check_disk_space(tmp_path, required_gb=1.0) is True

    def fake_get_disk_free_space(path, _a, _b, free_bytes):
        free_bytes.value = 2 * 1024**3

    fake_ctypes = SimpleNamespace(
        c_ulonglong=lambda value=0: SimpleNamespace(value=value),
        pointer=lambda obj: obj,
        windll=SimpleNamespace(
            kernel32=SimpleNamespace(GetDiskFreeSpaceExW=fake_get_disk_free_space)
        ),
    )
    with (
        patch("scribe.utils.platform.is_windows", return_value=True),
        patch.dict(sys.modules, {"ctypes": fake_ctypes}),
    ):
        assert check_disk_space(tmp_path, required_gb=1.0) is True

    with (
        patch("scribe.utils.platform.is_windows", return_value=False),
        patch("os.statvfs", side_effect=OSError("bad fs"), create=True),
    ):
        assert check_disk_space(tmp_path, required_gb=10.0) is True

    with patch.object(Path, "resolve", side_effect=RuntimeError("resolve failed")):
        normalized = normalize_path('"relative path.txt"')
    assert isinstance(normalized, Path)
