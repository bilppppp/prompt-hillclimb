"""High-level schema conversion pipeline."""

from pathlib import Path
from typing import Any
from .io import load_json_records, save_json_records
from .transformer import transform_all_records


def convert_file(
    input_file: str | Path,
    output_file: str | Path,
    indent: int = 2,
) -> list[dict[str, Any]]:
    """Convert input records file to output records file using schema rules."""
    records = load_json_records(input_file)
    transformed = transform_all_records(records)
    save_json_records(output_file, transformed, indent=indent)
    return transformed
