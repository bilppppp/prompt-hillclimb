"""Configuration validators."""

from typing import Any


def validate_timeout_value(val: Any) -> int:
    """Validate that timeout is a non-negative integer."""
    if val is None:
        raise ValueError("Timeout cannot be None")
    try:
        ival = int(val)
    except (ValueError, TypeError) as exc:
        raise TypeError(f"Timeout must be convertible to int, got {val!r}") from exc
    if ival < 0:
        raise ValueError("Timeout cannot be negative")
    return ival


def validate_host_string(host: Any) -> str:
    """Validate host string."""
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Host must be a non-empty string")
    return host.strip()
