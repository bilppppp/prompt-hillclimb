# Task: Fix String --limit Argument Bug in CLI

## Context
In `itemfilter/cli.py`, passing `--limit` as a command-line argument parses the value as a string instead of an integer. When passed to `filter_items()`, slicing with a string causes a `TypeError`.

## Instructions
1. Fix the bug in `itemfilter/cli.py` so that the `--limit` argument is parsed as an integer.
2. Do not refactor or redesign the CLI structure; keep the existing argument flags and behavior intact.
