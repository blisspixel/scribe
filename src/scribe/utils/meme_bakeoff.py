"""
Meme concept bake-off: Get concepts from multiple providers and pick the best.
"""

import logging
from typing import Any

from scribe.providers import get_provider
from scribe.utils.meme_generator import MemeConfig, _analyze_transcript_for_meme

logger = logging.getLogger(__name__)


def run_meme_bakeoff(
    transcript: str, config: MemeConfig, providers: list[str] | None = None
) -> dict[str, Any]:
    """
    Run a meme concept bake-off across multiple providers.

    Args:
        transcript: The meeting transcript text
        config: Meme generation config
        providers: List of provider names to test (default: all available)

    Returns:
        Dict with:
        - winner: Name of winning provider
        - concept: The winning meme concept
        - all_concepts: List of all concepts with scores
    """
    # Default to all available providers
    if providers is None:
        providers = ["xai", "openai", "gemini"]

    # Filter to only providers with API keys
    import os

    available_providers = []
    for provider_name in providers:
        if (
            provider_name == "xai"
            and os.getenv("XAI_API_KEY")
            or provider_name == "openai"
            and os.getenv("OPENAI_API_KEY")
            or provider_name == "gemini"
            and os.getenv("GEMINI_API_KEY")
            or provider_name == "anthropic"
            and os.getenv("ANTHROPIC_API_KEY")
        ):
            available_providers.append(provider_name)

    if not available_providers:
        raise ValueError("No providers available with API keys")

    logger.info(
        f"🎭 Starting meme bake-off with {len(available_providers)} providers: {', '.join(available_providers)}"
    )

    # Collect concepts from all providers
    concepts = []

    for provider_name in available_providers:
        logger.info(f"  → Getting concept from {provider_name.upper()}...")

        try:
            provider = get_provider(feature="meme", provider_name=provider_name)
            concept = _analyze_transcript_for_meme(
                provider, transcript, config, show_reasoning=False
            )

            if concept:
                concepts.append(
                    {
                        "provider": provider_name,
                        "concept": concept,
                        "top_text": concept.get("top_text", ""),
                        "bottom_text": concept.get("bottom_text", ""),
                        "template": concept.get("template", ""),
                        "judgment": concept.get("judgment", ""),
                    }
                )
                logger.info(
                    f"    ✓ {provider_name}: \"{concept.get('top_text')}\" / \"{concept.get('bottom_text')}\""
                )
            else:
                logger.warning(f"    ✗ {provider_name} returned no concept")

        except Exception as e:
            logger.warning(f"    ✗ {provider_name} failed: {e}")

    if not concepts:
        raise ValueError("No providers successfully generated concepts")

    # Now judge the concepts using the best available provider
    logger.info(f"\n🏆 Judging {len(concepts)} concepts...")

    # Use OpenAI for judging if available (most reliable), otherwise use first available
    judge_provider_name = "openai" if "openai" in available_providers else available_providers[0]
    judge_provider = get_provider(feature="meme", provider_name=judge_provider_name)

    # Build judging prompt
    concepts_text = ""
    for i, c in enumerate(concepts, 1):
        concepts_text += f"\n\nCONCEPT {i} (from {c['provider'].upper()}):\n"
        concepts_text += f"Template: {c['template']}\n"
        concepts_text += f"Top text: {c['top_text']}\n"
        concepts_text += f"Bottom text: {c['bottom_text']}\n"
        concepts_text += f"Why it works: {c['judgment']}\n"

    judging_prompt = f"""You are a meme expert judging a comedy competition.

{len(concepts)} different AI models created meme concepts from the same meeting transcript. Your job is to pick the FUNNIEST one.

SPICE LEVEL: {config.spice_level}/10 - {"NSFW, no filter, crude humor encouraged" if config.spice_level >= 9 else "work-safe" if config.spice_level <= 5 else "edgy but professional"}

THE CONCEPTS:
{concepts_text}

JUDGING CRITERIA:
1. HILARITY: Which one makes you laugh the hardest?
2. SPECIFICITY: Which one uses the most specific details from the meeting?
3. CLEVERNESS: Which one has the most clever wordplay or observation?
4. SPICE MATCH: Which one best matches the spice level {config.spice_level}/10?

Pick the WINNER and explain why in 2-3 sentences.

Respond in JSON:
{{
    "winner": 1 or 2 or 3 (the concept number),
    "reasoning": "Why this one is the funniest (2-3 sentences)",
    "scores": {{
        "1": {{"hilarity": 0-10, "specificity": 0-10, "cleverness": 0-10, "spice_match": 0-10}},
        "2": {{"hilarity": 0-10, "specificity": 0-10, "cleverness": 0-10, "spice_match": 0-10}},
        "3": {{"hilarity": 0-10, "specificity": 0-10, "cleverness": 0-10, "spice_match": 0-10}}
    }}
}}
"""

    messages = [
        {
            "role": "system",
            "content": "You are an expert meme judge. Pick the funniest concept. Respond with valid JSON only.",
        },
        {"role": "user", "content": judging_prompt},
    ]

    try:
        response = judge_provider.chat_completion(messages=messages, max_tokens=2000)
        result = response["content"]

        # Extract JSON
        import json
        import re

        json_match = re.search(r"\{.*\}", result, re.DOTALL)
        if json_match:
            result = json_match.group()

        judgment = json.loads(result)

        winner_idx = int(judgment["winner"]) - 1
        winner_concept = concepts[winner_idx]

        logger.info(f"\n🎉 WINNER: {winner_concept['provider'].upper()}")
        logger.info(f"   Reasoning: {judgment['reasoning']}")

        return {
            "winner": winner_concept["provider"],
            "concept": winner_concept["concept"],
            "reasoning": judgment["reasoning"],
            "all_concepts": concepts,
            "scores": judgment.get("scores", {}),
        }

    except Exception as e:
        logger.warning(f"Judging failed: {e}, defaulting to first concept")
        # Fallback: just use the first concept
        return {
            "winner": concepts[0]["provider"],
            "concept": concepts[0]["concept"],
            "reasoning": "Judging failed, using first concept",
            "all_concepts": concepts,
            "scores": {},
        }
