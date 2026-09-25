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
USER_CONTENT_SUFFIXES = {
    ".avi",
    ".docx",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
    ".wma",
    ".wmv",
}
REQUIRED_COMMUNITY_FILES = {
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
}
TEXT_SUFFIXES = {
    ".example",
    ".go",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rs",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _markdown_files() -> Iterator[Path]:
    yield from sorted(REPOSITORY_ROOT.glob("*.md"))
    yield from sorted((REPOSITORY_ROOT / "docs").rglob("*.md"))
    yield from sorted((REPOSITORY_ROOT / "examples").rglob("*.md"))
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


def test_public_project_metadata_and_typed_package_marker_are_complete() -> None:
    missing = sorted(
        name for name in REQUIRED_COMMUNITY_FILES if not (REPOSITORY_ROOT / name).is_file()
    )
    assert missing == []

    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    project = configuration["project"]
    assert (
        project["description"]
        == "Local-first speech transcription, meeting notes, and recording tools"
    )
    assert project["license"] == "Apache-2.0"
    assert project["urls"]["Documentation"].endswith("/tree/main/docs")
    assert (REPOSITORY_ROOT / "src" / "scribe" / "py.typed").is_file()


def test_tracked_text_avoids_private_preparation_residue_and_em_dashes() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()

    problems: list[str] = []
    forbidden_phrases = (
        "publication " + "preparation",
        "publishable " + "tree",
        "RME" + "-ADI-2",
    )
    for relative_path in tracked:
        path = REPOSITORY_ROOT / relative_path
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if "\u2014" in text:
            problems.append(f"{relative_path}: em dash")
        for phrase in forbidden_phrases:
            if phrase.lower() in lowered:
                problems.append(f"{relative_path}: {phrase}")

    assert problems == []


def test_security_compatibility_bounds_and_zero_exception_audit_are_explicit() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    runtime_dependencies = set(configuration["project"]["dependencies"])
    whisperx_dependencies = set(configuration["project"]["optional-dependencies"]["whisperx"])
    assert "torch>=2.13.0" in runtime_dependencies
    # torchaudio is not a runtime dependency: its CUDA builds can disagree with the
    # installed PyTorch build, which breaks Transformers imports. Scribe reads audio
    # through scribe.utils.audio_io instead.
    assert not any(dep.startswith("torchaudio") for dep in runtime_dependencies)
    assert "whisperx>=3.7.2,<3.8" in whisperx_dependencies

    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--ignore-vuln" not in workflow
    assert "uv run --python ${{ matrix.python-version }} pytest" in workflow


def test_combined_coverage_floor_is_synchronized() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    assert configuration["tool"]["coverage"]["report"]["fail_under"] == 81
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--cov-fail-under=81" in workflow
    assert "--cov-fail-under=80" not in workflow


def test_mutation_testing_uses_current_schema_and_does_not_mask_crashes() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject:
        configuration = tomllib.load(pyproject)

    mutation = configuration["tool"]["mutmut"]
    assert mutation["debug"] is True
    assert mutation["source_paths"] == ["src/scribe"]
    assert mutation["only_mutate"] == [
        "src/scribe/models/transcript.py",
        "src/scribe/core/backends/registry.py",
        "src/scribe/core/diarizer.py",
        "src/scribe/cli/voice.py",
        "src/scribe/utils/transcript_writers.py",
    ]
    assert mutation["pytest_add_cli_args_test_selection"] == [
        "-m",
        "not gpu and not slow and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow",
        "tests/unit/test_transcript_model.py",
        "tests/unit/test_backend_selection.py",
        "tests/unit/test_diarizer.py",
        "tests/unit/test_voice.py",
        "tests/unit/test_transcript_writers.py",
    ]
    assert "paths_to_mutate" not in mutation
    assert "tests_dir" not in mutation

    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Validate mutation configuration" in workflow
    assert "timeout 900 uv run mutmut run || true" not in workflow


def test_readme_cli_preview_is_a_bounded_png_without_personal_source_data() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    preview_relative = "docs/assets/cli-recording-preview.png"
    assert preview_relative in readme

    preview = REPOSITORY_ROOT / preview_relative
    image = preview.read_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert 10_000 < len(image) < 2_000_000

    capture_script = (REPOSITORY_ROOT / "scripts" / "capture_cli_preview.py").read_text(
        encoding="utf-8"
    )
    assert '"./recordings"' in capture_script
    assert "OneDrive" in capture_script
    assert "C:\\Users\\" not in capture_script


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


def test_tracked_examples_are_synthetic_and_user_content_is_absent() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()

    user_content = sorted(
        path
        for path in tracked
        if Path(path).suffix.lower() in USER_CONTENT_SUFFIXES
        or path.endswith(("_transcription.txt", "_summary.json"))
    )
    assert user_content == []

    sample = (REPOSITORY_ROOT / "examples" / "sample_meeting.txt").read_text(encoding="utf-8")
    assert sample.startswith("SYNTHETIC EXAMPLE - NOT A REAL MEETING OR TRANSCRIPT\n")

    example_policy = (REPOSITORY_ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    assert "No example is derived from a real recording" in example_policy


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
