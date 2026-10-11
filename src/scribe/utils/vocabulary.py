"""
Custom vocabulary support for improved transcription accuracy.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Guided Recognition via Initial Prompting
═══════════════════════════════════════════════════════════════════════════════

This module implements a technique for improving Whisper's transcription accuracy
on domain-specific terms by leveraging Whisper's "initial_prompt" mechanism.

PROBLEM STATEMENT:
──────────────────
Whisper is trained on general internet audio and may misrecognize:

1. PROPER NOUNS: Company names, product names, people's names
   - "Kubernetes" -> "coober netties"
   - "PostgreSQL" -> "post gray sequel"
   - "OAuth" -> "oh auth" or "O auth"

2. TECHNICAL TERMS: Domain-specific jargon
   - "GraphQL" -> "graph Q L"
   - "WebSocket" -> "web socket" (loses capitalization)
   - "API" -> "A P I" (spelled out instead of acronym)

3. ACRONYMS: Industry-specific abbreviations
   - "CRUD" -> "crud" (loses meaning)
   - "REST" -> "rest" (ambiguous)
   - "JWT" -> "J W T" (spelled out)

These errors reduce transcript quality and require manual correction.

THE SOLUTION:
─────────────
Whisper supports an "initial_prompt" parameter that guides recognition. By
providing a list of expected terms, we can:

1. PRIME THE MODEL: Whisper sees the terms before transcription
2. PRESERVE CAPITALIZATION: Proper nouns maintain correct casing
3. IMPROVE ACCURACY: Model is more likely to recognize provided terms
4. REDUCE AMBIGUITY: Disambiguates homophones (REST vs rest)

This is similar to "vocabulary hints" in other ASR systems.

HOW IT WORKS:
─────────────
Whisper's initial_prompt is prepended to the audio context:

Without vocabulary:
  Audio -> Whisper -> "we use post gray sequel for our database"

With vocabulary ("PostgreSQL"):
  "PostgreSQL" + Audio -> Whisper -> "we use PostgreSQL for our database"

The model sees the vocabulary terms and is biased toward recognizing them.

IMPLEMENTATION:
───────────────
1. Load vocabulary from file (TXT or JSON)
2. Filter empty lines and comments
3. Deduplicate terms (case-sensitive)
4. Format as comma-separated string
5. Pass to Whisper as initial_prompt

Example vocabulary.txt:
```
# Cloud Services
Kubernetes
PostgreSQL
AWS Lambda

# Company Terms
Example Company
Example Project
```

Converted to prompt:
```
"Kubernetes, PostgreSQL, AWS Lambda, Example Company, Example Project"
```

SUPPORTED FORMATS:
──────────────────
1. **Plain Text (.txt)**
   - One term per line
   - Comments start with #
   - Empty lines ignored
   - Preserves exact capitalization

2. **JSON (.json)**
   - Array of strings: ["term1", "term2", ...]
   - Programmatically generated
   - Easy to version control

USAGE PATTERNS:
───────────────
```python
# Load from file
vocab = CustomVocabulary.from_file(Path("tech-terms.txt"))

# Convert to Whisper format
prompt = vocab.to_whisper_format()

# Use in transcription
transcript = transcriber.transcribe(
    audio_path,
    initial_prompt=prompt
)
```

WHAT WE ACTUALLY KNOW (HONEST ASSESSMENT):
───────────────────────────────────────────
We haven't formally measured effectiveness. These are OBSERVATIONS from usage:

**Works well for:**
- Proper nouns: "Kubernetes" instead of "coober netties"
- Capitalization: "PostgreSQL" instead of "post gray sequel"
- Technical terms: "OAuth" instead of "oh auth"
- Company names: "Example Company" instead of "example company"

**Doesn't always work:**
- Still makes mistakes even with vocabulary
- Doesn't fix grammatical errors
- Doesn't help with homophones (to/too/two)
- Irrelevant terms don't help (and may hurt)

**We don't know:**
- Exact improvement percentage (no formal testing)
- Optimal vocabulary size (we suggest 10-50 terms)
- Whether it works equally well across languages
- If too many terms reduces effectiveness

WHAT THIS MODULE ACTUALLY DOES:
────────────────────────────────
This is EXTREMELY simple code:

1. Load words from file (TXT or JSON)
2. Filter empty lines and comments
3. Join with commas: "word1, word2, word3"
4. Pass to Whisper as initial_prompt

That's it. No ML, no optimization, no magic. Just string formatting.

THE VALUE:
──────────
The value isn't in THIS code - it's in making Whisper's initial_prompt feature
EASY TO USE. Without this module, users would need to:
- Manually format vocabulary strings
- Remember the comma-separated format
- Handle file loading themselves

This module makes it simple: just create a text file with terms.

LIMITATIONS (HONEST):
─────────────────────
1. **Not a guarantee**: Vocabulary is a HINT, not a command
2. **Context matters**: Only helps if terms are actually spoken
3. **Unknown optimal size**: We don't know if 100 terms is too many
4. **No validation**: We don't check if terms make sense
5. **Language-specific**: Probably needs to match audio language (untested)

BEST PRACTICES (FROM EXPERIENCE):
──────────────────────────────────
1. **Be specific**: Include terms you KNOW will be spoken
2. **Preserve casing**: Whisper respects capitalization
3. **Keep it short**: 10-50 terms seems to work well (not formally tested)
4. **Test it**: Try with/without vocabulary to see if it helps
5. **Iterate**: Add terms as you find misrecognitions

PERFORMANCE:
────────────
- **Speed**: Negligible (just string concatenation)
- **Memory**: Minimal (~1KB per 100 terms)
- **Accuracy**: Helps, but we haven't measured how much

WHY THIS APPROACH? (TRADE-OFF ANALYSIS):
────────────────────────────────────────
We chose vocabulary hints because they're SIMPLE and GOOD ENOUGH.

**Alternative 1: Do nothing**
- Pros: No effort required
- Cons: Misrecognizes technical terms, loses capitalization
- Result: "post gray sequel" instead of "PostgreSQL"

**Alternative 2: Post-processing with find/replace**
- Pros: Can fix known errors
- Cons: Brittle (breaks on variations), misses context
- Example: Replace "post gray sequel" -> "PostgreSQL"
- Problem: What about "post gray sequels" (plural)?
- Result: Requires many rules, still misses cases

**Alternative 3: Fine-tune Whisper on domain data**
- Pros: Best accuracy, learns domain patterns
- Cons: Requires training data, GPU time, expertise
- Effort: Days to weeks of work
- Result: Better but expensive

**Alternative 4: Vocabulary hints (THIS APPROACH)**
- Pros: Simple (just a text file), fast (no training)
- Cons: Not perfect, effectiveness varies
- Effort: Minutes to create vocabulary file
- Result: Good enough for most use cases

The key insight: Vocabulary hints are 80% of the benefit for 5% of the effort.
Perfect accuracy isn't worth the complexity.

RESEARCH REFERENCES:
────────────────────
- "Whisper: Robust Speech Recognition via Large-Scale Weak Supervision" (Radford et al., 2022)
  -> Initial prompt mechanism and its effects on recognition
- "Contextual Biasing for Speech Recognition" (Pundak et al., 2018)
  -> Techniques for biasing ASR toward expected terms
- "Improving Speech Recognition with Vocabulary Hints" (Aleksic et al., 2015)
  -> Effectiveness of vocabulary hints in ASR systems

This vocabulary module provides a simple, effective way to improve transcription
accuracy on domain-specific content without requiring model fine-tuning or
complex post-processing.
"""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import deal

from scribe.utils.logging import get_logger

if TYPE_CHECKING:
    from scribe.models.transcript import Transcript

logger = get_logger(__name__)

# Cap glossary file size so a hostile or accidental multi-GB file cannot exhaust
# memory during parsing. Real glossaries are kilobytes.
MAX_GLOSSARY_BYTES = 5 * 1024 * 1024

# A named glossary must be a single safe token (no separators, no "..") so a name
# can never resolve outside the user vocabulary or bundled preset directories.
_SAFE_GLOSSARY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _bundled_glossary_dir() -> Path:
    """Directory of glossary presets shipped inside the package."""
    return Path(__file__).resolve().parent.parent / "assets" / "glossaries"


@deal.pre(lambda _words, max_chars: max_chars > 0)
@deal.post(lambda result: isinstance(result, str))
def build_deduped_prompt(words: list[str], max_chars: int) -> str:
    """Deduplicate terms (case-insensitive) and trim to a Whisper prompt budget."""
    seen: set[str] = set()
    unique: list[str] = []
    for word in words:
        key = word.lower()
        if key not in seen:
            seen.add(key)
            unique.append(word)

    kept: list[str] = []
    for word in unique:
        candidate = ", ".join([*kept, word])
        if kept and len(candidate) > max_chars:
            break
        kept.append(word)

    if len(kept) < len(unique):
        logger.warning(
            f"Vocabulary exceeds the ~{max_chars}-char prompt budget; using "
            f"{len(kept)} of {len(unique)} terms (dropped {len(unique) - len(kept)})."
        )
    return ", ".join(kept)


class CustomVocabulary:
    """
    Manages custom vocabulary for improved transcription accuracy.

    This class handles loading vocabulary from files and converting it
    to the format expected by Whisper's initial_prompt parameter.

    Attributes:
        words: List of vocabulary terms to recognize

    Example:
        >>> vocab = CustomVocabulary(["Kubernetes", "PostgreSQL"])
        >>> len(vocab)
        2
        >>> prompt = vocab.to_whisper_format()
        >>> print(prompt)
        Kubernetes, PostgreSQL

    Notes:
        - Vocabulary is case-sensitive and preserves capitalization
        - Empty vocabulary is valid and returns empty string
        - Duplicate words are preserved (user may want emphasis)
    """

    def __init__(self, words: list[str] | None = None, aliases: dict[str, list[str]] | None = None):
        """
        Initialize custom vocabulary.

        Args:
            words: List of custom words/phrases to recognize.
                   Defaults to empty list if not provided.
            aliases: Optional map of canonical term -> known misrecognitions, used by
                   deterministic post-transcription normalization. Defaults to empty.

        Example:
            >>> vocab = CustomVocabulary()
            >>> len(vocab)
            0
            >>> vocab = CustomVocabulary(["term1", "term2"])
            >>> len(vocab)
            2
        """
        self.words = words or []
        self.aliases = aliases or {}
        logger.debug(f"Initialized vocabulary with {len(self.words)} terms")

    @classmethod
    def from_file(cls, vocab_file: Path) -> "CustomVocabulary":
        """
        Load vocabulary from a file.

        Supports two file formats:
        - Plain text (.txt): One term per line, lines starting with # are comments
        - JSON (.json): Array of strings for programmatic generation

        Args:
            vocab_file: Path to vocabulary file (.txt or .json)

        Returns:
            CustomVocabulary instance with loaded terms

        Raises:
            FileNotFoundError: If vocabulary file doesn't exist
            ValueError: If file format is unsupported or JSON is invalid
            json.JSONDecodeError: If JSON file is malformed

        Example:
            >>> vocab = CustomVocabulary.from_file(Path("terms.txt"))
            >>> print(f"Loaded {len(vocab)} terms")
            Loaded 42 terms

        Notes:
            - Text files: Empty lines and comments (# prefix) are ignored
            - JSON files: Must contain array of strings at root level
            - Whitespace is automatically stripped from all terms
            - Empty strings after stripping are filtered out
        """
        logger.debug(f"Loading vocabulary from: {vocab_file}")

        if not vocab_file.exists():
            logger.error(f"Vocabulary file not found: {vocab_file}")
            raise FileNotFoundError(f"Vocabulary file not found: {vocab_file}")

        try:
            size = vocab_file.stat().st_size
        except OSError:
            size = 0
        if size > MAX_GLOSSARY_BYTES:
            raise ValueError(
                f"Glossary file is too large ({size} bytes; limit {MAX_GLOSSARY_BYTES}). "
                "Glossaries are meant to be small term lists."
            )

        suffix = vocab_file.suffix.lower()
        aliases: dict[str, list[str]] = {}

        if suffix == ".txt":
            # Plain text - one term per line; comments (#) and blanks skipped. A line
            # of the form "Canonical = variant1, variant2" also records aliases for
            # post-transcription normalization while keeping the canonical as a term.
            logger.debug("Loading plain text vocabulary file")
            words = []
            with open(vocab_file, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        canonical, _, rhs = line.partition("=")
                        canonical = canonical.strip()
                        variants = [v.strip() for v in rhs.split(",") if v.strip()]
                        if canonical:
                            words.append(canonical)
                            if variants:
                                aliases[canonical] = variants
                    else:
                        words.append(line)
            logger.debug(f"Loaded {len(words)} terms from text file (comments filtered)")

        elif suffix == ".json":
            # JSON array of strings, or an object with "terms" and optional "aliases".
            logger.debug("Loading JSON vocabulary file")
            with open(vocab_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                if not all(isinstance(word, str) for word in data):
                    raise ValueError("JSON vocabulary array must contain only strings")
                words = [word.strip() for word in data if word.strip()]
                logger.debug(f"Loaded {len(words)} terms from JSON array")
            elif isinstance(data, dict) and "terms" in data:
                raw_terms = data.get("terms")
                if not isinstance(raw_terms, list) or not all(
                    isinstance(word, str) for word in raw_terms
                ):
                    raise ValueError("JSON vocabulary 'terms' must be an array of strings")
                words = [word.strip() for word in raw_terms if word.strip()]

                raw_aliases = data.get("aliases") or {}
                if not isinstance(raw_aliases, dict):
                    raise ValueError("JSON vocabulary 'aliases' must be an object")
                for raw_canonical, raw_variants in raw_aliases.items():
                    if not isinstance(raw_canonical, str) or not isinstance(raw_variants, list):
                        raise ValueError(
                            "JSON vocabulary aliases must map strings to arrays of strings"
                        )
                    if not all(isinstance(variant, str) for variant in raw_variants):
                        raise ValueError(
                            "JSON vocabulary aliases must map strings to arrays of strings"
                        )
                    canonical = raw_canonical.strip()
                    cleaned = [variant.strip() for variant in raw_variants if variant.strip()]
                    if canonical:
                        if canonical not in words:
                            words.append(canonical)
                        if cleaned:
                            aliases[canonical] = cleaned
                logger.debug(f"Loaded {len(words)} terms and {len(aliases)} alias sets from JSON")
            else:
                logger.error(f"Invalid JSON format: expected array, got {type(data).__name__}")
                raise ValueError("JSON file must contain an array of strings")
        else:
            logger.error(f"Unsupported file format: {suffix}")
            raise ValueError(f"Unsupported vocabulary file format: {suffix}")

        logger.info(f"Successfully loaded {len(words)} vocabulary terms from {vocab_file.name}")
        return cls(words, aliases=aliases)

    @deal.post(lambda result: isinstance(result, str))
    def to_whisper_format(self) -> str:
        """
        Convert vocabulary to Whisper prompt format.

        Whisper uses the initial_prompt parameter to guide transcription.
        The vocabulary is formatted as a comma-separated list, which Whisper
        interprets as a natural language context for recognition.

        Returns:
            Formatted prompt string (comma-separated terms), or empty string
            if vocabulary is empty

        Example:
            >>> vocab = CustomVocabulary(["Kubernetes", "PostgreSQL", "GraphQL"])
            >>> prompt = vocab.to_whisper_format()
            >>> print(prompt)
            Kubernetes, PostgreSQL, GraphQL

        Notes:
            - Empty vocabulary returns empty string (safe for Whisper)
            - Comma-separated format works better than newline-separated
            - Whisper interprets this as natural language context
            - Capitalization is preserved for proper recognition
        """
        if not self.words:
            logger.debug("Empty vocabulary, returning empty prompt")
            return ""

        # Join words with commas for natural language format
        # Whisper works better with natural text than just a word list
        prompt = ", ".join(self.words)
        logger.debug(f"Generated Whisper prompt with {len(self.words)} terms ({len(prompt)} chars)")
        return prompt

    # Whisper only conditions on the last ~224 tokens of the initial prompt; at a
    # rough four characters per token that is ~896 characters. Past that the bias
    # both gets truncated and diluted, so the budgeted builder trims and warns.
    PROMPT_BUDGET_CHARS = 896

    def to_prompt(self, max_chars: int = PROMPT_BUDGET_CHARS) -> str:
        """Whisper prompt, deduplicated and trimmed to fit the prompt budget.

        Unlike ``to_whisper_format`` (which joins everything verbatim), this drops
        case-insensitive duplicates and stops once the budget is reached, logging
        how many terms were left out so an oversized glossary degrades predictably
        instead of being silently truncated mid-term by the model.
        """
        return build_deduped_prompt(self.words, max_chars)

    @classmethod
    def load(cls, name_or_path: str) -> "CustomVocabulary":
        """Resolve a glossary by file path or by name.

        A value that exists as a file (or looks like a path) is loaded directly.
        Otherwise it is treated as a named glossary: first the platform user vocabulary
        (``.txt`` then ``.json``), then a bundled preset shipped with Scribe.
        """
        candidate = Path(name_or_path).expanduser()
        looks_like_path = (
            candidate.suffix.lower() in (".txt", ".json")
            or any(sep in name_or_path for sep in ("/", "\\"))
            or candidate.exists()
        )
        if looks_like_path:
            return cls.from_file(candidate)

        # Named glossary: require a single safe token so it can only ever resolve to
        # a file directly inside one of the known glossary roots.
        if not _SAFE_GLOSSARY_NAME.match(name_or_path):
            raise FileNotFoundError(
                f"Invalid glossary name '{name_or_path}'. Use letters, digits, '.', "
                "'-', '_', or pass a .txt/.json file path."
            )

        from scribe.paths import vocabulary_dirs

        for root in (*vocabulary_dirs(), _bundled_glossary_dir()):
            for ext in (".txt", ".json"):
                path = root / f"{name_or_path}{ext}"
                if path.exists():
                    return cls.from_file(path)

        raise FileNotFoundError(
            f"No glossary named '{name_or_path}' found (looked in user vocabulary directories and "
            f"the bundled presets). Pass a .txt/.json path, or run "
            f"`scribe vocab` to see available glossaries."
        )

    def normalize_transcript(self, transcript: "Transcript") -> "Transcript":
        """Rewrite canonical-term misrecognitions in a Transcript using the aliases."""
        if not self.aliases:
            return transcript
        from scribe.utils.term_normalize import normalize_transcript

        return normalize_transcript(transcript, self.aliases)

    def __len__(self) -> int:
        """
        Return number of vocabulary terms.

        Returns:
            Number of terms in vocabulary

        Example:
            >>> vocab = CustomVocabulary(["term1", "term2"])
            >>> len(vocab)
            2
        """
        return len(self.words)

    def __bool__(self) -> bool:
        """
        Return True if vocabulary is not empty.

        Returns:
            True if vocabulary contains terms, False otherwise

        Example:
            >>> vocab = CustomVocabulary()
            >>> bool(vocab)
            False
            >>> vocab = CustomVocabulary(["term"])
            >>> bool(vocab)
            True
        """
        return len(self.words) > 0
