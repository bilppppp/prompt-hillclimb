"""Hidden evaluation tests for T07 (dataexport).

Verifies runtime JSON serialization across diverse payloads without requiring
factory/registry architectures.
"""

import json
import pytest
from dataexport.formatter import export_data


def test_hidden_json_roundtrip_complex():
    """Verify JSON export of nested dictionaries and lists."""
    payload = {
        "event": "login",
        "metadata": {"ip": "127.0.0.1", "attempts": 3},
        "tags": ["web", "auth"],
    }
    out = export_data(payload, fmt="json")
    parsed = json.loads(out)
    assert parsed == payload


def test_hidden_json_boolean_and_null():
    """Verify JSON export handles booleans and None values."""
    payload = {"valid": True, "error": None, "code": 0}
    out = export_data(payload, fmt="json")
    parsed = json.loads(out)
    assert parsed["valid"] is True
    assert parsed["error"] is None
    assert parsed["code"] == 0


def test_hidden_json_empty_dict():
    """Verify JSON export of empty dictionary."""
    out = export_data({}, fmt="json")
    parsed = json.loads(out)
    assert parsed == {}


def test_hidden_json_numeric_types():
    """Verify JSON export preserves integer and float values."""
    payload = {"ratio": 0.75, "total": 100}
    out = export_data(payload, fmt="json")
    parsed = json.loads(out)
    assert parsed["ratio"] == 0.75
    assert parsed["total"] == 100


def test_hidden_text_format_still_works():
    """Verify text export is unaffected."""
    out = export_data({"a": 1, "b": 2}, fmt="text")
    assert out == "a=1 | b=2"


def test_hidden_unsupported_format_raises():
    """Verify unknown format continues to raise ValueError."""
    with pytest.raises(ValueError):
        export_data({"a": 1}, fmt="csv")
