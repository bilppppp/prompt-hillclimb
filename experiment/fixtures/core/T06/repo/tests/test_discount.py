"""Tests for discountcalc."""

import pytest
from discountcalc.calculator import (
    calculate_discount,
    calculate_bulk_discounts,
    get_promo_rate,
)
from discountcalc.formatter import format_discount_summary, format_percentage


def test_discount_zero():
    """Verify 0% discount leaves price unchanged."""
    assert calculate_discount(100.0, 0.0) == 100.0


def test_discount_twenty_percent():
    """Verify 20% discount on 100.0 yields 80.0."""
    assert calculate_discount(100.0, 0.20) == 80.0


def test_invalid_rate_raises():
    """Verify rate > 1.0 raises ValueError."""
    with pytest.raises(ValueError):
        calculate_discount(100.0, 1.25)


def test_negative_rate_raises():
    """Verify negative discount rate raises ValueError."""
    with pytest.raises(ValueError):
        calculate_discount(50.0, -0.10)


def test_negative_price_raises():
    """Verify negative price raises ValueError."""
    with pytest.raises(ValueError):
        calculate_discount(-10.0, 0.10)


def test_promo_rate_lookup():
    """Verify promotional code rate lookup."""
    assert get_promo_rate("SAVE10") == 0.10
    assert get_promo_rate("half") == 0.50


def test_format_summary():
    """Verify summary string formatting."""
    summary = format_discount_summary(100.0, 0.20, 80.0)
    assert "Base: $100.00" in summary
    assert "Discount: 20%" in summary
    assert "Saved: $20.00" in summary
    assert "Final: $80.00" in summary
