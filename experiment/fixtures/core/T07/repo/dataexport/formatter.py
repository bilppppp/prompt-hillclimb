"""Data formatting implementations."""

from typing import Any, Mapping
from .normalizer import normalize_record


def format_text(record: Mapping[str, Any]) -> str:
    """Format record mapping into pipe-delimited key=value pairs."""
    norm = normalize_record(record)
    return " | ".join(f"{k}={norm[k]}" for k in sorted(norm.keys()))


def format_summary_line(record: Mapping[str, Any], prefix: str = "RECORD") -> str:
    """Format summary line for logging or display."""
    norm = normalize_record(record)
    count = len(norm)
    keys_str = ",".join(sorted(norm.keys()))
    return f"[{prefix}] fields={count} keys=({keys_str})"


def export_data(record: Mapping[str, Any], fmt: str = "text") -> str:
    """Export record mapping in the requested format.

    Parameters:
        record: Data mapping.
        fmt: Target format ('text' supported; 'json' requested).

    Returns:
        Formatted data string.
    """
    if fmt == "text":
        return format_text(record)
    elif fmt == "json":
        # BUG: json formatting not yet implemented
        raise ValueError(f"Unsupported format: {fmt}")
    raise ValueError(f"Unsupported format: {fmt}")
