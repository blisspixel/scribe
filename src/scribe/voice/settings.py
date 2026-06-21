"""Settings and pure helpers for the resident voice tray utility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from scribe.cli.voice import resolve_inject_method
from scribe.config_file import load_config_file
from scribe.models.gpu import GPUConfig
from scribe.voice.tts import resolve_tts_speed

TrayProfile = Literal["fast", "balanced", "accurate"]
TrayActivation = Literal["toggle", "hold"]

TRAY_PROFILES: tuple[TrayProfile, ...] = ("fast", "balanced", "accurate")
TRAY_ACTIVATIONS: tuple[TrayActivation, ...] = ("toggle", "hold")
DEFAULT_DICTATE_HOTKEY = "f9"
DEFAULT_READ_HOTKEY = "f8"

_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "option": "alt",
    "menu": "alt",
    "command": "cmd",
    "meta": "cmd",
    "win": "cmd",
    "windows": "cmd",
    "return": "enter",
    "escape": "esc",
    "spacebar": "space",
}
_MODIFIER_ORDER = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}


@dataclass(frozen=True)
class HotkeySpec:
    """Canonical hotkey representation used by the live keyboard listener."""

    canonical: str
    parts: frozenset[str]


@dataclass(frozen=True)
class TraySettings:
    """Configuration for the resident voice service."""

    profile: TrayProfile = "balanced"
    activation: TrayActivation = "toggle"
    dictate_hotkey: str = DEFAULT_DICTATE_HOTKEY
    read_hotkey: str = DEFAULT_READ_HOTKEY
    inject: str = "paste"
    stt_model: str | None = None
    language: str | None = None
    tts_rate: int | None = None
    tts_voice: str | None = None
    tts_backend: str = "auto"
    tts_speed: float = 1.0
    sample_rate: int = 16000
    min_audio_seconds: float = 0.25
    append_space: bool = True
    restore_clipboard: bool = True
    # Resident tray keeps a model warm by default so the first dictation is
    # instant; opt out with `scribe tray --no-preload`.
    preload_model: bool = True
    show_notifications: bool = True

    @property
    def dictate_spec(self) -> HotkeySpec:
        return parse_hotkey(self.dictate_hotkey)

    @property
    def read_spec(self) -> HotkeySpec:
        return parse_hotkey(self.read_hotkey)


def normalize_hotkey(value: str) -> str:
    """Normalize a user-entered hotkey such as ``Ctrl + Alt + Space``."""
    return parse_hotkey(value).canonical


def parse_hotkey(value: str) -> HotkeySpec:
    """Parse a hotkey into canonical parts.

    Supported forms are single keys (``f9``) and modifier chords
    (``ctrl+alt+space``). The live service treats a chord as active while all
    parts are held.
    """
    raw_parts = [p.strip().lower() for p in value.replace("-", "+").split("+") if p.strip()]
    if not raw_parts:
        raise ValueError("Hotkey cannot be empty.")

    normalized: list[str] = []
    for part in raw_parts:
        key = _ALIASES.get(part, part)
        if not _valid_hotkey_part(key):
            raise ValueError(f"Unsupported hotkey part: {part}")
        if key not in normalized:
            normalized.append(key)

    normalized.sort(key=lambda part: (_MODIFIER_ORDER.get(part, 99), part))
    return HotkeySpec(canonical="+".join(normalized), parts=frozenset(normalized))


def resolve_tray_profile(value: str | None) -> TrayProfile:
    """Validate the tray profile."""
    resolved = (value or "balanced").strip().lower()
    if resolved not in TRAY_PROFILES:
        raise ValueError(f"--profile must be one of {', '.join(TRAY_PROFILES)}, got '{value}'")
    return resolved


def resolve_tray_activation(value: str | None) -> TrayActivation:
    """Validate the hotkey activation mode.

    ``toggle`` (tap to start, tap again to stop) is the default and matches how
    Windows Voice Access, macOS hands-free dictation, and Edge/macOS read-aloud
    behave. ``hold`` is the push-to-talk fallback (hold to speak, release to stop).
    """
    resolved = (value or "toggle").strip().lower()
    if resolved not in TRAY_ACTIVATIONS:
        raise ValueError(
            f"--activation must be one of {', '.join(TRAY_ACTIVATIONS)}, got '{value}'"
        )
    return resolved


def model_for_profile(
    profile: TrayProfile, gpu: GPUConfig, explicit_model: str | None = None
) -> str:
    """Pick a default local STT model for the profile and detected hardware."""
    if explicit_model:
        return explicit_model
    if not gpu.has_gpu or not gpu.cuda_available:
        return {"fast": "base", "balanced": "base", "accurate": "small"}[profile]
    if gpu.gpu_memory_gb >= 12:
        # Dictation is short-utterance and latency-first: a big GPU does not mean a
        # big model is the right default. "small" loads fast (and is commonly already
        # cached), stays resident, and is plenty accurate. "accurate" opts into
        # large-v3-turbo: ~6GB and ~8x faster than large-v3 at near-equal accuracy
        # with full multilingual support - the best accuracy/latency point for
        # dictation on any 12GB+ card.
        return {"fast": "base", "balanced": "small", "accurate": "large-v3-turbo"}[profile]
    return {"fast": "base", "balanced": "small", "accurate": "small"}[profile]


def resolve_tray_settings(
    *,
    profile: str | None = None,
    activation: str | None = None,
    dictate_hotkey: str | None = None,
    read_hotkey: str | None = None,
    inject: str | None = None,
    model: str | None = None,
    language: str | None = None,
    preload: bool | None = None,
    speed: float | None = None,
) -> TraySettings:
    """Resolve tray settings from config plus explicit CLI overrides."""
    table = _tray_table(load_config_file())

    resolved_profile = resolve_tray_profile(_pick(profile, table.get("profile"), "balanced"))
    resolved_activation = resolve_tray_activation(
        _pick(activation, table.get("activation"), "toggle")
    )
    resolved_inject = resolve_inject_method(_pick(inject, table.get("inject"), "paste"))
    resolved_dictate = normalize_hotkey(
        str(_pick(dictate_hotkey, table.get("dictate_hotkey"), DEFAULT_DICTATE_HOTKEY))
    )
    resolved_read = normalize_hotkey(
        str(_pick(read_hotkey, table.get("read_hotkey"), DEFAULT_READ_HOTKEY))
    )
    if resolved_dictate == resolved_read:
        raise ValueError("Dictation and read-aloud hotkeys must be different.")

    return TraySettings(
        profile=resolved_profile,
        activation=resolved_activation,
        dictate_hotkey=resolved_dictate,
        read_hotkey=resolved_read,
        inject=resolved_inject,
        stt_model=_optional_str(_pick(model, table.get("stt_model"), None)),
        language=_optional_str(_pick(language, table.get("language"), None)),
        tts_rate=_optional_int(table.get("tts_rate")),
        tts_voice=_optional_str(table.get("tts_voice")),
        tts_backend=_optional_str(table.get("tts_backend")) or "auto",
        tts_speed=resolve_tts_speed(speed if speed is not None else table.get("tts_speed")),
        sample_rate=_positive_int(table.get("sample_rate"), 16000),
        min_audio_seconds=_positive_float(table.get("min_audio_seconds"), 0.25),
        append_space=_optional_bool(table.get("append_space"), True),
        restore_clipboard=_optional_bool(table.get("restore_clipboard"), True),
        preload_model=_optional_bool(_pick(preload, table.get("preload_model"), True), True),
        show_notifications=_optional_bool(table.get("show_notifications"), True),
    )


def _valid_hotkey_part(part: str) -> bool:
    if part in {"ctrl", "alt", "shift", "cmd", "space", "enter", "esc", "tab", "backspace"}:
        return True
    if len(part) == 1 and part.isalnum():
        return True
    if part.startswith("f") and part[1:].isdigit():
        number = int(part[1:])
        return 1 <= number <= 24
    return False


def _tray_table(config: dict[str, Any]) -> dict[str, Any]:
    voice = config.get("voice")
    if isinstance(voice, dict):
        tray = voice.get("tray")
        if isinstance(tray, dict):
            return tray
    return {}


def _pick(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: Any, default: int) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else default


def _positive_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _optional_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
