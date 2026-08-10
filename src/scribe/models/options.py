"""Dependency-free public option types shared by CLI and runtime models."""

from typing import Literal

TranscriptionMethod = Literal["auto", "local", "openai"]
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
