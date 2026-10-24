"""Check an installed Scribe distribution for patched dependency floors.

`uv tool install` does not use uv.lock. The wheel metadata is the contract that
fresh installs resolve.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys

SECURITY_FLOORS = {
    "pillow": ">=13.0.0",
    "filelock": ">=4.2.1",
    "setuptools": ">=84.1.0",
}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def requirement_name(requirement: str) -> str:
    bare = requirement.split(";", 1)[0].strip()
    match = _NAME.match(bare)
    if match is None:
        raise ValueError(f"Malformed requirement: {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def floor_failures(requirements: list[str]) -> list[str]:
    found: dict[str, list[str]] = {name: [] for name in SECURITY_FLOORS}
    for requirement in requirements:
        name = requirement_name(requirement)
        if name not in found:
            continue
        found[name].append(requirement.split(";", 1)[0].replace(" ", ""))
    failures = [f"missing {name}" for name, specs in found.items() if not specs]
    failures.extend(
        f"{spec} is below {SECURITY_FLOORS[name]}"
        for name, specs in found.items()
        for spec in specs
        if SECURITY_FLOORS[name] not in spec
    )
    return failures


def main() -> int:
    requirements = list(importlib.metadata.requires("scribe") or [])
    failures = floor_failures(requirements)
    if failures:
        print("Installed Scribe metadata failed security floors:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Installed Scribe metadata meets the security floors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
