"""Label validation logic for clilabel."""

from .config import MAX_LABEL_LENGTH


def validate_label(label: str) -> bool:
    """Validate that the given label meets format and length constraints."""
    if not isinstance(label, str):
        raise TypeError(f"Label must be a string, got {type(label).__name__}")
    if not label:
        raise ValueError("Label cannot be empty")
    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"Label exceeds maximum length of {MAX_LABEL_LENGTH}")
    return True
