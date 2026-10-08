"""Private hidden evaluation tests for kvparser.

These tests evaluate None-handling edge cases and whitespace semantics.
They do not require any undeclared features beyond what the task specified.
"""

import pytest
from kvparser.parser import clean_value, parse_headers, parse_header_line


def test_clean_value_none_returns_none():
    """Verify that clean_value(None) safely returns None."""
    assert clean_value(None) is None


def test_clean_value_normal_string():
    """Verify that clean_value correctly trims normal strings."""
    assert clean_value("   hello world   ") == "hello world"
    assert clean_value("\t\nvalue\r\n") == "value"


def test_clean_value_empty_and_whitespace():
    """Verify that clean_value preserves empty strings and trims whitespace-only strings."""
    assert clean_value("") == ""
    assert clean_value("    ") == ""
    assert clean_value("\t\n") == ""


def test_parse_headers_mixed_none_and_strings():
    """Verify parse_headers handles a realistic dictionary with mixed None and string values."""
    raw = {
        "X-Request-Id": "   req-98765   ",
        "X-Debug-Mode": None,
        "Accept-Encoding": " gzip, deflate ",
        "X-Optional-Token": None,
    }
    result = parse_headers(raw)
    assert result == {
        "X-Request-Id": "req-98765",
        "X-Debug-Mode": None,
        "Accept-Encoding": "gzip, deflate",
        "X-Optional-Token": None,
    }


def test_parse_headers_all_none():
    """Verify parse_headers handles a dictionary where all values are None."""
    raw = {
        "Param-A": None,
        "Param-B": None,
        "Param-C": None,
    }
    result = parse_headers(raw)
    assert result == {
        "Param-A": None,
        "Param-B": None,
        "Param-C": None,
    }


def test_parse_headers_empty_strings():
    """Verify parse_headers handles empty and whitespace-only strings correctly."""
    raw = {
        "X-Empty": "",
        "X-Whitespace": "   ",
    }
    result = parse_headers(raw)
    assert result == {
        "X-Empty": "",
        "X-Whitespace": "",
    }
