"""Tests for schemaconvert."""

from pathlib import Path
import pytest
from schemaconvert.io import save_json_records, load_json_records
from schemaconvert.converter import convert_file
from schemaconvert.transformer import transform_record
from schemaconvert.cli import main


def test_convert_file_empty(tmp_path: Path):
    """Verify converting an empty records file."""
    src = tmp_path / "empty_in.json"
    tgt = tmp_path / "empty_out.json"
    save_json_records(src, [])

    res = convert_file(src, tgt)
    assert res == []
    assert load_json_records(tgt) == []


def test_transform_full_name_and_status(tmp_path: Path):
    """Verify converting name fields into full_name and setting active status."""
    src = tmp_path / "input.json"
    tgt = tmp_path / "output.json"
    raw_data = [{"first_name": "John", "last_name": "Doe", "email": "john@example.com"}]
    save_json_records(src, raw_data)

    res = convert_file(src, tgt)
    assert len(res) == 1
    record = res[0]
    assert record["full_name"] == "John Doe"
    assert record["email"] == "john@example.com"
    assert record["status"] == "active"


def test_preserve_email():
    """Verify email field is preserved."""
    rec = transform_record({"first_name": "A", "email": "a@domain.com"})
    assert rec.get("email") == "a@domain.com"


def test_cli_invocation(tmp_path: Path):
    """Verify CLI execution on input and output files."""
    src = tmp_path / "cli_in.json"
    tgt = tmp_path / "cli_out.json"
    save_json_records(src, [{"email": "test@test.org"}])

    ret = main([str(src), str(tgt)])
    assert ret == 0
    assert tgt.is_file()


def test_missing_input_file_raises(tmp_path: Path):
    """Verify missing input file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        convert_file(tmp_path / "not_found.json", tmp_path / "out.json")


def test_invalid_json_raises(tmp_path: Path):
    """Verify malformed JSON raises ValueError."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("NOT JSON", encoding="utf-8")
    with pytest.raises(ValueError):
        convert_file(bad_file, tmp_path / "out.json")
