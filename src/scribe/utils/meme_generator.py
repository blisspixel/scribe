"""
Agentic AI Meme Generation for Meeting Transcripts

Uses GPT-5 to analyze transcript and create meme concept,
then generates the meme image using OpenAI's image generation API.
"""

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from openai import OpenAI
from dotenv import load_dotenv, find_dotenv

# Load environment
load_dotenv(find_dotenv(usecwd=True), override=False)

logger = logging.getLogger("meme_generator")
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
logger.setLevel(getattr(logging, os.getenv("MEME_LOG_LEVEL", "WARNING").upper(), logging.WARNING))


@dataclass
class MemeConfig:
    """Configuration for meme generation."""
    model: str = "gpt-5"
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
                    logger.warning(f"Invalid SCRIBE_MEME_QA_THRESHOLD: {threshold_str} (must be 0.0-10.0), using default: {config.qa_threshold}")
            except ValueError:
                logger.warning(f"Invalid SCRIBE_MEME_QA_THRESHOLD: {threshold_str} (not a number), using default: {config.qa_threshold}")
        
        # Read max attempts from environment
        attempts_str = os.getenv("SCRIBE_MEME_QA_ATTEMPTS")
        if attempts_str:
            try:
                attempts = int(attempts_str)
                if 1 <= attempts <= 10:
                    config.max_retries = attempts
                else:
                    logger.warning(f"Invalid SCRIBE_MEME_QA_ATTEMPTS: {attempts_str} (must be 1-10), using default: {config.max_retries}")
            except ValueError:
                logger.warning(f"Invalid SCRIBE_MEME_QA_ATTEMPTS: {attempts_str} (not an integer), using default: {config.max_retries}")
        
        # Read spice level from environment
        spice_str = os.getenv("SCRIBE_HUMOR_SPICE")
        if spice_str:
            try:
                spice = int(spice_str)
                if 0 <= spice <= 10:
                    config.spice_level = spice
                else:
                    logger.warning(f"Invalid SCRIBE_HUMOR_SPICE: {spice_str} (must be 0-10), using default: {config.spice_level}")
            except ValueError:
                logger.warning(f"Invalid SCRIBE_HUMOR_SPICE: {spice_str} (not an integer), using default: {config.spice_level}")
        
        return config


def _analyze_transcript_for_meme(
    client: OpenAI,
    transcript: str,
    config: MemeConfig,
    show_reasoning: bool = False
) -> Optional[Dict[str, Any]]:
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
    logger.info(f"Analyzing transcript for meme concept... (transcript length: {transcript_length} characters)")
    
    # Spice level descriptions
    spice_descriptions = {
        0: "DISABLED - No meme should be generated",
        1: "MILD - Office-safe, gentle irony, no edge",
        2: "MILD - Polite observations, very safe",
        3: "MILD - Light humor, suitable for all audiences",
        4: "HONEST - Witty, slightly pointed, still professional",
        5: "HONEST - Default level - accurate, clever, shareable",
        6: "HONEST - Occasionally dark, but still appropriate",
        7: "CUTTING - Slightly uncomfortable, punches up at processes",
        8: "CUTTING - Dark humor, exposes absurdity, still shareable",
        9: "SPICY - Brutally honest, may make people flinch (but laugh)",
        10: "SPICY - 'I can't believe this app said that' funny - no filter"
    }
    
    spice_desc = spice_descriptions.get(config.spice_level, "HONEST - Default level")
    
    # Detailed spice guidance
    if config.spice_level <= 3:
        spice_guidance = "Be extremely cautious and gentle. Avoid any edge or discomfort. Keep it extremely safe."
    elif config.spice_level <= 6:
        spice_guidance = "Be witty and honest. Punch up at processes, not people. Keep it shareable."
    elif config.spice_level <= 8:
        spice_guidance = "Be cutting and expose absurdity. Make them laugh and think. Balance humor with professionalism."
    elif config.spice_level == 9:
        spice_guidance = "Be brutally honest. Expose the dysfunction, the waste, the quiet despair. Make them laugh uncomfortably but still want to share it."
    else:  # Level 10
        spice_guidance = "NO FILTER. Say what everyone was thinking but would never say out loud. Expose the absurdity, the dysfunction, the collective delusion. Be savage but accurate. This is 'I can't believe this app said that' territory. Make it so honest it stings."
    
    analysis_prompt = f"""You are a PhD-level meme theorist. You understand Benign Violation Theory, semiotics, Grice's Maxims, and comedic theory. But you're not a robot following a checklist—you're an AGENTIC creative who uses these tools to find what's genuinely hilarious.

FULL TRANSCRIPT ({transcript_length} characters):
{transcript}

YOUR MISSION:
Create a meme that makes people laugh and say "OH MY GOD, YES, EXACTLY!"

SPICE LEVEL: {config.spice_level}/10 - {spice_desc}
{spice_guidance}

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
   - Layout = timing: Top (setup) → Image (pause) → Bottom (punchline)

YOUR PROCESS (be adaptive, not rigid):

1. Read the ENTIRE transcript and understand what happened
2. Hunt for the funniest moments—violations, contradictions, absurdities, specific details
3. Consider multiple meme ideas (don't just pick the first one)
4. For each idea, think about which template's "myth" would perfectly reframe it
5. Score your ideas on: Cleverness (non-obvious), Relevance (specific details), Safety (punches concepts not people)
6. Pick the BEST one and compress it ruthlessly
7. Verify it's a true Benign Violation: clear violation + clearly benign + simultaneously perceived

BE AGENTIC:
- If you find something funnier than what the theories predict, GO WITH IT
- Invent new template concepts if they're better than existing ones
- Trust your judgment on what's hilarious
- The theories are tools, not constraints

RESPOND IN JSON:
{{
    "summary": "Brief meeting summary with emotional tone",
    "opportunities": ["List 3-5 potential meme ideas with quotes and why they're funny"],
    "selected_idea": "Which idea you chose and why (include your Cleverness/Relevance/Safety assessment)",
    "template": "Template name (or describe new concept)",
    "template_myth": "What cultural meaning this template brings",
    "match_type": "Synergy or Ironic Juxtaposition (or something else if you're being creative)",
    "optimal_size": "Best image size for this template: '1024x1024' (square), '1536x1024' (landscape), '1024x1536' (portrait), or 'auto' (let model decide)",
    "top_text": "MAX 8 WORDS",
    "bottom_text": "MAX 8 WORDS",
    "image_prompt": "Detailed visual description with Impact font styling. Be specific about composition and framing to avoid cropping issues.",
    "concept": "One sentence: Why this is hilarious",
    "judgment": "Why this meme is perfect for this meeting"
}}

Think deeply. Be creative. Make it HILARIOUS.
"""

    try:
        # Use Responses API for GPT-5 with high reasoning
        response = client.responses.create(
            model=config.model,
            input=[
                {"role": "developer", "content": """You are an expert in memetic theory, comedy, and semiotics.

You understand:
- Benign Violation Theory
- Grice's Maxims
- Semiotic matching (templates as cultural "myths")
- The Rule of Comedic Economy

Your memes are HILARIOUS, SPECIFIC, and CLEVER.

Think deeply. Use your full reasoning capacity. Find the perfect moment ANYWHERE in the transcript.

Respond with valid JSON only."""},
                {"role": "user", "content": analysis_prompt}
            ],
            reasoning={"effort": "high"}  # Let GPT-5 think deeply
        )
        
        # Extract text from response
        result = response.output_text
        meme_concept = json.loads(result)  # Parse JSON response
        
        # Add metadata for transparency
        meme_concept["transcript_length"] = transcript_length
        
        # Extract API-level reasoning (if available)
        api_reasoning = []
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'type') and item.type == 'reasoning':
                    if hasattr(item, 'summary') and item.summary:
                        for summary_item in item.summary:
                            if hasattr(summary_item, 'text'):
                                api_reasoning.append(summary_item.text)
        
        if api_reasoning:
            meme_concept["api_reasoning"] = api_reasoning
            logger.info(f"GPT-5 API reasoning captured ({len(api_reasoning)} items)")
        
        # Log the structured reasoning from the response
        if "summary" in meme_concept:
            logger.info(f"Meeting summary: {meme_concept['summary'][:100]}...")
        if "opportunities" in meme_concept:
            logger.info(f"Identified {len(meme_concept.get('opportunities', []))} meme opportunities")
        if "selected_idea" in meme_concept:
            logger.info(f"Selected idea: {meme_concept['selected_idea'][:100]}...")
        
        logger.info(f"Meme concept: {meme_concept.get('concept', 'N/A')}")
        logger.info(f"Analyzed {transcript_length} characters of transcript")
        logger.debug(f"Full meme concept: {meme_concept}")
        
        # Show reasoning if requested (for trust/validation)
        if show_reasoning:
            print("\n" + "="*80)
            print("GPT-5 MEMETIC ANALYSIS (PhD-Level Transparency)")
            print("="*80)
            print(f"\nTranscript analyzed: {transcript_length} characters")
            
            # Step 1: Meeting Summary
            if "summary" in meme_concept:
                print("\n" + "-"*80)
                print("STEP 1: MEETING SUMMARY & CONTEXT")
                print("-"*80)
                print(meme_concept["summary"])
            
            # Step 2: Comedic Mining
            if "opportunities" in meme_concept:
                print("\n" + "-"*80)
                print("STEP 2: COMEDIC MINING (Grice's Maxims + Benign Violations)")
                print("-"*80)
                for i, opp in enumerate(meme_concept["opportunities"], 1):
                    print(f"\n{i}. {opp}")
            
            # Step 4: Selected Idea with Scoring
            if "selected_idea" in meme_concept:
                print("\n" + "-"*80)
                print("STEP 4: SELECTED IDEA (Multi-Objective Optimization)")
                print("-"*80)
                print(meme_concept["selected_idea"])
            
            # Semiotic Analysis
            if "template_myth" in meme_concept or "match_type" in meme_concept:
                print("\n" + "-"*80)
                print("SEMIOTIC MATCHING ANALYSIS")
                print("-"*80)
                if "template_myth" in meme_concept:
                    print(f"Template Myth: {meme_concept['template_myth']}")
                if "match_type" in meme_concept:
                    print(f"Match Type: {meme_concept['match_type']}")
            
            # Step 6: Final Judgment
            if "judgment" in meme_concept:
                print("\n" + "-"*80)
                print("STEP 6: FINAL BENIGN VIOLATION CHECK")
                print("-"*80)
                print(meme_concept["judgment"])
            
            # API-level reasoning (if available)
            if api_reasoning:
                print("\n" + "-"*80)
                print("GPT-5 API REASONING (Low-Level)")
                print("-"*80)
                for i, reasoning in enumerate(api_reasoning, 1):
                    print(f"\n{i}. {reasoning}")
            
            # Final Meme Concept
            print("\n" + "="*80)
            print("FINAL MEME ARTIFACT:")
            print("="*80)
            print(f"Template: {meme_concept.get('template', 'N/A')}")
            print(f"Top Text: {meme_concept.get('top_text', 'N/A')}")
            print(f"Bottom Text: {meme_concept.get('bottom_text', 'N/A')}")
            print(f"Benign Violation: {meme_concept.get('concept', 'N/A')}")
            print("="*80 + "\n")
        
        return meme_concept
        
    except Exception as e:
        logger.error(f"Failed to analyze transcript for meme: {e}")
        return None


def _refine_prompt_from_feedback(
    client: OpenAI,
    meme_concept: Dict[str, Any],
    qa_feedback: Dict[str, Any],
    attempt: int,
    config: MemeConfig
) -> Dict[str, Any]:
    """
    Use GPT-5 to analyze QA feedback and refine the image prompt.
    
    Args:
        client: OpenAI client
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
- Template: {meme_concept.get('template', 'N/A')}
- Top Text: {meme_concept.get('top_text', 'N/A')}
- Bottom Text: {meme_concept.get('bottom_text', 'N/A')}
- Original Image Prompt: {meme_concept.get('image_prompt', 'N/A')}

QA FEEDBACK (Score: {qa_feedback.get('score', 0)}/10):
- Visual Quality: {qa_feedback.get('visual_quality', 'N/A')}
- Template Accuracy: {qa_feedback.get('template_accuracy', 'N/A')}
- Text Integration: {qa_feedback.get('text_integration', 'N/A')}
- Overall: {qa_feedback.get('overall', 'N/A')}
- Issues: {', '.join(qa_feedback.get('issues', []))}

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
        response = client.responses.create(
            model=config.model,
            input=refinement_prompt,
            reasoning={"effort": "medium"}
        )
        
        result = response.output_text
        refinement = json.loads(result)
        
        logger.info(f"Refinement analysis: {refinement.get('analysis', 'N/A')[:100]}...")
        logger.debug(f"Key fixes: {refinement.get('key_fixes', [])}")
        
        # Update meme concept with refined prompt
        meme_concept["image_prompt"] = refinement.get("refined_prompt", meme_concept["image_prompt"])
        meme_concept[f"qa_refinement_{attempt}"] = refinement
        
        return meme_concept
        
    except Exception as e:
        logger.error(f"Failed to refine prompt: {e}")
        # Fallback: just append feedback to original prompt
        meme_concept["image_prompt"] += f"\n\nIMPROVEMENT NEEDED (Attempt {attempt}): {qa_feedback.get('overall', 'Improve quality')}"
        return meme_concept


def _qa_grade_meme(
    client: OpenAI,
    meme_path: Path,
    meme_concept: Dict[str, Any],
    config: MemeConfig
) -> tuple[float, Dict[str, Any]]:
    """
    Use GPT-4o vision to grade the generated meme.
    
    Args:
        client: OpenAI client
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
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Create QA prompt
        qa_prompt = f"""You are a meme quality expert. Grade this meme on a scale of 1-10.

ORIGINAL CONCEPT:
- Template: {meme_concept.get('template', 'N/A')}
- Top Text: {meme_concept.get('top_text', 'N/A')}
- Bottom Text: {meme_concept.get('bottom_text', 'N/A')}
- Why It's Funny: {meme_concept.get('concept', 'N/A')}

GRADING CRITERIA (Be fair and balanced):

1. Visual Quality (3 points):
   - Composition: Is the image reasonably well-framed? Minor cropping is acceptable.
   - Contrast: Is text mostly readable? Perfect contrast not required.
   - Overall: Does it look like a meme people would share?
   - Give 2.5+ if text is readable and image looks decent

2. Template Accuracy (3 points):
   - Recognition: Does it capture the spirit of the template concept?
   - Elements: Are the key visual elements present enough to convey the idea?
   - Composition: Does it feel like the right template style?
   - Give 2.5+ if the concept is recognizable, even if not pixel-perfect

3. Text Integration (2 points):
   - Placement: Is text positioned reasonably well?
   - Styling: Is text readable with decent contrast?
   - Readability: Can you understand it without squinting?
   - Give 1.5+ if text is legible and placed appropriately

4. Humor & Relevance (2 points):
   - Topical: Does it relate to the meeting content?
   - Funny: Would this get at least a chuckle or knowing nod?
   - Spice: Does it match the requested humor intensity?
   - Give 1.5+ if it's relevant and amusing

RESPOND IN JSON:
{{
    "score": 8.5,
    "visual_quality_score": 2.5,
    "visual_quality": "Brief feedback",
    "template_accuracy_score": 2.8,
    "template_accuracy": "Brief feedback",
    "text_integration_score": 1.7,
    "text_integration": "Brief feedback",
    "hilarity_score": 1.5,
    "hilarity": "Brief feedback",
    "overall": "Overall assessment",
    "issues": ["Issue 1 if any", "Issue 2 if any"],
    "strengths": ["What's working well"],
    "critical_fixes": ["Fix 1 if needed", "Fix 2 if needed"]
}}

SCORING GUIDE:
- 8.5-10.0 = EXCELLENT - Ship it immediately
- 8.0-8.4 = GOOD - Acceptable, ship it
- 7.0-7.9 = OKAY - Could be better but usable
- <7.0 = NEEDS WORK - Try again

Be fair. We want good memes that are funny and relevant, not perfect pixel art.
"""
        
        # Use GPT-5 vision to grade
        response = client.chat.completions.create(
            model="gpt-4o",  # Use vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": qa_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        
        # Parse response
        result_text = response.choices[0].message.content
        
        # Try to extract JSON
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            score = float(result.get("score", 0))
            
            logger.info(f"QA Score: {score}/10")
            logger.debug(f"QA Feedback: {result.get('overall', 'N/A')}")
            
            return score, result
        else:
            logger.warning("Could not parse QA response as JSON")
            return 5.0, {"overall": result_text, "issues": [], "critical_fixes": []}
            
    except Exception as e:
        logger.error(f"QA grading failed: {e}")
        return 5.0, {"overall": f"QA failed: {e}", "issues": [], "critical_fixes": []}


def _generate_meme_image(
    client: OpenAI,
    meme_concept: Dict[str, str],
    config: MemeConfig,
    output_path: Path
) -> Optional[Path]:
    """
    Generate meme image using OpenAI image generation API.
    
    Args:
        client: OpenAI client
        meme_concept: Meme concept from analysis
        config: Meme generation config
        output_path: Where to save the meme
        
    Returns:
        Path to saved meme image, or None if failed
    """
    logger.info("Generating meme image...")
    
    # Use optimal size from concept if available
    size = meme_concept.get("optimal_size", config.size)
    logger.info(f"Using image size: {size}")
    
    # Build comprehensive image prompt
    image_prompt = meme_concept.get("image_prompt", "")
    
    # Add text overlay instructions if we have top/bottom text
    top_text = meme_concept.get("top_text", "")
    bottom_text = meme_concept.get("bottom_text", "")
    
    if top_text or bottom_text:
        text_instructions = "\n\nText overlay requirements:\n"
        if top_text:
            text_instructions += f"- Top text (white, bold, impact font style): \"{top_text}\"\n"
        if bottom_text:
            text_instructions += f"- Bottom text (white, bold, impact font style): \"{bottom_text}\"\n"
        text_instructions += "- Text should have black outline for readability\n"
        text_instructions += "- Text should be large and clearly visible\n"
        text_instructions += "- Ensure full composition is visible, nothing cut off\n"
        
        image_prompt += text_instructions
    
    logger.debug(f"Final image prompt: {image_prompt}")
    
    try:
        # Generate image using OpenAI API
        # Note: gpt-image-1 always returns base64, no need for response_format
        response = client.images.generate(
            model=config.image_model,
            prompt=image_prompt,
            n=1,
            size=size,
            quality=config.quality
        )
        
        # Extract base64 image data
        image_b64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_b64)
        
        # Save to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        
        logger.info(f"Meme saved to: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Failed to generate meme image: {e}")
        return None


def generate_meeting_meme(
    transcript_path: Path,
    output_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
    config: Optional[MemeConfig] = None,
    show_reasoning: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Generate a meme from a meeting transcript.
    
    Args:
        transcript_path: Path to transcript file
        output_dir: Directory to save meme (defaults to same dir as transcript)
        api_key: OpenAI API key (or uses OPENAI_API_KEY env var)
        config: Meme generation config
        show_reasoning: If True, displays GPT-5's reasoning process (for trust/validation)
        
    Returns:
        Dictionary with:
        - final_path: Path to best meme
        - attempts: List of all attempts with paths and scores
        Or None if completely failed
    """
    # Setup - use environment config if not provided
    config = config or MemeConfig.from_env()
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("No OpenAI API key provided")
        return None
    
    client = OpenAI(api_key=api_key)
    
    # Read transcript
    try:
        transcript = transcript_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read transcript: {e}")
        return None
    
    if not transcript.strip():
        logger.error("Transcript is empty")
        return None
    
    # Log full transcript length for transparency
    logger.info(f"Reading transcript: {len(transcript)} characters")
    
    # Determine output path
    if output_dir is None:
        output_dir = transcript_path.parent
    
    output_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"
    
    # Step 1: Analyze transcript and create meme concept
    meme_concept = _analyze_transcript_for_meme(client, transcript, config, show_reasoning)
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
    all_attempts = []  # Track all attempts with scores
    
    # Import console for progress updates
    from rich.console import Console
    console = Console()
    
    for attempt in range(1, max_attempts + 1):
        logger.info(f"Meme generation attempt {attempt}/{max_attempts}")
        
        # Save each attempt with numbered suffix
        attempt_path = output_dir / f"{transcript_path.stem}_meme_attempt{attempt}.{config.output_format}"
        
        meme_path = _generate_meme_image(client, meme_concept, config, attempt_path)
        if not meme_path:
            logger.error(f"Failed to generate meme image on attempt {attempt}")
            continue
        
        # Run QA check if enabled
        score = None
        qa_feedback = None
        
        if config.qa_enabled:
            score, qa_feedback = _qa_grade_meme(client, meme_path, meme_concept, config)
            
            # Track this attempt
            all_attempts.append({
                "path": meme_path,
                "attempt": attempt,
                "score": score
            })
            
            # Log QA result (don't print to console - spinner handles it)
            if score >= config.qa_threshold:
                logger.info(f"Meme passed QA (score: {score:.1f}/10)")
            else:
                logger.info(f"Score: {score:.1f}/10 (threshold: {config.qa_threshold}) - refining...")
            
            if show_reasoning:
                print(f"\n[QA CHECK - Attempt {attempt}]")
                print(f"Score: {score}/10")
                print(f"Overall: {qa_feedback.get('overall', 'N/A')}")
                if qa_feedback.get('critical_fixes'):
                    print(f"Critical Fixes Needed:")
                    for fix in qa_feedback.get('critical_fixes', []):
                        print(f"  - {fix}")
                print()
            
            if score >= config.qa_threshold:
                logger.info(f"Meme passed QA with score {score}/10")
                # Copy best attempt to final meme.png
                final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"
                import shutil
                shutil.copy2(meme_path, final_path)
                logger.info(f"Best meme saved as: {final_path}")
                return {
                    "final_path": final_path,
                    "attempts": all_attempts,
                    "best_score": score
                }
            else:
                logger.warning(f"Meme scored {score}/10 (threshold: {config.qa_threshold}), regenerating...")
                if attempt < max_attempts:
                    # Use agentic refinement to improve the prompt
                    meme_concept = _refine_prompt_from_feedback(client, meme_concept, qa_feedback, attempt, config)
        else:
            # QA disabled, accept first generation
            all_attempts.append({
                "path": meme_path,
                "attempt": attempt,
                "score": None
            })
            # Copy to final meme.png
            final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"
            import shutil
            shutil.copy2(meme_path, final_path)
            return {
                "final_path": final_path,
                "attempts": all_attempts,
                "best_score": None
            }
    
    # If we get here, all attempts failed QA but we have at least one meme
    if all_attempts:
        # Find best scoring attempt
        best_attempt = max(all_attempts, key=lambda x: x["score"] if x["score"] is not None else 0)
        logger.warning(f"No meme met QA threshold. Using best attempt (score: {best_attempt['score']}/10)")
        
        # Copy best attempt to final meme.png
        final_path = output_dir / f"{transcript_path.stem}_meme.{config.output_format}"
        import shutil
        shutil.copy2(best_attempt["path"], final_path)
        logger.info(f"Best meme saved as: {final_path}")
        
        # Log all attempts for user review
        logger.info(f"Generated {len(all_attempts)} meme attempts:")
        for att in all_attempts:
            score_str = f"{att['score']}/10" if att['score'] is not None else "N/A"
            logger.info(f"  Attempt {att['attempt']}: {att['path']} (score: {score_str})")
        
        return {
            "final_path": final_path,
            "attempts": all_attempts,
            "best_score": best_attempt["score"]
        }
    
    logger.error("Failed to generate any memes")
    return None


def generate_meme_from_text(
    transcript_text: str,
    output_path: Path,
    api_key: Optional[str] = None,
    config: Optional[MemeConfig] = None
) -> Optional[Path]:
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
    if not meme_path:
        logger.error("Failed to generate meme image")
        return None
    
    return meme_path
