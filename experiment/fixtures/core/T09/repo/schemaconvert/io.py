"""JSON file I/O utilities for schemaconvert."""

import json
from pathlib import Path
from typing import Any, Sequence


def load_json_records(file_path: str | Path) -> list[dict[str, Any]]:
    """Load list of JSON records from file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON format in {file_path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list of objects in {file_path}, got {type(data).__name__}")
    return [dict(item) for item in data]


def save_json_records(
    file_path: str | Path,
    records: Sequence[dict[str, Any]],
    indent: int = 2,
) -> None:
    """Save records list to output JSON file."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(list(records), indent=indent)
    path.write_text(content + "\n", encoding="utf-8")
