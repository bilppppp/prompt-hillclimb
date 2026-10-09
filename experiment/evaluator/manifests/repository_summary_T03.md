The original repository is a small Python package named itemfilter. It has four
source files: itemfilter/__init__.py (public exports), itemfilter/validator.py
(collection validation), itemfilter/filter.py (filter_items and filter_matching),
and itemfilter/cli.py (argparse parser, process, and main). Existing tests in
tests/test_cli.py verify default limit (10), direct filter_items calls, empty collection
filtering, reverse ordering, and custom limits via CLI. In cli.py, --limit lacks type=int,
leaving it as a string that triggers a TypeError when slicing items in filter_items.
The ordinary README describes CLI usage and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
