"""Best-guess real names for diarized speakers, from a local or cloud language model.

Diarization labels speakers anonymously (SPEAKER_00, SPEAKER_01, ...). People
usually reveal names in conversation: introductions ("I'm Dana"), direct address
("Thanks, Dana" followed by Dana's reply), and hand-offs ("Sam, any thoughts?").
This module asks a language model to map labels to names from that evidence.

Language models readily invent names and often attribute a name to whoever says
it, so the model only proposes which names occur. Each name is then assigned by
counting evidence across every mention (see ``score_name``): the speakers next
to a mention gain, the speaker who says it loses, and a self-introduction counts
strongly. A name is assigned only with a clear lead, and anything ambiguous stays
unidentified. The result is a best guess that the transcript header presents for
easy correction.

Naming is opt-in and defaults to the local Ollama model. A cloud provider is used
only when configured explicitly (SCRIBE_SPEAKERS_PROVIDER or [providers]
speakers_provider), and local-only mode always keeps it local.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from scribe.utils.logging import get_logger

if TYPE_CHECKING:
    from scribe.models.transcript import Transcript
    from scribe.providers.base import AIProvider

logger = get_logger(__name__)

FEATURE = "speakers"
_MAX_NAME_CHARS = 40
#: Transcript characters sent to the model: the start (introductions) and the end
#: (thanks and goodbyes) carry most naming evidence.
_HEAD_CHARS = 18000
_TAIL_CHARS = 8000

_SYSTEM_PROMPT = """You identify the real names of people in a meeting transcript.
The transcript was labeled by automatic speaker diarization, so labels such as
SPEAKER_00 are anonymous and occasionally wrong for a sentence or two.

Rules:
1. Name a speaker only with direct evidence in the transcript: the speaker
   introduces themself ("I'm Dana", "this is Dana"), or someone addresses them by
   name and they answer in the next turn, or several remarks consistently point
   to the same person.
2. A name a speaker says is usually someone else's name. People say the names of
   the people they are talking to or about, not their own.
3. When someone says "Thanks, Dana" or "Dana, what do you think?", Dana is
   usually the speaker right before or right after, not the one talking.
4. Never guess or invent. If the evidence is weak or missing, use null.
5. Each name belongs to at most one speaker.
6. The evidence must be a short quote (at most 12 words) copied exactly from the
   transcript that contains the name.
7. Also list in "people" every person's first name that is spoken anywhere in
   the meeting, whether or not you can tell which speaker they are.

Return only JSON, no commentary."""

#: JSON Schema for the reply. Ollama uses it for constrained decoding; other
#: providers receive it as an instruction.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "string"},
                },
                "required": ["label", "name", "confidence", "evidence"],
            },
        },
        "people": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["speakers", "people"],
}
#: Output budget: the reply is a short JSON object, one entry per speaker.
_MAX_OUTPUT_TOKENS = 1500
#: The model only proposes names (scoring assigns them), so a mid-size local model
#: is enough; capping its memory keeps it fast and leaves VRAM for everything else.
_LOCAL_MODEL_BUDGET_GB = 12.0
#: Naming is an enhancement; give up rather than hold the pipeline for long.
_REQUEST_TIMEOUT_SECONDS = 180


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _turns(transcript: Transcript) -> list[tuple[str, float, str]]:
    """Speaker turns as (label, start, text), merging consecutive same-speaker segments."""
    turns: list[tuple[str, float, str]] = []
    for segment in transcript.segments:
        text = segment.text.strip()
        if not text or not segment.speaker:
            continue
        if turns and turns[-1][0] == segment.speaker:
            label, start, previous = turns[-1]
            turns[-1] = (label, start, f"{previous} {text}")
        else:
            turns.append((segment.speaker, segment.start, text))
    return turns


def transcript_excerpt(transcript: Transcript) -> str:
    """Speaker-labeled lines, one per turn, trimmed to the head and tail budget."""
    lines = [f"[{_clock(start)}] {label}: {text}" for label, start, text in _turns(transcript)]
    full = "\n".join(lines)
    if len(full) <= _HEAD_CHARS + _TAIL_CHARS:
        return full
    head = full[:_HEAD_CHARS].rsplit("\n", 1)[0]
    tail = full[-_TAIL_CHARS:].split("\n", 1)[-1]
    return f"{head}\n[... middle of the meeting omitted ...]\n{tail}"


def build_messages(transcript: Transcript) -> list[dict[str, Any]]:
    """Chat messages asking for a label-to-name mapping."""
    labels = ", ".join(transcript.speakers)
    user = (
        f"Speakers to identify: {labels}\n\n"
        f"Transcript:\n{transcript_excerpt(transcript)}\n\n"
        "Identify each speaker's name following the rules. Include every label."
    )
    return [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w']+", " ", text.lower()).split())


def _extract_json(content: str) -> Any:
    """Parse the first JSON object in a model reply, tolerating code fences and prose."""
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the model reply")
    return json.loads(content[start : end + 1])


_SELF_INTRO = r"(?:\bi'm|\bi am|\bthis is|\bmy name is|\bit's)\s+{name}\b|\b{name}\s+here\b"
#: Scoring: a turn that says a name points to the speakers on either side of it;
#: saying a name counts against being that person (people rarely say their own
#: name except to introduce themselves, which counts strongly for).
_ADJACENT_POINTS = 1
_SELF_MENTION_POINTS = -2
_SELF_INTRO_POINTS = 3
_MODEL_HINT_POINTS = 1
#: A name is assigned only with at least this score and a clear lead: ahead of the
#: next most likely speaker by this margin, or at least double its score.
_MIN_SCORE = 2
_MIN_MARGIN = 2


def score_name(
    first_name: str, turns: list[tuple[str, float, str]], labels: list[str]
) -> tuple[dict[str, int], str | None]:
    """Per-speaker evidence scores for a first name, and a supporting quote.

    Every turn that contains the name adds a point to the speakers just before
    and after it (someone thanked is usually the previous speaker; someone asked
    a question is usually the next), subtracts from the speaker who said it, and
    adds strongly for a self-introduction.
    """
    scores = dict.fromkeys(labels, 0)
    pattern = re.compile(rf"\b{re.escape(first_name)}\b")
    intro = re.compile(_SELF_INTRO.format(name=re.escape(first_name)))
    quote: str | None = None
    for i, (speaker, _, text) in enumerate(turns):
        normalized = _normalize(text)
        if not pattern.search(normalized):
            continue
        if intro.search(normalized):
            scores[speaker] = scores.get(speaker, 0) + _SELF_INTRO_POINTS
            quote = quote or _quote_around(text, first_name)
            continue
        scores[speaker] = scores.get(speaker, 0) + _SELF_MENTION_POINTS
        for j in (i - 1, i + 1):
            if 0 <= j < len(turns) and turns[j][0] != speaker:
                scores[turns[j][0]] = scores.get(turns[j][0], 0) + _ADJACENT_POINTS
        quote = quote or _quote_around(text, first_name)
    return scores, quote


def _quote_around(text: str, first_name: str, width: int = 60) -> str:
    """A short excerpt of ``text`` around the first mention of a name."""
    match = re.search(rf"(?i)\b{re.escape(first_name)}\b", text)
    if not match:
        return text[: width * 2].strip()
    start = max(0, match.start() - width)
    return text[start : match.end() + width].strip()


def _candidate_names(entries: list[Any], corpus: str, labels: set[str]) -> dict[str, str | None]:
    """Plausible person names proposed by the model, with the label it suggested."""
    names: dict[str, str | None] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().strip(".,")
        if not name or len(name) > _MAX_NAME_CHARS or name.lower() in ("null", "none", "unknown"):
            continue
        if re.fullmatch(r"(?i)speaker[_ ]?\d+", name):
            continue
        normalized = _normalize(name)
        first = normalized.split(" ")[0] if normalized else ""
        if not first or f" {first} " not in f" {corpus} ":
            logger.debug(f"Speaker naming: '{name}' does not occur in the transcript")
            continue
        label = str(entry.get("label") or "")
        names.setdefault(name, label if label in labels else None)
    return names


def _salvage_names(content: str) -> dict[str, Any]:
    """Recover proposed names from a malformed or truncated JSON reply."""
    names = re.findall(r'"name"\s*:\s*"([^"]{1,40})"', content)
    people = re.search(r'"people"\s*:\s*\[([^\]]*)', content)
    if people:
        names += re.findall(r'"([^"]{1,40})"', people.group(1))
    return {"speakers": [], "people": names}


def validate_names(content: str, transcript: Transcript) -> dict[str, dict[str, Any]]:
    """Assign model-proposed names to speakers using evidence from the transcript.

    The model only proposes which person names occur; the assignment is decided
    by :func:`score_name` over every mention, so a model that attributes a name
    to whoever says it cannot mislabel a speaker. A name is assigned only with a
    clear lead. When one speaker collects several names (often two similar voices
    merged by diarization), the strongest is used and the rest are listed as
    alternatives.
    """
    try:
        payload = _extract_json(content)
    except (ValueError, json.JSONDecodeError) as e:
        # A truncated reply still names people; scoring decides who is who.
        payload = _salvage_names(content)
        if not payload["people"]:
            logger.warning(f"Speaker naming reply was not valid JSON: {e}")
            return {}
    entries = payload.get("speakers") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {}
    people = payload.get("people") if isinstance(payload.get("people"), list) else []
    entries = [*entries, *({"name": str(person)} for person in people)]

    labels = transcript.speakers
    corpus = _normalize(" ".join(segment.text for segment in transcript.segments))
    turns = _turns(transcript)

    claims: dict[str, list[tuple[int, str, str, str]]] = {}
    for name, hinted in _candidate_names(entries, corpus, set(labels)).items():
        first = _normalize(name).split(" ")[0]
        scores, quote = score_name(first, turns, labels)
        if hinted is not None:
            scores[hinted] = scores.get(hinted, 0) + _MODEL_HINT_POINTS
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_label, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        clear_lead = best - runner_up >= _MIN_MARGIN or runner_up * 2 <= best
        if best < _MIN_SCORE or not clear_lead:
            logger.debug(f"Speaker naming: evidence for '{name}' is ambiguous ({scores})")
            continue
        confidence = "high" if best >= 4 and best - runner_up >= 3 else "medium"
        claims.setdefault(best_label, []).append((best, name, confidence, quote or ""))

    accepted: dict[str, dict[str, Any]] = {}
    for label, options in claims.items():
        options.sort(key=lambda option: option[0], reverse=True)
        _score, name, confidence, quote = options[0]
        entry: dict[str, Any] = {"name": name, "confidence": confidence, "evidence": quote}
        if len(options) > 1:
            entry["alternatives"] = [option[1] for option in options[1:]]
        accepted[label] = entry
    return accepted


def identify_speakers(transcript: Transcript, provider: AIProvider) -> dict[str, dict[str, Any]]:
    """Ask ``provider`` for speaker names and return only the verified ones."""
    if not transcript.speakers:
        return {}
    extra: dict[str, Any] = {}
    if provider.config.provider_name == "ollama":
        # Reasoning models (Qwen3, Gemma 4) otherwise think at length before
        # answering; this task needs a short structured answer.
        extra["think"] = False
        # Unload right after answering so the local model never holds GPU memory
        # that the next transcription needs.
        extra["keep_alive"] = 0
    provider.config.timeout = min(provider.config.timeout, _REQUEST_TIMEOUT_SECONDS)
    response = provider.chat_completion_with_json(
        build_messages(transcript),
        json_schema=_SCHEMA,
        max_tokens=_MAX_OUTPUT_TOKENS,
        temperature=0.0,
        **extra,
    )
    names = validate_names(str(response.get("content") or ""), transcript)
    source = f"{provider.config.provider_name}:{provider.config.model}"
    return {label: {**entry, "source": source} for label, entry in names.items()}


def resolve_provider() -> AIProvider | None:
    """The configured naming provider, or None (with the reason logged) if unusable.

    Defaults to local Ollama. Returns None when Ollama is selected but not running
    or has no models, so naming never blocks or fails a transcription.
    """
    import os

    from scribe.providers.factory import _config_provider, _local_only_enabled, get_provider

    name = (
        "ollama"
        if _local_only_enabled()
        else (os.getenv("SCRIBE_SPEAKERS_PROVIDER") or _config_provider(FEATURE) or "ollama")
    ).lower()

    if name == "ollama":
        from scribe.utils.ollama_models import list_installed_models

        try:
            installed = list_installed_models(os.getenv("SCRIBE_OLLAMA_BASE_URL"), timeout=3.0)
        except Exception:
            installed = []
        if not installed:
            logger.info(
                "Speaker naming skipped: no local model is available (start Ollama and pull "
                "a model), or set SCRIBE_SPEAKERS_PROVIDER to openai, openrouter, anthropic, "
                "gemini, or xai to use a cloud model"
            )
            return None

    model = os.getenv("SCRIBE_SPEAKERS_MODEL") or None
    if name == "ollama" and model is None:
        from scribe.utils.ollama_models import available_model_memory_gb, select_ollama_model

        budget = min(available_model_memory_gb() or _LOCAL_MODEL_BUDGET_GB, _LOCAL_MODEL_BUDGET_GB)
        model = select_ollama_model(installed, budget)
    try:
        return get_provider(FEATURE, provider_name=name, model=model)
    except (ValueError, ImportError) as e:
        logger.info(f"Speaker naming skipped: {e}")
        return None


def name_speakers(transcript: Transcript) -> dict[str, dict[str, Any]]:
    """Best-guess names for ``transcript``'s speakers; empty on any failure."""
    if len(transcript.speakers) == 0:
        return {}
    provider = resolve_provider()
    if provider is None:
        return {}
    try:
        logger.info(
            f"Identifying speaker names with {provider.config.provider_name} "
            f"({provider.config.model})"
        )
        names = identify_speakers(transcript, provider)
    except Exception as e:
        logger.warning(f"Speaker naming failed, keeping speaker labels: {e}")
        return {}
    logger.info(f"Speaker naming identified {len(names)} of {len(transcript.speakers)} speakers")
    return names
