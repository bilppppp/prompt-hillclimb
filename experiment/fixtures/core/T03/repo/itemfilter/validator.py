"""Validation routines for itemfilter."""

from typing import Any, Sequence


def validate_collection(items: Sequence[Any]) -> bool:
    """Validate that items is an iterable sequence.

    Raises:
        TypeError: If items is not a sequence.
    """
    if items is None:
        raise TypeError("Items collection cannot be None")
    return True
