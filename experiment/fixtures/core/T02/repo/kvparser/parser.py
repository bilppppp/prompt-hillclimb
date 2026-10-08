"""Key-value and header parsing logic."""

from typing import Any, Mapping
from .validator import validate_key


def clean_value(value: str | None) -> str | None:
    """Normalize a header value by stripping surrounding whitespace.

    Parameters:
        value: The header value string to clean.

    Returns:
        The trimmed string value.
    """
    return value.strip()


def parse_header_line(line: str) -> tuple[str, str | None]:
    """Parse a single header line of the form 'Key: Value'.

    Parameters:
        line: Raw header line string.

    Returns:
        A tuple of (key, cleaned_value).
    """
    if not line or ":" not in line:
        raise ValueError(f"Invalid header line format: {line!r}")
    raw_key, raw_val = line.split(":", 1)
    key = raw_key.strip()
    validate_key(key)
    cleaned_val = clean_value(raw_val)
    return key, cleaned_val


def parse_headers(raw_headers: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and validate a mapping of raw headers.

    Keys are validated and stripped of whitespace. Values have surrounding
    whitespace trimmed.

    Parameters:
        raw_headers: Dictionary-like object of header key-value pairs.

    Returns:
        Dictionary of normalized headers.
    """
    normalized: dict[str, Any] = {}
    for key, val in raw_headers.items():
        validate_key(key)
        cleaned_key = key.strip()
        cleaned_val = clean_value(val)
        normalized[cleaned_key] = cleaned_val
    return normalized
