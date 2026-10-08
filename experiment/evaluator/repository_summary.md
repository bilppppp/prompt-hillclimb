The original repository is a small Python package named kvparser. It has three
source files: kvparser/__init__.py (public exports and convenience utilities),
kvparser/parser.py (clean_value, parse_header_line, and parse_headers), and
kvparser/validator.py (header-key validation). Existing tests cover a simple
header, whitespace stripping, parsing a mapping, invalid keys, and a None-valued
header. clean_value is annotated for str | None but calls value.strip()
unconditionally. parse_headers routes each mapping value through clean_value.
The ordinary README describes the public parsing API and how to run pytest.
There is no existing persistence, registry, snapshot or checkpoint infrastructure.
