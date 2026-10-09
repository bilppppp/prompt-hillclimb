# Task: Add JSON Format Support to Data Exporter

## Context
In `dataexport/formatter.py`, `export_data(record, fmt="text")` supports text formatting, but requesting `fmt="json"` currently raises `ValueError: Unsupported format: json`.

## Instructions
1. Add support for `fmt="json"` in `export_data(record, fmt="text")` so that the record mapping is properly serialized into a valid JSON string.
2. The project only requires `'text'` and `'json'` formats; keep the implementation straightforward and simple.
3. Ensure existing `fmt="text"` behavior and unsupported format rejection remain intact.
