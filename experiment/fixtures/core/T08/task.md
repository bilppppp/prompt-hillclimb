# Task: Fix Duplicate Records Bug in Data Import

## Context
When running `import_data.py` (or `recordstore.storage.import_records_file`), importing records from a source JSON file into the local target JSON file appends incoming records without checking for existing entries. Running imports repeatedly results in duplicate records with the same `'id'`.

## Instructions
1. Fix the import logic so that incoming records whose `'id'` already exists in the target storage are not duplicated.
2. New records with distinct IDs should be appended to the storage while preserving the original records.
3. This is intended for small local datasets, so complex optimizations are not required.
