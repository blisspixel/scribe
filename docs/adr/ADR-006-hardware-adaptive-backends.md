# ADR-006: Hardware-adaptive local transcription backends

## Status

Accepted (2026-06).

## Context

Local transcription was CUDA-only. `LocalWhisperTranscriber` hardcoded
`faster_whisper.WhisperModel` and chose `device="cuda"` whenever a GPU was present,
falling back to faster-whisper on the CPU otherwise. That leaves real local
acceleration on the table for everyone not on an NVIDIA card: Apple Silicon (where
mlx-whisper runs Whisper on the Metal GPU far faster than CPU faster-whisper) and
AMD/Intel machines (served by whisper.cpp's Metal/Vulkan/ROCm builds). There was no
seam to add an engine without editing the one transcriber.

## Decision

Introduce a backend abstraction under `core/backends/`:

- `base.TranscriptionBackend`: an ABC with `is_available()` and a single
  `transcribe(audio) -> Transcript` method. Every backend produces the shared
  `Transcript` model (ADR-005), so the writers and the `.txt` formatter are unchanged.
- Concrete backends: `FasterWhisperBackend` (NVIDIA CUDA and the CPU int8 floor, by
  wrapping the existing engine so that path stays byte-for-byte identical),
  `MLXWhisperBackend` (Apple Silicon), `WhisperCppBackend` (AMD/Intel/Apple via
  pywhispercpp).
- `hardware.detect_hardware()` classifies the machine as a `(vendor, memory_gb)` pair.
  NVIDIA detection reuses `GPUConfig` so there is one source of truth for CUDA; AMD is
  probed before NVIDIA because ROCm masquerades as CUDA.
- `registry.select_backend(hardware, override, available)` is a pure, total function
  that maps vendor to an engine through a per-vendor preference list, honoring a
  `SCRIBE_LOCAL_BACKEND` / `config.local_backend` override when it names an available
  backend, and always terminating at the CPU floor.

The `.txt` writer was lifted out of `LocalWhisperTranscriber` into a module-level
`write_clean_transcript` so every backend emits identical plain text. mlx-whisper and
whisper.cpp ship as optional extras (`scribe[mlx]`, `scribe[whispercpp]`); a missing
extra means `is_available()` is False and the registry falls back rather than erroring.

## Selection matrix

| Vendor | Preference order |
| --- | --- |
| nvidia | faster-whisper |
| apple | mlx, whispercpp, cpu |
| amd | whispercpp, cpu |
| intel | whispercpp, cpu |
| cpu | cpu |

`cpu` resolves to faster-whisper running on the CPU, which is always present in the
base install, so selection is total: every machine gets a working engine.

## Consequences

- The base install is unchanged (NVIDIA/CPU + API). New engines are opt-in extras, so
  no heavy or platform-specific wheels enter the default dependency set.
- NVIDIA users see no behavioral change: their path still runs through
  `LocalWhisperTranscriber` with the same model load, VAD, beam width, and silence
  pre-pass, verified by the unchanged local-whisper tests.
- `select_backend` and `detect_hardware` are unit-tested across the full hardware and
  availability matrix, including a property test asserting totality and determinism.
  The mlx and whisper.cpp result-to-Transcript mappings are tested with fake modules.
- Honesty on coverage: the mlx and whisper.cpp engines cannot be run end to end on the
  NVIDIA/Windows development host, nor mlx anywhere but Apple Silicon. Their pure
  mapping and dispatch logic is covered; the live model runs are validated on the
  target hardware (a copy-paste Mac recipe is in the README) rather than claimed here.
- `scribe info` now reports the detected vendor, the selected backend, and which
  optional engines are installed.
