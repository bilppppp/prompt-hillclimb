"""Data export validation routines."""

from typing import Any, Mapping


def validate_record_structure(record: Any) -> bool:
    """Validate that record is a mapping structure."""
    if not isinstance(record, Mapping):
        raise TypeError(f"Record must be a Mapping, got {type(record).__name__}")
    return True


def ensure_valid_keys(record: Mapping[str, Any]) -> bool:
    """Ensure all keys in record can be converted to strings."""
    for key in record.keys():
        if key is None:
            raise ValueError("Record key cannot be None")
    return True
