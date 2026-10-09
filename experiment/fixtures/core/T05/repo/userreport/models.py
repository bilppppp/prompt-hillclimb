"""User data models and validation."""

from typing import Any, Mapping, Sequence


class UserModel:
    """Represents a validated user profile."""

    def __init__(
        self,
        name: str,
        age: int,
        skills: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError("Name must be a string")
        if not isinstance(age, int):
            raise TypeError("Age must be an integer")
        if age < 0:
            raise ValueError("Age cannot be negative")
        self.name = name
        self.age = age
        self.skills = list(skills) if skills is not None else []

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary representation."""
        return {
            "name": self.name,
            "age": self.age,
            "skills": list(self.skills),
        }
