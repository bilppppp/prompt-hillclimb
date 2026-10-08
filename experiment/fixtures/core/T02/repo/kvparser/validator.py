"""Header key validation utilities."""

import re

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_key(key: str) -> bool:
    """Validate that a header key conforms to allowed naming conventions.

    Keys must be non-empty strings composed solely of alphanumeric characters,
    underscores, or hyphens.
    """
    if not isinstance(key, str):
        raise TypeError(f"Header key must be a string, got {type(key).__name__}")
    stripped = key.strip()
    if not stripped:
        raise ValueError("Header key cannot be empty")
    if not _KEY_PATTERN.match(stripped):
        raise ValueError(f"Invalid characters in header key: {key!r}")
    return True
