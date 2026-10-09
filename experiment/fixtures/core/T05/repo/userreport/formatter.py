"""Formatting logic for user report data."""

from typing import Any, Mapping


def format_text_report(data: Mapping[str, Any]) -> str:
    """Format report dictionary as readable text."""
    name = data.get("name", "unknown")
    age = data.get("age", 0)
    skills = ", ".join(data.get("skills", []))
    return f"User: {name} | Age: {age} | Skills: {skills}"


def format_report(data: Mapping[str, Any], fmt: str = "text") -> str:
    """Format report dictionary into a string representation.

    Parameters:
        data: Mapping containing user report fields.
        fmt: Format name ('text' supported; 'json' requested).

    Returns:
        Formatted string representation.
    """
    if fmt == "text":
        return format_text_report(data)
    elif fmt == "json":
        # BUG: json formatting not yet implemented
        raise ValueError(f"Unsupported format: {fmt}")
    raise ValueError(f"Unsupported format: {fmt}")
