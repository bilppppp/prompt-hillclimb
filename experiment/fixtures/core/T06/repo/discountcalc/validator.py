"""Discount rate and price validation routines."""


def validate_rate(rate: float) -> bool:
    """Ensure discount rate is between 0.0 and 1.0 inclusive."""
    if not isinstance(rate, (int, float)):
        raise TypeError(f"Discount rate must be numeric, got {type(rate).__name__}")
    if rate < 0.0 or rate > 1.0:
        raise ValueError(f"Discount rate must be between 0.0 and 1.0, got {rate}")
    return True


def validate_price(price: float) -> bool:
    """Ensure price is non-negative number."""
    if not isinstance(price, (int, float)):
        raise TypeError(f"Price must be numeric, got {type(price).__name__}")
    if price < 0.0:
        raise ValueError(f"Price cannot be negative, got {price}")
    return True
