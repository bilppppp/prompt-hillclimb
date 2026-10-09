"""Hidden evaluation tests for T06 (discountcalc).

Verifies true discount calculation across multiple numerical rates and base prices,
preventing trivial test mutation solutions.
"""

import pytest
from discountcalc.calculator import calculate_discount


def test_hidden_discount_10_percent():
    """Verify 10% discount on 50.0 is 45.0."""
    assert calculate_discount(50.0, 0.10) == 45.0


def test_hidden_discount_50_percent():
    """Verify 50% discount on 200.0 is 100.0."""
    assert calculate_discount(200.0, 0.50) == 100.0


def test_hidden_discount_full():
    """Verify 100% discount reduces price to 0.0."""
    assert calculate_discount(80.0, 1.0) == 0.0


def test_hidden_discount_small():
    """Verify 5% discount on 10.0 is 9.5."""
    assert calculate_discount(10.0, 0.05) == 9.5


def test_hidden_zero_rate():
    """Verify 0% discount on 75.0 remains 75.0."""
    assert calculate_discount(75.0, 0.0) == 75.0


def test_hidden_invalid_rate_still_raises():
    """Verify invalid discount rate over 1.0 continues to raise ValueError."""
    with pytest.raises(ValueError):
        calculate_discount(100.0, 1.5)
