"""Hidden evaluation tests for T09 (schemaconvert).

Verifies conversion of first_name/last_name combinations into full_name and status='active'.
"""

from pathlib import Path
import pytest
from schemaconvert.converter import convert_file
from schemaconvert.io import save_json_records, load_json_records
from schemaconvert.cli import main


def test_hidden_convert_only_first_name(tmp_path: Path):
    """Verify record with only first_name has full_name trimmed and status active."""
    src = tmp_path / "in1.json"
    tgt = tmp_path / "out1.json"
    save_json_records(src, [{"first_name": "Alice", "email": "alice@corp.com"}])

    res = convert_file(src, tgt)
    assert res[0]["full_name"] == "Alice"
    assert res[0]["status"] == "active"
    assert res[0]["email"] == "alice@corp.com"


def test_hidden_convert_only_last_name(tmp_path: Path):
    """Verify record with only last_name has full_name trimmed and status active."""
    src = tmp_path / "in2.json"
    tgt = tmp_path / "out2.json"
    save_json_records(src, [{"last_name": "Smith", "email": "smith@corp.com"}])

    res = convert_file(src, tgt)
    assert res[0]["full_name"] == "Smith"
    assert res[0]["status"] == "active"


def test_hidden_convert_multiple_records(tmp_path: Path):
    """Verify batch conversion of multiple records with varying names."""
    src = tmp_path / "in_batch.json"
    tgt = tmp_path / "out_batch.json"
    data = [
        {"first_name": "Bob", "last_name": "Jones", "email": "b@j.org"},
        {"first_name": "Carol", "last_name": "Danvers", "email": "c@d.org"},
        {"first_name": "Dave", "last_name": "", "email": "dave@d.org"},
    ]
    save_json_records(src, data)

    res = convert_file(src, tgt)
    assert len(res) == 3
    assert [r["full_name"] for r in res] == ["Bob Jones", "Carol Danvers", "Dave"]
    assert all(r["status"] == "active" for r in res)


def test_hidden_convert_cli_execution(tmp_path: Path):
    """Verify executing CLI command transforms file correctly."""
    src = tmp_path / "cli_in.json"
    tgt = tmp_path / "cli_out.json"
    save_json_records(src, [{"first_name": "Zara", "last_name": "Moon", "email": "z@m.org"}])

    ret = main([str(src), str(tgt)])
    assert ret == 0
    loaded = load_json_records(tgt)
    assert loaded[0]["full_name"] == "Zara Moon"
    assert loaded[0]["status"] == "active"


def test_hidden_empty_first_and_last_name(tmp_path: Path):
    """Verify record with empty first and last name produces empty string full_name."""
    src = tmp_path / "in_empty.json"
    tgt = tmp_path / "out_empty.json"
    save_json_records(src, [{"first_name": "", "last_name": "", "email": "empty@org.com"}])

    res = convert_file(src, tgt)
    assert res[0]["full_name"] == ""
    assert res[0]["status"] == "active"


def test_hidden_output_file_created(tmp_path: Path):
    """Verify output JSON file is written to target path."""
    src = tmp_path / "touch_in.json"
    tgt = tmp_path / "touch_out.json"
    save_json_records(src, [{"sample": 1}])

    convert_file(src, tgt)
    assert tgt.is_file()
