"""Audit all registry versions in uv.lock without installing optional stacks.

Markers are deliberately not evaluated: every locked Python/platform branch is
checked. Workspace and VCS sources are reported separately, outside registry
advisory coverage. No advisory is ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def registry_inventory(lock_path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    with lock_path.open("rb") as stream:
        lock = tomllib.load(stream)
    registry: set[tuple[str, str]] = set()
    other: list[str] = []
    for package in lock["package"]:
        name, version = _name(package["name"]), package["version"]
        source = package["source"]
        if "registry" in source:
            registry.add((name, version))
        else:
            other.append(f"{name}=={version}: {json.dumps(source, sort_keys=True)}")
    if not registry:
        raise ValueError("Lock contains no registry packages to audit")
    return sorted(registry), sorted(other)


def requirement_batches(packages: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Keep every version while avoiding conflicting same-name requirements."""
    batches: list[dict[str, str]] = []
    for name, version in packages:
        for batch in batches:
            if name not in batch:
                batch[name] = version
                break
        else:
            batches.append({name: version})
    return [list(batch.items()) for batch in batches]


def audit_batch(packages: list[tuple[str, str]], directory: Path, index: int) -> bool:
    requirements = directory / f"requirements-{index}.txt"
    requirements.write_text(
        "".join(f"{name}=={version}\n" for name, version in packages), encoding="utf-8"
    )
    result = subprocess.run(  # noqa: S603 - current interpreter, fixed pip-audit arguments
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--disable-pip",
            "--no-deps",
            "--progress-spinner",
            "off",
            "--format",
            "json",
            "--requirement",
            str(requirements),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise ValueError(f"pip-audit failed: {result.stderr.strip()}")
    try:
        dependencies = json.loads(result.stdout)["dependencies"]
        audited = {(_name(item["name"]), item["version"]) for item in dependencies}
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Invalid pip-audit response: {result.stderr.strip()}") from exc
    skipped = [item for item in dependencies if "skip_reason" in item]
    if skipped or audited != set(packages):
        raise ValueError(f"Incomplete registry audit: expected {len(packages)}, got {audited!r}")
    clean = True
    for dependency in dependencies:
        for vulnerability in dependency["vulns"]:
            clean = False
            fixes = ", ".join(vulnerability["fix_versions"]) or "no released fix"
            print(
                f"{dependency['name']}=={dependency['version']}: "
                f"{vulnerability['id']} (fix: {fixes})"
            )
    if result.returncode == 1 and clean:
        raise ValueError(f"pip-audit failed without advisory results: {result.stderr.strip()}")
    print(f"Checked {len(audited)} registry versions in batch {index + 1}; zero skips.")
    return clean


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "lock", nargs="?", type=Path, default=Path(__file__).resolve().parents[1] / "uv.lock"
    )
    args = parser.parse_args()
    try:
        packages, other = registry_inventory(args.lock)
        for source in other:
            print(f"Outside registry advisory coverage: {source}", flush=True)
        clean = True
        with tempfile.TemporaryDirectory(prefix="scribe-lock-audit-") as temporary:
            for index, batch in enumerate(requirement_batches(packages)):
                if not audit_batch(batch, Path(temporary), index):
                    clean = False
        print(f"Registry audit checked {len(packages)} locked versions across all markers.")
        return 0 if clean else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Registry audit incomplete: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
