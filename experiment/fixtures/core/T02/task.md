# Task: Fix NoneType AttributeError in Header Parser

## Problem Description
In `kvparser/parser.py`, parsing a header that contains a `None` value (such as `{"X-Optional": None}`) causes `clean_value()` to raise an `AttributeError: 'NoneType' object has no attribute 'strip'`.

## Instructions
1. Fix the bug in `kvparser/parser.py` so that when a header value is `None`, it is handled safely by returning `None` instead of raising an `AttributeError`.
2. Existing behavior for valid, non-None string values must be preserved (leading and trailing whitespace must still be trimmed).
3. Run the specific targeted test in `tests/test_parser.py`:
   ```bash
   pytest tests/test_parser.py::test_parse_header_with_none_value
   ```
4. Stop once that test passes and there is no evidence of new test failures.
