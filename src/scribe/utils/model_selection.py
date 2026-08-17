"""
Effective local Whisper model resolution.

The configured `default_model` is a preference, not a promise: when the user has
not pinned a model, Scribe auto-tunes it to the detected hardware, so a CPU-only
machine runs a smaller model than the `large-v3` default.

This module exists so the transcription pipeline and `scribe info` answer
"which model will actually run?" the same way. Reporting the configured value
where the effective value differs tells a CPU user their run will use a model it
will not use.
"""


def resolve_local_model[ModelT](
    configured_model: ModelT,
    configured_fields: set[str],
    recommended_model: ModelT,
) -> tuple[ModelT, bool]:
    """
    Resolve the local Whisper model that will actually be used.

    An explicitly pinned model always wins; hardware auto-tuning applies only to
    the untouched default.

    Args:
        configured_model: The model currently set on the config.
        configured_fields: Names the user explicitly set (Pydantic's
            ``model_fields_set``), used to tell an explicit choice from a default.
        recommended_model: The model the detected hardware suggests.

    Returns:
        Tuple of (effective model, whether hardware overrode the default).
    """
    if "default_model" in configured_fields:
        return configured_model, False
    return recommended_model, recommended_model != configured_model
