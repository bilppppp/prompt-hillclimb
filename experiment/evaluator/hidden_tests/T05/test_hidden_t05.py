"""Hidden evaluation tests for T05 (userreport).

Verifies runtime JSON serialization for diverse user data and fields.
"""

import json
import pytest
from userreport.report import generate_report
from userreport.formatter import format_report
from userreport.cli import run_cli


def test_hidden_json_different_names():
    """Verify JSON output with different names and skills."""
    out = run_cli(["--name", "Charlie", "--age", "42", "--skills", "c++", "go", "--format", "json"])
    parsed = json.loads(out)
    assert parsed["name"] == "Charlie"
    assert parsed["age"] == 42
    assert parsed["skills"] == ["c++", "go"]


def test_hidden_json_empty_skills():
    """Verify JSON output with empty skills list."""
    out = generate_report("Dana", 19, skills=[], fmt="json")
    parsed = json.loads(out)
    assert parsed["name"] == "Dana"
    assert parsed["age"] == 19
    assert parsed["skills"] == []


def test_hidden_json_many_skills():
    """Verify JSON output with many skills."""
    skills = ["python", "rust", "kubernetes", "sql", "git"]
    out = generate_report("Eve", 28, skills=skills, fmt="json")
    parsed = json.loads(out)
    assert parsed["name"] == "Eve"
    assert parsed["skills"] == skills


def test_hidden_json_types_preserved():
    """Verify integer and list types are preserved in serialized JSON."""
    out = run_cli(["--name", "Frank", "--age", "55", "--skills", "management", "--format", "json"])
    parsed = json.loads(out)
    assert isinstance(parsed["age"], int)
    assert isinstance(parsed["skills"], list)


def test_hidden_text_format_still_works():
    """Verify existing text formatting remains completely intact."""
    out = generate_report("Grace", 31, skills=["design"], fmt="text")
    assert "User: Grace | Age: 31 | Skills: design" == out


def test_hidden_invalid_format_raises():
    """Verify unknown format strings still raise ValueError."""
    with pytest.raises(ValueError):
        format_report({"name": "Test", "age": 20}, fmt="yaml")
