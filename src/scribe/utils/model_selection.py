"""Shared file-transcription policy, independent of hardware and voice profiles."""

from scribe.models.options import FileQuality, ModelSize

_PROFILE_MODELS: dict[FileQuality, ModelSize] = {
    "accurate": "large-v3",
    "balanced": "large-v3-turbo",
    "fast": "small",
}


def resolve_local_model(
    configured_model: ModelSize,
    configured_fields: set[str],
    quality: FileQuality = "accurate",
) -> tuple[ModelSize, bool]:
    """An explicit model wins; otherwise use the requested file quality profile.

    Hardware controls the engine and memory use, never the model's identity.
    The boolean indicates whether the profile changed the configured default.
    """
    if "default_model" in configured_fields:
        return configured_model, False
    model = _PROFILE_MODELS[quality]
    return model, model != configured_model


def resolve_local_batch_size(quality: FileQuality, configured: int | None) -> int | None:
    """Prefer conditioned sequential decoding for accuracy unless explicitly set."""
    if configured is not None:
        return configured
    return 0 if quality == "accurate" else None


def resolve_local_language(
    forced_language: str | None, auto_detect: bool, primary_language: str
) -> str | None:
    """Explicit language wins; primary is a manual preset, never an auto prior."""
    if forced_language is not None:
        return forced_language
    return None if auto_detect else primary_language


def local_resource_guidance(model: str) -> str:
    """Describe planning estimates, not a fit guarantee or an invented runtime."""
    if model.startswith("large") or model == "turbo":
        return (
            "Plan for several GB of free RAM; full large-v3 CPU int8 weights alone are "
            "about 1.6 GB. CUDA float16 sequential decoding typically needs about 5 GB "
            "free VRAM, with more for batching and speaker labels. Native builds differ."
        )
    return "Memory use depends on model, engine, audio length and speaker labels."
