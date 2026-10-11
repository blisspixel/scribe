"""
First-run config wizard. Writes ~/.scribe/config.toml.

Triggered automatically on first run when no config file exists, or manually
via `scribe init`. Existing SCRIBE_* env vars and CLI flags continue to
override values written here.
"""

from __future__ import annotations

import os
import sys
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from scribe.config_file import CONFIG_PATH, save_config_file


def _detect_gpu_summary() -> tuple[bool, str]:
    """Return (has_capable_gpu, friendly description)."""
    try:
        from scribe.utils.gpu import detect_gpu_capability, is_high_end_gpu

        info = detect_gpu_capability()
        name = info.get("gpu_name") or ""
        vram = float(info.get("gpu_memory_gb") or 0)
        cuda_ok = bool(info.get("cuda_available"))
        if cuda_ok and name:
            tier = "high-end" if is_high_end_gpu(name, vram) else "available"
            return True, f"{name} ({vram:.0f}GB VRAM, {tier})"
        return False, "no CUDA-capable GPU detected"
    except Exception as e:
        # ADR-002: hardware probes may fail on broken drivers; wizard must continue.
        return False, f"GPU detection failed: {e}"


def _detected_keys() -> dict[str, bool]:
    """
    Detect provider API keys.

    Looks beyond os.environ - also loads scribe's discovered .env file (cwd,
    home, package dir) so the wizard sees keys even when run from outside the
    project directory.
    """
    try:
        from dotenv import dotenv_values

        from scribe.models.config import _find_env_file

        env_file = _find_env_file()
        env_data: dict[str, str] = {}
        if env_file:
            env_data = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    except (ImportError, OSError, TypeError, ValueError):
        # dotenv_values or file issues should not block the wizard; fall back to empty.
        env_data = {}

    def has(*names: str) -> bool:
        return any(os.getenv(n) or env_data.get(n) for n in names)

    return {
        "openai": has("OPENAI_API_KEY", "SCRIBE_OPENAI_API_KEY"),
        "openrouter": has("OPENROUTER_API_KEY", "SCRIBE_OPENROUTER_API_KEY"),
        "xai": has("XAI_API_KEY", "SCRIBE_XAI_API_KEY"),
    }


def _default_output_folder() -> str:
    """Return the best default for the init wizard's output folder prompt."""
    env_output = os.getenv("SCRIBE_OUTPUT_FOLDER")
    if env_output:
        return env_output

    with suppress(Exception):
        if CONFIG_PATH.is_file():
            data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            configured = data.get("output", {}).get("folder")
            if configured:
                return str(configured)

    from scribe.utils.platform import get_default_output_directory

    return str(get_default_output_directory())


def _default_obs_settings() -> dict[str, str]:
    """Return defaults for OBS WebSocket prompts from env, config, or OBS itself.

    Defensive: never fails the wizard if OBS config is missing or unreadable.
    Adaptive: prefers OBS's own settings when user has enabled the server.
    """
    host = os.getenv("SCRIBE_OBS_HOST")
    port = os.getenv("SCRIBE_OBS_PORT")
    password = os.getenv("SCRIBE_OBS_PASSWORD")

    with suppress(Exception):
        if CONFIG_PATH.is_file():
            data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            obs = data.get("obs", {})
            host = host or obs.get("host")
            port = port or str(obs.get("port") or "")
            password = password or obs.get("password")

    # Also pull from OBS's own config for better defaults (port, whether auth is on).
    # Password still needs user to copy from OBS UI (it's not stored in plain text).
    # Non-fatal: any failure here just leaves the wizard with what it already has.
    with suppress(Exception):
        from scribe.utils.obs_config import read_obs_websocket_config

        obs_cfg = read_obs_websocket_config()
        if obs_cfg and obs_cfg.exists and not obs_cfg.error:
            if obs_cfg.server_port:
                port = port or str(obs_cfg.server_port)
            # We don't override password from OBS config (hashed or absent).

    return {
        "host": str(host or "localhost"),
        "port": str(port or "4455"),
        "password": str(password or ""),
    }


def run_wizard(console: Console | None = None, *, force: bool = False) -> Path:
    """
    Run the interactive wizard. Returns the path written.

    Args:
        console: Rich console (created if None).
        force: Overwrite an existing config without confirmation.
    """
    console = console or Console()

    # Defensive: non-interactive runs should not hang on Prompts/Confirms.
    # Use defaults and write a minimal usable config (or refuse unless --force + explicit).
    if not sys.stdin.isatty() and not force:
        if CONFIG_PATH.is_file():
            console.print(
                "[dim]Non-interactive and config exists; leaving as-is (use --force to overwrite).[/dim]"
            )
            return CONFIG_PATH
        console.print("[yellow]Non-interactive terminal detected.[/yellow]")
        console.print(
            "[dim]Writing safe defaults. Re-run interactively or with `scribe init --force` for full wizard.[/dim]"
        )
        safe_defaults: dict[str, Any] = {
            "output": {"folder": _default_output_folder()},
            "transcription": {
                "method": "auto",
                "auto_detect_language": True,
                "primary_language": "en",
            },
            # Paid AI extras stay off in non-interactive safe defaults (cost safety);
            # the user can opt in later via the wizard, env vars, or per-run flags.
            "features": {
                "generate_notes": False,
                "generate_joke": False,
                "generate_meme": False,
            },
        }
        path = save_config_file(safe_defaults)
        console.print(f"[green]Wrote minimal config to {path}.[/green]")
        return path

    # Adaptive QOL: warn if running from source in a way that may not match global
    # PATH. Purely advisory, so any failure to introspect the install is ignored.
    with suppress(Exception):
        import scribe

        src_path = str(scribe.__file__)
        if "site-packages" not in src_path and "uv tool" not in src_path.lower():
            console.print(
                "[dim]Running from source tree. For durable global use, consider "
                "`uv tool install --editable .` or plain `uv tool install`.[/dim]"
            )

    if CONFIG_PATH.is_file() and not force:
        if not Confirm.ask(
            f"[yellow]Config already exists at {CONFIG_PATH}.[/yellow] Overwrite?",
            default=False,
            console=console,
        ):
            console.print("[dim]Keeping existing config.[/dim]")
            return CONFIG_PATH

    console.print(
        Panel.fit(
            "[bold]scribe[/bold] first-run setup\n"
            "[dim]Writing your preferences to[/dim] "
            f"[cyan]{CONFIG_PATH}[/cyan]\n"
            "[dim]Env vars and CLI flags still override these values.[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # 1. Output folder
    default_output = _default_output_folder()
    output_folder = Prompt.ask(
        "[bold]Output folder[/bold]",
        default=default_output,
        console=console,
    )

    # 2. Transcription method
    has_gpu, gpu_desc = _detect_gpu_summary()
    console.print(f"\n[dim]GPU check:[/dim] {gpu_desc}")
    method_default = "auto"
    if has_gpu:
        method_help = (
            "[green]GPU detected[/green] - auto stays local and uses the GPU for speed and privacy"
        )
    else:
        method_help = (
            "[yellow]No CUDA GPU[/yellow] - auto stays local on CPU at no cost, but runs slower. "
            "Choose openai or openrouter only for explicit cloud transcription."
        )
    console.print(method_help)
    method = Prompt.ask(
        "[bold]Transcription method[/bold]",
        choices=["auto", "local", "openai", "openrouter"],
        default=method_default,
        console=console,
    )

    # 3. Features
    console.print("\n[bold]Default features[/bold] [dim](still toggleable per command)[/dim]")
    generate_notes = Confirm.ask(
        "  Generate meeting notes by default?", default=False, console=console
    )
    generate_joke = Confirm.ask("  Generate a joke by default?", default=False, console=console)
    generate_meme = Confirm.ask(
        "  Generate a meme by default? [dim](uses a paid image API)[/dim]",
        default=False,
        console=console,
    )

    # 4. AI vendor. Skip this entirely when no optional AI output is enabled;
    # cloud provider keys are not prerequisites for the default local transcript.
    keys = _detected_keys()
    vendor_choice: str | None = None
    needs_ai_vendor = generate_notes or generate_joke or generate_meme
    if needs_ai_vendor and keys["openai"] and keys["xai"]:
        console.print("\n[bold]AI vendor[/bold] [dim](both keys detected)[/dim]")
        vendor_choice = Prompt.ask(
            "  Default vendor for joke / meme",
            choices=["openai", "xai"],
            default="xai",
            console=console,
        )
    elif needs_ai_vendor and keys["openai"]:
        vendor_choice = "openai"
        console.print("\n[dim]Only OPENAI_API_KEY detected - using openai.[/dim]")
    elif needs_ai_vendor and keys["xai"]:
        vendor_choice = "xai"
        console.print("\n[dim]Only XAI_API_KEY detected - using xai.[/dim]")
    elif needs_ai_vendor:
        console.print(
            "\n[yellow]No AI vendor keys detected.[/yellow] "
            "[dim]Set OPENAI_API_KEY or XAI_API_KEY in .env then re-run `scribe init`.[/dim]"
        )
    if method == "openai" and not keys["openai"]:
        console.print(
            "\n[yellow]OpenAI transcription requires OPENAI_API_KEY.[/yellow] "
            "[dim]Set it before transcribing, or choose auto for local processing.[/dim]"
        )
    if method == "openrouter" and not keys["openrouter"]:
        console.print(
            "\n[yellow]OpenRouter transcription requires OPENROUTER_API_KEY.[/yellow] "
            "[dim]Set it before transcribing, or choose auto for local processing.[/dim]"
        )

    # 5. OBS WebSocket
    obs_defaults = _default_obs_settings()
    console.print("\n[bold]OBS recording[/bold] [dim](optional, used by `scribe rec`)[/dim]")
    configure_obs = Confirm.ask(
        "  Configure OBS WebSocket for Quick Record?",
        default=bool(obs_defaults["password"]),
        console=console,
    )

    data: dict[str, Any] = {
        "output": {"folder": output_folder},
        "transcription": {"method": method, "auto_detect_language": True, "primary_language": "en"},
        "features": {
            "generate_notes": generate_notes,
            "generate_joke": generate_joke,
            "generate_meme": generate_meme,
        },
    }
    if vendor_choice:
        # Use the vendor the user actually has a key for. Hardcoding "openai" here
        # made notes fail for an xai-only setup (no openai key -> "No API key found").
        data["providers"] = {
            "joke_provider": vendor_choice,
            "meme_provider": vendor_choice,
            "notes_provider": vendor_choice,
        }

    # Bound up front so they are provably defined wherever they are read later
    # (every read is already guarded by `configure_obs`, but this keeps the
    # static checkers and future edits honest).
    obs_host: str = obs_defaults["host"]
    obs_port: int = 4455
    obs_password: str = ""
    if configure_obs:
        obs_host = Prompt.ask(
            "  OBS WebSocket host",
            default=obs_defaults["host"],
            console=console,
        )
        obs_port_text = Prompt.ask(
            "  OBS WebSocket port",
            default=obs_defaults["port"],
            console=console,
        )
        try:
            obs_port = int(obs_port_text)
        except ValueError:
            console.print("[yellow]Invalid OBS port; using 4455.[/yellow]")
            obs_port = 4455
        obs_password = Prompt.ask(
            "  OBS WebSocket password (blank if auth is disabled)",
            default=obs_defaults["password"],
            password=True,
            console=console,
        )

        data["obs"] = {
            "host": obs_host,
            "port": obs_port,
        }
        if obs_password:
            data["obs"]["password"] = obs_password

    # --- Polished review step for extremely good QOL ---
    console.print("\n[bold]Review your setup[/bold]")
    review_lines = [
        f"Output folder: [cyan]{output_folder}[/cyan]",
        f"Transcription: [cyan]{method}[/cyan] (GPU: {gpu_desc})",
        f"Notes: {'yes' if generate_notes else 'no'}   Joke: {'yes' if generate_joke else 'no'}   Meme: {'yes' if generate_meme else 'no'}",
    ]
    if vendor_choice:
        review_lines.append(f"AI vendor: [cyan]{vendor_choice}[/cyan]")
    if configure_obs:
        review_lines.append(
            f"OBS: host={obs_host} port={obs_port} password={'set' if obs_password else 'none'}"
        )
    console.print(Panel("\n".join(review_lines), border_style="cyan", padding=(0, 1)))

    if not force and not Confirm.ask("\nSave this configuration?", default=True, console=console):
        console.print("[yellow]Setup cancelled. Nothing written.[/yellow]")
        return CONFIG_PATH

    path = save_config_file(data)
    console.print(f"\n[green]+ Saved to[/green] [cyan]{path}[/cyan]")

    _resolve_env_conflicts(
        console=console,
        chosen={
            "SCRIBE_ENABLE_NOTES": generate_notes,
            "SCRIBE_ENABLE_JOKE": generate_joke,
            "SCRIBE_ENABLE_MEME": generate_meme,
        },
    )

    _maybe_setup_voice(console)

    # --- Post-setup verification (the "extremely polished" part) ---
    console.print("\n[bold]Verification[/bold]")
    try:
        from scribe.models.config import ScribeConfig

        cfg = ScribeConfig()
        checks = []
        if cfg.obs_password:
            checks.append("[green]+[/green] OBS password configured")
        else:
            checks.append("[yellow]![/yellow] OBS password not set")
        console.print("  " + "  ".join(checks))
    except Exception as e:
        console.print(f"[yellow]! Config validation issue: {e}[/yellow]")

    # If OBS was configured, do a real lightweight preflight so user gets instant confidence
    if configure_obs and obs_password:
        try:
            from scribe.core.recorder import OBSRecorder
            from scribe.models.config import ScribeConfig as _Cfg

            rec = OBSRecorder(_Cfg())
            result = rec.check_obs_preflight()
            if result.ok:
                console.print(
                    f"[green]+ OBS WebSocket reachable[/green] ({result.endpoint or 'ok'})"
                )
            else:
                console.print(f"[yellow]! OBS preflight: {result.message}[/yellow]")
                if result.fix_suggestion:
                    console.print(f"  [dim]-> {result.fix_suggestion}[/dim]")
        except Exception as e:
            console.print(f"[yellow]! Could not run OBS preflight: {e}[/yellow]")

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("[dim]Next steps:[/dim]")
    console.print("  [cyan]scribe doctor[/cyan]          - full system health check")
    console.print(
        '  [cyan]scribe rec "Meeting Name"[/cyan]  - start a recording (or use the desktop shortcut)'
    )
    console.print("  [cyan]scribe shortcut[/cyan]        - create Quick Record launcher")
    console.print("[dim]Re-run `scribe init` anytime to change these settings.[/dim]")

    # Extremely polished QOL: offer to create the launcher right now as part of setup
    try:
        if Confirm.ask(
            "\nCreate the Quick Record desktop/taskbar launcher now?",
            default=True,
            console=console,
        ):
            from scribe.cli.shortcut import install_quick_record_launcher

            created = install_quick_record_launcher(desktop=True)
            console.print("[green]+ Launcher created.[/green]")
            for p in created:
                console.print(f"  [dim]{p}[/dim]")
            console.print("[dim]Drag the desktop one to your taskbar if desired.[/dim]")
    except Exception as e:
        console.print(f"[dim]Launcher offer skipped: {e}[/dim]")

    return path


def _maybe_setup_voice(console: Console) -> None:
    """Offer to pre-download the dictation model and set up a read-aloud voice.

    Only shown when the voice extra is already installed, so users who never opted
    into voice see no extra prompt. Defensive: any failure here is non-fatal to the
    wizard, since voice is an optional surface.
    """
    # Only prompt in a real interactive terminal; piped/non-TTY runs (and tests)
    # skip silently and can use `scribe tray --setup` later.
    if not sys.stdin.isatty():
        return

    try:
        from scribe.voice.service import missing_dependency_packages
    except ImportError:
        return

    # No voice extra installed -> nothing to set up, stay quiet.
    if missing_dependency_packages(include_tray=False):
        return

    if not Confirm.ask(
        "\nSet up voice dictation + read-aloud now? "
        "[dim](pre-downloads the model so the first use is instant)[/dim]",
        default=True,
        console=console,
    ):
        console.print("[dim]Skipped. Run `scribe tray --setup` anytime.[/dim]")
        return

    try:
        from scribe.voice.setup import run_voice_setup

        run_voice_setup(console, interactive=True)
    except (ImportError, OSError, KeyboardInterrupt) as e:
        console.print(f"[yellow]Voice setup did not complete: {e}[/yellow]")
        console.print("[dim]You can retry later with `scribe tray --setup`.[/dim]")


def _resolve_env_conflicts(console: Console, chosen: dict[str, bool]) -> None:
    """
    Detect SCRIBE_ENABLE_* lines in .env that contradict wizard choices and
    offer to comment them out - env vars override the TOML config, so leaving
    a stale `SCRIBE_ENABLE_NOTES=true` would silently undo a wizard choice.
    """
    from scribe.models.config import _find_env_file

    env_file = _find_env_file()
    if not env_file:
        return

    env_path = Path(env_file)
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        # Best effort; missing or unreadable .env is not fatal for init wizard.
        return

    conflicts: list[tuple[int, str, str]] = []  # (line_idx, var, current_value)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        if key not in chosen:
            continue
        is_true = val.strip().lower() in ("true", "1", "yes", "on")
        if is_true != chosen[key]:
            conflicts.append((i, key, val.strip()))

    if not conflicts:
        return

    console.print(
        f"\n[yellow]Heads up:[/yellow] {len(conflicts)} env var(s) in [cyan]{env_path}[/cyan] "
        "will override your wizard choices:"
    )
    for _, key, val in conflicts:
        console.print(f"  [dim]{key}={val}[/dim]")

    if not Confirm.ask(
        "Comment them out so your wizard choices take effect?",
        default=True,
        console=console,
    ):
        console.print("[dim]Leaving .env as-is. Edit manually if you change your mind.[/dim]")
        return

    for idx, _, _ in conflicts:
        lines[idx] = "# " + lines[idx] + "  # commented by scribe init"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Commented out {len(conflicts)} line(s) in {env_path}.[/green]")


def maybe_prompt_first_run(console: Console | None = None) -> bool:
    """
    If no config exists and stdin is interactive, offer to run the wizard.

    Returns True if the wizard ran and wrote a config; False otherwise.
    Skipped when SCRIBE_SKIP_INIT=1 is set or stdin is not a TTY.
    """
    if CONFIG_PATH.is_file():
        return False
    if os.getenv("SCRIBE_SKIP_INIT", "").lower() in ("1", "true", "yes"):
        return False
    if not sys.stdin.isatty():
        return False

    console = console or Console()
    console.print()
    if not Confirm.ask(
        "[bold cyan]Welcome to scribe![/bold cyan] No config found yet. Run the friendly first-run setup now?",
        default=True,
        console=console,
    ):
        console.print("[dim]No problem - run `scribe init` later whenever you're ready.[/dim]")
        return False

    run_wizard(console=console, force=True)
    return True
