"""Recording-wide language observations and conservative decoding boundaries."""

from dataclasses import dataclass

from scribe.models.transcription_review import LanguageWindow

WINDOW_SECONDS = 15.0
WINDOW_STRIDE = 7.5


@dataclass(frozen=True)
class AudioRegion:
    start: float
    end: float
    language: str | None
    uncertain: bool


def scan_bounds(duration: float) -> list[tuple[float, float]]:
    """Cover the whole timeline, including the terminal short window."""
    bounds = []
    start = 0.0
    while start < duration:
        bounds.append((start, min(start + WINDOW_SECONDS, duration)))
        start += WINDOW_STRIDE
    return bounds


def decoding_regions(
    duration: float, windows: list[LanguageWindow], forced_language: str | None
) -> list[AudioRegion]:
    """Merge stable language cells; uncertain cells never carry previous text."""
    regions: list[AudioRegion] = []
    start = 0.0
    while start < duration:
        end = min(start + WINDOW_STRIDE, duration)
        midpoint = (start + end) / 2
        covering = [window for window in windows if window.start <= midpoint < window.end]
        languages = {window.stable_language for window in covering}
        stable = bool(covering) and len(languages) == 1 and None not in languages
        language = forced_language or (next(iter(languages)) if stable else None)
        uncertain = not stable
        if (
            regions
            and not uncertain
            and not regions[-1].uncertain
            and regions[-1].language == language
            and end - regions[-1].start <= 300
        ):
            previous = regions.pop()
            regions.append(AudioRegion(previous.start, end, language, False))
        else:
            regions.append(AudioRegion(start, end, language, uncertain))
        start = end
    return regions
