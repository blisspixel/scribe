"""Validate the portable root wheel contract using only the standard library."""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import sys
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

WORKSPACE_ONLY_REQUIREMENTS = {"scribe-audio-core"}
REQUIRED_RUNTIME_REQUIREMENTS = {"deal"}
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
NATIVE_ARTIFACT_SUFFIXES = frozenset({".dll", ".dylib", ".exe", ".pyd", ".so"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict[str, object]:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        project = tomllib.load(pyproject)["project"]
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml has no valid project table")
    return project


def _declared_project_version() -> str:
    project = _project_metadata()
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml has no valid project version")
    return version


def _declared_requires_python() -> str:
    requires_python = _project_metadata().get("requires-python")
    if not isinstance(requires_python, str) or not requires_python.strip():
        raise ValueError("pyproject.toml has no valid requires-python value")
    return requires_python


def _normalized_specifiers(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def _declared_project_license() -> str | None:
    license_value = _project_metadata().get("license")
    if license_value is None:
        return None
    if not isinstance(license_value, str) or not license_value.strip():
        raise ValueError("pyproject.toml project license must be an SPDX expression string")
    return license_value.strip()


def _literal_project_version(source: str, label: str) -> str:
    module = ast.parse(source, filename=label)
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            return statement.value.value
    raise ValueError(f"{label} has no literal __version__")


def _runtime_project_version() -> str:
    path = REPOSITORY_ROOT / "src" / "scribe" / "__init__.py"
    return _literal_project_version(path.read_text(encoding="utf-8"), str(path))


def _repository_license_files() -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("LICENSE*", "COPYING*"):
        candidates.extend(path for path in REPOSITORY_ROOT.glob(pattern) if path.is_file())
    return sorted(set(candidates))


def _normalized_requirement_name(requirement: str) -> str:
    match = REQUIREMENT_NAME.match(requirement.strip())
    if match is None:
        raise ValueError(f"Malformed Requires-Dist value: {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def check_wheel(wheel_path: Path) -> None:
    if not wheel_path.is_file() or wheel_path.suffix != ".whl":
        raise ValueError(f"Expected a wheel file: {wheel_path}")

    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_point_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(metadata_names) != 1:
            raise ValueError("Wheel must contain exactly one dist-info/METADATA file")
        if len(entry_point_names) != 1:
            raise ValueError("Wheel must contain exactly one dist-info/entry_points.txt file")
        if "scribe/__init__.py" not in names:
            raise ValueError("Wheel is missing the scribe package")
        if "scribe/py.typed" not in names:
            raise ValueError("Wheel is missing the PEP 561 py.typed marker")
        native_members = sorted(
            name for name in names if PurePosixPath(name).suffix.lower() in NATIVE_ARTIFACT_SUFFIXES
        )
        if native_members:
            joined = ", ".join(native_members)
            raise ValueError(f"Portable root wheel contains platform-native payload: {joined}")

        metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
        if metadata.get("Name", "").lower() != "scribe":
            raise ValueError("Wheel metadata project name is not scribe")
        declared_version = _declared_project_version()
        runtime_version = _runtime_project_version()
        if runtime_version != declared_version:
            raise ValueError(
                "Source and project versions differ: "
                f"pyproject.toml={declared_version}, src/scribe/__init__.py={runtime_version}"
            )
        if metadata.get("Version") != declared_version:
            raise ValueError(
                "Wheel version does not match pyproject.toml: "
                f"expected {declared_version}, found {metadata.get('Version', '<missing>')}"
            )
        declared_requires_python = _declared_requires_python()
        packaged_requires_python = metadata.get("Requires-Python", "")
        if _normalized_specifiers(packaged_requires_python) != _normalized_specifiers(
            declared_requires_python
        ):
            raise ValueError(
                "Wheel Python support does not match pyproject.toml: "
                f"expected {declared_requires_python}, "
                f"found {packaged_requires_python or '<missing>'}"
            )
        try:
            packaged_version = _literal_project_version(
                wheel.read("scribe/__init__.py").decode("utf-8"),
                "wheel scribe/__init__.py",
            )
        except UnicodeDecodeError as exc:
            raise ValueError("Wheel scribe/__init__.py is not valid UTF-8") from exc
        if packaged_version != declared_version:
            raise ValueError(
                "Packaged runtime version does not match pyproject.toml: "
                f"expected {declared_version}, found {packaged_version}"
            )

        license_claims = [
            claim.strip()
            for claim in (metadata.get("License-Expression", ""), metadata.get("License", ""))
            if claim.strip() and claim.strip().upper() != "UNKNOWN"
        ]
        license_classifiers = [
            classifier
            for classifier in metadata.get_all("Classifier", [])
            if classifier.startswith("License ::")
        ]
        declared_license = _declared_project_license()
        repository_license_files = _repository_license_files()
        wheel_license_files = metadata.get_all("License-File", [])
        if (
            license_claims or license_classifiers or wheel_license_files
        ) and not repository_license_files:
            raise ValueError(
                "Wheel claims a license but the repository has no canonical license file"
            )
        if declared_license is not None and not repository_license_files:
            raise ValueError("pyproject.toml claims a license without a canonical license file")
        if repository_license_files:
            if declared_license is None:
                raise ValueError(
                    "Repository license exists but pyproject.toml has no license expression"
                )
            if metadata.get("License-Expression") != declared_license:
                raise ValueError("Wheel license expression does not match pyproject.toml")
            if not wheel_license_files:
                raise ValueError("Wheel omits the repository license file")
            metadata_directory = PurePosixPath(metadata_names[0]).parent
            for license_file in wheel_license_files:
                relative_license = PurePosixPath(license_file)
                if relative_license.is_absolute() or ".." in relative_license.parts:
                    raise ValueError("Wheel contains an unsafe License-File path")
                archive_path = (metadata_directory / "licenses" / relative_license).as_posix()
                if archive_path not in names:
                    raise ValueError(f"Wheel License-File member is missing: {license_file}")

        requirements = metadata.get_all("Requires-Dist", [])
        requirement_names = {
            _normalized_requirement_name(requirement) for requirement in requirements
        }
        workspace_requirements = sorted(
            requirement
            for requirement in requirements
            if _normalized_requirement_name(requirement) in WORKSPACE_ONLY_REQUIREMENTS
        )
        if workspace_requirements:
            joined = ", ".join(workspace_requirements)
            raise ValueError(f"Wheel declares workspace-only dependency: {joined}")
        missing_runtime_requirements = sorted(REQUIRED_RUNTIME_REQUIREMENTS - requirement_names)
        if missing_runtime_requirements:
            joined = ", ".join(missing_runtime_requirements)
            raise ValueError(f"Wheel is missing required runtime dependency: {joined}")

        parser = configparser.ConfigParser()
        parser.read_string(wheel.read(entry_point_names[0]).decode("utf-8"))
        expected_entry_point = "scribe.cli.main:main"
        actual_entry_point = parser.get("console_scripts", "scribe", fallback="")
        if actual_entry_point != expected_entry_point:
            raise ValueError(
                "Wheel console entry point mismatch: "
                f"expected {expected_entry_point!r}, found {actual_entry_point!r}"
            )

        unsafe_names = [
            name
            for name in names
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
        ]
        if unsafe_names:
            raise ValueError("Wheel contains unsafe archive paths")


def _resolve_wheel_path(path: Path) -> Path:
    if not path.is_dir():
        return path
    candidates = sorted(
        candidate
        for candidate in path.glob("scribe-*.whl")
        if not candidate.name.startswith("scribe_audio_core-")
    )
    if len(candidates) != 1:
        raise ValueError(
            f"Expected exactly one root Scribe wheel in {path}, found {len(candidates)}"
        )
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Root Scribe wheel or build directory")
    args = parser.parse_args()
    try:
        wheel_path = _resolve_wheel_path(args.wheel)
        check_wheel(wheel_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Artifact contract failed: {exc}", file=sys.stderr)
        return 1
    print(f"Artifact contract passed: {wheel_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
