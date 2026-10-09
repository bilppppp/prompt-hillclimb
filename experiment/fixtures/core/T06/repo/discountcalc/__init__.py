"""discountcalc package exports."""

from .validator import validate_rate, validate_price
from .calculator import (
    calculate_discount,
    calculate_bulk_discounts,
    get_promo_rate,
    apply_promo_code,
    PROMO_CODES,
)
from .formatter import format_currency, format_percentage, format_discount_summary

__all__ = [
    "validate_rate",
    "validate_price",
    "calculate_discount",
    "calculate_bulk_discounts",
    "get_promo_rate",
    "apply_promo_code",
    "PROMO_CODES",
    "format_currency",
    "format_percentage",
    "format_discount_summary",
]
