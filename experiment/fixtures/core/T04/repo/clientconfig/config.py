"""Configuration value accessors."""

from typing import Any, Mapping
from .validator import validate_host_string

DEFAULT_TIMEOUT: int = 30
DEFAULT_HOST: str = "localhost"
DEFAULT_RETRIES: int = 3


def get_timeout(config: Mapping[str, Any]) -> int:
    """Extract the timeout setting from configuration.

    Parameters:
        config: Mapping of configuration key-value pairs.

    Returns:
        Timeout in seconds.
    """
    # BUG: Hardcoded return 30 instead of reading config
    return 30


def get_host(config: Mapping[str, Any]) -> str:
    """Extract host setting from configuration."""
    raw = config.get("host", DEFAULT_HOST)
    return validate_host_string(raw)


def get_retries(config: Mapping[str, Any]) -> int:
    """Extract retries count from configuration."""
    raw = config.get("retries")
    if raw is None:
        return DEFAULT_RETRIES
    return int(raw)
