"""Repository structure and documentation integrity contracts."""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INLINE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FORBIDDEN_ROOT_FILES = {
    "CURRENT-STATE-ANALYSIS.md",
    "DISCLAIMER.md",
    "PROGRESS-LOG.md",
    "SKILLS.md",
    "requirements-dev.txt",
    "requirements.txt",
}


def _markdown_files() -> Iterator[Path]:
    yield from sorted(REPOSITORY_ROOT.glob("*.md"))
    yield from sorted((REPOSITORY_ROOT / "docs").rglob("*.md"))
    yield from sorted((REPOSITORY_ROOT / "tests").rglob("*.md"))


def _inline_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def test_agent_state_and_dependency_shims_stay_out_of_repository_root() -> None:
    present = sorted(name for name in FORBIDDEN_ROOT_FILES if (REPOSITORY_ROOT / name).exists())

    assert present == []
    ignore_rules = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".agent/" in ignore_rules
    assert "logs/" in ignore_rules


def test_development_dependencies_have_one_canonical_group() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    optional_dependencies = configuration["project"].get("optional-dependencies", {})
    assert "dev" not in optional_dependencies
    assert "dev" in configuration["dependency-groups"]


def test_security_compatibility_bounds_and_zero_exception_audit_are_explicit() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    runtime_dependencies = set(configuration["project"]["dependencies"])
    whisperx_dependencies = set(configuration["project"]["optional-dependencies"]["whisperx"])
    assert "torch>=2.13.0" in runtime_dependencies
    assert "torchaudio>=2.11.0" in runtime_dependencies
    assert "whisperx>=3.7.2,<3.8" in whisperx_dependencies

    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--ignore-vuln" not in workflow
    assert "uv run --python ${{ matrix.python-version }} pytest" in workflow


def test_native_executables_are_generated_and_ignored() -> None:
    ignore_rules = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "cmd/scribe-tray/*.exe" in ignore_rules

    tracked = subprocess.run(
        ["git", "ls-files", "cmd/scribe-tray/*.exe"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    tracked_existing = [path for path in tracked if (REPOSITORY_ROOT / path).is_file()]
    assert tracked_existing == []


def test_local_markdown_links_resolve() -> None:
    broken: list[str] = []
    for document in _markdown_files():
        text = document.read_text(encoding="utf-8")
        for match in INLINE_LINK.finditer(text):
            target = _inline_link_target(match.group(1))
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_path = unquote(target.split("#", maxsplit=1)[0])
            if relative_path and not (document.parent / relative_path).resolve().exists():
                broken.append(f"{document.relative_to(REPOSITORY_ROOT)} -> {target}")

    assert broken == []


def test_markdown_code_fences_are_balanced() -> None:
    unbalanced: list[str] = []
    for document in _markdown_files():
        fence_count = sum(
            line.lstrip().startswith("```")
            for line in document.read_text(encoding="utf-8").splitlines()
        )
        if fence_count % 2:
            unbalanced.append(str(document.relative_to(REPOSITORY_ROOT)))

    assert unbalanced == []
