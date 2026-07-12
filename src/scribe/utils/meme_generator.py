"""
Agentic AI Meme Generation for Meeting Transcripts

Uses GPT-5 to analyze transcript and create meme concept,
then generates the meme image using OpenAI's image generation API.
"""

import base64
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from dotenv import find_dotenv, load_dotenv
from openai import AuthenticationError, OpenAI

from scribe.utils.transcript_loader import load_transcript_text

# Load environment
load_dotenv(find_dotenv(usecwd=True), override=False)

logger = logging.getLogger("meme_generator")
# Use universal SCRIBE_LOG_LEVEL, fall back to MEME_LOG_LEVEL for backward compat
log_level = os.getenv("SCRIBE_LOG_LEVEL") or os.getenv("MEME_LOG_LEVEL", "ERROR")
level = getattr(logging, (log_level or "ERROR").upper(), logging.ERROR)
logger.setLevel(level)
if not logger.handlers:
    # Only log to file, not console (reduces noise)
    handler = logging.NullHandler()
    logger.addHandler(handler)
logger.propagate = False  # Don't propagate to root logger


@dataclass
class MemeConfig:
    """Configuration for meme generation."""

    model: str = "gpt-5.5"
    image_model: str = "gpt-image-1"
    size: str = "1024x1024"  # Default square, but will be overridden by template needs
    quality: str = "high"
    output_format: str = "png"
    max_retries: int = 3
    timeout: int = 120
    qa_enabled: bool = True  # Enable QA loop
    qa_threshold: float = 8.0  # Minimum score to accept (out of 10)
    spice_level: int = 5  # Humor intensity 0-10 (0=off, 5=default, 10=spicy)

    @classmethod
    def from_env(cls) -> "MemeConfig":
        """Create config from environment variables.

        Environment variables:
            SCRIBE_MEME_QA_THRESHOLD: QA score threshold (0.0-10.0, default: 8.0)
            SCRIBE_MEME_QA_ATTEMPTS: Max generation attempts (1-10, default: 3)
            SCRIBE_HUMOR_SPICE: Humor intensity level (0-10, default: 5)

        Returns:
            MemeConfig instance with values from environment
        """
        config = cls()

        # Read QA threshold from environment
        threshold_str = os.getenv("SCRIBE_MEME_QA_THRESHOLD")
        if threshold_str:
            try:
                threshold = float(threshold_str)
                if 0.0 <= threshold <= 10.0:
                    config.qa_threshold = threshold
                else:
                    logger.warning(
                        f"Invalid SCRIBE_MEME_QA_THRESHOLD: {threshold_str} (must be 0.0-10.0), using default: {config.qa_threshold}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid SCRIBE_MEME_QA_THRESHOLD: {threshold_str} (not a number), using default: {config.qa_threshold}"
                )

        # Read max attempts from environment
        attempts_str = os.getenv("SCRIBE_MEME_QA_ATTEMPTS")
        if attempts_str:
            try:
                attempts = int(attempts_str)
                if 1 <= attempts <= 10:
                    config.max_retries = attempts
                else:
                    logger.warning(
                        f"Invalid SCRIBE_MEME_QA_ATTEMPTS: {attempts_str} (must be 1-10), using default: {config.max_retries}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid SCRIBE_MEME_QA_ATTEMPTS: {attempts_str} (not an integer), using default: {config.max_retries}"
                )

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


class AttemptRecord(TypedDict):
    path: Path
    attempt: int
    score: float | None


def _analyze_transcript_for_meme(
    provider: Any,  # Provider interface (OpenAI or XAI)
    transcript: str,
    config: MemeConfig,
    show_reasoning: bool = False,
    previous_attempt: dict[str, Any] | None = None,
    make_safer: bool = False,
) -> dict[str, Any] | None:
    """
    Use GPT-5 to analyze transcript and create meme concept.

    Returns dict with:
        - template: Meme template description (e.g., "Distracted Boyfriend", "Drake Hotline Bling")
        - top_text: Text for top of meme
        - bottom_text: Text for bottom of meme
        - image_prompt: Detailed prompt for image generation
        - concept: Brief explanation of the meme concept
        - reasoning: (optional) GPT-5's reasoning process if show_reasoning=True
        - transcript_length: Character count of analyzed transcript (for transparency)
    """
    # Log transcript length for transparency
    transcript_length = len(transcript)
    logger.info(
        f"Analyzing transcript for meme concept... (transcript length: {transcript_length} characters)"
    )

    # If previous attempt was blocked, reduce spice level and add safety guidance.
    # Rebind a local copy rather than mutating the caller's shared config, which
    # would permanently lower spice for the rest of the run.
    if make_safer:
        from dataclasses import replace as _dc_replace

        logger.info("Generating safer meme concept after safety filter block")
        config = _dc_replace(config, spice_level=max(1, config.spice_level - 2))

    # Spice level descriptions
    # 0-5: Work-safe, shareable
    # 6-8: Edgy but still professional
    # 9-10: NSFW, potentially offensive, no filter
    spice_descriptions = {
        0: "DISABLED - No meme should be generated",
        1: "MILD - Office-safe, gentle irony, no edge",
        2: "MILD - Polite observations, very safe",
        3: "MILD - Light humor, suitable for all audiences",
        4: "HONEST - Witty, slightly pointed, still professional",
        5: "HONEST - Default level - hilarious but still shareable at work",
        6: "HONEST - Occasionally dark, pushing boundaries but still appropriate",
        7: "CUTTING - Slightly uncomfortable, punches up at processes",
        8: "CUTTING - Dark humor, exposes absurdity, edgy but shareable",
        9: "SPICY - Brutally honest, potentially offensive, NSFW territory",
        10: "SPICY - NO FILTER - Offensive, sexual innuendo OK, definitely NSFW",
    }

    spice_desc = spice_descriptions.get(config.spice_level, "HONEST - Default level")

    # Detailed spice guidance
    if config.spice_level <= 3:
        spice_guidance = "Be extremely cautious and gentle. Avoid any edge or discomfort. Keep it extremely safe and work-appropriate."
    elif config.spice_level <= 5:
        spice_guidance = "Be witty and honest. Punch up at processes, not people. Keep it hilarious but still shareable at work. This is the sweet spot: funny enough to make people laugh out loud, safe enough to share in Slack."
    elif config.spice_level <= 8:
        spice_guidance = "Be cutting and expose absurdity. Make them laugh and think. Push boundaries but stay professional. Edgy humor that makes people go 'ooh that's a bit much' but still laugh and share it."
    elif config.spice_level == 9:
        spice_guidance = "NSFW TERRITORY. Be brutally honest and potentially offensive. Expose the dysfunction, the waste, the quiet despair. Sexual innuendo is acceptable if it fits. Make them laugh uncomfortably and think twice before sharing it at work. This is 'send it in a private DM' humor."
    else:  # Level 10
        spice_guidance = "ABSOLUTELY NO FILTER. NSFW. Potentially offensive. Sexual innuendo and crude humor are ENCOURAGED if they land the joke. Say what everyone was thinking but would NEVER say out loud. Expose the absurdity, the dysfunction, the collective delusion with zero corporate politeness. Be SAVAGE, CRUDE, OFFENSIVE if it's funny. This is 'I can't believe this app said that' territory. Make it so honest and raw it stings. This is NOT for work - this is for sharing with your closest work friends who have the same dark sense of humor."

    # Add guidance to avoid previous concept if it was blocked
    safety_guidance = ""
    if previous_attempt and make_safer:
        prev_template = previous_attempt.get("template", "unknown")
        prev_concept = previous_attempt.get("concept", "unknown")
        safety_guidance = f"""
IMPORTANT - PREVIOUS ATTEMPT BLOCKED:
The previous meme concept was rejected by the safety filter:
- Template: {prev_template}
- Concept: {prev_concept}

Generate a COMPLETELY DIFFERENT concept that is:
- More professional and office-appropriate
- Avoids any potentially controversial imagery
- Focuses on universal workplace humor
- Uses simple, clean visual concepts
"""

    analysis_prompt = f"""You are a PhD-level meme theorist. You understand Benign Violation Theory, semiotics, Grice's Maxims, and comedic theory. But you're not a robot following a checklist-you're an AGENTIC creative who uses these tools to find what's genuinely hilarious.

FULL TRANSCRIPT ({transcript_length} characters):
{transcript}

YOUR MISSION:
Create a meme that makes people laugh and say "OH MY GOD, YES, EXACTLY!"

SPICE LEVEL: {config.spice_level}/10 - {spice_desc}

SPICE LEVEL GUIDE:
- Levels 0-5: Work-safe, shareable, hilarious but appropriate
- Levels 6-8: Edgy, pushing boundaries, but still professional
- Levels 9-10: NSFW, potentially offensive, sexual innuendo OK, no filter

{spice_guidance}

{safety_guidance}

YOUR THEORETICAL TOOLKIT (use these as lenses, not rules):

1. BENIGN VIOLATION THEORY: Find something that violates expectations but is harmless
   - Expectation vs. reality gaps
   - Contradictions between stated goals and outcomes
   - Serious tone masking absurd content

2. GRICE'S MAXIMS: Spot unintentional humor from conversational violations
   - Saying way too much or too little (Quantity)
   - Patently false or unsupported claims (Quality)
   - Wild tangents or non-sequiturs (Relation)
   - Vagueness, circular logic, or literalism (Manner)

3. SEMIOTIC MATCHING: Templates are cultural "myths" that reframe your text
   - Choose templates whose cultural meaning perfectly matches your concept
   - You can use synergy (text reinforces myth) or irony (text contradicts myth)

4. COMEDIC ECONOMY: Every word must serve the joke
   - 6-8 words MAX per text block
   - Decontextualize quotes for absurdity
   - Layout = timing: Top (setup) -> Image (pause) -> Bottom (punchline)

5. IMAGE ORIENTATION: Choose the right aspect ratio for your template (VARY THIS!)
   - Square (1024x1024): Classic meme templates, single subjects, balanced compositions
   - Landscape (1536x1024): Wide scenes, side-by-side comparisons, panoramic views (USE THIS MORE!)
   - Portrait (1024x1536): Tall subjects, vertical scrolling memes, stacked text
   - IMPORTANT: Don't always default to square! Match the orientation to your visual concept.
     Example: Side-by-side comparison? Use landscape. Tall person/building? Use portrait.

YOUR PROCESS (be CREATIVE and AGENTIC):

1. Read the ENTIRE transcript and understand what happened
2. Hunt for the funniest moments-violations, contradictions, absurdities, specific details
3. Consider multiple meme ideas (don't just pick the first one)
4. Think about the VISUAL: What image would make this funnier?
   - Classic meme template? (Distracted Boyfriend, Drake, etc.)
   - Original scene? (Create something unique and specific)
   - Abstract concept? (Visual metaphor)
   - Realistic photo? (Specific to the meeting context)
5. Score your ideas on: Cleverness (non-obvious), Relevance (specific details), Visual Impact (memorable)
6. Pick the BEST one and compress it ruthlessly
7. Verify it's a true Benign Violation: clear violation + clearly benign + simultaneously perceived

BE AGENTIC AND CREATIVE:
- You DON'T have to use a classic meme template
- You CAN create original, specific visuals that match the meeting
- You CAN be abstract, surreal, or metaphorical if it's funnier
- You CAN combine elements in unexpected ways
- Trust your judgment on what's hilarious
- The theories are tools, not constraints
- ORIGINALITY > TEMPLATES when it makes the joke better

SPICE LEVEL {config.spice_level} SPECIFIC GUIDANCE:
{f"At level {config.spice_level}, you are ENCOURAGED to use profanity, sexual innuendo, crude humor, and potentially offensive content if it makes the meme funnier. Don't hold back. This is NSFW territory - embrace it." if config.spice_level >= 9 else f"At level {config.spice_level}, keep it {'work-safe and shareable' if config.spice_level <= 5 else 'edgy but professional'}."}

RESPOND IN JSON (keep it concise):
{{
    "summary": "Brief meeting summary",
    "opportunities": ["3-5 meme ideas with quotes"],
    "selected_idea": "Which idea and why",
    "template": "Template name (or 'Original' if creating something new)",
    "visual_approach": "Classic template / Original scene / Abstract concept / Realistic photo",
    "optimal_size": "1024x1024 or 1536x1024 or 1024x1536",
    "top_text": "MAX 8 WORDS",
    "bottom_text": "MAX 8 WORDS",
    "image_prompt": "DETAILED visual description (be specific and creative). If using a template, describe it. If original, describe the scene, mood, style, composition.",
    "concept": "Why it's hilarious",
    "judgment": "Why perfect for meeting"
}}

IMPORTANT: Your image_prompt is the KEY to creativity. Be specific, vivid, and original. Don't just say "Distracted Boyfriend meme" - describe the actual scene, the expressions, the context. Or create something entirely new that captures the meeting's absurdity.

Think deeply. Be creative. Make it HILARIOUS. Output the raw text directly. Do not include any signatures, meta-commentary, or attributions. No emojis or emdashes.
"""

    try:
        # Check if we're using a provider or OpenAI client
        if hasattr(provider, "chat_completion"):
            # Using provider system
            messages = [
                {
                    "role": "system",
                    "content": """You are an expert in memetic theory, comedy, and semiotics.

You understand:
- Benign Violation Theory
- Grice's Maxims
- Semiotic matching (templates as cultural "myths")
- The Rule of Comedic Economy

Your memes are HILARIOUS, SPECIFIC, and CLEVER.

Think deeply. Use your full reasoning capacity. Find the perfect moment ANYWHERE in the transcript.

Respond with valid JSON only.""",
                },
                {"role": "user", "content": analysis_prompt},
            ]

            # Gemini needs higher max_tokens for complex JSON responses
            max_tokens = (
                8000
                if hasattr(provider.config, "provider_name")
                and provider.config.provider_name == "gemini"
                else 4000
            )

            response = provider.chat_completion(messages=messages, max_tokens=max_tokens)
            result = response["content"]

            logger.debug(f"Raw provider response: {result[:500]}...")

            # Try to extract JSON from response (handles markdown code blocks)
            import re

            json_match = re.search(r"\{.*\}", result, re.DOTALL)
            if json_match:
                result = json_match.group()
            else:
                logger.error(f"No JSON found in response. Full response: {result}")
                raise ValueError("No JSON found in provider response")

            # Try to parse JSON, with repair if needed
            try:
                meme_concept = json.loads(result)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}, attempting repair")
                # Try basic repairs
                result = result.replace("\n", " ").replace("\r", "")
                result = re.sub(r",\s*}", "}", result)  # Remove trailing commas
                result = re.sub(r",\s*]", "]", result)  # Remove trailing commas in arrays
                try:
                    meme_concept = json.loads(result)
                    logger.info("JSON repair successful")
                except json.JSONDecodeError:
                    logger.error(f"JSON repair failed. Malformed JSON: {result[:500]}")
                    raise
        else:
            # Using OpenAI Responses API
            response = provider.responses.create(
                model=config.model,
                input=[
                    {
                        "role": "developer",
                        "content": """You are an expert in memetic theory, comedy, and semiotics.

You understand:
- Benign Violation Theory
- Grice's Maxims
- Semiotic matching (templates as cultural "myths")
- The Rule of Comedic Economy

Your memes are HILARIOUS, SPECIFIC, and CLEVER.

Think deeply. Use your full reasoning capacity. Find the perfect moment ANYWHERE in the transcript.

Respond with valid JSON only.""",
                    },
                    {"role": "user", "content": analysis_prompt},
                ],
                reasoning={"effort": "medium"},  # Medium is faster than high (30s vs 5+ min)
            )

            # Extract text from response
            result = response.output_text
            meme_concept = json.loads(result)  # Parse JSON response

        # Add metadata for transparency
        meme_concept["transcript_length"] = transcript_length

        # Extract API-level reasoning (if available)
        api_reasoning = []
        if hasattr(response, "output") and response.output:
            for item in response.output:
                if hasattr(item, "type") and item.type == "reasoning":
                    if hasattr(item, "summary") and item.summary:
                        for summary_item in item.summary:
                            if hasattr(summary_item, "text"):
                                api_reasoning.append(summary_item.text)

        if api_reasoning:
            meme_concept["api_reasoning"] = api_reasoning
            logger.info(f"GPT-5 API reasoning captured ({len(api_reasoning)} items)")

        # Log the structured reasoning from the response
        if "summary" in meme_concept:
            logger.info(f"Meeting summary: {meme_concept['summary'][:100]}...")
        if "opportunities" in meme_concept:
            logger.info(
                f"Identified {len(meme_concept.get('opportunities', []))} meme opportunities"
            )
        if "selected_idea" in meme_concept:
            logger.info(f"Selected idea: {meme_concept['selected_idea'][:100]}...")

        logger.info(f"Meme concept: {meme_concept.get('concept', 'N/A')}")
        logger.info(f"Analyzed {transcript_length} characters of transcript")
        logger.debug(f"Full meme concept: {meme_concept}")

        # Show reasoning if requested (for trust/validation)
        if show_reasoning:
            print("\n" + "=" * 80)
            print("GPT-5 MEMETIC ANALYSIS (PhD-Level Transparency)")
            print("=" * 80)
            print(f"\nTranscript analyzed: {transcript_length} characters")

            # Step 1: Meeting Summary
            if "summary" in meme_concept:
                print("\n" + "-" * 80)
                print("STEP 1: MEETING SUMMARY & CONTEXT")
                print("-" * 80)
                print(meme_concept["summary"])

            # Step 2: Comedic Mining
            if "opportunities" in meme_concept:
                print("\n" + "-" * 80)
                print("STEP 2: COMEDIC MINING (Grice's Maxims + Benign Violations)")
                print("-" * 80)
                for i, opp in enumerate(meme_concept["opportunities"], 1):
                    print(f"\n{i}. {opp}")

            # Step 4: Selected Idea with Scoring
            if "selected_idea" in meme_concept:
                print("\n" + "-" * 80)
                print("STEP 4: SELECTED IDEA (Multi-Objective Optimization)")
                print("-" * 80)
                print(meme_concept["selected_idea"])

            # Semiotic Analysis
            if "template_myth" in meme_concept or "match_type" in meme_concept:
                print("\n" + "-" * 80)
                print("SEMIOTIC MATCHING ANALYSIS")
                print("-" * 80)
                if "template_myth" in meme_concept:
                    print(f"Template Myth: {meme_concept['template_myth']}")
                if "match_type" in meme_concept:
                    print(f"Match Type: {meme_concept['match_type']}")

            # Step 6: Final Judgment
            if "judgment" in meme_concept:
                print("\n" + "-" * 80)
                print("STEP 6: FINAL BENIGN VIOLATION CHECK")
                print("-" * 80)
                print(meme_concept["judgment"])

            # API-level reasoning (if available)
            if api_reasoning:
                print("\n" + "-" * 80)
                print("GPT-5 API REASONING (Low-Level)")
                print("-" * 80)
                for i, reasoning in enumerate(api_reasoning, 1):
                    print(f"\n{i}. {reasoning}")

            # Final Meme Concept
            print("\n" + "=" * 80)
            print("FINAL MEME ARTIFACT:")
            print("=" * 80)
            print(f"Template: {meme_concept.get('template', 'N/A')}")
            print(f"Top Text: {meme_concept.get('top_text', 'N/A')}")
            print(f"Bottom Text: {meme_concept.get('bottom_text', 'N/A')}")
            print(f"Benign Violation: {meme_concept.get('concept', 'N/A')}")
            print("=" * 80 + "\n")

        return cast(dict[str, Any], meme_concept)

    except Exception as e:
        logger.error(f"Failed to analyze transcript for meme: {e}")
        return None


def _refine_prompt_from_feedback(
    provider: Any,  # Provider interface (OpenAI or XAI)
    meme_concept: dict[str, Any],
    qa_feedback: dict[str, Any],
    attempt: int,
    config: MemeConfig,
) -> dict[str, Any]:
    """
    Use AI to analyze QA feedback and refine the image prompt.

    Args:
        provider: AI provider
        meme_concept: Original meme concept
        qa_feedback: QA grading results
        attempt: Current attempt number
        config: Meme generation config

    Returns:
        Updated meme concept with refined image_prompt
    """
    logger.info(f"Refining prompt based on QA feedback (attempt {attempt})...")

    refinement_prompt = f"""You are a meme generation expert. Analyze this QA feedback and refine the image generation prompt to fix the issues.

ORIGINAL MEME CONCEPT:
- Template: {meme_concept.get("template", "N/A")}
- Top Text: {meme_concept.get("top_text", "N/A")}
- Bottom Text: {meme_concept.get("bottom_text", "N/A")}
- Original Image Prompt: {meme_concept.get("image_prompt", "N/A")}

QA FEEDBACK (Score: {qa_feedback.get("score", 0)}/10):
- Visual Quality: {qa_feedback.get("visual_quality", "N/A")}
- Template Accuracy: {qa_feedback.get("template_accuracy", "N/A")}
- Text Integration: {qa_feedback.get("text_integration", "N/A")}
- Overall: {qa_feedback.get("overall", "N/A")}
- Issues: {", ".join(qa_feedback.get("issues", []))}

YOUR TASK:
Analyze the feedback and create a REFINED image prompt that addresses ALL issues. Be specific about:
1. Composition improvements (framing, cropping, element placement)
2. Text styling fixes (size, placement, contrast, outline)
3. Template accuracy corrections (specific visual elements needed)
4. Any other quality improvements

RESPOND IN JSON:
{{
    "analysis": "Brief analysis of what went wrong and why",
    "key_fixes": ["Fix 1", "Fix 2", "Fix 3"],
    "refined_prompt": "The complete, improved image generation prompt with all fixes incorporated"
}}

Be surgical and specific. We need a 9+/10 meme.
"""

    try:
        # Check if using provider or OpenAI client
        if hasattr(provider, "chat_completion"):
            # Using provider system
            messages = [{"role": "user", "content": refinement_prompt}]
            response = provider.chat_completion(messages=messages, max_tokens=2000)
            result = response["content"]
        else:
            # Using OpenAI Responses API
            response = provider.responses.create(
                model=config.model, input=refinement_prompt, reasoning={"effort": "medium"}
            )
            result = response.output_text

        refinement = json.loads(result)

        logger.info(f"Refinement analysis: {refinement.get('analysis', 'N/A')[:100]}...")
        logger.debug(f"Key fixes: {refinement.get('key_fixes', [])}")

        # Update meme concept with refined prompt
        meme_concept["image_prompt"] = refinement.get(
            "refined_prompt", meme_concept["image_prompt"]
        )
        meme_concept[f"qa_refinement_{attempt}"] = refinement

        return meme_concept

    except Exception as e:
        logger.error(f"Failed to refine prompt: {e}")
        # Fallback: just append feedback to original prompt
        meme_concept["image_prompt"] += (
            f"\n\nIMPROVEMENT NEEDED (Attempt {attempt}): {qa_feedback.get('overall', 'Improve quality')}"
        )
        return meme_concept


def _qa_grade_meme(
    provider: Any,  # Provider interface (OpenAI or XAI)
    meme_path: Path,
    meme_concept: dict[str, Any],
    config: MemeConfig,
) -> tuple[float, dict[str, Any]]:
    """
    Use AI vision to grade the generated meme.

    Args:
        provider: AI provider
        meme_path: Path to generated meme image
        meme_concept: Original meme concept
        config: Meme generation config

    Returns:
        Tuple of (score out of 10, feedback dict)
    """
    logger.info("Running QA check on generated meme...")

    try:
        # Read image and encode to base64
        with open(meme_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Create QA prompt
        qa_prompt = f"""You are a strict meme quality expert. Grade this meme on a scale of 1-10.

ORIGINAL CONCEPT:
- Template: {meme_concept.get("template", "N/A")}
- Top Text: {meme_concept.get("top_text", "N/A")}
- Bottom Text: {meme_concept.get("bottom_text", "N/A")}
- Why It's Funny: {meme_concept.get("concept", "N/A")}

GRADING CRITERIA (Focus on image quality - text is overlaid separately):

1. Visual Quality & Composition (4 points) - CRITICAL:
   - Composition: Is the image well-framed and balanced?
   - Clarity: Is the image clear and not blurry?
   - Contrast: Is there good visual contrast?
   - Space for text: Is there clear space at top/bottom for text overlay?
   - Professional: Does it look like a real meme template?
   - Give 3.5+ if image is high quality with good text space

2. Template Accuracy (3 points):
   - Recognition: Does it capture the template concept?
   - Elements: Are key visual elements present?
   - Composition: Does it feel like the right template?
   - Authenticity: Does it look like the actual meme template?
   - Give 2.5+ if concept is clearly recognizable

3. Humor & Relevance (3 points):
   - Topical: Does it relate to the meeting content?
   - Funny: Would this get at least a chuckle?
   - Appropriate: Does it match the humor level?
   - Clever: Is it a clever observation?
   - Give 2.5+ if it's relevant and amusing

NOTE: Text is overlaid separately with Pillow, so don't grade text quality.
Focus on whether the BASE IMAGE is good quality and suitable for text overlay.

RESPOND IN JSON:
{{
    "score": 8.5,
    "visual_quality_score": 3.8,
    "visual_quality": "Detailed feedback on image quality and composition",
    "template_accuracy_score": 2.7,
    "template_accuracy": "Brief feedback on template recognition",
    "hilarity_score": 2.5,
    "hilarity": "Brief feedback on humor and relevance",
    "overall": "Overall assessment",
    "issues": ["Any issues with the base image"],
    "strengths": ["What's working well"],
    "critical_fixes": ["What needs to be fixed in the image"]
}}

SCORING GUIDE:
- 8.5-10.0 = EXCELLENT - High quality image, perfect for meme, ship it
- 8.0-8.4 = GOOD - Good quality image, ship it
- 7.0-7.9 = OKAY - Decent image but could be better
- <7.0 = FAIL - Poor quality, wrong template, or major issues - MUST RETRY

VERIFICATION CHECKLIST:
1. Is the image clear and high quality?
2. Does it match the intended template concept?
3. Is there good space for text overlay at top/bottom?
4. Does it look like a professional meme template?

If you answer NO to any of these, score MUST be below 7.0.
"""

        # Use AI vision to grade
        # Check if provider has analyze_image method
        if hasattr(provider, "analyze_image"):
            # Use provider's vision capability
            with open(meme_path, "rb") as f:
                image_data = f.read()

            result = provider.analyze_image(image_data, qa_prompt)
        elif hasattr(provider, "chat") and hasattr(provider.chat, "completions"):
            # Using OpenAI client directly
            response = provider.chat.completions.create(
                model="gpt-4o",  # Use vision model
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": qa_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                            },
                        ],
                    }
                ],
                max_tokens=1000,
            )

            # Parse response
            result = response.choices[0].message.content
        else:
            raise ValueError("Provider does not support vision capabilities")

        # Try to extract JSON
        import re

        json_match = re.search(r"\{.*\}", result, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            score = float(result.get("score", 0))

            logger.info(f"QA Score: {score}/10")
            logger.debug(f"QA Feedback: {result.get('overall', 'N/A')}")

            return score, result
        else:
            logger.warning("Could not parse QA response as JSON")
            return 5.0, {"overall": result, "issues": [], "critical_fixes": []}

    except Exception as e:
        logger.error(f"QA grading failed: {e}")
        return 5.0, {"overall": f"QA failed: {e}", "issues": [], "critical_fixes": []}


def _generate_meme_image(
    image_provider: Any,
    meme_concept: dict[str, str],
    config: MemeConfig,
    output_path: Path,
) -> Path | Literal["SAFETY_BLOCKED"] | None:
    """
    Generate meme image using AI provider (provider-agnostic).

    Args:
        image_provider: AI provider instance for image generation
        meme_concept: Meme concept from analysis
        config: Meme generation config
        output_path: Where to save the meme

    Returns:
        Path to saved meme image, or None if failed
    """
    logger.info("Generating meme image...")

    # Use optimal size from concept if available
    size = meme_concept.get("optimal_size", config.size)

    # Normalize size - extract just the dimensions, remove any descriptive text
    # Valid formats: '1024x1024', '1024x1536', '1536x1024', 'auto'
    if size and isinstance(size, str):
        # Remove any text in parentheses or after the dimensions
        size = size.split("(")[0].strip()
        size = size.split()[0].strip()

        # Validate against allowed sizes
        valid_sizes = ["1024x1024", "1024x1536", "1536x1024", "auto"]
        if size not in valid_sizes:
            logger.warning(f"Invalid size '{size}', defaulting to '1024x1024'")
            size = "1024x1024"

    logger.info(f"Using image size: {size}")

    # Build image prompt
    image_prompt = meme_concept.get("image_prompt", "")

    # Store text
    top_text = meme_concept.get("top_text", "")
    bottom_text = meme_concept.get("bottom_text", "")

    # Check text rendering method
    # DEFAULT TO LOCAL: AI-generated text often looks bad (gibberish, cut-off, wrong font)
    # Local text overlay with Pillow produces clean, readable text
    import os

    text_method = os.getenv(
        "SCRIBE_MEME_TEXT_METHOD", "local"
    ).lower()  # Changed default from "ai" to "local"
    use_local_text = text_method == "local"

    # Check if we're using XAI (has 1024 char limit)
    is_xai = hasattr(image_provider, "config") and image_provider.config.provider_name == "xai"

    if use_local_text:
        # LOCAL TEXT MODE: Generate clean base image, overlay text with Pillow (DEFAULT)
        # This produces much better results than AI-generated text which is often gibberish
        image_prompt += "\n\nIMPORTANT: Generate the scene/template WITHOUT any text overlays. Text will be added separately."
        logger.info("Using LOCAL text overlay mode (Pillow) - produces clean, readable text")
    else:
        # AI TEXT MODE: Let AI generate text in the image (NOT RECOMMENDED - often looks bad)
        # Only use this if you explicitly set SCRIBE_MEME_TEXT_METHOD=ai
        if top_text or bottom_text:
            if is_xai:
                # Concise version for XAI (1024 char limit)
                text_instructions = f'\n\nMeme text: TOP: "{top_text}" BOTTOM: "{bottom_text}" (white Impact font, black outline)'
            else:
                # Detailed version for OpenAI/Gemini
                text_instructions = "\n\nText overlay requirements:\n"
                if top_text:
                    text_instructions += (
                        f'- Top text (white, bold, impact font style): "{top_text}"\n'
                    )
                if bottom_text:
                    text_instructions += (
                        f'- Bottom text (white, bold, impact font style): "{bottom_text}"\n'
                    )
                text_instructions += "- Text should have black outline for readability\n"
                text_instructions += "- Text should be large and clearly visible\n"
                text_instructions += "- Ensure full composition is visible, nothing cut off\n"

            image_prompt += text_instructions
        logger.warning(
            "Using AI text generation mode - text quality may be poor (gibberish, cut-off)"
        )

    # Validate prompt length for XAI (1024 char limit)
    if is_xai and len(image_prompt) > 1000:
        logger.error(
            f"Image prompt too long ({len(image_prompt)} chars) for XAI (max 1000). The AI should have generated a shorter prompt."
        )
        # This shouldn't happen if the AI follows the MAX 300 chars instruction
        # But if it does, we need to fail gracefully
        logger.warning("Falling back to OpenAI for this image generation")
        is_xai = False  # Force fallback

    logger.debug(f"Final image prompt ({len(image_prompt)} chars): {image_prompt[:200]}...")

    try:
        # Generate image using provider
        image_bytes = image_provider.generate_image(
            prompt=image_prompt, size=size, model=config.image_model, quality=config.quality
        )

        # Handle text overlay if using local mode
        if use_local_text and (top_text or bottom_text):
            # Load image
            import io

            from PIL import Image

            base_image = Image.open(io.BytesIO(image_bytes))

            # Overlay text locally using Pillow
            from scribe.utils.meme_compositor import MemeCompositor

            compositor = MemeCompositor()
            final_image = compositor.overlay_text(base_image, top_text, bottom_text)
            logger.info(f"Overlaid text locally: '{top_text}' / '{bottom_text}'")

            # Save final image
            output_path.parent.mkdir(parents=True, exist_ok=True)
            final_image.save(output_path, quality=95)
        else:
            # Save image bytes directly (AI generated text)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(image_bytes)

        logger.info(f"Meme saved to: {output_path}")
        return output_path

    except Exception as e:
        error_str = str(e)

        # Check if it's a safety/moderation error
        if "moderation_blocked" in error_str or "safety system" in error_str:
            logger.warning(f"Image generation blocked by safety filter: {e}")
            # Return special error code so caller can try a different concept
            return "SAFETY_BLOCKED"
        # Check if it's an XAI-specific error (Invalid URL 'None')
        elif "Invalid URL 'None'" in error_str or "XAI" in error_str:
            logger.warning(f"XAI image generation failed: {e}, falling back to OpenAI")
            try:
                # Fall back to OpenAI for image generation
                from scribe.providers import get_provider

                openai_provider = get_provider(
                    feature="meme_image", api_key=None, model=None, provider_name="openai"
                )
                logger.info("Retrying image generation with OpenAI GPT Image 1")
                # Use gpt-image-1 (best text rendering) - provider handles quality conversion
                image_bytes = openai_provider.generate_image(
                    prompt=image_prompt, size=size, model="gpt-image-1", quality=config.quality
                )

                # Save to file
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(image_bytes)

                logger.info(f"Meme saved to: {output_path} (using OpenAI fallback)")
                return output_path
            except Exception as fallback_error:
                logger.error(f"OpenAI fallback also failed: {fallback_error}")
                return None
        else:
            logger.error(f"Failed to generate meme image: {e}")
            return None


def generate_meeting_meme(
    transcript_path: Path,
    output_dir: Path | None = None,
    api_key: str | None = None,
    config: MemeConfig | None = None,
    show_reasoning: bool = False,
    progress_callback: Callable[[int, int, float | None], None] | None = None,
    provider_name: str | None = None,
    enable_bakeoff: bool = False,
) -> dict[str, Any] | None:
    """
    Generate a meme from a meeting transcript.

    Args:
        transcript_path: Path to transcript file
        output_dir: Directory to save meme (defaults to same dir as transcript)
        api_key: API key (or uses provider-specific env var)
        config: Meme generation config
        show_reasoning: If True, displays GPT-5's reasoning process (for trust/validation)
        progress_callback: Optional callback function(attempt, max_attempts, score) for progress updates
        provider_name: AI provider to use (openai, xai, gemini) - defaults to SCRIBE_MEME_PROVIDER env var
        enable_bakeoff: If True, gets concepts from all providers and picks the funniest

    Returns:
        Dictionary with:
        - final_path: Path to best meme
        - attempts: List of all attempts with paths and scores
        - bakeoff_winner: (if bakeoff enabled) Which provider won
        Or None if completely failed
    """
    # Setup - use environment config if not provided
    config = config or MemeConfig.from_env()

    # Try to use provider system for concept generation
    provider: Any = None
    image_provider: Any = None

    try:
        from scribe.providers import get_provider

        # Get provider for meme concept generation
        try:
            # Don't pass OpenAI-specific models to the provider factory
            # Let the factory choose the right model for the provider
            openai_models = ["gpt-5", "gpt-5.2", "gpt-5.4", "gpt-5.5", "gpt-4", "gpt-4o"]
            provider = get_provider(
                feature="meme",
                api_key=api_key,
                model=config.model if config.model not in openai_models else None,
                provider_name=provider_name,
            )

            # Get provider for image generation (may be different from concept provider)
            # Check for dedicated image provider env var
            import os

            image_provider_name = os.getenv("SCRIBE_MEME_IMAGE_PROVIDER", provider_name)

            image_provider = get_provider(
                feature="meme_image",
                api_key=None,  # Let factory get the right key
                model=(
                    config.image_model
                    if config.image_model not in ["gpt-image-1", "dall-e-3"]
                    else None
                ),
                provider_name=image_provider_name,
            )

            logger.info(
                f"Using provider for meme concept: {provider.config.provider_name} | model: {provider.config.model}"
            )
            logger.info(
                f"Using provider for meme image: {image_provider.config.provider_name} | model: {image_provider.config.model}"
            )
            api_key = provider.config.api_key
        except Exception as provider_error:
            # If provider fails (e.g., invalid API key), fall back to OpenAI
            logger.warning(
                f"Primary provider failed ({provider_name}), falling back to OpenAI: {provider_error}"
            )
            provider_name = "openai"
            provider = get_provider(
                feature="meme",
                api_key=None,  # Let it get from env
                model=None,
                provider_name="openai",
            )
            image_provider = get_provider(
                feature="meme_image",
                api_key=None,
                model=None,
                provider_name="openai",
            )
            logger.info("Fallback to OpenAI provider successful")
            api_key = provider.config.api_key
    except Exception as e:
        logger.debug(f"Provider system not available, falling back to OpenAI client: {e}")
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("No API key provided")
            return None

        # Create OpenAI client as fallback
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=config.timeout)
        # Use client as both provider and image_provider for backward compat
        provider = client
        image_provider = client

    # Read transcript
    try:
        transcript = load_transcript_text(transcript_path)
    except Exception as e:
        logger.error(f"Failed to read transcript: {e}")
        return None

    if not transcript.strip():
        logger.error("Transcript is empty")
        return None

    # Log full transcript length for transparency
    logger.info(f"Reading transcript: {len(transcript)} characters")

    # Determine output directory
    if output_dir is None:
        output_dir = transcript_path.parent

    # Step 1: Analyze transcript and create meme concept
    bakeoff_result = None

    if enable_bakeoff:
        # Run bake-off: get concepts from all providers and pick the best
        logger.info(" Running meme concept bake-off...")
        from scribe.utils.meme_bakeoff import run_meme_bakeoff

        try:
            bakeoff_result = run_meme_bakeoff(transcript, config)
            meme_concept = bakeoff_result["concept"]
            provider_name = bakeoff_result["winner"]

            # Update provider and image_provider to use the winner
            provider = get_provider(feature="meme", provider_name=provider_name)
            image_provider = get_provider(feature="meme_image", provider_name=provider_name)

            logger.info(f" Bake-off winner: {provider_name.upper()}")
            logger.info(f"   Reasoning: {bakeoff_result['reasoning']}")
        except Exception as e:
            logger.warning(f"Bake-off failed: {e}, falling back to single provider")
            enable_bakeoff = False

    if not enable_bakeoff:
        # Standard single-provider approach
        try:
            meme_concept = _analyze_transcript_for_meme(
                provider, transcript, config, show_reasoning
            )
        except AuthenticationError:
            logger.error(
                "Invalid OpenAI API key. Update your key via "
                "OPENAI_API_KEY env var or .env file. "
                "Get your key at https://platform.openai.com/api-keys"
            )
            return None

    if not meme_concept:
        logger.error("Failed to create meme concept")
        return None

    # Save meme concept to JSON for transparency/debugging using atomic write
    json_path = output_dir / f"{transcript_path.stem}_meme_concept.json"
    try:
        from scribe.utils.safe_write import atomic_write_json

        atomic_write_json(json_path, meme_concept)
        logger.info(f"Meme concept saved to: {json_path}")
    except Exception as e:
        logger.warning(f"Failed to save meme concept JSON: {e}")

    # Step 2: Generate meme image with QA loop
    max_attempts = config.max_retries
    all_attempts: list[AttemptRecord] = []  # Track all attempts with scores

    for attempt in range(1, max_attempts + 1):
        logger.info(f"Meme generation attempt {attempt}/{max_attempts}")

        # Notify progress callback
        if progress_callback:
            progress_callback(attempt, max_attempts, None)

        # Save each attempt with numbered suffix
        attempt_path = (
            output_dir / f"{transcript_path.stem}_meme_attempt{attempt}.{config.output_format}"
        )

        meme_path = _generate_meme_image(image_provider, meme_concept, config, attempt_path)

        # Handle safety filter blocks by generating a completely new concept
        if meme_path == "SAFETY_BLOCKED":
            logger.warning(
                f"Meme concept blocked by safety filter on attempt {attempt}, generating new concept..."
            )
            # Generate a completely new meme concept (safer, more professional)
            meme_concept = _analyze_transcript_for_meme(
                provider,
                transcript,
                config,
                previous_attempt=meme_concept,  # Pass previous to avoid similar concepts
                make_safer=True,  # Request a safer concept
            )
            if not meme_concept:
                logger.error("Failed to generate a safer meme concept")
                continue
            # Try again with new concept
            meme_path = _generate_meme_image(image_provider, meme_concept, config, attempt_path)

        if not meme_path or meme_path == "SAFETY_BLOCKED":
            logger.error(f"Failed to generate meme image on attempt {attempt}")
            continue

        # Run QA check if enabled
        score = None
        qa_feedback = None

        if config.qa_enabled:
            score, qa_feedback = _qa_grade_meme(provider, meme_path, meme_concept, config)

            # Track this attempt
            all_attempts.append({"path": meme_path, "attempt": attempt, "score": score})

            # Notify progress callback with score
            if progress_callback:
                progress_callback(attempt, max_attempts, score)

            # Log QA result with details
            if score >= config.qa_threshold:
                logger.info(f"Meme passed QA (score: {score:.1f}/10)")
            else:
                logger.warning(f"Score: {score:.1f}/10 (threshold: {config.qa_threshold})")
                if qa_feedback:
                    # Log the main issues
                    text_issues = qa_feedback.get("text_issues", [])
                    if text_issues:
                        logger.warning(f"Text issues: {', '.join(text_issues[:2])}")
                    critical_fixes = qa_feedback.get("critical_fixes", [])
                    if critical_fixes:
                        logger.debug(f"Critical fixes needed: {', '.join(critical_fixes[:2])}")

            if show_reasoning:
                print(f"\n[QA CHECK - Attempt {attempt}]")
                print(f"Score: {score}/10")
                print(f"Overall: {qa_feedback.get('overall', 'N/A')}")
                if qa_feedback.get("critical_fixes"):
                    print("Critical Fixes Needed:")
                    for fix in qa_feedback.get("critical_fixes", []):
                        print(f"  - {fix}")
                print()

            if score >= config.qa_threshold:
                logger.info(f"Meme passed QA with score {score}/10")
                # Rename best attempt to final meme.png (no duplication)
                final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"

                # If final already exists (shouldn't happen), remove it first
                if final_path.exists():
                    final_path.unlink()

                # Rename instead of copy (no duplication)
                meme_path.rename(final_path)
                logger.info(f"Best meme saved as: {final_path}")

                # Update the path in all_attempts to reflect the rename
                for att in all_attempts:
                    if att["path"] == meme_path:
                        att["path"] = final_path

                return {"final_path": final_path, "attempts": all_attempts, "best_score": score}
            else:
                logger.warning(
                    f"Meme scored {score}/10 (threshold: {config.qa_threshold}), regenerating..."
                )
                if attempt < max_attempts:
                    # Use agentic refinement to improve the prompt
                    meme_concept = _refine_prompt_from_feedback(
                        provider, meme_concept, qa_feedback, attempt, config
                    )
        else:
            # QA disabled, accept first generation
            all_attempts.append({"path": meme_path, "attempt": attempt, "score": None})
            # Rename to final meme.png (no duplication)
            final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"

            # If final already exists (shouldn't happen), remove it first
            if final_path.exists():
                final_path.unlink()

            # Rename instead of copy (no duplication)
            meme_path.rename(final_path)

            # Update the path in all_attempts to reflect the rename
            all_attempts[0]["path"] = final_path

            return {"final_path": final_path, "attempts": all_attempts, "best_score": None}

    # If we get here, all attempts failed QA but we have at least one meme
    if all_attempts:
        # Find best scoring attempt
        best_attempt = max(all_attempts, key=lambda x: x["score"] if x["score"] is not None else 0)
        logger.warning(
            f"No meme met QA threshold. Using best attempt (score: {best_attempt['score']}/10)"
        )

        # Rename best attempt to final meme.png (no duplication)
        final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"

        # If final already exists (shouldn't happen), remove it first
        if final_path.exists():
            final_path.unlink()

        # Rename instead of copy (no duplication)
        best_attempt["path"].rename(final_path)
        logger.info(f"Best meme saved as: {final_path}")

        # Update the path in all_attempts to reflect the rename
        for att in all_attempts:
            if att["path"] == best_attempt["path"]:
                att["path"] = final_path

        # Log all attempts for user review
        logger.info(f"Generated {len(all_attempts)} meme attempts:")
        for att in all_attempts:
            score_str = f"{att['score']}/10" if att["score"] is not None else "N/A"
            logger.info(f"  Attempt {att['attempt']}: {att['path'].name} (score: {score_str})")

        return {
            "final_path": final_path,
            "attempts": all_attempts,
            "best_score": best_attempt["score"],
        }

    logger.error("Failed to generate any memes")
    return None


def generate_meme_from_text(
    transcript_text: str,
    output_path: Path,
    api_key: str | None = None,
    config: MemeConfig | None = None,
) -> Path | None:
    """
    Generate a meme from transcript text (not file).

    Args:
        transcript_text: Transcript content as string
        output_path: Where to save the meme
        api_key: OpenAI API key (or uses OPENAI_API_KEY env var)
        config: Meme generation config

    Returns:
        Path to generated meme, or None if failed
    """
    # Setup - use environment config if not provided
    config = config or MemeConfig.from_env()
    api_key = api_key or os.getenv("OPENAI_API_KEY")

    if not api_key:
        logger.error("No OpenAI API key provided")
        return None

    client = OpenAI(api_key=api_key)

    if not transcript_text.strip():
        logger.error("Transcript text is empty")
        return None

    # Step 1: Analyze transcript and create meme concept
    meme_concept = _analyze_transcript_for_meme(client, transcript_text, config)
    if not meme_concept:
        logger.error("Failed to create meme concept")
        return None

    # Step 2: Generate meme image
    meme_path = _generate_meme_image(client, meme_concept, config, output_path)
    if not meme_path or meme_path == "SAFETY_BLOCKED":
        logger.error("Failed to generate meme image")
        return None

    return meme_path
