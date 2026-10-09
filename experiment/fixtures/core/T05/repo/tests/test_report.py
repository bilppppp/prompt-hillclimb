"""Tests for userreport."""

import json
import pytest
from userreport.report import generate_report
from userreport.formatter import format_report
from userreport.models import UserModel
from userreport.cli import run_cli


def test_format_text_default():
    """Verify default text formatting."""
    out = generate_report("Alice", 30, skills=["python"])
    assert "User: Alice" in out
    assert "Age: 30" in out


def test_format_text_custom_user():
    """Verify text formatting with multiple skills."""
    out = generate_report("Bob", 25, skills=["docker", "linux"])
    assert "User: Bob | Age: 25 | Skills: docker, linux" == out


def test_cli_text_format():
    """Verify CLI text output format."""
    out = run_cli(["--name", "Bob", "--age", "25", "--skills", "docker", "--format", "text"])
    assert "User: Bob" in out
    assert "Age: 25" in out


def test_format_json_alice():
    """Verify JSON formatting for Alice via CLI format option."""
    out = run_cli(["--name", "Alice", "--age", "30", "--skills", "python", "--format", "json"])
    parsed = json.loads(out)
    assert parsed["name"] == "Alice"
    assert parsed["age"] == 30
    assert parsed["skills"] == ["python"]


def test_invalid_format_raises():
    """Verify unknown format raises ValueError."""
    with pytest.raises(ValueError):
        format_report({"name": "Test"}, fmt="xml")


def test_user_model_negative_age():
    """Verify user model rejects negative age."""
    with pytest.raises(ValueError):
        UserModel("Invalid", -5)
