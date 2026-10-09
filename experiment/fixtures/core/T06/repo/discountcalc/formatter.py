"""Formatting utilities for discountcalc."""


def format_currency(amount: float) -> str:
    """Format floating point number as currency string."""
    return f"${amount:.2f}"


def format_percentage(rate: float) -> str:
    """Format rate as percentage string."""
    pct = int(round(rate * 100))
    return f"{pct}%"


def format_discount_summary(
    base_price: float,
    rate: float,
    final_price: float,
) -> str:
    """Format a summary string of the discount applied."""
    pct_str = format_percentage(rate)
    saved = round(base_price - final_price, 2)
    return (
        f"Base: {format_currency(base_price)} | "
        f"Discount: {pct_str} | "
        f"Saved: {format_currency(saved)} | "
        f"Final: {format_currency(final_price)}"
    )
