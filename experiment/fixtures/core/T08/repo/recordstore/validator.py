"""Record validation utilities."""

from typing import Any, Mapping


def validate_record(record: Mapping[str, Any]) -> bool:
    """Validate that record is a mapping and contains an 'id' key."""
    if not isinstance(record, Mapping):
        raise TypeError(f"Record must be a Mapping, got {type(record).__name__}")
    if "id" not in record:
        raise KeyError("Record missing required 'id' key")
    if record["id"] is None or str(record["id"]).strip() == "":
        raise ValueError("Record 'id' cannot be None or empty")
    return True
