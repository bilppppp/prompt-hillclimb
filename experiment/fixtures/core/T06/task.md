# Task: Fix Calculation Bug in Discount Calculator

## Context
In `discountcalc/calculator.py`, `calculate_discount(price, rate)` computes an incorrect result due to a bug in the calculation formula.

## Instructions
1. Fix the calculation in `discountcalc/calculator.py` so that discounted prices are correctly computed by deducting the discount rate from the base price.
2. Fix the source code directly; do not modify or weaken the test assertions in `tests/test_discount.py` to accommodate incorrect behavior.
3. Preserve all price and rate validation constraints.
