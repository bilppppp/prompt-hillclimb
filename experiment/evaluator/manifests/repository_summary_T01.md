The original repository is a small Python package named clilabel. It has four
source files: clilabel/__init__.py (public exports), clilabel/config.py
(defines DEFAULT_LABEL = "foo" and limits), clilabel/validator.py (label format validation),
and clilabel/cli.py (argparse parser, format_label, and get_label helper). Existing
tests in tests/test_cli.py verify default label behavior ("foo"), custom --label flag,
-l short flag, None arguments, prefix formatting, uppercase formatting, and validation.
DEFAULT_LABEL is currently "foo" and tests assert "foo" for default invocations.
The ordinary README describes CLI usage and pytest execution.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
