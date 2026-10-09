"""Report generation pipeline."""

from typing import Any, Sequence
from .models import UserModel
from .formatter import format_report


def generate_report(
    name: str,
    age: int,
    skills: Sequence[str] | None = None,
    fmt: str = "text",
) -> str:
    """Generate a user report in the requested format."""
    model = UserModel(name=name, age=age, skills=skills)
    return format_report(model.to_dict(), fmt=fmt)
