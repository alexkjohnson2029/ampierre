"""Check the model end of the app without the browser.

    python3 tools/try_llm.py my_schematic.png

Prints the netlist it read back, or the error. One call, a fraction of a cent.
Needs ANTHROPIC_API_KEY in .env or the environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm import LLMError, extract_netlist  # noqa: E402
from app.main import load_dotenv  # noqa: E402
from app.placer import place  # noqa: E402

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"No such file: {path}")
        return 2

    load_dotenv()
    try:
        netlist = extract_netlist(path.read_bytes(), MEDIA.get(path.suffix.lower(), "image/png"))
    except LLMError as e:
        print(f"Model call failed: {e}")
        return 1

    print(f"{netlist.title}\n")
    for c in netlist.components:
        pins = ", ".join(f"{k}={v}" for k, v in c.pins.items())
        print(f"  {c.ref:6s} {c.kind.value:12s} {c.value or '':10s} {pins}")
    if netlist.warnings:
        print("\nthe model was unsure about:")
        for w in netlist.warnings:
            print(f"  ! {w}")

    layout = place(netlist)
    print(f"\nplaces onto the board as {len(layout.components)} parts and "
          f"{len(layout.wires)} jumpers, {len(layout.warnings)} problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
