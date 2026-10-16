"""Command line entry point — place a netlist without starting the server.

    python3 -m app.cli examples/three_band_equalizer.json          # summary
    python3 -m app.cli examples/common_emitter.json -o layout.json # for the renderer
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Netlist
from .placer import place


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Netlist JSON -> breadboard layout JSON")
    ap.add_argument("netlist", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="write layout JSON here")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument(
        "-s",
        "--style",
        default="flow",
        choices=("flow", "packed"),
        help="flow: schematic-shaped (default); packed: fill the board",
    )
    args = ap.parse_args(argv)

    netlist = Netlist.model_validate_json(args.netlist.read_text(encoding="utf-8"))
    layout = place(netlist, style=args.style)

    if args.out:
        args.out.write_text(layout.model_dump_json(indent=2))

    if not args.quiet:
        print(layout.title)
        print("-" * len(layout.title))
        for step in layout.build_order:
            print(f"  {step.index:2d}. {step.text}")
            if step.detail:
                print(f"      {step.detail}")
        if layout.warnings:
            print("\nwarnings:")
            for w in layout.warnings:
                print(f"  ! {w}")
    if args.out and args.quiet:
        print(json.dumps({"out": str(args.out), "warnings": len(layout.warnings)}))
    return 1 if layout.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
