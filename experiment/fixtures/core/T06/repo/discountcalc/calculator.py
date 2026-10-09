"""Discount calculation implementation."""

from typing import Mapping, Sequence
from .validator import validate_rate, validate_price

PROMO_CODES: Mapping[str, float] = {
    "SAVE10": 0.10,
    "SAVE20": 0.20,
    "HALF": 0.50,
}


def calculate_discount(price: float, rate: float) -> float:
    """Compute the discounted price.

    Parameters:
        price: Original base price.
        rate: Discount rate between 0.0 and 1.0.

    Returns:
        Final price after discount.
    """
    validate_price(price)
    validate_rate(rate)
    # BUG: Adds rate instead of subtracting discount: price * (1.0 + rate)
    return round(price * (1.0 + rate), 2)


def calculate_bulk_discounts(
    items: Sequence[tuple[float, float]],
) -> list[float]:
    """Compute discounted prices for a sequence of (price, rate) pairs."""
    return [calculate_discount(p, r) for p, r in items]


def get_promo_rate(code: str) -> float:
    """Retrieve discount rate for a named promo code."""
    cleaned = code.strip().upper()
    if cleaned not in PROMO_CODES:
        raise KeyError(f"Unknown promo code: {code}")
    return PROMO_CODES[cleaned]


def apply_promo_code(price: float, code: str) -> float:
    """Apply a promo code discount to a base price."""
    rate = get_promo_rate(code)
    return calculate_discount(price, rate)
