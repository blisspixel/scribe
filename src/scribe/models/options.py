"""Dependency-free public option types shared by CLI and runtime models."""

from typing import Literal

TranscriptionMethod = Literal["auto", "local", "openai", "openrouter"]
FileQuality = Literal["max", "accurate", "balanced", "fast"]
VerificationPolicy = Literal["required", "best-effort", "off"]
LocalComputeType = Literal["float32", "float16", "int8", "int8_float32", "int8_float16"]
ModelSize = Literal[
    "tiny",
    "base",
    "small",
    "medium",
    "large",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "turbo",
]
