"""Release artifact contract tests."""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import scripts.check_release_artifact as artifact_check

PROJECT_VERSION = artifact_check._declared_project_version()


def _write_wheel(
    path: Path,
    *,
    requirements: tuple[str, ...] = ("deal>=4.1",),
    version: str = PROJECT_VERSION,
    requires_python: str = "<3.14,>=3.12",
    packaged_version: str | None = None,
    license_expression: str | None = "Apache-2.0",
    license_file: str | None = "LICENSE",
    classifiers: tuple[str, ...] = (),
    include_license_member: bool = True,
    include_typed_marker: bool = True,
    extra_members: tuple[str, ...] = (),
) -> None:
    metadata = [
        "Metadata-Version: 2.4",
        "Name: scribe",
        f"Version: {version}",
        f"Requires-Python: {requires_python}",
    ]
    if license_expression is not None:
        metadata.append(f"License-Expression: {license_expression}")
    if license_file is not None:
        metadata.append(f"License-File: {license_file}")
    metadata.extend(f"Classifier: {classifier}" for classifier in classifiers)
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    with zipfile.ZipFile(path, "w") as wheel:
        runtime_version = packaged_version or version
        wheel.writestr("scribe/__init__.py", f'__version__ = "{runtime_version}"\n')
        if include_typed_marker:
            wheel.writestr("scribe/py.typed", "")
        wheel.writestr(f"scribe-{version}.dist-info/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            f"scribe-{version}.dist-info/entry_points.txt",
            "[console_scripts]\nscribe = scribe.cli.main:main\n",
        )
        if include_license_member and license_file is not None:
            wheel.writestr(f"scribe-{version}.dist-info/licenses/{license_file}", "terms\n")
        for member in extra_members:
            wheel.writestr(member, b"native payload")


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


def test_release_artifact_check_rejects_missing_typed_marker(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, include_typed_marker=False)

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "py.typed marker" in result.stderr


def test_release_artifact_check_rejects_workspace_native_requirement(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("deal>=4.1", "scribe-audio-core"))

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "workspace-only dependency" in result.stderr


def test_release_artifact_check_rejects_native_payload_in_portable_wheel(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(
        wheel,
        requirements=("deal>=4.1", "typer>=0.9"),
        extra_members=("scribe/assets/bin/scribe-tray.exe",),
    )

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "platform-native payload" in result.stderr
    assert "scribe-tray.exe" in result.stderr


def test_release_artifact_check_rejects_missing_runtime_requirement(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requirements=("typer>=0.9",))

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "missing required runtime dependency: deal" in result.stderr


def test_release_artifact_check_rejects_version_mismatch(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-9.9.9-py3-none-any.whl"
    _write_wheel(wheel, version="9.9.9")

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "Wheel version does not match pyproject.toml" in result.stderr


def test_release_artifact_check_rejects_python_support_mismatch(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, requires_python=">=3.12")

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "Wheel Python support does not match pyproject.toml" in result.stderr


def test_release_artifact_check_rejects_unsupported_license_claim(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, license_expression="MIT")

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "license expression does not match" in result.stderr


def test_release_artifact_check_rejects_packaged_runtime_version_mismatch(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(wheel, packaged_version="9.9.9")

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "Packaged runtime version does not match pyproject.toml" in result.stderr


@pytest.mark.parametrize(
    ("license_expression", "license_file"), [(None, "LICENSE"), ("Apache-2.0", None)]
)
def test_release_artifact_check_rejects_incomplete_license_evidence(
    tmp_path, license_expression, license_file
):
    repo_root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(
        wheel,
        license_expression=license_expression,
        license_file=license_file,
    )

    result = _run_check(repo_root, wheel)

    assert result.returncode == 1
    assert "license" in result.stderr.lower()


def _write_licensed_repository(path: Path, *, expression: str = "MIT") -> None:
    (path / "src" / "scribe").mkdir(parents=True)
    (path / "LICENSE").write_text("terms\n", encoding="utf-8")
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "scribe"\nversion = "{PROJECT_VERSION}"\n'
        f'requires-python = ">=3.12,<3.14"\nlicense = "{expression}"\n',
        encoding="utf-8",
    )
    (path / "src" / "scribe" / "__init__.py").write_text(
        f'__version__ = "{PROJECT_VERSION}"\n', encoding="utf-8"
    )


def test_release_artifact_check_requires_declared_license_member(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    _write_licensed_repository(repository)
    monkeypatch.setattr(artifact_check, "REPOSITORY_ROOT", repository)
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(
        wheel,
        license_expression="MIT",
        license_file="LICENSE",
        include_license_member=False,
    )

    with pytest.raises(ValueError, match="License-File member is missing"):
        artifact_check.check_wheel(wheel)


def test_release_artifact_check_accepts_aligned_license_evidence(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    _write_licensed_repository(repository)
    monkeypatch.setattr(artifact_check, "REPOSITORY_ROOT", repository)
    wheel = tmp_path / "scribe-2.8.1-py3-none-any.whl"
    _write_wheel(
        wheel,
        license_expression="MIT",
        license_file="LICENSE",
        include_license_member=True,
    )

    artifact_check.check_wheel(wheel)
