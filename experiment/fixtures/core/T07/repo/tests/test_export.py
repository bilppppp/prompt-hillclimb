"""Tests for dataexport."""

import json
import pytest
from dataexport.formatter import export_data, format_text, format_summary_line
from dataexport.normalizer import clean_none_values, filter_keys


def test_format_text_basic():
    """Verify default text formatting produces pipe-separated key-value pairs."""
    out = export_data({"status": "ok", "code": 200})
    assert out == "code=200 | status=ok"


def test_format_text_single_field():
    """Verify single field text formatting."""
    out = export_data({"msg": "hello"})
    assert out == "msg=hello"


def test_export_json_format():
    """Verify JSON export produces valid JSON string."""
    data = {"status": "ok", "count": 1}
    out = export_data(data, fmt="json")
    parsed = json.loads(out)
    assert parsed == data


def test_invalid_format_error():
    """Verify unknown format raises ValueError."""
    with pytest.raises(ValueError):
        export_data({}, fmt="xml")


def test_format_summary_line():
    """Verify summary line formatting."""
    line = format_summary_line({"user": "admin", "role": "root"})
    assert "[RECORD]" in line
    assert "fields=2" in line


def test_clean_none_values():
    """Verify cleaning None values from mapping."""
    res = clean_none_values({"a": 1, "b": None, "c": 3})
    assert res == {"a": 1, "c": 3}


def test_filter_keys():
    """Verify filtering record to allowed keys."""
    res = filter_keys({"a": 1, "b": 2, "c": 3}, ["a", "c"])
    assert res == {"a": 1, "c": 3}
