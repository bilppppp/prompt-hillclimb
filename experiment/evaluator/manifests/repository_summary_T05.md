The original repository is a small Python package named userreport. It has five
source files: userreport/__init__.py (public exports), userreport/models.py
(UserModel profile representation and validation), userreport/formatter.py
(format_text_report and format_report), userreport/report.py (generate_report),
and userreport/cli.py (argparse CLI runner with --format options). Existing tests in
tests/test_report.py cover default text format, custom user text format, CLI text output,
JSON format for Alice via CLI (which fails with ValueError), invalid format exceptions,
and model validation. format_report only handles fmt="text" and raises ValueError for "json".
The ordinary README describes user report generation and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
