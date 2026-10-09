# Task: Read Configured Timeout Value Instead of Hardcoding

## Context
In `clientconfig/config.py`, the `get_timeout(config)` function currently hardcodes `return 30` rather than reading the configured value from the input mapping.

## Instructions
1. Update `get_timeout(config)` in `clientconfig/config.py` to inspect the `config` mapping and return the configured timeout integer (key `'timeout'`).
2. If `'timeout'` is not provided in `config` or is `None`, default to `30`.
3. Properly parse or return the integer value from the mapping rather than hardcoding a static constant.
