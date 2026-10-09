"""Hidden evaluation tests for T04 (clientconfig).

Verifies that get_timeout dynamically reads timeout configurations (5, 17, 120, etc.)
and defaults properly without hardcoding.
"""

from clientconfig.config import get_timeout


def test_hidden_timeout_5():
    """Verify timeout=5 is returned."""
    assert get_timeout({"timeout": 5}) == 5


def test_hidden_timeout_17():
    """Verify timeout=17 is returned."""
    assert get_timeout({"timeout": 17}) == 17


def test_hidden_timeout_120():
    """Verify timeout=120 is returned."""
    assert get_timeout({"timeout": 120}) == 120


def test_hidden_default_fallback():
    """Verify missing timeout defaults to 30."""
    assert get_timeout({}) == 30


def test_hidden_none_fallback():
    """Verify None timeout defaults to 30."""
    assert get_timeout({"timeout": None}) == 30


def test_hidden_timeout_zero():
    """Verify timeout=0 is returned as 0, not default 30."""
    assert get_timeout({"timeout": 0}) == 0
