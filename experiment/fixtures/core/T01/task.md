# Task: Update Default CLI Label from foo to bar

## Context
In `clilabel/config.py`, the default label constant `DEFAULT_LABEL` is currently configured as `"foo"`.

## Instructions
1. Update `DEFAULT_LABEL` in `clilabel/config.py` from `"foo"` to `"bar"`.
2. Update the corresponding existing test assertions in `tests/test_cli.py` that check the default label to expect `"bar"`.
3. Preserve all other existing CLI behavior and custom label overriding via command-line flags.
