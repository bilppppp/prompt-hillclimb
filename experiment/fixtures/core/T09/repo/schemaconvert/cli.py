"""Command line interface for schemaconvert."""

import argparse
from typing import Sequence
from .converter import convert_file


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(description="Convert JSON records schema")
    parser.add_argument(
        "input_file",
        help="Path to input JSON file",
    )
    parser.add_argument(
        "output_file",
        help="Path to output converted JSON file",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default: 2)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)
    transformed = convert_file(args.input_file, args.output_file, indent=args.indent)
    print(f"Successfully converted {len(transformed)} records.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
