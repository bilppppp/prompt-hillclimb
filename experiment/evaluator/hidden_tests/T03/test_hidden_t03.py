"""Hidden evaluation tests for T03 (itemfilter).

Verifies integer conversion and slicing semantics for various limit values.
"""

from itemfilter.cli import process, parse_args


def test_hidden_limit_zero():
    """Verify limit=0 returns empty list."""
    assert process([1, 2, 3], ["--limit", "0"]) == []


def test_hidden_limit_three():
    """Verify limit=3 on 5 items."""
    assert process(["a", "b", "c", "d", "e"], ["--limit", "3"]) == ["a", "b", "c"]


def test_hidden_limit_large():
    """Verify limit exceeding list length returns full list."""
    assert process([10, 20], ["--limit", "100"]) == [10, 20]


def test_hidden_limit_type_int():
    """Verify parsed limit attribute is an int instance."""
    args = parse_args(["--limit", "5"])
    assert isinstance(args.limit, int)


def test_hidden_empty_collection():
    """Verify filtering an empty collection with custom limit."""
    assert process([], ["--limit", "3"]) == []


def test_hidden_default_limit_still_int():
    """Verify default limit remains an integer."""
    args = parse_args([])
    assert isinstance(args.limit, int) and args.limit == 10
