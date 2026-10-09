"""Command line interface for userreport."""

import argparse
from typing import Sequence
from .report import generate_report


def create_parser() -> argparse.ArgumentParser:
    """Create command line parser for userreport."""
    parser = argparse.ArgumentParser(description="Generate user profile reports")
    parser.add_argument(
        "--name",
        default="",
        help="User full name",
    )
    parser.add_argument(
        "--age",
        type=int,
        default=0,
        help="User age",
    )
    parser.add_argument(
        "--skills",
        nargs="*",
        default=[],
        help="List of skills",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    return parser


def run_cli(argv: Sequence[str] | None = None) -> str:
    """Execute CLI and return formatted report output string."""
    parser = create_parser()
    args = parser.parse_args(argv)
    output = generate_report(
        name=args.name,
        age=args.age,
        skills=args.skills,
        fmt=args.fmt,
    )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    output = run_cli(argv)
    print(output)
    return 0
