"""CLI parsing and formatting logic for clilabel."""

import argparse
from typing import Sequence
from .config import DEFAULT_LABEL
from .validator import validate_label


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(description="CLI labeling utility")
    parser.add_argument(
        "-l",
        "--label",
        default=DEFAULT_LABEL,
        help=f"Target label (default: {DEFAULT_LABEL})",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        default=None,
        help="Optional prefix to prepend to label",
    )
    parser.add_argument(
        "-u",
        "--uppercase",
        action="store_true",
        help="Convert label to uppercase",
    )
    return parser


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = create_parser()
    if args is None:
        args = []
    return parser.parse_args(args)


def get_label(args: Sequence[str] | None = None) -> str:
    """Retrieve effective label from arguments or default."""
    parsed = parse_args(args)
    label = str(parsed.label)
    validate_label(label)
    return label


def format_label(label: str, prefix: str | None = None, uppercase: bool = False) -> str:
    """Format label with optional prefix and case modification."""
    validate_label(label)
    res = label.upper() if uppercase else label
    if prefix:
        return f"{prefix}:{res}"
    return res


def main(args: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parsed = parse_args(args)
    lbl = format_label(parsed.label, prefix=parsed.prefix, uppercase=parsed.uppercase)
    print(lbl)
    return 0
