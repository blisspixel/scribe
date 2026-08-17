"""Implement the CLI commands that inspect and diagnose a Scribe installation.

The Typer command declarations remain in :mod:`scribe.cli.main`. Keeping the
rendering and orchestration here gives the entrypoint one responsibility while
preserving its stable patch seams and command names.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from scribe.exceptions import ScribeError
from scribe.utils.branding import brand_header_markup
from scribe.utils.model_selection import resolve_local_model
from scribe.utils.theme import ScribeTheme

if TYPE_CHECKING:
    from logging import Logger

    from rich.console import Console

    from scribe.models.config import ScribeConfig
    from scribe.models.gpu import GPUConfig
    from scribe.utils.diagnostics import DiagnosticResult


def show_info(
    console: Console,
    version: str,
    config: ScribeConfig,
    gpu_config: GPUConfig,
) -> None:
    """Render system, backend, configuration, and local-readiness information."""
    from scribe.utils.terminal_ui import get_terminal_ui_config

    ui_config = get_terminal_ui_config()

    console.print()
    console.print(
        f"[bold {ScribeTheme.PRIMARY_BRIGHT}]scribe info[/bold {ScribeTheme.PRIMARY_BRIGHT}] "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(version)}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print()

    console.print(f"[bold {ScribeTheme.SECONDARY}]gpu[/bold {ScribeTheme.SECONDARY}]")
    if gpu_config.has_gpu:
        cuda_status = (
            f"CUDA {gpu_config.cuda_version}" if gpu_config.cuda_version else "CUDA detected"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]"
            f"{escape(str(gpu_config.gpu_name or 'Unknown GPU'))}"
            f"[/{ScribeTheme.TEXT_PRIMARY}] [{ScribeTheme.TEXT_MUTED}]"
            f"{gpu_config.gpu_memory_gb:.0f}GB VRAM[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_MUTED}]{escape(cuda_status)} · "
            f"{escape(str(gpu_config.model_size))} · beam={gpu_config.beam_size} · "
            f"{escape(gpu_config.get_expected_speed())}[/{ScribeTheme.TEXT_MUTED}]"
        )
    else:
        console.print(
            f"  [{ScribeTheme.WARNING}]not detected[/{ScribeTheme.WARNING}] "
            f"[{ScribeTheme.TEXT_MUTED}]"
            f"{escape(str(gpu_config.reason))}[/{ScribeTheme.TEXT_MUTED}]"
        )
    console.print()

    from scribe.core.backends import backend_availability, detect_hardware, select_backend

    hardware = detect_hardware()
    availability = backend_availability()
    chosen_backend = select_backend(hardware, override=config.local_backend, available=availability)
    installed = ", ".join(sorted(name for name, ok in availability.items() if ok)) or "none"

    console.print(f"[bold {ScribeTheme.SECONDARY}]local backend[/bold {ScribeTheme.SECONDARY}]")
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]selected[/{ScribeTheme.TEXT_PRIMARY}]  "
        f"[{ScribeTheme.SUCCESS}]{escape(chosen_backend)}[/{ScribeTheme.SUCCESS}] "
        f"[{ScribeTheme.TEXT_MUTED}]· vendor "
        f"{escape(hardware.vendor)}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]installed[/{ScribeTheme.TEXT_PRIMARY}] "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(installed)}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print()

    console.print(f"[bold {ScribeTheme.SECONDARY}]config[/bold {ScribeTheme.SECONDARY}]")
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]output[/{ScribeTheme.TEXT_PRIMARY}]    "
        f"[{ScribeTheme.TEXT_MUTED}]"
        f"{escape(str(config.output_folder))}[/{ScribeTheme.TEXT_MUTED}]"
    )
    # Report the model that will actually run, not the configured preference:
    # on a machine without a GPU the default is auto-tuned down (ADR-006).
    effective_model, hardware_adjusted = resolve_local_model(
        config.default_model,
        config.model_fields_set,
        gpu_config.model_size,
    )
    model_note = (
        f" [{ScribeTheme.TEXT_MUTED}](auto for this hardware; "
        f"{escape(str(config.default_model))} configured)[/{ScribeTheme.TEXT_MUTED}]"
        if hardware_adjusted
        else ""
    )
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]model[/{ScribeTheme.TEXT_PRIMARY}]     "
        f"[{ScribeTheme.TEXT_MUTED}]"
        f"{escape(str(effective_model))}[/{ScribeTheme.TEXT_MUTED}]{model_note}"
    )
    language = config.default_language or "auto"
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]language[/{ScribeTheme.TEXT_PRIMARY}]  "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(language)}[/{ScribeTheme.TEXT_MUTED}]"
    )

    from scribe.config_file import CONFIG_PATH

    cfg_state = "present" if CONFIG_PATH.exists() else "defaults"
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]file[/{ScribeTheme.TEXT_PRIMARY}]      "
        f"[{ScribeTheme.TEXT_MUTED}]"
        f"{escape(str(CONFIG_PATH))} ({cfg_state})[/{ScribeTheme.TEXT_MUTED}]"
    )
    features = (
        f"notes:{'on' if config.enable_notes else 'off'} "
        f"joke:{'on' if config.enable_joke else 'off'} "
        f"meme:{'on' if config.enable_meme else 'off'}"
    )
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]features[/{ScribeTheme.TEXT_PRIMARY}]  "
        f"[{ScribeTheme.TEXT_MUTED}]{features}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print()

    console.print(f"[bold {ScribeTheme.SECONDARY}]ui[/bold {ScribeTheme.SECONDARY}]")
    cap = ui_config.capabilities
    color_state = "enabled" if ui_config.use_color else "disabled"
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]animations[/{ScribeTheme.TEXT_PRIMARY}] "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(ui_config.animation_mode)}"
        f"[/{ScribeTheme.TEXT_MUTED}] "
        f"[{ScribeTheme.TEXT_MUTED}]({ui_config.fps} fps)[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]color[/{ScribeTheme.TEXT_PRIMARY}]      "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(ui_config.color_mode)} "
        f"({color_state})[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(
        f"  [{ScribeTheme.TEXT_PRIMARY}]terminal[/{ScribeTheme.TEXT_PRIMARY}]   "
        f"[{ScribeTheme.TEXT_MUTED}]tty={cap.is_tty} dumb={cap.is_dumb_terminal} "
        f"ci={cap.is_ci} windows={cap.is_windows}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print()

    console.print(f"[bold {ScribeTheme.SECONDARY}]api keys[/bold {ScribeTheme.SECONDARY}]")
    _print_api_key_status(console, "openai", bool(config.openai_api_key))
    _print_api_key_status(console, "xai", bool(os.getenv("XAI_API_KEY")))
    _print_api_key_status(console, "gemini", bool(os.getenv("GEMINI_API_KEY")))
    _print_api_key_status(console, "anthropic", bool(os.getenv("ANTHROPIC_API_KEY")))
    console.print()

    from scribe.utils.ollama_models import (
        available_model_memory_gb,
        list_installed_models,
        select_default_ollama_model,
    )

    console.print(f"[bold {ScribeTheme.SECONDARY}]local llm[/bold {ScribeTheme.SECONDARY}]")
    ollama_base_url = os.getenv("SCRIBE_OLLAMA_BASE_URL")
    ollama_models = list_installed_models(ollama_base_url)
    if ollama_models:
        budget = available_model_memory_gb()
        chosen = select_default_ollama_model(ollama_base_url)
        budget_label = f"{budget:.0f}GB budget" if budget > 0 else "conservative (cpu)"
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]ollama[/{ScribeTheme.TEXT_PRIMARY}]    "
            f"[{ScribeTheme.SUCCESS}]{len(ollama_models)} models[/{ScribeTheme.SUCCESS}] "
            f"[{ScribeTheme.TEXT_MUTED}]· {budget_label}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]auto[/{ScribeTheme.TEXT_PRIMARY}]      "
            f"[{ScribeTheme.TEXT_MUTED}]"
            f"{escape(chosen)} (notes --provider ollama)[/{ScribeTheme.TEXT_MUTED}]"
        )
    else:
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]ollama[/{ScribeTheme.TEXT_PRIMARY}]    "
            f"[{ScribeTheme.TEXT_MUTED}]not running "
            f"(optional, for free local notes)[/{ScribeTheme.TEXT_MUTED}]"
        )
    console.print()

    tx_kind = "GPU" if gpu_config.recommendation == "local" else "CPU"
    notes_bit = " + Ollama notes" if ollama_models else ""
    console.print(
        f"[{ScribeTheme.SUCCESS}]$0 local ready: {tx_kind} transcription{notes_bit}"
        f"[/{ScribeTheme.SUCCESS}]"
    )
    if tx_kind == "CPU":
        console.print(
            f"  [{ScribeTheme.TEXT_MUTED}]CPU is slower; pass --method openai to use "
            f"the paid OpenAI API instead.[/{ScribeTheme.TEXT_MUTED}]"
        )
    console.print()


def _print_api_key_status(console: Console, name: str, configured: bool) -> None:
    status = (
        f"[{ScribeTheme.SUCCESS}]set[/{ScribeTheme.SUCCESS}]"
        if configured
        else f"[{ScribeTheme.TEXT_MUTED}]not set[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(f"  [{ScribeTheme.TEXT_PRIMARY}]{name:<9}[/{ScribeTheme.TEXT_PRIMARY}] {status}")


def run_doctor(console: Console, version: str, live: bool, logger: Logger) -> None:
    """Run diagnostics and render a complete local-readiness report."""
    from scribe.utils.diagnostics import SystemDiagnostics

    console.print()
    doctor_header = (
        f"{brand_header_markup('scribe doctor', fallback_color=ScribeTheme.PRIMARY_BRIGHT)} "
        f"[{ScribeTheme.TEXT_MUTED}]{escape(version)}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(doctor_header)
    if live:
        console.print("[dim]Live provider checks enabled for configured API keys.[/dim]")
    else:
        console.print(
            "[dim]Live provider checks skipped. "
            "Use `scribe doctor --live` to validate API keys.[/dim]"
        )
    console.print()

    diagnostics = SystemDiagnostics()
    with console.status(
        f"[{ScribeTheme.PRIMARY}]Running diagnostics...[/{ScribeTheme.PRIMARY}]",
        spinner="dots",
    ):
        results = diagnostics.run_all_checks(live=live)

    passed = [result for result in results if result.status == "pass"]
    warnings = [result for result in results if result.status == "warn"]
    failures = [result for result in results if result.status == "fail"]

    transcription = next(
        (result for result in results if result.name == "Local Transcription ($0)"), None
    )
    notes = next((result for result in results if result.name == "Local Notes ($0)"), None)
    if transcription is not None:
        can_take_notes = notes is not None and notes.status == "pass"
        if transcription.status == "pass":
            capability = "transcribe and take notes" if can_take_notes else "transcribe"
            console.print(
                f"[bold {ScribeTheme.SUCCESS}]$0 LOCAL[/bold {ScribeTheme.SUCCESS}]  "
                f"[{ScribeTheme.SUCCESS}]You can {capability} on this machine "
                f"with no API key.[/{ScribeTheme.SUCCESS}]"
            )
            console.print(
                f"  [{ScribeTheme.TEXT_MUTED}]transcription: "
                f"{escape(transcription.message)}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if notes is not None:
                console.print(
                    f"  [{ScribeTheme.TEXT_MUTED}]notes: "
                    f"{escape(notes.message)}[/{ScribeTheme.TEXT_MUTED}]"
                )
        else:
            console.print(
                f"[bold {ScribeTheme.WARNING}]$0 LOCAL[/bold {ScribeTheme.WARNING}]  "
                f"[{ScribeTheme.WARNING}]Local transcription needs setup: "
                f"{escape(transcription.message)}[/{ScribeTheme.WARNING}]"
            )
        console.print()

    if failures:
        _print_diagnostic_group(console, "FAILED", failures, ScribeTheme.ERROR, "×")
    if warnings:
        _print_diagnostic_group(console, "WARNINGS", warnings, ScribeTheme.WARNING, "!")

    if passed:
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 1, 0, 0),
            collapse_padding=True,
        )
        table.add_column(style=ScribeTheme.SUCCESS, width=2)
        table.add_column(style=ScribeTheme.TEXT_PRIMARY, width=20)
        table.add_column(style=ScribeTheme.TEXT_MUTED)
        for result in passed:
            first_line = result.message.splitlines()[0] if result.message else ""
            table.add_row("+", escape(result.name), escape(first_line))
        console.print(table)
        console.print()

    pass_count, warn_count, fail_count = diagnostics.get_summary()
    _print_doctor_summary(console, pass_count, warn_count, fail_count)
    console.print()

    if fail_count > 0:
        try:
            from rich.prompt import Confirm

            if Confirm.ask("Run the setup wizard to fix issues?", default=False, console=console):
                from scribe.cli.init import run_wizard

                run_wizard(console=console, force=True)
        except Exception as error:
            logger.debug("Setup-wizard self-heal prompt failed: %s", error)
        raise typer.Exit(1)


def _print_diagnostic_group(
    console: Console,
    heading: str,
    results: Sequence[DiagnosticResult],
    color: str,
    marker: str,
) -> None:
    """Render diagnostic results while treating every result field as literal text."""
    console.print(f"[bold {color}]{heading}[/bold {color}]")
    for result in results:
        name = escape(result.name)
        message = escape(result.message)
        suggestion = result.fix_suggestion
        console.print(
            f"  [{color}]{marker}[/{color}] "
            f"[{ScribeTheme.TEXT_PRIMARY}]{name}[/{ScribeTheme.TEXT_PRIMARY}]"
        )
        console.print(f"    [{ScribeTheme.TEXT_MUTED}]{message}[/{ScribeTheme.TEXT_MUTED}]")
        if suggestion:
            console.print(
                f"    [{ScribeTheme.PRIMARY}]-> {escape(str(suggestion))}[/{ScribeTheme.PRIMARY}]"
            )
    console.print()


def _print_doctor_summary(
    console: Console,
    pass_count: int,
    warn_count: int,
    fail_count: int,
) -> None:
    if fail_count == 0 and warn_count == 0:
        check_label = "check" if pass_count == 1 else "checks"
        console.print(f"[{ScribeTheme.SUCCESS}]+ All systems ready[/] ({pass_count} {check_label})")
        console.print(
            '[dim]Try: [cyan]scribe rec "Team sync"[/cyan] or create a launcher with '
            "[cyan]scribe shortcut[/cyan][/dim]"
        )
    elif fail_count == 0:
        warning_label = "warning" if warn_count == 1 else "warnings"
        console.print(
            f"[{ScribeTheme.WARNING}]Ready with warnings[/] "
            f"({pass_count} passed, {warn_count} {warning_label})"
        )
    else:
        failed_label = "failure" if fail_count == 1 else "failures"
        warning_label = "warning" if warn_count == 1 else "warnings"
        console.print(
            f"[{ScribeTheme.ERROR}]Needs attention[/] "
            f"({fail_count} {failed_label}, {warn_count} {warning_label})"
        )


def run_health_check(
    console: Console,
    provider: str | None,
    force: bool,
    logger: Logger,
) -> None:
    """Check configured AI providers and render a literal, bounded status report."""
    from scribe.providers.health import get_health_monitor

    console.print()
    console.print(brand_header_markup("scribe health", fallback_color=ScribeTheme.PRIMARY_BRIGHT))
    console.print()

    monitor = get_health_monitor()
    api_keys = {
        name: key
        for name, key in (
            ("openai", os.getenv("OPENAI_API_KEY")),
            ("xai", os.getenv("XAI_API_KEY")),
            ("anthropic", os.getenv("ANTHROPIC_API_KEY")),
            ("gemini", os.getenv("GEMINI_API_KEY")),
        )
        if key
    }
    provider_key_names = {
        "openai": "OPENAI_API_KEY",
        "xai": "XAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    normalized_provider = provider.strip().lower() if provider is not None else None
    if normalized_provider is not None and normalized_provider not in provider_key_names:
        console.print(
            f"[{ScribeTheme.ERROR}]Unknown provider: {escape(provider or '')}[/{ScribeTheme.ERROR}]"
        )
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]Choose one of: openai, xai, anthropic, gemini."
            f"[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    if not api_keys:
        console.print(f"[{ScribeTheme.WARNING}]no api keys configured[/{ScribeTheme.WARNING}]")
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]set OPENAI_API_KEY, XAI_API_KEY, etc."
            f"[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    if normalized_provider is not None and normalized_provider not in api_keys:
        key_name = provider_key_names[normalized_provider]
        console.print(
            f"[{ScribeTheme.WARNING}]{key_name} is not configured[/{ScribeTheme.WARNING}]"
        )
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]Set {key_name}, then retry "
            f"`scribe health --provider {normalized_provider}`.[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    providers_to_check = [normalized_provider] if normalized_provider else list(api_keys)
    all_healthy = True
    results: list[tuple[str, bool, str]] = []
    for provider_name in providers_to_check:
        if provider_name is None or provider_name not in api_keys:
            continue
        try:
            status = monitor.check_provider_health(
                provider_name, api_keys[provider_name], force=force
            )
            if status.is_healthy:
                response_time = (
                    f"{status.response_time_ms:.0f}ms"
                    if status.response_time_ms is not None
                    else ""
                )
                results.append((provider_name, True, response_time))
            else:
                results.append((provider_name, False, status.error_message or "error"))
                all_healthy = False
        except ScribeError as error:
            results.append((provider_name, False, str(error)[:30]))
            all_healthy = False
        except Exception as error:
            logger.debug("Provider health check failed for %s: %s", provider_name, error)
            results.append((provider_name, False, str(error)[:30]))
            all_healthy = False

    for name, healthy, detail in results:
        marker = "+" if healthy else "x"
        color = ScribeTheme.SUCCESS if healthy else ScribeTheme.ERROR
        console.print(
            f"  [{color}]{marker}[/{color}] "
            f"[{ScribeTheme.TEXT_PRIMARY}]{name:<12}[/{ScribeTheme.TEXT_PRIMARY}]"
            f"[{ScribeTheme.TEXT_MUTED}]{escape(detail)}[/{ScribeTheme.TEXT_MUTED}]"
        )
    console.print()

    if all_healthy:
        console.print(f"[{ScribeTheme.SUCCESS}]all providers healthy[/{ScribeTheme.SUCCESS}]")
    else:
        console.print(f"[{ScribeTheme.WARNING}]some providers have issues[/{ScribeTheme.WARNING}]")
    console.print()
    if not all_healthy:
        raise typer.Exit(1)


def create_support_bundle(console: Console, output: Path | None) -> None:
    """Create a redacted support bundle and explain its privacy boundary."""
    from scribe.utils.support_bundle import generate_support_bundle_cli

    console.print()
    console.print(Panel.fit(brand_header_markup("Generating Support Bundle"), border_style="cyan"))
    console.print()

    output_dir = output if output else Path.cwd()
    console.print("[cyan]Collecting system information...[/cyan]")
    console.print("[cyan]Running diagnostics...[/cyan]")
    console.print("[cyan]Gathering durable session and log metadata...[/cyan]")
    bundle_path = generate_support_bundle_cli(output_dir)

    console.print()
    console.print("[bold green]Support bundle created successfully[/bold green]")
    console.print()
    console.print(f"[cyan]Location:[/cyan] {escape(str(bundle_path))}", soft_wrap=True)
    console.print()
    console.print("[dim]This bundle contains:[/dim]")
    console.print("[dim]  - System information (OS, Python, GPU)[/dim]")
    console.print("[dim]  - Redacted environment configuration[/dim]")
    console.print("[dim]  - Diagnostic results[/dim]")
    console.print("[dim]  - Redacted recent session summaries[/dim]")
    console.print("[dim]  - Recent log metadata[/dim]")
    console.print()
    console.print("Log contents are not included.")
    console.print("Automated redaction covers known home-identifier and credential patterns.")
    console.print("[bold]Review the file before sharing it for troubleshooting.[/bold]")
    console.print()
