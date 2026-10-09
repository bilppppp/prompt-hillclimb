"""Tests for itemfilter CLI."""

import pytest
from itemfilter.cli import process, parse_args
from itemfilter.filter import filter_items, filter_matching


def test_default_limit():
    """Verify default limit behaviour."""
    items = list(range(15))
    result = process(items, [])
    assert result == list(range(10))


def test_filter_items_function():
    """Verify direct call to filter_items."""
    items = ["a", "b", "c", "d"]
    assert filter_items(items, 2) == ["a", "b"]


def test_filter_items_empty():
    """Verify filtering an empty collection."""
    assert filter_items([], 5) == []


def test_cli_custom_limit():
    """Verify passing --limit via CLI arguments filters correctly."""
    items = ["first", "second", "third", "fourth"]
    result = process(items, ["--limit", "2"])
    assert result == ["first", "second"]


def test_cli_limit_one():
    """Verify passing --limit 1 returns single item."""
    items = ["a", "b", "c"]
    result = process(items, ["--limit", "1"])
    assert result == ["a"]


def test_cli_reverse_flag():
    """Verify reverse flag ordering."""
    items = [1, 2, 3]
    result = process(items, ["--reverse"])
    assert result == [3, 2, 1]
