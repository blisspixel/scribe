"""
Input validation utilities with defensive programming.

This module provides comprehensive validation functions for all user inputs,
file paths, API keys, and configuration values with clear error messages.
"""

import os
import re
from pathlib import Path

import deal

from scribe.exceptions import ValidationError
from scribe.utils.network import OutboundURLPolicyError, safe_url_for_logs, validate_public_url
from scribe.utils.platform import normalize_path


def _is_internal_host(host: str) -> bool:
    """True if a host points at loopback, link-local, private, or internal targets.

    Used to keep media downloads from being aimed at localhost or an internal
    network (SSRF), including the cloud metadata endpoint at 169.254.169.254.
    Literal IPs are checked precisely; bare/internal hostnames are matched by name.
    DNS rebinding (a public name resolving to an internal IP) is not covered here.
    """
    if not host:
        return True
    authority = f"[{host}]" if ":" in host else host
    try:
        validate_public_url(
            f"http://{authority}", allowed_schemes=frozenset({"http"}), resolve_dns=False
        )
    except OutboundURLPolicyError:
        return True
    return False


def validate_file_path(path: str, must_exist: bool = True, must_be_file: bool = True) -> Path:
    """
    Validate and sanitize file path.

    This function:
    - Strips quotes and whitespace
    - Expands ~ and environment variables
    - Converts to absolute path
    - Optionally checks existence
    - Optionally verifies it's a file (not directory)

    Args:
        path: Path string to validate
        must_exist: Whether file must exist
        must_be_file: Whether path must be a file (not directory)

    Returns:
        Validated Path object

    Raises:
        ValidationError: If validation fails
    """
    if not path or not path.strip():
        raise ValidationError("File path cannot be empty")

    try:
        # Normalize path (handles quotes, ~, etc.)
        validated_path = normalize_path(path)

        if must_exist and not validated_path.exists():
            raise ValidationError(
                f"File does not exist: {validated_path}", context={"path": str(validated_path)}
            )

        if must_exist and must_be_file and not validated_path.is_file():
            if validated_path.is_dir():
                raise ValidationError(
                    f"Path is a directory, not a file: {validated_path}",
                    context={"path": str(validated_path)},
                )
            else:
                raise ValidationError(
                    f"Path exists but is not a regular file: {validated_path}",
                    context={"path": str(validated_path)},
                )

        return validated_path

    except ValidationError:
        raise
    except (OSError, TypeError, ValueError) as e:
        raise ValidationError(f"Invalid file path: {path}", context={"error": str(e)})


def validate_directory_path(path: str, must_exist: bool = False, create: bool = True) -> Path:
    """
    Validate and sanitize directory path.

    Args:
        path: Directory path to validate
        must_exist: Whether directory must already exist
        create: Whether to create directory if it doesn't exist

    Returns:
        Validated Path object

    Raises:
        ValidationError: If validation fails
    """
    if not path or not path.strip():
        raise ValidationError("Directory path cannot be empty")

    try:
        validated_path = normalize_path(path)

        if must_exist and not validated_path.exists():
            raise ValidationError(
                f"Directory does not exist: {validated_path}", context={"path": str(validated_path)}
            )

        if validated_path.exists() and not validated_path.is_dir():
            raise ValidationError(
                f"Path exists but is not a directory: {validated_path}",
                context={"path": str(validated_path)},
            )

        if create and not validated_path.exists():
            try:
                validated_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValidationError(
                    f"Cannot create directory: {validated_path}", context={"error": str(e)}
                )

        return validated_path

    except ValidationError:
        raise
    except (OSError, TypeError, ValueError) as e:
        raise ValidationError(f"Invalid directory path: {path}", context={"error": str(e)})


def validate_audio_file(path: str | Path) -> Path:
    """
    Validate audio file format and readability.

    Args:
        path: Path to audio file (string or Path object)

    Returns:
        Validated Path object

    Raises:
        ValidationError: If file is not a valid audio file
    """
    # Convert to Path if string
    if isinstance(path, str):
        path = Path(path)

    # Check file exists
    if not path.exists():
        raise ValidationError(f"Audio file does not exist: {path}", context={"path": str(path)})

    # Check file size (must be > 0)
    if path.stat().st_size == 0:
        raise ValidationError(f"Audio file is empty: {path}", context={"path": str(path)})

    # Check file extension
    valid_extensions = {".wav", ".mp3", ".mp4", ".m4a", ".mkv", ".flac", ".ogg", ".webm"}
    if path.suffix.lower() not in valid_extensions:
        raise ValidationError(
            f"Unsupported audio format: {path.suffix}",
            context={
                "path": str(path),
                "extension": path.suffix,
                "supported": ", ".join(sorted(valid_extensions)),
            },
        )

    # Check file is readable
    try:
        with open(path, "rb") as f:
            # Try to read first few bytes
            f.read(1024)
    except OSError as e:
        raise ValidationError(
            f"Cannot read audio file: {path}", context={"path": str(path), "error": str(e)}
        )

    return path


def validate_api_key(api_key: str | None, service: str = "OpenAI") -> str:
    """
    Validate API key format.

    Args:
        api_key: API key to validate
        service: Service name for error messages

    Returns:
        Validated API key

    Raises:
        ValidationError: If API key is invalid
    """
    if not api_key:
        raise ValidationError(f"{service} API key is required", context={"service": service})

    api_key = api_key.strip()

    if not api_key:
        raise ValidationError(f"{service} API key cannot be empty", context={"service": service})

    # OpenAI-specific validation
    if service.lower() == "openai":
        if not api_key.startswith("sk-"):
            raise ValidationError(
                "Invalid OpenAI API key format (should start with 'sk-')",
                context={"service": service},
            )

        if len(api_key) < 20:
            raise ValidationError("OpenAI API key is too short", context={"length": len(api_key)})

    return api_key


@deal.post(lambda result: bool(result) and len(result) <= 100)
def sanitize_meeting_name(name: str) -> str:
    """
    Sanitize meeting name for use in filenames.

    This function:
    - Removes invalid filename characters
    - Replaces spaces with underscores
    - Limits length
    - Ensures non-empty result

    Args:
        name: Meeting name to sanitize

    Returns:
        Sanitized meeting name

    Raises:
        ValidationError: If name cannot be sanitized
    """
    if not name or not name.strip():
        raise ValidationError("Meeting name cannot be empty")

    # Remove leading/trailing whitespace
    name = name.strip()

    # Remove or replace invalid filename characters
    # Invalid: < > : " / \ | ? *
    invalid_chars = r'[<>:"/\\|?*]'
    name = re.sub(invalid_chars, "", name)

    # Replace spaces and multiple underscores with single underscore
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)

    # Remove leading/trailing underscores
    name = name.strip("_")

    # Strip control characters and trailing dots/spaces (Windows trims trailing dots
    # and spaces from filenames, which can produce surprising or colliding names).
    name = "".join(ch for ch in name if ch.isprintable())
    name = name.rstrip(". ").strip("_")

    # Avoid Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9),
    # which do not behave as ordinary files. Compare on the stem before any dot.
    reserved = (
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )
    if name.split(".")[0].upper() in reserved:
        name = f"_{name}"

    # Limit length (leave room for timestamps and extensions)
    max_length = 100
    if len(name) > max_length:
        name = name[:max_length].rstrip("_")

    # Ensure we still have a valid name
    if not name:
        raise ValidationError(
            "Meeting name contains only invalid characters", context={"original": name}
        )

    return name


def validate_model_name(model: str, valid_models: list[str]) -> str:
    """
    Validate model name against list of valid models.

    Args:
        model: Model name to validate
        valid_models: List of valid model names

    Returns:
        Validated model name

    Raises:
        ValidationError: If model is invalid
    """
    if not model or not model.strip():
        raise ValidationError("Model name cannot be empty")

    model = model.strip().lower()

    if model not in [m.lower() for m in valid_models]:
        raise ValidationError(
            f"Invalid model: {model}",
            context={"provided": model, "valid_models": ", ".join(valid_models)},
        )

    # Return original case from valid_models
    for valid_model in valid_models:
        if valid_model.lower() == model:
            return valid_model

    return model


# Language name to ISO 639-1 code mapping
# Supports common names, variations, and native names
LANGUAGE_ALIASES = {
    # English
    "english": "en",
    "eng": "en",
    # Spanish
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "spa": "es",
    # French
    "french": "fr",
    "français": "fr",
    "francais": "fr",
    "fra": "fr",
    # German
    "german": "de",
    "deutsch": "de",
    "deu": "de",
    "ger": "de",
    # Italian
    "italian": "it",
    "italiano": "it",
    "ita": "it",
    # Portuguese
    "portuguese": "pt",
    "português": "pt",
    "portugues": "pt",
    "por": "pt",
    # Russian
    "russian": "ru",
    "русский": "ru",
    "rus": "ru",
    # Japanese
    "japanese": "ja",
    "日本語": "ja",
    "jpn": "ja",
    "jp": "ja",
    # Chinese
    "chinese": "zh",
    "中文": "zh",
    "mandarin": "zh",
    "zho": "zh",
    "chi": "zh",
    "cn": "zh",
    # Korean
    "korean": "ko",
    "한국어": "ko",
    "kor": "ko",
    "kr": "ko",
    # Arabic
    "arabic": "ar",
    "العربية": "ar",
    "ara": "ar",
    # Hindi
    "hindi": "hi",
    "हिन्दी": "hi",
    "hin": "hi",
    # Dutch
    "dutch": "nl",
    "nederlands": "nl",
    "nld": "nl",
    # Polish
    "polish": "pl",
    "polski": "pl",
    "pol": "pl",
    # Turkish
    "turkish": "tr",
    "türkçe": "tr",
    "turkce": "tr",
    "tur": "tr",
    # Vietnamese
    "vietnamese": "vi",
    "tiếng việt": "vi",
    "vie": "vi",
    # Thai
    "thai": "th",
    "ไทย": "th",
    "tha": "th",
    # Swedish
    "swedish": "sv",
    "svenska": "sv",
    "swe": "sv",
    # Norwegian
    "norwegian": "no",
    "norsk": "no",
    "nor": "no",
    # Danish
    "danish": "da",
    "dansk": "da",
    "dan": "da",
    # Finnish
    "finnish": "fi",
    "suomi": "fi",
    "fin": "fi",
    # Greek
    "greek": "el",
    "ελληνικά": "el",
    "ell": "el",
    # Hebrew
    "hebrew": "he",
    "עברית": "he",
    "heb": "he",
    # Czech
    "czech": "cs",
    "čeština": "cs",
    "cestina": "cs",
    "ces": "cs",
    # Romanian
    "romanian": "ro",
    "română": "ro",
    "romana": "ro",
    "ron": "ro",
    # Hungarian
    "hungarian": "hu",
    "magyar": "hu",
    "hun": "hu",
    # Indonesian
    "indonesian": "id",
    "bahasa indonesia": "id",
    "ind": "id",
    # Malay
    "malay": "ms",
    "bahasa melayu": "ms",
    "msa": "ms",
    # Ukrainian
    "ukrainian": "uk",
    "українська": "uk",
    "ukr": "uk",
}


def validate_language_code(language: str) -> str:
    """
    Validate and normalize language input to ISO 639-1 code.

    Accepts:
        - ISO 639-1 codes: "en", "es", "fr"
        - Full names: "english", "spanish", "french"
        - Native names: "español", "français", "deutsch"
        - Common abbreviations: "eng", "spa", "jpn"

    Args:
        language: Language code or name to validate

    Returns:
        ISO 639-1 language code (lowercase, 2 letters)

    Raises:
        ValidationError: If language is not recognized

    Examples:
        >>> validate_language_code("spanish")
        'es'
        >>> validate_language_code("ES")
        'es'
        >>> validate_language_code("français")
        'fr'
    """
    if not language or not language.strip():
        raise ValidationError("Language cannot be empty")

    language = language.strip().lower()

    # Check if it's already a valid 2-letter ISO code. Require ASCII: without it,
    # CJK native names like "中文" are 2 chars and .isalpha() is True, so they would
    # be returned verbatim as a bogus "code" instead of resolving via the aliases.
    if len(language) == 2 and language.isascii() and language.isalpha():
        return language

    # Check aliases
    if language in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[language]

    # Not found - provide helpful error
    raise ValidationError(
        f"Unknown language: '{language}'",
        context={
            "provided": language,
            "hint": "Use language name (spanish, french) or ISO code (es, fr)",
        },
    )


@deal.pre(lambda port: isinstance(port, int))
@deal.post(lambda result: 1 <= result <= 65535)
def validate_port(port: int) -> int:
    """
    Validate port number.

    Args:
        port: Port number to validate

    Returns:
        Validated port number

    Raises:
        ValidationError: If port is invalid
    """
    if not isinstance(port, int):
        raise ValidationError(
            "Port must be an integer", context={"provided": port, "type": type(port).__name__}
        )

    if not (1 <= port <= 65535):
        raise ValidationError("Port must be between 1 and 65535", context={"provided": port})

    return port


@deal.post(lambda result: result >= 0)
def validate_positive_number(value: float, name: str = "value", min_value: float = 0.0) -> float:
    """
    Validate positive number.

    Args:
        value: Number to validate
        name: Name of the value for error messages
        min_value: Minimum allowed value

    Returns:
        Validated number

    Raises:
        ValidationError: If number is invalid
    """
    if not isinstance(value, int | float):
        raise ValidationError(
            f"{name} must be a number", context={"provided": value, "type": type(value).__name__}
        )

    if value < min_value:
        raise ValidationError(
            f"{name} must be >= {min_value}", context={"provided": value, "min": min_value}
        )

    return float(value)


def validate_email(email: str) -> str:
    """
    Validate email address format.

    Args:
        email: Email address to validate

    Returns:
        Validated email address

    Raises:
        ValidationError: If email is invalid
    """
    if not email or not email.strip():
        raise ValidationError("Email address cannot be empty")

    email = email.strip().lower()

    # Basic email regex
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if not re.match(email_pattern, email):
        raise ValidationError("Invalid email address format", context={"provided": email})

    return email


def validate_url(url: str) -> str:
    """
    Validate URL format.

    Args:
        url: URL to validate

    Returns:
        Validated URL

    Raises:
        ValidationError: If URL is invalid
    """
    if not url or not url.strip():
        raise ValidationError("URL cannot be empty")

    url = url.strip()

    # Basic URL regex
    url_pattern = r"^https?://[^\s/$.?#].[^\s]*$"

    if not re.match(url_pattern, url, re.IGNORECASE):
        raise ValidationError("Invalid URL format", context={"provided": safe_url_for_logs(url)})

    return url


def validate_media_url(url: str) -> str:
    """
    Validate a URL for media download (YouTube, direct links, etc.).

    Validates format and checks that the scheme is http/https.
    Does not probe the URL - that happens at download time.

    Args:
        url: URL to validate

    Returns:
        Validated and cleaned URL

    Raises:
        ValidationError: If URL format is invalid
    """
    url = validate_url(url)

    # Reject file:// and other non-http schemes (already covered by validate_url, but explicit)
    if not url.lower().startswith(("http://", "https://")):
        raise ValidationError(
            "Only http:// and https:// URLs are supported", context={"provided": url}
        )

    # Refuse loopback/internal targets by default, including public names that resolve
    # to a non-public address. A user with a local media server can explicitly opt in.
    allow_local = os.getenv("SCRIBE_ALLOW_LOCAL_URLS", "").strip().lower() in ("1", "true", "yes")
    if not allow_local:
        try:
            validate_public_url(url, allowed_schemes=frozenset({"http", "https"}))
        except OutboundURLPolicyError as error:
            raise ValidationError(
                "Refusing a URL that is invalid or resolves to a local or internal "
                "address. Set SCRIBE_ALLOW_LOCAL_URLS=1 to allow it.",
                context={"provided": safe_url_for_logs(url)},
            ) from error

    return url
