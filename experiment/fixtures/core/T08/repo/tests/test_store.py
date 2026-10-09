"""Tests for recordstore and import_data CLI."""

import json
from pathlib import Path
import pytest
from recordstore.storage import import_records, import_records_file
from recordstore.io import load_records, save_records
from recordstore.validator import validate_record
import import_data


def test_import_new_records(tmp_path: Path):
    """Verify importing records into an empty storage file."""
    src = tmp_path / "source.json"
    tgt = tmp_path / "target.json"
    save_records(src, [{"id": "1", "data": "alpha"}])

    records = import_records_file(src, tgt)
    assert len(records) == 1
    assert records[0]["id"] == "1"


def test_import_deduplicates_by_id(tmp_path: Path):
    """Verify that importing existing IDs does not create duplicates."""
    src = tmp_path / "incoming.json"
    tgt = tmp_path / "storage.json"

    save_records(tgt, [{"id": "1", "data": "alpha"}])
    save_records(src, [{"id": "1", "data": "alpha_dup"}, {"id": "2", "data": "beta"}])

    records = import_records_file(src, tgt)
    # Target test: must contain exactly 2 unique records
    assert len(records) == 2
    ids = [r["id"] for r in records]
    assert ids == ["1", "2"]


def test_cli_import_script(tmp_path: Path):
    """Verify executing import_data.py CLI."""
    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    save_records(src, [{"id": "10", "data": "ten"}])

    ret = import_data.main(["--source", str(src), "--target", str(tgt)])
    assert ret == 0
    loaded = load_records(tgt)
    assert len(loaded) == 1


def test_validate_record_missing_id():
    """Verify validation raises KeyError if record lacks id."""
    with pytest.raises(KeyError):
        validate_record({"name": "No ID"})


def test_load_missing_file_returns_empty(tmp_path: Path):
    """Verify loading a non-existent file returns empty list."""
    missing = tmp_path / "nonexistent.json"
    assert load_records(missing) == []


def test_preserve_existing_order():
    """Verify ordering of existing records is preserved."""
    existing = [{"id": "a"}, {"id": "b"}]
    incoming = [{"id": "c"}]
    result = import_records(existing, incoming)
    assert [r["id"] for r in result] == ["a", "b", "c"]
