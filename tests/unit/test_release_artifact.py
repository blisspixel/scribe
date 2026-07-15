"""Release artifact contract tests."""

import subprocess
import sys
import zipfile
from pathlib import Path


def _write_wheel(path: Path, *, requirements: tuple[str, ...] = ("deal>=4.1",)) -> None:
    metadata = ["Metadata-Version: 2.4", "Name: scribe", "Version: 2.8.1"]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("scribe/__init__.py", "")
        wheel.writestr("scribe-2.8.1.dist-info/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            "scribe-2.8.1.dist-info/entry_points.txt",
            "[console_scripts]\nscribe = scribe.cli.main:main\n",
        )


def _run_check(repo_root: Path, wheel: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "check_release_artifact.py"), str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_artifact_check_accepts_portable_wheel(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("deal>=4.1", "typer>=0.9"))

    result = _run_check(repo_root, wheel)

    assert result.returncode == 0
    assert "Artifact contract passed" in result.stdout


def test_release_artifact_check_accepts_build_directory(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("deal>=4.1", "typer>=0.9"))

    result = _run_check(repo_root, tmp_path)

    assert result.returncode == 0
    assert wheel.name in result.stdout


def test_release_artifact_check_rejects_workspace_native_requirement(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("deal>=4.1", "scribe-audio-core"))

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "workspace-only dependency" in result.stderr


def test_release_artifact_check_rejects_missing_runtime_requirement(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("typer>=0.9",))

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "missing required runtime dependency: deal" in result.stderr
