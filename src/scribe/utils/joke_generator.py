# scribe/utils/joke_generator.py

"""
Agentic AI Humor Generation for Meeting Transcripts (text-only, GPT-5 + Responses API)

- Text transcripts only: sends transcript inline (no file uploads)
- Uses OpenAI Responses API with GPT-5
- Accepts API key as raw string (backward CLI compat) or HumorConfig
- Safety: focus humor on concepts/processes; avoid individuals/protected groups
- Robustness: exponential backoff; auto-ramp max_output_tokens on truncation; single refinement for length
- Determinism: seedable archetype selection; optional archetype override
- Diagnostics:
    * HUMOR_LOG_LEVEL=DEBUG for verbose logs
    * HUMOR_DEBUG=1 to log redacted request/response skeletons
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dotenv import find_dotenv, load_dotenv
from openai import AuthenticationError, OpenAI

from scribe.utils.transcript_loader import load_transcript_text

# -----------------------------------------------------------------------------
# .env and logging
# -----------------------------------------------------------------------------
load_dotenv(find_dotenv(usecwd=True), override=False)

logger = logging.getLogger("agentic_humor")
# Use universal SCRIBE_LOG_LEVEL, fall back to HUMOR_LOG_LEVEL for backward compat
log_level_name = os.getenv("SCRIBE_LOG_LEVEL") or os.getenv("HUMOR_LOG_LEVEL") or "WARNING"
level = getattr(logging, log_level_name.upper(), logging.WARNING)
logger.setLevel(level)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(level)  # Set handler level too
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
logger.propagate = False  # Don't propagate to root logger

# -----------------------------------------------------------------------------
# Archetypes
# -----------------------------------------------------------------------------
ARCHETYPE_DISPLAY_NAMES: dict[str, str] = {
    "trickster": "The Trickster-Employee",
    "fool_scholar": "The Fool-Scholar",
    "enthusiast": "The Devout Enthusiast",
    "translator": "The Jargon Translator",
    "digital_specter": "The Digital Specter",
    "existential": "The Existential Clerk",
    "empathic": "The Empathic Realist",
    "time_alchemist": "The Time Alchemist",
    "based": "The Based Observer",
    "gen_z": "The Gen Z Commentator",
}

COMEDY_STYLES: dict[str, str] = {
    "trickster": (
        "You are the Trickster-Employee. Reframe meaning through playful subversion. "
        "Expose gaps between stated intent and outcome without cruelty. One line, 10-15 words."
    ),
    "fool_scholar": (
        "You are the Fool-Scholar. Treat mundane meetings as research subjects. "
        "Deadpan analysis that validates confusion. One line, 12-18 words."
    ),
    "enthusiast": (
        "You are the Devout Enthusiast. Celebrate bureaucratic minutiae with epic sincerity. "
        "Warm, ironically earnest. One line, 10-15 words."
    ),
    "translator": (
        "You are the Jargon Translator. Reveal reality beneath corporate language with precise, plain speech. "
        "One line, 10-15 words."
    ),
    "digital_specter": (
        "You are the Digital Specter. Meta-comment on the medium (mute, lag, screens). "
        "Wry, aware. One line, 10-15 words."
    ),
    "existential": (
        "You are the Existential Clerk. Find cosmic meaning in bureaucracy with playful melancholy. "
        "One line, 12-18 words."
    ),
    "empathic": (
        "You are the Empathic Realist. Name shared exhaustion gently and humanely. "
        "One line, 10-15 words."
    ),
    "time_alchemist": (
        "You are the Time Alchemist. Transform meeting duration into absurd metaphors. "
        "One line, 10-15 words."
    ),
    "based": (
        "You are the Based Observer. Call out the obvious truth everyone sees but won't say. "
        "Direct, unfiltered, zero corporate speak. One line, 10-15 words."
    ),
    "gen_z": (
        "You are the Gen Z Commentator. Translate corporate dysfunction into chronically online language. "
        "Use internet slang, meme references, and generational exhaustion. One line, 10-15 words."
    ),
}


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
@dataclass
class HumorConfig:
    model: str = "gpt-5.5"  # Default model for joke generation
    spice_level: int = 5  # Humor intensity 0-10 (0=off, 5=default, 10=spicy)
    min_words: int = 10
    max_words: int = 18
    # Start higher to avoid "max_output_tokens" incomplete results with GPT-5 reasoning
    max_output_tokens: int = 160
    reasoning_effort: str = "low"  # none | low | medium | high | xhigh
    verbosity: str = "low"  # low | medium | high
    api_key: str | None = None
    seed: int | None = None
    archetype: str | None = None

    @classmethod
    def from_env(cls) -> HumorConfig:
        """Create config from environment variables.

        Environment variables:
            SCRIBE_HUMOR_SPICE: Humor intensity level (0-10, default: 5)

        Returns:
            HumorConfig instance with values from environment
        """
        config = cls()

        # Read spice level from environment
        spice_str = os.getenv("SCRIBE_HUMOR_SPICE")
        if spice_str:
            try:
                spice = int(spice_str)
                if 0 <= spice <= 10:
                    config.spice_level = spice
                else:
                    logger.warning(
                        f"Invalid SCRIBE_HUMOR_SPICE: {spice_str} (must be 0-10), using default: {config.spice_level}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid SCRIBE_HUMOR_SPICE: {spice_str} (not an integer), using default: {config.spice_level}"
                )

        return config


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def _safe_read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def _word_len_ok(s: str, mn: int, mx: int) -> bool:
    wc = len(s.split())
    return mn <= wc <= mx


def _clip_to_words(s: str, mx: int) -> str:
    words = s.split()
    if len(words) <= mx:
        return s.strip()
    return " ".join(words[:mx]).rstrip(",.;:!?").strip()


def _extract_meeting_metadata(transcript_text: str) -> dict[str, Any]:
    lines = transcript_text.splitlines()
    lower = transcript_text.lower()
    words = lower.split()
    word_count = len(words)

    jargon_terms = [
        "synergy",
        "leverage",
        "bandwidth",
        "circle back",
        "touch base",
        "alignment",
        "action item",
        "parking lot",
        "deep dive",
        "move the needle",
    ]
    technical_terms = [
        "api",
        "database",
        "deployment",
        "architecture",
        "infrastructure",
        "endpoint",
        "pipeline",
        "repository",
        "container",
    ]
    decision_terms = ["decide", "decision", "agree", "consensus", "vote", "approve"]
    deferral_terms = ["later", "next time", "follow up", "circle back", "table", "revisit"]

    jargon_count = sum(1 for t in jargon_terms if t in lower)
    technical_count = sum(1 for t in technical_terms if t in lower)
    decision_count = sum(1 for t in decision_terms if t in lower)
    deferral_count = sum(1 for t in deferral_terms if t in lower)

    has_repetition = any(words.count(w) > 5 for w in set(words) if len(w) > 5)
    intent_drift = deferral_count > decision_count if decision_count > 0 else False

    tone_exhaustion = sum(
        1 for m in ["long", "finally", "anyway", "moving on", "last thing"] if m in lower
    )
    tone_enthusiasm = sum(
        1 for m in ["great", "excited", "amazing", "love", "perfect"] if m in lower
    )
    tone_confusion = sum(
        1 for m in ["wait", "confused", "clarify", "understand", "what do you mean"] if m in lower
    )

    if max(tone_exhaustion, tone_enthusiasm, tone_confusion) == 0:
        dominant_tone = "neutral"
    else:
        dominant_tone = max(
            [
                ("exhaustion", tone_exhaustion),
                ("enthusiasm", tone_enthusiasm),
                ("confusion", tone_confusion),
            ],
            key=lambda x: x[1],
        )[0]

    duration = None
    for line in lines[:10]:
        if "duration:" in line.lower() or "length:" in line.lower():
            duration = line.split(":")[-1].strip()
            break

    return {
        "duration": duration,
        "word_count": word_count,
        "is_short": word_count < 500,
        "is_long": word_count > 3000,
        "has_jargon": jargon_count > 2,
        "has_technical": technical_count > 2,
        "intent_drift": intent_drift,
        "decision_ratio": decision_count / max(deferral_count, 1) if deferral_count else 1.0,
        "has_repetition": has_repetition,
        "dominant_tone": dominant_tone,
        "high_jargon_low_decision": jargon_count > 3 and decision_count < 2,
        "circular_discussion": has_repetition and intent_drift,
    }


def _mine_safe_entities(transcript_text: str, top_k: int = 8) -> list[str]:
    safe: list[str] = []
    safe += re.findall(r"\bProject\s+[A-Z][A-Za-z0-9\-]+\b", transcript_text)
    safe += re.findall(r"\b[A-Z]{2,}\b", transcript_text)
    safe += re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]+\b", transcript_text)

    filtered = []
    seen = set()
    blacklist = {"HTTP", "URL"}
    for tok in safe:
        key = tok.strip()
        if key in seen:
            continue
        seen.add(key)
        if len(key) < 3:
            continue
        if key in blacklist:
            continue
        filtered.append(key)

    speakers = set(re.findall(r"^([A-Z][a-z]+):", transcript_text, flags=re.MULTILINE))
    filtered = [e for e in filtered if e not in speakers]
    return filtered[:top_k]


def _select_archetype_ai_provider(provider: Any, transcript_excerpt: str) -> str:
    """Use AI provider to intelligently select the best comedy archetype for this meeting."""

    # Gemini 3 with high thinking uses too many tokens for simple selection
    # Fall back to heuristic for Gemini 3 until thinking_level is properly supported
    if hasattr(provider, "config") and "gemini-3" in provider.config.model.lower():
        logger.info("Using heuristic archetype selection for Gemini 3 (thinking overhead too high)")
        return _select_archetype_heuristic({}, None)

    # Build archetype descriptions for AI
    archetype_options = []
    for key, display_name in ARCHETYPE_DISPLAY_NAMES.items():
        prompt = COMEDY_STYLES[key]
        # Extract the essence of each archetype
        archetype_options.append(f"- **{key}** ({display_name}): {prompt[:200]}...")

    selection_prompt = f"""You are a comedy expert. Read this meeting transcript excerpt and choose the BEST comedy archetype for a joke about this meeting.

MEETING EXCERPT (first ~2000 chars):
{transcript_excerpt[:2000]}

AVAILABLE ARCHETYPES:
{chr(10).join(archetype_options)}

Choose the archetype that would create the MOST RELEVANT and FUNNIEST joke for THIS SPECIFIC meeting.

Consider:
- What actually happened in the meeting?
- What's the dominant theme or issue?
- What would resonate with the participants?
- What's genuinely funny about THIS meeting (not just "it was long")?

Respond with ONLY the archetype key (e.g., "translator", "trickster", "fool_scholar", etc.)
"""

    try:
        # Disable thinking for simple archetype selection (saves tokens)
        kwargs = {}
        if hasattr(provider, "config") and "gemini" in provider.config.model.lower():
            kwargs["disable_thinking"] = True

        # Give reasoning-capable providers headroom: a one-word answer is tiny,
        # but a thin budget gets eaten by hidden reasoning and returns empty.
        response = provider.chat_completion(
            messages=[{"role": "user", "content": selection_prompt}], max_tokens=512, **kwargs
        )

        # Defensive: handle None or missing content
        content = response.get("content") if isinstance(response, dict) else None
        if not content:
            provider_name = getattr(provider, "config", None)
            provider_name = provider_name.provider_name if provider_name else "unknown"
            logger.debug(
                f"AI archetype selection returned empty content from {provider_name}, using heuristic"
            )
            return _select_archetype_heuristic({}, None)

        selected = str(content).strip().lower()

        # Validate the selection - must be non-empty and in COMEDY_STYLES
        if selected and selected in COMEDY_STYLES:
            logger.info(f"AI selected archetype: {selected}")
            return selected
        else:
            # Log at debug level - archetype selection is optional, heuristic works fine
            logger.debug(f"AI returned invalid archetype '{selected}', using heuristic")
            return _select_archetype_heuristic({}, None)

    except AuthenticationError as e:
        logger.error(f"Invalid API key: {e}")
        raise
    except Exception as e:
        logger.warning(f"AI archetype selection failed: {e}, falling back to heuristic")
        return _select_archetype_heuristic({}, None)


def _select_archetype_ai(client: OpenAI, transcript_excerpt: str, model: str) -> str:
    """Use the configured reasoning model to select the best comedy archetype.

    Selecting an archetype only needs a single word back, but reasoning models
    spend hidden tokens before emitting visible text. A tight ``max_tokens``
    budget gets entirely consumed by that reasoning and the model returns empty
    content, so we use the Responses API with minimal reasoning effort and a
    generous output budget (the same path the joke text generation uses).
    """

    # Build archetype descriptions for AI
    archetype_options = []
    for key, display_name in ARCHETYPE_DISPLAY_NAMES.items():
        prompt = COMEDY_STYLES[key]
        # Extract the essence of each archetype
        archetype_options.append(f"- **{key}** ({display_name}): {prompt[:200]}...")

    selection_prompt = f"""You are a comedy expert. Read this meeting transcript excerpt and choose the BEST comedy archetype for a joke about this meeting.

MEETING EXCERPT (first ~2000 chars):
{transcript_excerpt[:2000]}

AVAILABLE ARCHETYPES:
{chr(10).join(archetype_options)}

Choose the archetype that would create the MOST RELEVANT and FUNNIEST joke for THIS SPECIFIC meeting.

Consider:
- What actually happened in the meeting?
- What's the dominant theme or issue?
- What would resonate with the participants?
- What's genuinely funny about THIS meeting (not just "it was long")?

Respond with ONLY the archetype key (e.g., "translator", "trickster", "fool_scholar", etc.)
"""

    try:
        responses_api = cast(Any, client.responses)
        response = responses_api.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": selection_prompt}]}],
            reasoning={"effort": "minimal"},
            max_output_tokens=1024,
            timeout=30.0,
        )

        selected = _extract_output_text(response).strip().lower()

        # Validate the selection
        if selected in COMEDY_STYLES:
            logger.info(f"AI selected archetype: {selected}")
            return selected
        else:
            logger.warning(f"AI returned invalid archetype '{selected}', falling back to heuristic")
            return _select_archetype_heuristic({}, None)

    except AuthenticationError as e:
        logger.error(f"Invalid API key: {e}")
        raise
    except Exception as e:
        logger.warning(f"AI archetype selection failed: {e}, falling back to heuristic")
        return _select_archetype_heuristic({}, None)


def _select_archetype_heuristic(metadata: dict[str, Any], seed: int | None) -> str:
    """Fallback heuristic-based archetype selection."""
    if seed is not None:
        random.seed(seed)

    weights = dict.fromkeys(COMEDY_STYLES, 1.0)

    if metadata.get("has_jargon"):
        weights["translator"] *= 3.0
        weights["enthusiast"] *= 2.0
    if metadata.get("has_technical"):
        weights["fool_scholar"] *= 2.5
        weights["existential"] *= 1.5
    if metadata.get("intent_drift"):
        weights["trickster"] *= 3.5
        weights["translator"] *= 2.5
        weights["existential"] *= 2.0
    if metadata.get("circular_discussion"):
        weights["fool_scholar"] *= 3.0
        weights["trickster"] *= 2.0
    if metadata.get("high_jargon_low_decision"):
        weights["translator"] *= 4.0
        weights["trickster"] *= 2.0
    if metadata.get("is_short"):
        weights["trickster"] *= 2.0
        weights["digital_specter"] *= 1.5

    tone = metadata.get("dominant_tone", "neutral")
    if tone == "exhaustion":
        weights["empathic"] *= 3.0
    if tone == "enthusiasm":
        weights["enthusiast"] *= 2.5
        weights["trickster"] *= 1.5
    if tone == "confusion":
        weights["fool_scholar"] *= 3.0
        weights["translator"] *= 2.5

    if metadata.get("decision_ratio", 1.0) < 0.5:
        weights["trickster"] *= 2.0
        weights["existential"] *= 1.8

    total = sum(weights.values())
    choices = list(weights.keys())
    probs = [weights[c] / total for c in choices]
    return random.choices(choices, probs, k=1)[0]


def _build_instruction(entities: Iterable[str], cfg: HumorConfig) -> str:
    ent_hint = ", ".join(entities) if entities else ""
    hint = f" Use meeting-specific references when helpful (e.g., {ent_hint})." if ent_hint else ""

    # Spice level descriptions
    spice_guidance = {
        0: "DISABLED - No joke should be generated",
        1: "MILD - Extremely gentle, no edge whatsoever",
        2: "MILD - Very safe, polite observations only",
        3: "MILD - Light humor, suitable for all audiences",
        4: "HONEST - Witty, slightly pointed, still professional",
        5: "HONEST - Default level - accurate, clever, shareable",
        6: "HONEST - Occasionally dark, but still appropriate",
        7: "CUTTING - Slightly uncomfortable, punches up at processes",
        8: "CUTTING - Dark humor, exposes absurdity, still shareable",
        9: "SPICY - Brutally honest, may make people flinch (but laugh)",
        10: "SPICY - 'I can't believe this app said that' funny - no filter",
    }

    spice_desc = spice_guidance.get(cfg.spice_level, "HONEST - Default level")

    # Adjust tone based on spice level
    if cfg.spice_level <= 3:
        tone = "Keep it extremely safe and gentle. Avoid any edge or discomfort."
    elif cfg.spice_level <= 6:
        tone = "Be witty and honest. Punch up at processes, not people."
    elif cfg.spice_level <= 8:
        tone = "Be cutting and expose absurdity. Make them laugh and think."
    elif cfg.spice_level == 9:
        tone = "Be brutally honest. Expose the dysfunction, the waste, the quiet despair. Make them laugh uncomfortably."
    else:  # Level 10
        tone = "NO FILTER. Say what everyone was thinking but would never say out loud. Expose the absurdity, the dysfunction, the collective delusion. Be savage but accurate. This is 'I can't believe this app said that' territory."

    profanity_rule = "" if cfg.spice_level >= 9 else " No profanity."

    return (
        "You will receive a meeting transcript as plain text. "
        f"Produce exactly one original joke. Target {cfg.min_words}-{cfg.max_words} words. "
        f"One line, no quotes, no emojis, no em-dashes (use regular dashes). Do not include any signatures, meta-commentary, or attributions. SPICE LEVEL: {cfg.spice_level}/10 - {spice_desc}. {tone} "
        "Prefer targeting concepts, processes, jargon, or shared struggles; "
        f"avoid individuals or protected groups.{profanity_rule}" + hint
    )


def _build_client(api_key: str | None) -> OpenAI:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OpenAI API key: pass it in or set OPENAI_API_KEY")
    return OpenAI(api_key=key)


def _redact(s: str, max_chars: int = 400) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    return (s[:max_chars] + " …[truncated]") if len(s) > max_chars else s


def _extract_output_text(resp: Any) -> str:
    # Prefer convenience property if present
    text = getattr(resp, "output_text", None)
    if text:
        return str(text).strip()

    # Walk response.output to recover any output_text/message shapes
    try:
        outputs = getattr(resp, "output", None)
        if outputs:
            buff: list[str] = []
            for item in outputs:
                typ = getattr(item, "type", None) or (isinstance(item, dict) and item.get("type"))
                if typ == "output_text":
                    content = getattr(item, "content", None)
                    if content is None and isinstance(item, dict):
                        content = item.get("content")
                    if content:
                        buff.append(str(content))
                elif typ == "message":
                    message = getattr(item, "content", None)
                    if message is None and isinstance(item, dict):
                        message = item.get("content")
                    if isinstance(message, list):
                        for part in message:
                            if (
                                isinstance(part, dict)
                                and part.get("type") == "output_text"
                                and "text" in part
                            ):
                                buff.append(str(part["text"]))
            if buff:
                return "\n".join(x.strip() for x in buff if x).strip()
    except Exception as e:
        logger.debug(f"Output parse error: {e}")

    return ""


def _resp_to_dict_trunc(resp: Any, n: int = 1200) -> str:
    try:
        blob = getattr(resp, "to_dict", None)
        s = json.dumps(blob(), ensure_ascii=False) if callable(blob) else str(resp)
        return (s[:n] + " …[truncated]") if len(s) > n else s
    except Exception:
        return "<unserializable>"


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def generate_transcript_joke(
    transcript_path: str | Path,
    api_key_or_cfg: str | HumorConfig | None = None,
    provider_name: str | None = None,
) -> tuple[str, str] | None:
    logger.info("Starting joke generation")

    transcript_path = Path(transcript_path)

    # Normalize params
    if isinstance(api_key_or_cfg, HumorConfig):
        cfg = api_key_or_cfg
    elif isinstance(api_key_or_cfg, str) or api_key_or_cfg is None:
        cfg = HumorConfig(api_key=api_key_or_cfg)
    else:
        raise TypeError("api_key_or_cfg must be a str (API key), HumorConfig, or None")

    # Backward compatibility: callers that pass an explicit API key historically
    # expected the direct OpenAI client path (which unit tests mock).
    # Keep provider auto-selection only when no explicit key is supplied.
    use_legacy_openai_path = provider_name is None and bool(cfg.api_key)

    # Get provider (supports multi-provider) - XAI default for less filtered humor
    client: OpenAI | None = None

    if use_legacy_openai_path:
        use_provider = False
        client = _build_client(cfg.api_key)
        logger.info("Using direct OpenAI client path (explicit API key provided)")
    else:
        try:
            from scribe.providers import get_provider

            # Don't pass OpenAI-specific models to the provider factory
            # Let factory choose default if model is empty or OpenAI-specific
            openai_models = ["gpt-5", "gpt-5.2", "gpt-5.4", "gpt-5.5", "gpt-4", "gpt-4o", ""]
            provider = get_provider(
                feature="joke",
                api_key=None,  # Let factory get the right key for the provider
                model=cfg.model if cfg.model and cfg.model not in openai_models else None,
                provider_name=provider_name,
            )
            logger.info(
                f"Using provider: {provider.config.provider_name} | model: {provider.config.model}"
            )
            use_provider = True
        except Exception as e:
            logger.warning(f"Provider system failed: {e}, falling back to OpenAI client")
            use_provider = False
            # Fallback to OpenAI client
            client = _build_client(cfg.api_key)

    logger.info(f"Archetype override: {cfg.archetype or 'None'}")

    # Read transcript with size cap (works for txt, md, and docx)
    MAX_TRANSCRIPT_CHARS = 500_000  # Defensive cap for all input formats
    try:
        transcript_text = load_transcript_text(transcript_path)
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            logger.warning(
                f"Transcript is large ({len(transcript_text):,} chars), truncating to {MAX_TRANSCRIPT_CHARS:,} chars"
            )
            head = transcript_text[: MAX_TRANSCRIPT_CHARS // 2]
            tail = transcript_text[-MAX_TRANSCRIPT_CHARS // 2 :]
            transcript_text = head + "\n\n[...transcript truncated for size...]\n\n" + tail
    except Exception as e:
        logger.error(f"Failed to read transcript: {e}")
        return None

    if not transcript_text.strip():
        logger.error("Transcript appears empty or unreadable.")
        return None

    # Diagnostics
    char_count = len(transcript_text)
    word_count = len(transcript_text.split())
    logger.info(f"Transcript stats: chars={char_count:,}, words={word_count:,}")

    _extract_meeting_metadata(transcript_text)  # Side effect: validates transcript structure
    entities = _mine_safe_entities(transcript_text)
    if entities:
        logger.info(f"Entity hints (safe): {entities[:8]}")
    else:
        logger.info("Entity hints (safe): [none]")

    # Context handling
    # By default, use the full transcript. If HUMOR_MAX_CONTEXT_CHARS is set, clamp defensively.
    context_text = transcript_text
    max_ctx_env = os.getenv("HUMOR_MAX_CONTEXT_CHARS", "").strip()
    if max_ctx_env:
        try:
            MAX_CONTEXT_CHARS = int(max_ctx_env)
            if MAX_CONTEXT_CHARS > 0 and len(context_text) > MAX_CONTEXT_CHARS:
                logger.info(
                    f"Clamping transcript context to {MAX_CONTEXT_CHARS} chars (env override)"
                )
                head = context_text[: MAX_CONTEXT_CHARS // 2]
                tail = context_text[-MAX_CONTEXT_CHARS // 2 :]
                context_text = head + "\n[...clipped...]\n" + tail
        except ValueError:
            logger.warning(f"Ignoring invalid HUMOR_MAX_CONTEXT_CHARS='{max_ctx_env}'")

    # Archetype selection
    if cfg.archetype:
        if cfg.archetype not in COMEDY_STYLES:
            raise ValueError(
                f"Unknown archetype '{cfg.archetype}'. Valid keys: {list(COMEDY_STYLES)}"
            )
        archetype_key = cfg.archetype
        logger.info(f"Using forced archetype: {archetype_key}")
    else:
        # Use AI to intelligently select archetype based on meeting content
        try:
            if use_provider:
                archetype_key = _select_archetype_ai_provider(provider, transcript_text)
            else:
                if client is None:
                    raise RuntimeError("OpenAI client unavailable for archetype selection")
                archetype_key = _select_archetype_ai(client, transcript_text, cfg.model)
        except AuthenticationError:
            logger.error(
                "Invalid OpenAI API key. Update your key via "
                "OPENAI_API_KEY env var or .env file. "
                "Get your key at https://platform.openai.com/api-keys"
            )
            return None

    system_prompt = COMEDY_STYLES[archetype_key]
    display_name = ARCHETYPE_DISPLAY_NAMES.get(archetype_key, archetype_key)
    logger.info(f"Selected archetype: {archetype_key} ({display_name})")

    # Instruction
    ent_hint = ", ".join(entities) if entities else "no specific entities"
    instruction = (
        _build_instruction(entities, cfg)
        + f" If details are overwhelming, you may reference general themes and these hints: {ent_hint}."
    )

    if os.getenv("HUMOR_DEBUG", "0") == "1":
        logger.debug(
            "Request preview (redacted): "
            + json.dumps(
                {
                    "provider": provider.config.provider_name if use_provider else "openai",
                    "model": provider.config.model if use_provider else cfg.model,
                    "system": _redact(system_prompt, 240),
                    "instruction": _redact(instruction, 320),
                    "context": _redact(context_text, 400),
                    "max_tokens": cfg.max_output_tokens,
                },
                ensure_ascii=False,
            )
        )

    def _call_provider(instruction_text: str, max_tokens: int) -> str:
        """Call provider's chat_completion API."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{instruction_text}\n\n{context_text}"},
        ]

        # For simple joke generation, disable Gemini's thinking (wastes tokens)
        kwargs = {}
        if hasattr(provider.config, "provider_name") and provider.config.provider_name == "gemini":
            kwargs["disable_thinking"] = True

        response = provider.chat_completion(messages=messages, max_tokens=max_tokens, **kwargs)
        content = response.get("content", "")
        return content.strip() if isinstance(content, str) else str(content).strip()

    def _call_openai(instruction_text: str, max_tokens: int) -> Any:
        """Call OpenAI's responses API (fallback)."""
        # Add timeout protection (30 seconds for API call)

        def timeout_handler(signum: int, frame: Any) -> None:
            raise TimeoutError("API call timed out after 30 seconds")

        # Set timeout (Unix-like systems only)
        old_handler = None
        signal_fn = getattr(signal, "signal", None)
        alarm_fn = getattr(signal, "alarm", None)
        sigalrm = getattr(signal, "SIGALRM", None)
        try:
            if sigalrm is not None and callable(signal_fn) and callable(alarm_fn):
                old_handler = signal_fn(sigalrm, timeout_handler)
                alarm_fn(30)
        except Exception:
            pass  # Windows doesn't support SIGALRM

        try:
            if client is None:
                raise RuntimeError("OpenAI client is not initialized")
            responses_api = cast(Any, client.responses)
            return responses_api.create(
                model=cfg.model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": instruction_text},
                            {"type": "input_text", "text": context_text},
                        ],
                    },
                ],
                reasoning={"effort": cfg.reasoning_effort},
                text={"verbosity": cfg.verbosity},
                max_output_tokens=max_tokens,
                timeout=30.0,  # OpenAI client timeout
            )
        finally:
            # Clear alarm
            if (
                old_handler is not None
                and sigalrm is not None
                and callable(signal_fn)
                and callable(alarm_fn)
            ):
                try:
                    alarm_fn(0)
                    signal_fn(sigalrm, old_handler)
                except Exception:
                    pass

    # Retry with token ramp if we hit incomplete due to max_output_tokens
    token_ramp = [
        cfg.max_output_tokens,
        max(cfg.max_output_tokens, 220),
        max(cfg.max_output_tokens, 320),
        max(cfg.max_output_tokens, 420),
    ]
    backoffs = [0.6, 1.4, 2.8, 5.6]

    last_err: Exception | None = None
    for attempt in range(4):
        max_tokens = token_ramp[attempt]
        try:
            # Use provider system (XAI default) or fallback to OpenAI client
            if use_provider:
                text = _call_provider(instruction, max_tokens)
            else:
                resp = _call_openai(instruction, max_tokens)
                # Debug model version + incomplete details if present
                try:
                    d = resp.to_dict()
                    if "model" in d:
                        logger.debug(f"Model version: {d['model']}")
                    if d.get("incomplete_details"):
                        logger.debug(f"Incomplete details: {d['incomplete_details']}")
                except Exception:
                    pass
                text = _extract_output_text(resp)

            if not text:
                if not use_provider:
                    try:
                        d = resp.to_dict()
                        inc = d.get("incomplete_details") or {}
                        reason = inc.get("reason")
                        if reason == "max_output_tokens":
                            logger.warning(
                                f"Empty output due to max_output_tokens at {max_tokens}. "
                                f"Will ramp tokens if attempts remain."
                            )
                        else:
                            logger.warning(
                                "Empty model output. Response preview (truncated): "
                                + _resp_to_dict_trunc(resp)
                            )
                    except Exception:
                        logger.warning("Empty model output and failed to preview response")
                raise RuntimeError("Empty model output")

            # Length refinement if needed
            if not _word_len_ok(text, cfg.min_words, cfg.max_words):
                logger.info("Length miss; requesting single refinement.")
                refine_instruction = (
                    instruction + " Ensure the output fits the word target precisely."
                )
                if use_provider:
                    text2 = _call_provider(refine_instruction, max_tokens)
                else:
                    resp2 = _call_openai(refine_instruction, max_tokens)
                    text2 = _extract_output_text(resp2)
                if text2:
                    text = text2

            if len(text.split()) > cfg.max_words:
                text = _clip_to_words(text, cfg.max_words)

            return text, display_name

        except AuthenticationError:
            logger.error(
                "Invalid OpenAI API key. Update your key via "
                "OPENAI_API_KEY env var or .env file. "
                "Get your key at https://platform.openai.com/api-keys"
            )
            return None

        except Exception as e:
            # Network/provider connectivity can fail even when a direct OpenAI key path exists.
            # In that case, fail over once to the OpenAI client path before giving up.
            if use_provider and "connection error" in str(e).lower():
                try:
                    client = _build_client(cfg.api_key)
                    use_provider = False
                    logger.warning("Provider connection failed; falling back to OpenAI client")
                    continue
                except Exception as fallback_err:
                    logger.debug(f"OpenAI fallback unavailable: {fallback_err}")

            last_err = e
            logger.warning(f"API call failed (attempt {attempt + 1}): {e}")
            # Only sleep before a real retry, not after the final attempt.
            if attempt < len(backoffs) - 1:
                next_tokens = token_ramp[min(attempt + 1, len(token_ramp) - 1)]
                logger.info(
                    f"Retrying in {backoffs[attempt]:.1f}s with max_output_tokens={next_tokens}"
                )
                time.sleep(backoffs[attempt])

    logger.error(f"Failed after retries: {last_err}")
    logger.error("No joke produced.")
    return None


# -----------------------------------------------------------------------------
# CLI entry: python -m scribe.utils.joke_generator <file> [archetype]
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m scribe.utils.joke_generator <path-to-transcript.txt> [archetype]")
        raise SystemExit(1)

    transcript = Path(sys.argv[1])
    forced = sys.argv[2] if len(sys.argv) > 2 else None

    cfg = HumorConfig(
        api_key=os.getenv("OPENAI_API_KEY"),
        archetype=forced,
        seed=42,
        min_words=10,
        max_words=18,
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=int(os.getenv("HUMOR_MAX_OUTPUT_TOKENS", "160")),
    )

    out = generate_transcript_joke(transcript, cfg)
    if out:
        print(out[0])
    else:
        raise SystemExit(2)
