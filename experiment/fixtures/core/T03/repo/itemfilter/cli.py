"""Command line interface for itemfilter."""

import argparse
from typing import Any, Sequence
from .filter import filter_items, filter_matching


def create_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(description="Filter items by limit")
    # BUG: Missing type=int, so --limit "5" is parsed as string "5"
    parser.add_argument(
        "--limit",
        default=10,
        help="Maximum number of items to return",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Optional prefix filter string",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse items before filtering",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = create_parser()
    return parser.parse_args(argv)


def process(items: Sequence[Any], argv: Sequence[str] | None = None) -> list[Any]:
    """Filter items according to CLI arguments."""
    args = parse_args(argv)
    pool = list(reversed(items)) if args.reverse else list(items)
    if args.prefix:
        pool = filter_matching(pool, lambda x: str(x).startswith(args.prefix))
    limit = args.limit
    return filter_items(pool, limit)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    print(f"Configured limit: {args.limit}")
    return 0
