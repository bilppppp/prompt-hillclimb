The original repository is a small Python package named discountcalc. It has four
source files: discountcalc/__init__.py (public exports), discountcalc/validator.py
(rate and price validation), discountcalc/formatter.py (currency and summary formatting),
and discountcalc/calculator.py (calculate_discount, bulk discounts, promo code support).
Existing tests in tests/test_discount.py cover zero discount, 20% discount (which fails
because calculator adds rate rather than subtracting), rate and price boundaries, promo
code lookups, and formatted summaries. The bug is in calculator.py: calculate_discount
computes price * (1.0 + rate).
The ordinary README describes pricing calculation usage and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
