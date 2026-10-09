"""Item collection filtering routines."""

from typing import Any, Callable, Sequence
from .validator import validate_collection


def filter_items(items: Sequence[Any], limit: int) -> list[Any]:
    """Return a list sliced up to limit items.

    Parameters:
        items: Sequence of items.
        limit: Maximum number of items to return (must be an integer).

    Returns:
        List of at most limit items.
    """
    validate_collection(items)
    return list(items[:limit])


def filter_matching(
    items: Sequence[Any],
    predicate: Callable[[Any], bool],
    limit: int | None = None,
) -> list[Any]:
    """Filter items matching predicate, optionally limited."""
    validate_collection(items)
    matched = [item for item in items if predicate(item)]
    if limit is not None:
        return list(matched[:limit])
    return matched
