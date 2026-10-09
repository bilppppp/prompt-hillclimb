"""Record storage and import routines."""

from pathlib import Path
from typing import Any, Mapping, Sequence
from .validator import validate_record
from .io import load_records, save_records


def import_records(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge incoming records into existing collection.

    Parameters:
        existing: Currently stored records.
        incoming: New records to import.

    Returns:
        Combined list of records.
    """
    for rec in incoming:
        validate_record(rec)

    # BUG: unconditionally appends incoming records without deduplication by id
    result = [dict(r) for r in existing]
    for rec in incoming:
        result.append(dict(rec))
    return result


def import_records_file(
    source_path: str | Path,
    target_path: str | Path,
) -> list[dict[str, Any]]:
    """Import records from source JSON file into target JSON storage file."""
    existing = load_records(target_path)
    incoming = load_records(source_path)
    updated = import_records(existing, incoming)
    save_records(target_path, updated)
    return updated
