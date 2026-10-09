"""Configuration loading utilities."""

from typing import Any, Mapping


def parse_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize raw configuration into a dictionary."""
    if raw is None:
        return {}
    return dict(raw)


def merge_configs(
    base: Mapping[str, Any],
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge base configuration with overrides."""
    result = dict(base)
    if override:
        result.update(override)
    return result
