"""Record normalization utilities."""

from typing import Any, Mapping, Sequence
from .validator import validate_record_structure, ensure_valid_keys


def normalize_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ensure record is a normalized dictionary with string keys."""
    if record is None:
        return {}
    validate_record_structure(record)
    ensure_valid_keys(record)
    return {str(k): v for k, v in record.items()}


def clean_none_values(record: Mapping[str, Any]) -> dict[str, Any]:
    """Filter out keys with None values."""
    norm = normalize_record(record)
    return {k: v for k, v in norm.items() if v is not None}


def filter_keys(record: Mapping[str, Any], allowed_keys: Sequence[str]) -> dict[str, Any]:
    """Keep only keys that are in the allowed sequence."""
    norm = normalize_record(record)
    allowed_set = set(allowed_keys)
    return {k: v for k, v in norm.items() if k in allowed_set}
