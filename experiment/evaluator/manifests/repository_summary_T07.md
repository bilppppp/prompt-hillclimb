The original repository is a small Python package named dataexport. It has four
source files: dataexport/__init__.py (public exports), dataexport/validator.py
(record structure and key validation), dataexport/normalizer.py (normalize_record,
clean_none_values, filter_keys), and dataexport/formatter.py (format_text,
format_summary_line, and export_data). Existing tests in tests/test_export.py verify
basic text formatting, single-field text formatting, JSON export (which fails with ValueError),
unknown format rejection, summary line formatting, None cleaning, and key filtering.
export_data only handles fmt="text" and raises ValueError for "json".
The ordinary README describes data export usage and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
