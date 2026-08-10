"""Adaptive setup for resident voice: pre-download STT and TTS assets.

Used by ``scribe init`` (optional voice step) and ``scribe tray --setup`` so the
first dictation or read-aloud does not stall on a multi-gigabyte download. Every
step is defensive: missing optional packages, no network, partial files, and
already-cached assets are all handled without raising into the CLI.
"""

from __future__ import annotations

import gc
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scribe.voice.tts import (
    KOKORO_MODEL_FILE,
    KOKORO_MODEL_URL,
    KOKORO_VOICES_FILE,
    KOKORO_VOICES_URL,
    kokoro_asset_paths,
    kokoro_assets_ready,
    kokoro_dir,
    kokoro_installed,
)

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class SetupStepResult:
    """Outcome of a single setup step, for display and exit-code decisions."""

    name: str
    ok: bool
    message: str


def download_stt_model(
    console: Console, model_name: str, *, device: str = "cpu"
) -> SetupStepResult:  # pragma: no cover - network + model load, exercised by hand
    """Ensure the faster-whisper dictation model is downloaded and loadable.

    Loading a ``WhisperModel`` triggers the one-time download into the shared
    Hugging Face cache, after which every later run loads instantly. Defensive:
    a missing package or a download/runtime error becomes a failed step, never an
    exception into the wizard.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return SetupStepResult(
            "STT model",
            ok=False,
            message="faster-whisper is not installed; install scribe to enable dictation.",
        )

    try:
        with console.status(
            f"[cyan]Downloading and verifying STT model '{model_name}' ({device})...[/cyan]",
            spinner="dots",
        ):
            # Construct on CPU/int8 for the verification load even if the user will
            # run on CUDA: it only needs to prove the weights download and open.
            loaded_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            backend = getattr(loaded_model, "model", None)
            unload_model = getattr(backend, "unload_model", None)
            if callable(unload_model):
                try:
                    unload_model()
                except Exception as error:
                    console.print(
                        f"[yellow]Could not explicitly release the setup model:[/yellow] {error}"
                    )
            del loaded_model
            del backend
            gc.collect()
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        # Defensive: network/model failures must not abort the wizard.
        return SetupStepResult(
            "STT model",
            ok=False,
            message=f"Could not fetch '{model_name}': {e}",
        )
    except Exception as e:
        # Last-resort: vendor-specific model load errors are not enumerable.
        return SetupStepResult(
            "STT model",
            ok=False,
            message=f"Could not fetch '{model_name}': {e}",
        )
    return SetupStepResult(
        "STT model", ok=True, message=f"'{model_name}' ready (cached for instant loads)."
    )


def _download_file(
    url: str, dest: Path, console: Console, label: str
) -> None:  # pragma: no cover - network I/O
    """Stream ``url`` to ``dest`` atomically with a progress bar."""
    import httpx
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TransferSpeedColumn,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=dest.parent,
        prefix=f".{dest.name}.",
        suffix=".part",
        delete=False,
    ) as temporary:
        tmp = Path(temporary.name)
    written = 0
    total: int | None = None
    completed = False
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0)) or None
            with (
                Progress(
                    TextColumn("[cyan]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    console=console,
                ) as progress,
                tmp.open("wb") as handle,
            ):
                task = progress.add_task(label, total=total)
                for block in response.iter_bytes(chunk_size=1 << 20):
                    handle.write(block)
                    written += len(block)
                    progress.update(task, advance=len(block))
        # Verify completeness: a dropped connection ends iter_bytes without error, so
        # without this a truncated file could be promoted and then wrongly pass the
        # readiness size floor. Reject the partial and leave nothing half-written.
        if total is not None and written < total:
            raise OSError(f"incomplete download: got {written} of {total} bytes")
        tmp.replace(dest)
        completed = True
    except httpx.HTTPError as e:
        raise OSError(f"download failed for {label}: {e}") from e
    finally:
        if not completed:
            try:
                tmp.unlink(missing_ok=True)
            except OSError as error:
                console.print(
                    f"[yellow]Could not remove partial download {tmp.name}:[/yellow] {error}"
                )


def download_kokoro_assets(
    console: Console, *, home: Path | None = None
) -> SetupStepResult:  # pragma: no cover - network I/O, exercised by hand
    """Download the Kokoro model and voice files if not already present.

    Defensive: if the package is not installed we skip (pyttsx3 still works); if a
    download fails we report it and leave any good cached file in place. Atomic
    writes mean an interrupted download never leaves a half file that looks ready.
    """
    if not kokoro_installed():
        return SetupStepResult(
            "Kokoro voice",
            ok=False,
            message='not installed; install Scribe with its "kokoro" extra (system TTS still works).',
        )
    if kokoro_assets_ready(home):
        return SetupStepResult(
            "Kokoro voice", ok=True, message=f"voice files already present in {kokoro_dir(home)}."
        )

    model_path, voices_path = kokoro_asset_paths(home)
    download_errors: tuple[type[Exception], ...] = (
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
    )
    try:
        import httpx
    except ImportError:
        pass
    else:
        download_errors = (*download_errors, httpx.HTTPError)

    try:
        if not model_path.is_file():
            _download_file(KOKORO_MODEL_URL, model_path, console, KOKORO_MODEL_FILE)
        if not voices_path.is_file():
            _download_file(KOKORO_VOICES_URL, voices_path, console, KOKORO_VOICES_FILE)
    except download_errors as e:
        # Defensive: a failed optional download degrades to the system voice.
        return SetupStepResult(
            "Kokoro voice",
            ok=False,
            message=f"download failed ({e}); read-aloud will use the system voice.",
        )

    if kokoro_assets_ready(home):
        return SetupStepResult("Kokoro voice", ok=True, message="high-quality voice ready.")
    return SetupStepResult(
        "Kokoro voice",
        ok=False,
        message="downloaded files look incomplete; read-aloud will use the system voice.",
    )


def _prompt_kokoro_voice(
    console: Console, current: str | None
) -> str:  # pragma: no cover - interactive prompt
    """Let the user pick a Kokoro voice from the curated catalogue."""
    from rich.prompt import Prompt

    from scribe.voice.tts import KOKORO_VOICE_CHOICES, resolve_tts_voice

    console.print("\n[bold]Choose a read-aloud voice:[/bold]")
    for index, choice in enumerate(KOKORO_VOICE_CHOICES, start=1):
        console.print(f"  [cyan]{index}[/cyan]. {choice.label} [dim]({choice.voice_id})[/dim]")
    answer = Prompt.ask("Voice number", default="1")
    try:
        position = int(answer) - 1
    except ValueError:
        position = -1
    if 0 <= position < len(KOKORO_VOICE_CHOICES):
        return KOKORO_VOICE_CHOICES[position].voice_id
    return resolve_tts_voice(current)


def run_voice_setup(
    console: Console,
    *,
    interactive: bool = True,
    profile: str | None = None,
    home: Path | None = None,
) -> int:  # pragma: no cover - orchestrates network/model/prompt I/O, tested by hand
    """Pre-download voice models and configure read-aloud, then persist the result.

    Adaptive and defensive: picks the dictation model from the detected GPU, only
    offers Kokoro when its package is installed, downloads with progress, and
    falls back to the system voice if anything is missing. Choices are written to
    the ``[voice.tray]`` config table. Returns 0 when dictation is ready (TTS
    failures degrade rather than fail the whole step).
    """
    from scribe.config_file import load_config_file_strict, save_config_file
    from scribe.models.gpu import GPUConfig
    from scribe.utils.branding import brand_header_markup
    from scribe.voice.service import missing_dependency_packages
    from scribe.voice.settings import model_for_profile, resolve_tray_profile

    console.print(brand_header_markup("scribe voice setup"))
    console.print()

    missing = missing_dependency_packages(include_tray=False)
    if missing:
        console.print(
            "[yellow]Some voice packages are missing: "
            f"{', '.join(missing)}.[/yellow]\n"
            'Install Scribe with its "tray" extra for the full experience.\n',
            markup=True,
        )

    try:
        config = load_config_file_strict()
    except (OSError, tomllib.TOMLDecodeError) as e:
        console.print(f"[red]Could not read existing config safely:[/red] {e}")
        return 1
    voice_cfg = config.get("voice")
    tray_cfg = voice_cfg.get("tray", {}) if isinstance(voice_cfg, dict) else {}
    if not isinstance(tray_cfg, dict):
        tray_cfg = {}

    gpu = GPUConfig.detect()
    resolved_profile = resolve_tray_profile(profile or tray_cfg.get("profile"))
    model_name = str(tray_cfg.get("stt_model") or model_for_profile(resolved_profile, gpu))
    device = "cuda" if gpu.has_gpu and gpu.cuda_available else "cpu"
    console.print(
        f"[dim]GPU: {gpu.gpu_name or 'none'} - dictation model "
        f"'{model_name}' on {device} (profile: {resolved_profile}).[/dim]"
    )

    results: list[SetupStepResult] = [download_stt_model(console, model_name, device=device)]

    # Read-aloud (TTS): offer/refresh Kokoro when installed; otherwise hint.
    chosen_backend = str(tray_cfg.get("tts_backend") or "auto")
    chosen_voice = tray_cfg.get("tts_voice")
    if kokoro_installed():
        want_kokoro = True
        if interactive:
            from rich.prompt import Confirm

            want_kokoro = Confirm.ask(
                "Set up the high-quality Kokoro read-aloud voice (downloads ~330MB)?",
                default=not kokoro_assets_ready(home),
            )
        if want_kokoro:
            kokoro_result = download_kokoro_assets(console, home=home)
            results.append(kokoro_result)
            if kokoro_result.ok:
                chosen_backend = "kokoro"
                if interactive:
                    chosen_voice = _prompt_kokoro_voice(console, chosen_voice)
                elif not chosen_voice:
                    from scribe.voice.tts import DEFAULT_KOKORO_VOICE

                    chosen_voice = DEFAULT_KOKORO_VOICE
    else:
        console.print(
            '[dim]Tip: install Scribe with its "kokoro" extra for a higher-quality local '
            "read-aloud voice. Using the system voice for now.[/dim]"
        )

    # Persist choices to the nested [voice.tray] table.
    new_tray = dict(tray_cfg)
    new_tray["profile"] = resolved_profile
    new_tray["preload_model"] = True
    new_tray["tts_backend"] = chosen_backend
    if chosen_voice:
        new_tray["tts_voice"] = str(chosen_voice)
    # Coerce (don't setdefault): if [voice] is a malformed non-table scalar, the
    # settings would otherwise be silently dropped despite a "success" message.
    if not isinstance(config.get("voice"), dict):
        config["voice"] = {}
    config["voice"]["tray"] = new_tray
    settings_saved = True
    try:
        save_config_file(config)
    except OSError as e:
        settings_saved = False
        console.print(f"[red]Could not save voice settings:[/red] {e}")

    console.print()
    for result in results:
        marker = "[green]ok[/green]" if result.ok else "[yellow]skipped[/yellow]"
        console.print(f"  {marker} {result.name}: {result.message}")
    console.print()

    stt_ok = results[0].ok if results else False
    if stt_ok and settings_saved:
        console.print("[green]Voice setup complete.[/green] Try `scribe tray --preload`.")
        return 0
    if stt_ok:
        console.print(
            "[yellow]Voice models are ready, but setup is incomplete because settings "
            "could not be saved.[/yellow]"
        )
        return 1
    console.print("[yellow]Dictation model not ready - see messages above.[/yellow]")
    return 1
