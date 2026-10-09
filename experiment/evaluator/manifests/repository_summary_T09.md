The original repository is a small Python package named schemaconvert. It has five
source files: schemaconvert/__init__.py (public exports), schemaconvert/io.py
(load_json_records and save_json_records file I/O), schemaconvert/transformer.py
(transform_record and transform_all_records), schemaconvert/converter.py (convert_file
pipeline), and schemaconvert/cli.py (argparse CLI runner taking input and output file paths).
Existing tests in tests/test_convert.py test empty file conversion, email field preservation,
schema conversion with full_name and status (which fails because transform_record copies records
directly without combining names or setting status), CLI execution, missing input file error,
and malformed JSON error.
The ordinary README describes schema conversion usage and pytest execution.
There is no existing persistence, registry, snapshot, recovery or checkpoint infrastructure.
