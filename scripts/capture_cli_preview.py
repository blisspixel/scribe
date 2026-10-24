"""Capture a sanitized README preview from the real recording CLI output."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.ansi import AnsiDecoder
from rich.console import Console
from rich.terminal_theme import TerminalTheme

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = REPOSITORY_ROOT / "docs" / "assets" / "cli-recording-preview.png"
NOTES_PREVIEW_PATH = REPOSITORY_ROOT / "docs" / "assets" / "cli-notes-preview.png"

_TERMINAL_THEME = TerminalTheme(
    background=(10, 14, 26),
    foreground=(226, 232, 240),
    normal=[
        (15, 23, 42),
        (248, 113, 113),
        (74, 222, 128),
        (250, 204, 21),
        (96, 165, 250),
        (192, 132, 252),
        (34, 211, 238),
        (226, 232, 240),
    ],
    bright=[
        (100, 116, 139),
        (252, 165, 165),
        (134, 239, 172),
        (253, 224, 71),
        (147, 197, 253),
        (216, 180, 254),
        (103, 232, 249),
        (248, 250, 252),
    ],
)

_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; width: 100%; min-height: 100%; background: #070b16; }}
  body {{ box-sizing: border-box; padding: 28px; }}
  .terminal {{
    width: 980px;
    overflow: hidden;
    border: 1px solid #26324a;
    border-radius: 14px;
    background: #0a0e1a;
    box-shadow: 0 22px 60px rgba(0, 0, 0, .45);
  }}
  .titlebar {{
    height: 42px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid #26324a;
    background: #111827;
  }}
  .dots {{ display: flex; gap: 8px; padding-left: 16px; }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; }}
  .red {{ background: #fb7185; }}
  .yellow {{ background: #fbbf24; }}
  .green {{ background: #4ade80; }}
  .title {{
    flex: 1;
    padding-right: 75px;
    color: #94a3b8;
    font: 12px "Cascadia Mono", Consolas, monospace;
    text-align: center;
  }}
  pre {{
    box-sizing: border-box;
    margin: 0;
    padding: 24px 30px 28px;
    color: #e2e8f0;
    background: #0a0e1a;
    font: 16px/1.22 "Cascadia Mono", Consolas, monospace;
    white-space: pre-wrap;
  }}
</style>
</head>
<body>
  <div class="terminal">
    <div class="titlebar">
      <div class="dots">
        <span class="dot red"></span>
        <span class="dot yellow"></span>
        <span class="dot green"></span>
      </div>
      <div class="title">{title}</div>
    </div>
    <pre>{code}</pre>
  </div>
</body>
</html>
"""


def _edge_path() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Microsoft Edge is required to render the CLI preview on Windows")


def _capture_recording_prompt(temp_root: Path) -> str:
    output_folder = temp_root / "recordings"
    log_folder = temp_root / "logs"
    environment = os.environ.copy()
    environment.update(
        {
            "FORCE_COLOR": "1",
            "COLUMNS": "120",
            "PYTHONIOENCODING": "utf-8",
            "SCRIBE_ANIMATIONS": "off",
            "SCRIBE_COLOR": "always",
            "SCRIBE_BANNER": "on",
            "SCRIBE_ASSUME_CONSENT": "1",
            "SCRIBE_OUTPUT_FOLDER": str(output_folder),
            "SCRIBE_LOG_FOLDER": str(log_folder),
            "SCRIBE_DEFAULT_MODEL": "large-v3",
            "SCRIBE_DEFAULT_LANGUAGE": "en",
            "SCRIBE_MAX_RECORDING_HOURS": "9.0",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "scribe", "record"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    output = result.stdout.replace(str(output_folder.resolve()), "./recordings")
    prompt_position = output.find("Meeting name")
    if prompt_position < 0:
        raise RuntimeError("Recording prompt was missing from captured CLI output")

    prompt_line_end = output.find("\n", prompt_position)
    if prompt_line_end >= 0:
        output = output[:prompt_line_end]

    private_fragments = {
        "home directory": str(Path.home()),
        "account name": os.environ.get("USERNAME", ""),
        "cloud-folder name": "OneDrive",
        "temporary directory": str(temp_root),
    }
    leaked = [
        label for label, fragment in private_fragments.items() if fragment and fragment in output
    ]
    if leaked:
        labels = ", ".join(leaked)
        raise RuntimeError(f"Captured CLI output contains private fragments: {labels}")
    return output.rstrip()


def _render_html(output: str, *, title: str = "scribe record") -> str:
    decoder = AnsiDecoder()
    console = Console(
        file=io.StringIO(),
        record=True,
        width=92,
        color_system="truecolor",
        force_terminal=True,
        legacy_windows=False,
    )
    for line in decoder.decode(output):
        console.print(line)
    return console.export_html(
        theme=_TERMINAL_THEME,
        inline_styles=True,
        code_format=_HTML_TEMPLATE.replace("{title}", title),
    )


def _sample_notes() -> str:
    """Synthetic notes in the real notes layout. No personal names or paths."""

    from scribe.utils.notes_content import format_notes

    return format_notes(
        (
            "The group agreed to keep transcription on the machine. Cloud notes "
            "stay an explicit choice, and generated claims still need source review."
        ),
        {
            "current_state_business": ["Recordings stay in the selected output folder."],
            "current_state_technical": ["The default file profile is local faster-whisper."],
            "drivers": ["The team wants a searchable transcript without uploading audio."],
            "blockers": ["A clean macOS and Omarchy recording record is still outstanding."],
            "future_state_business": ["New installs use the documented GitHub release."],
            "future_state_technical": [
                "Desktop voice remains experimental until hardware evidence exists."
            ],
            "next_steps": [
                "Reinstall from the documented release before the next recording.",
                "Review generated notes against the transcript before sharing them.",
            ],
        },
        {"meeting_name": "Sample meeting", "duration": "12 minutes"},
    )


def capture_notes_preview() -> Path:
    """Render the synthetic notes sample and return the PNG path."""

    NOTES_PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = "scribe sample-meeting.wav --notes\n\n" + _sample_notes()
    temp_parent = REPOSITORY_ROOT / ".agent"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="notes-preview-", dir=temp_parent) as temp_dir:
        html_path = Path(temp_dir) / "cli-notes-preview.html"
        html_path.write_text(_render_html(output, title="scribe notes"), encoding="utf-8")
        subprocess.run(  # noqa: S603 - executes the resolved, bundled Edge binary only
            [
                str(_edge_path()),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1060,920",
                f"--screenshot={NOTES_PREVIEW_PATH}",
                html_path.as_uri(),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

    image = NOTES_PREVIEW_PATH.read_bytes()
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) < 10_000:
        raise RuntimeError("Notes preview renderer did not create a valid PNG")
    return NOTES_PREVIEW_PATH


def capture_preview() -> Path:
    """Generate the sanitized PNG preview and return its path."""
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_parent = REPOSITORY_ROOT / ".agent"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cli-preview-", dir=temp_parent) as temp_dir:
        temp_root = Path(temp_dir)
        output = _capture_recording_prompt(temp_root)
        html_path = temp_root / "cli-recording-preview.html"
        html_path.write_text(_render_html(output), encoding="utf-8")

        subprocess.run(  # noqa: S603 - executes the resolved, bundled Edge binary only
            [
                str(_edge_path()),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1060,540",
                f"--screenshot={PREVIEW_PATH}",
                html_path.as_uri(),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

    image = PREVIEW_PATH.read_bytes()
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) < 10_000:
        raise RuntimeError("CLI preview renderer did not create a valid PNG")
    return PREVIEW_PATH


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "notes":
        print(capture_notes_preview())
    else:
        print(capture_preview())
