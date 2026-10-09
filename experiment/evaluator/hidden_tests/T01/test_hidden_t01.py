"""Hidden evaluation tests for T01 (clilabel).

Verifies that default label has been correctly updated to 'bar' while
preserving custom label overriding capabilities.
"""

from clilabel.config import DEFAULT_LABEL
from clilabel.cli import get_label


def test_hidden_default_label_is_bar():
    """Verify empty arguments produce 'bar'."""
    assert get_label([]) == "bar"


def test_hidden_none_args_is_bar():
    """Verify None arguments produce 'bar'."""
    assert get_label(None) == "bar"


def test_hidden_config_constant_is_bar():
    """Verify DEFAULT_LABEL constant itself is 'bar'."""
    assert DEFAULT_LABEL == "bar"


def test_hidden_custom_override_intact():
    """Verify --label still overrides the default."""
    assert get_label(["--label", "custom-prod"]) == "custom-prod"


def test_hidden_custom_short_override():
    """Verify -l still overrides the default."""
    assert get_label(["-l", "stage-1"]) == "stage-1"


def test_hidden_explicit_foo_override():
    """Verify explicit override with 'foo' works and is not coerced to bar."""
    assert get_label(["--label", "foo"]) == "foo"
