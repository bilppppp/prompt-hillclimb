The original repository is a small Python package named recordstore. It has five
source files: recordstore/__init__.py (public exports), recordstore/io.py (load_records
and save_records JSON file I/O), recordstore/validator.py (record mapping and ID validation),
recordstore/storage.py (import_records and import_records_file), and import_data.py
(CLI script for importing JSON files into local storage). Existing tests in
tests/test_store.py test importing new records, deduplication by ID across repeated imports
(which fails because storage appends incoming records without checking ID), CLI script
execution, record validation, non-existent file fallback, and ordering preservation.
The ordinary README describes record store importing and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
