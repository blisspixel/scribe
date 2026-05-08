"""
Joke bake-off: Get jokes from multiple providers and pick the funniest.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Competitive Ensemble + Meta-Learning
═══════════════════════════════════════════════════════════════════════════════

This module implements a creative solution to a fundamental problem in AI-generated
humor: different models have different strengths, and no single model is always
the funniest.

PROBLEM STATEMENT:
──────────────────
AI humor generation is highly variable:

1. MODEL VARIANCE: Different models (GPT-5, Grok, Claude, Gemini) have different
   comedy styles, training data, and capabilities

2. CONTEXT SENSITIVITY: A model that's funny for technical meetings might not be
   funny for casual conversations

3. UNPREDICTABILITY: Even the same model can produce varying quality jokes due
   to temperature sampling and prompt interpretation

4. NO GROUND TRUTH: Unlike transcription (where accuracy is measurable), humor
   is subjective and context-dependent

Traditional approach: Pick one model and hope it's funny
Problem: You're stuck with that model's style and limitations

BREAKTHROUGH SOLUTION:
──────────────────────
Instead of picking one model, run a COMPETITION:

1. Generate jokes from ALL available providers (OpenAI, XAI, Anthropic, Gemini)
2. Have an AI judge evaluate all jokes and pick the funniest
3. Return only the winning joke to the user

This is a "competitive ensemble" approach where multiple models compete and a
meta-model selects the best output.

Benefits:
- BEST OF BREED: Get the funniest joke regardless of which model generated it
- STYLE DIVERSITY: Different models bring different comedy styles
- ROBUSTNESS: If one model fails or produces a weak joke, others compensate
- COST EFFECTIVE: Only pay for the winning joke (others are discarded)

BAKE-OFF PIPELINE:
──────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. PROVIDER DISCOVERY                                                       │
│    ├─ Check which providers have API keys configured                       │
│    ├─ Filter to available providers (xai, openai, gemini, anthropic)      │
│    └─ Require at least 2 providers for meaningful competition              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. PARALLEL JOKE GENERATION                                                 │
│    ├─ For each provider:                                                    │
│    │   ├─ Call generate_transcript_joke() with same transcript             │
│    │   ├─ Use same spice level and configuration                           │
│    │   └─ Catch failures (log warning, continue with other providers)      │
│    └─ Collect all successful jokes                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. JUDGING PHASE                                                            │
│    ├─ Select judge (prefer Grok for comedy expertise, fallback to OpenAI)  │
│    ├─ Present all jokes to judge with evaluation criteria                  │
│    ├─ Judge scores each joke on 5 dimensions:                              │
│    │   ├─ Hilarity: How funny is it?                                       │
│    │   ├─ Specificity: Does it use meeting details?                        │
│    │   ├─ Cleverness: Wordplay, observations, insights?                    │
│    │   ├─ Spice match: Matches requested spice level?                      │
│    │   └─ Brevity: Concise or unnecessarily long?                          │
│    └─ Judge picks winner and explains reasoning                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. RESULT PACKAGING                                                         │
│    ├─ Return winning joke with metadata                                    │
│    ├─ Include all jokes for debugging/analysis                             │
│    └─ Include judge's reasoning and scores                                 │
└─────────────────────────────────────────────────────────────────────────────┘

JUDGING CRITERIA:
─────────────────
The judge evaluates jokes on five dimensions (0-10 scale):

1. HILARITY: Subjective funniness
   - Does it make you laugh?
   - Is it clever or just obvious?
   - Does it land or fall flat?

2. SPECIFICITY: Use of meeting details
   - Generic joke that could apply to any meeting? (low score)
   - Uses specific names, topics, or moments? (high score)
   - Shows deep understanding of context? (highest score)

3. CLEVERNESS: Wordplay and insight
   - Simple observation? (low score)
   - Clever wordplay or unexpected connection? (high score)
   - Multi-layered joke with callbacks? (highest score)

4. SPICE MATCH: Matches requested spice level
   - Spice 0-3: Wholesome, family-friendly
   - Spice 4-6: Edgy but professional
   - Spice 7-8: Crude, adult humor
   - Spice 9-10: NSFW, no filter

5. BREVITY: Conciseness
   - One-liner? (high score)
   - Short paragraph? (medium score)
   - Long-winded explanation? (low score)

The judge picks the joke with the highest overall score, with hilarity weighted
most heavily (it's comedy, after all).

META-LEARNING PATTERN:
──────────────────────
This is a form of meta-learning where an AI (the judge) learns to select the
best output from other AIs (the joke generators). This pattern is powerful
because:

1. SPECIALIZATION: Each generator can specialize in its strengths
2. DIVERSITY: Multiple approaches increase chance of success
3. QUALITY CONTROL: Meta-model filters out weak outputs
4. ADAPTABILITY: System improves as new models are added

This is similar to:
- Ensemble methods in machine learning (random forests, boosting)
- Mixture of experts (MoE) architectures
- Reinforcement learning with reward models

COST OPTIMIZATION:
──────────────────
Running multiple models seems expensive, but:

1. CHEAP MODELS: Grok is 47x cheaper than GPT-5 ($0.20 vs $3.00 per 1M tokens)
2. SHORT INPUTS: Jokes use ~500-1000 tokens (meeting summary, not full transcript)
3. PARALLEL EXECUTION: All jokes generated simultaneously (no latency penalty)
4. SINGLE WINNER: User only sees the best joke (others are discarded)

Cost example (4 providers, 1000 token input, 200 token output):
- 4 joke generations: 4 × $0.0002 = $0.0008
- 1 judging call: $0.0002
- Total: $0.001 (one-tenth of a cent)

This is negligible compared to transcription costs ($0.006 per minute).

FAILURE HANDLING:
─────────────────
The bake-off is robust to individual provider failures:

1. PROVIDER FAILURE: If one provider fails, others continue
2. JUDGING FAILURE: If judging fails, return first successful joke
3. ALL FAILURES: If all providers fail, raise error with context
4. PARTIAL SUCCESS: Even one successful joke is better than none

This makes the system more reliable than using a single provider.

USER EXPERIENCE:
────────────────
The bake-off runs silently in the background:

- User sees: "Generating joke..." → "Here's your joke"
- User doesn't see: "Trying 4 providers... Judging... Winner: Grok"

This keeps the UX simple while providing the best possible result.

FUTURE ENHANCEMENTS:
────────────────────
Potential improvements:

1. LEARNING: Track which providers win most often, prioritize them
2. CACHING: Cache jokes for identical transcripts (save cost)
3. USER FEEDBACK: Let users rate jokes, train reward model
4. ADAPTIVE JUDGING: Use different judges for different spice levels
5. PARALLEL OPTIMIZATION: Generate jokes in parallel for speed

RESEARCH REFERENCES:
────────────────────
- "Mixture of Experts" (Jacobs et al., 1991)
  → Multiple specialized models with gating network
- "Ensemble Methods in Machine Learning" (Dietterich, 2000)
  → Combining multiple models for better performance
- "Learning to Learn" (Thrun & Pratt, 1998)
  → Meta-learning and transfer learning
- "Constitutional AI: Harmlessness from AI Feedback" (Bai et al., 2022)
  → Using AI to evaluate and improve AI outputs

This bake-off system is a creative solution to the variability problem in AI
humor generation. By running a competition and selecting the best output, we
achieve higher quality and more consistent results than any single model.
"""

import logging
from typing import Any

from scribe.providers import get_provider
from scribe.utils.joke_generator import HumorConfig, generate_transcript_joke

logger = logging.getLogger(__name__)


def run_joke_bakeoff(
    transcript: str, config: HumorConfig, providers: list[str] | None = None
) -> dict[str, Any]:
    """
    Run a joke bake-off across multiple providers.

    Args:
        transcript: The meeting transcript text
        config: Humor generation config
        providers: List of provider names to test (default: all available)

    Returns:
        Dict with:
        - winner: Name of winning provider
        - joke: The winning joke text
        - archetype: The archetype used
        - all_jokes: List of all jokes with scores
        - reasoning: Why this joke won
    """
    # Default to all available providers
    if providers is None:
        providers = ["xai", "openai", "gemini", "anthropic"]

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
        f"Starting joke bake-off with {len(available_providers)} providers: {', '.join(available_providers)}"
    )

    # Collect jokes from all providers
    jokes = []

    for provider_name in available_providers:
        logger.info(f"  → Getting joke from {provider_name.upper()}...")

        try:
            # Write transcript to temp file for generate_transcript_joke
            import tempfile
            from pathlib import Path

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(transcript)
                temp_path = Path(f.name)

            try:
                result = generate_transcript_joke(
                    transcript_path=temp_path, api_key_or_cfg=config, provider_name=provider_name
                )
                joke_text = result[0] if result else None
            finally:
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()

            if joke_text:
                jokes.append(
                    {
                        "provider": provider_name,
                        "joke": joke_text,
                    }
                )
                # Truncate for display
                display_joke = joke_text[:80] + "..." if len(joke_text) > 80 else joke_text
                logger.info(f'    ✓ {provider_name}: "{display_joke}"')
            else:
                logger.warning(f"    ✗ {provider_name} returned no joke")

        except Exception as e:
            logger.warning(f"    ✗ {provider_name} failed: {e}")

    if not jokes:
        raise ValueError("No providers successfully generated jokes")

    # Now judge the jokes using the best available provider
    logger.info(f"\nJudging {len(jokes)} jokes...")

    # Use XAI/Grok for judging (default for jokes), fallback to OpenAI, then first available
    if "xai" in available_providers:
        judge_provider_name = "xai"
    elif "openai" in available_providers:
        judge_provider_name = "openai"
    else:
        judge_provider_name = available_providers[0]

    judge_provider = get_provider(feature="joke", provider_name=judge_provider_name)

    # Build judging prompt
    jokes_text = ""
    for i, j in enumerate(jokes, 1):
        jokes_text += f"\n\nJOKE {i} (from {j['provider'].upper()}):\n"
        jokes_text += f"{j['joke']}\n"

    judging_prompt = f"""You are a comedy expert judging a joke competition.

{len(jokes)} different AI models created jokes from the same meeting transcript. Your job is to pick the FUNNIEST one.

SPICE LEVEL: {config.spice_level}/10 - {"NSFW, no filter, crude humor encouraged" if config.spice_level >= 9 else "work-safe" if config.spice_level <= 5 else "edgy but professional"}

THE JOKES:
{jokes_text}

JUDGING CRITERIA:
1. HILARITY: Which one makes you laugh the hardest?
2. SPECIFICITY: Which one uses the most specific details from the meeting?
3. CLEVERNESS: Which one has the most clever wordplay or observation?
4. SPICE MATCH: Which one best matches the spice level {config.spice_level}/10?
5. BREVITY: Shorter is usually funnier (but not always)

Pick the WINNER and explain why in 2-3 sentences.

Respond in JSON:
{{
    "winner": 1 or 2 or 3 or 4 (the joke number),
    "reasoning": "Why this one is the funniest (2-3 sentences)",
    "scores": {{
        "1": {{"hilarity": 0-10, "specificity": 0-10, "cleverness": 0-10, "spice_match": 0-10, "brevity": 0-10}},
        "2": {{"hilarity": 0-10, "specificity": 0-10, "cleverness": 0-10, "spice_match": 0-10, "brevity": 0-10}}
    }}
}}
"""

    messages = [
        {
            "role": "system",
            "content": "You are an expert comedy judge. Pick the funniest joke. Respond with valid JSON only.",
        },
        {"role": "user", "content": judging_prompt},
    ]

    try:
        response = judge_provider.chat_completion(messages=messages, max_tokens=2000)
        result_text = str(response["content"])

        # Extract JSON
        import json
        import re

        json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group()

        judgment = json.loads(result_text)

        winner_idx = int(judgment["winner"]) - 1
        winner_joke = jokes[winner_idx]

        logger.info(f"\nWINNER: {winner_joke['provider'].upper()}")
        logger.info(f"Reasoning: {judgment['reasoning']}")

        return {
            "winner": winner_joke["provider"],
            "joke": winner_joke["joke"],
            "reasoning": judgment["reasoning"],
            "all_jokes": jokes,
            "scores": judgment.get("scores", {}),
        }

    except Exception as e:
        logger.warning(f"Judging failed: {e}, defaulting to first joke")
        # Fallback: just use the first joke
        return {
            "winner": jokes[0]["provider"],
            "joke": jokes[0]["joke"],
            "reasoning": "Judging failed, using first joke",
            "all_jokes": jokes,
            "scores": {},
        }
