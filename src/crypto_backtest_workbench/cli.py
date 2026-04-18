"""Minimal CLI for scaffold introspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_backtest_workbench import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cbw")
    parser.add_argument("--version", action="store_true", help="Print package version.")

    subparsers = parser.add_subparsers(dest="command")

    scaffold = subparsers.add_parser("scaffold", help="Print the Phase 1 scaffold layout.")
    scaffold.add_argument(
        "--json",
        action="store_true",
        help="Print scaffold layout as JSON.",
    )
    return parser


def scaffold_layout() -> dict[str, list[str]]:
    return {
        "domain": [
            "common enums and identifiers",
            "dataset snapshots and validation splits",
            "feature artifacts and cache keys",
            "execution events and run manifests",
        ],
        "engine": [
            "historical data request and ingestion service",
            "strategy interface",
            "execution policy defaults",
            "portfolio account snapshot",
            "feature cache registry",
        ],
        "jobs": [
            "single run task payload",
            "parameter experiment task payload",
            "task lifecycle record",
        ],
        "storage": [
            "artifact uri helpers",
            "dataset repository scaffold",
        ],
        "docs": [
            "implementation design",
            "reference usage",
            "phase 1 code skeleton",
        ],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return 0

    if args.command == "scaffold":
        layout = scaffold_layout()
        if args.json:
            print(json.dumps(layout, indent=2, sort_keys=True))
        else:
            print("Phase 1 scaffold:")
            for section, items in layout.items():
                print(f"- {section}")
                for item in items:
                    print(f"  - {item}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
