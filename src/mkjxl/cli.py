"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mkjxl.app import MkJxlApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mkjxl",
        description="Batch convert images to JPEG XL.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Folder of images to convert. Defaults to the current directory.",
    )
    args = parser.parse_args(argv)
    directory = Path(args.directory).expanduser()
    if not directory.is_dir():
        print(f"Error: directory not found: {directory}", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Error: mkjxl needs a terminal.", file=sys.stderr)
        return 1
    MkJxlApp(directory).run()
    return 0
