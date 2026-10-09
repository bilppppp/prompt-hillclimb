# Task: Implement JSON Output Support in User Report CLI

## Context
The `userreport` CLI utility currently formats user profiles as plain text using `--format text` (the default). It accepts `--format json`, but JSON formatting is not yet implemented in `userreport/formatter.py` and currently raises an error.

## Instructions
1. Implement support for `--format json` (and `fmt="json"`) so that user profile data is properly serialized into a valid JSON string at runtime.
2. The JSON output must accurately reflect runtime profile fields (`name`, `age`, and `skills` list) rather than returning a static hardcoded string.
3. Preserve existing plain text formatting behavior when `--format text` is used.
