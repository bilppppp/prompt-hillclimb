# Task: Add Field Conversion Rule to Schema Converter CLI

## Context
The `schemaconvert` CLI converts JSON record files from an older format to a newer schema. Currently, the conversion pipeline copies fields but is missing the transformation rule for contact names and status.

## Instructions
1. Update the conversion logic so that:
   - `'first_name'` and `'last_name'` are combined into `'full_name'` as `f"{first_name} {last_name}".strip()`.
   - The `'email'` field is preserved.
   - A `'status'` field with value `'active'` is added to each record.
2. This is a one-off conversion tool; no recovery or failure resume features are needed.
3. Preserve all other existing CLI flags, input/output file handling, and exit code behaviors.
