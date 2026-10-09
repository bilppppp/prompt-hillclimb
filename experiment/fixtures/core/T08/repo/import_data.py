"""CLI script to import JSON records into local storage."""

import argparse
from typing import Sequence
from recordstore.storage import import_records_file


def create_parser() -> argparse.ArgumentParser:
    """Create command line parser."""
    parser = argparse.ArgumentParser(description="Import records from JSON file")
    parser.add_argument(
        "--source",
        required=True,
        help="Path to incoming records JSON file",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Path to target storage JSON file",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Import CLI entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)
    records = import_records_file(args.source, args.target)
    print(f"Total stored records: {len(records)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
