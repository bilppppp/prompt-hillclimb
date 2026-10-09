"""Record transformation logic."""

from typing import Any, Mapping, Sequence


def transform_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Transform a single record according to target schema.

    Parameters:
        record: Original record mapping.

    Returns:
        Transformed record dict.
    """
    # BUG: Copies record directly without transforming first_name/last_name into full_name
    # and without setting status="active"
    return dict(record)


def transform_all_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Transform a sequence of records."""
    return [transform_record(r) for r in records]
