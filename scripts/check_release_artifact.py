"""Validate the portable root wheel contract using only the standard library."""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

WORKSPACE_ONLY_REQUIREMENTS = {"scribe-audio-core"}
REQUIRED_RUNTIME_REQUIREMENTS = {"deal"}
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


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

        metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
        if metadata.get("Name", "").lower() != "scribe":
            raise ValueError("Wheel metadata project name is not scribe")
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
