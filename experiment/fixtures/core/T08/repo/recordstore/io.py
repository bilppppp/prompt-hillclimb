"""JSON file I/O utilities for recordstore."""

import json
from pathlib import Path
from typing import Any, Sequence


def load_records(file_path: str | Path) -> list[dict[str, Any]]:
    """Load JSON records list from a file. Returns empty list if file does not exist."""
    path = Path(file_path)
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError(f"Expected a list of records in {file_path}, got {type(data).__name__}")
    return [dict(item) for item in data]


def save_records(file_path: str | Path, records: Sequence[dict[str, Any]]) -> None:
    """Save records to a JSON file."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(list(records), indent=2)
    path.write_text(content + "\n", encoding="utf-8")
