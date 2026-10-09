"""Tests for clilabel CLI."""

import pytest
from clilabel.cli import get_label, format_label, parse_args
from clilabel.config import DEFAULT_LABEL
from clilabel.validator import validate_label


def test_default_label():
    """Verify default label when no arguments are provided."""
    assert get_label([]) == "foo"


def test_custom_label():
    """Verify custom label passed via --label flag."""
    assert get_label(["--label", "custom-tag"]) == "custom-tag"


def test_short_flag():
    """Verify custom label passed via short -l flag."""
    assert get_label(["-l", "short-tag"]) == "short-tag"


def test_empty_args_default():
    """Verify default label when args is None."""
    assert get_label(None) == "foo"


def test_format_label_prefix():
    """Verify formatting label with custom prefix."""
    assert format_label("prod", prefix="v1") == "v1:prod"


def test_format_label_uppercase():
    """Verify uppercase label formatting."""
    assert format_label("dev", uppercase=True) == "DEV"


def test_validate_label_empty():
    """Verify empty label raises ValueError."""
    with pytest.raises(ValueError):
        validate_label("")
