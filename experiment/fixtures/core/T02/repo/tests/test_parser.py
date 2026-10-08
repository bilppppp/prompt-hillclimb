"""Tests for kvparser."""

import pytest
from kvparser.parser import clean_value, parse_header_line, parse_headers
from kvparser.validator import validate_key


def test_parse_simple_header():
    """Verify parsing a basic single header line."""
    key, val = parse_header_line("Content-Type: application/json")
    assert key == "Content-Type"
    assert val == "application/json"


def test_parse_header_strips_whitespace():
    """Verify that both key and value whitespace are trimmed."""
    key, val = parse_header_line("  Authorization :   Bearer token123   ")
    assert key == "Authorization"
    assert val == "Bearer token123"


def test_parse_multiple_headers():
    """Verify parsing a dictionary of headers."""
    raw = {
        "Host": " example.com ",
        "Accept": "text/html",
    }
    result = parse_headers(raw)
    assert result == {
        "Host": "example.com",
        "Accept": "text/html",
    }


def test_parse_invalid_key_raises():
    """Verify that malformed keys raise ValueError."""
    with pytest.raises(ValueError):
        parse_header_line("Invalid Key%: value")


def test_parse_header_with_none_value():
    """Verify parsing headers where value is None does not crash."""
    raw = {
        "X-Optional": None,
    }
    result = parse_headers(raw)
    assert result["X-Optional"] is None
