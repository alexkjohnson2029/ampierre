"""Netlists that list pins, not SPICE lines — what LTspice writes under
View → Export Netlist, rather than the View → SPICE Netlist text.

These formats say which part pin sits on which net, and give each part a
value, but not what kind of part it is or what its pins are called. The
reference designator says the kind (R, C, D, Q, M, U...) and pins come in
LTspice's own order, the same order a SPICE line lists its nodes in. So each
part is written out as the SPICE line it would have been, and the SPICE
reader does the rest: one set of rules for what an X line or a Q line is.
"""

from __future__ import annotations

import re
import shlex

#: Stands in for a part the netlist names no model or value for (an op-amp
#: symbol dropped on the schematic with no part number). The SPICE reader
#: turns it back into "no value".
UNNAMED = "__unnamed__"


class PinListError(ValueError):
    """Looks like a pin-list netlist but can't be read as one."""


def detect(text: str) -> str | None:
    """Which pin-list format the text is, or None for SPICE (or anything else)."""
    first = text.lstrip().splitlines()[0].strip().strip('"').lower() if text.strip() else ""
    if first.startswith("expresspcb netlist"):
        return "expresspcb"
    return None


def to_spice(text: str) -> str:
    """The netlist as the SPICE text LTspice would have shown for it."""
    fmt = detect(text)
    if fmt == "expresspcb":
        title, parts, pins = _expresspcb(text)
    else:  # pragma: no cover — callers check detect() first
        raise PinListError("Not a netlist format AMPierre knows.")
    return _spice_lines(title, parts, pins)


# ---------------------------------------------------------------------------
# ExpressPCB
# ---------------------------------------------------------------------------


_SECTIONS = {"part ids table": "part", "net names table": "net", "net connections table": "connections"}


def _expresspcb(text: str):
    """
        "ExpressPCB Netlist"
        "LTspice"
        ...
        "Part IDs Table"
        "R1" "10k" ""             <- ref, value, footprint; part 1, 2, 3...
        "Net Names Table"
        "N001" 26                 <- net name; net 1, 2, 3...
        "Net Connections Table"
        5 4 1 27                  <- net, part, pin, next link (unused)
    """
    lines = [ln.strip() for ln in text.splitlines()]
    program = next((_words(ln)[0] for ln in lines[1:2] if ln), "")
    section = None
    parts: list[tuple[str, str]] = []
    nets: list[str] = []
    pins: dict[str, dict[int, str]] = {}
    for ln in lines:
        if not ln:
            continue
        low = ln.strip('"').lower()
        if low in _SECTIONS:
            section = _SECTIONS[low]
            continue
        if section == "part":
            words = _words(ln)
            if words:
                parts.append((words[0], words[1] if len(words) > 1 else ""))
        elif section == "net":
            words = _words(ln)
            if words:
                nets.append(words[0])
        elif section == "connections":
            nums = ln.split()
            if len(nums) < 3 or not all(n.isdigit() for n in nums[:3]):
                continue
            net, part, pin = (int(n) for n in nums[:3])
            if not (1 <= net <= len(nets) and 1 <= part <= len(parts)):
                raise PinListError(f"The connection '{ln}' names a net or part that isn't listed.")
            pins.setdefault(parts[part - 1][0], {})[pin] = nets[net - 1]
    if not parts:
        raise PinListError("This ExpressPCB netlist has no Part IDs Table, so there are no parts to place.")
    title = f"{program} export" if program else "Pasted netlist"
    return title, parts, pins


def _words(line: str) -> list[str]:
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.replace('"', " ").split()


# ---------------------------------------------------------------------------
# Back to SPICE
# ---------------------------------------------------------------------------

#: What a part's value becomes when the netlist leaves it empty, by letter.
_DEFAULT_MODEL = {"D": "D", "Q": UNNAMED, "M": UNNAMED, "J": UNNAMED}


def _net(name: str) -> str:
    # SPICE nodes are single words.
    return re.sub(r"\s+", "_", name.strip()) or "NC"


def _spice_lines(title: str, parts: list[tuple[str, str]], pins: dict[str, dict[int, str]]) -> str:
    out = [f"* {title}"]
    for ref, value in parts:
        on = pins.get(ref)
        if not on:
            continue  # a part with nothing wired to it: a label or a flag
        count = max(on)
        # A pin the netlist skips is on no net; give it one of its own so the
        # pins after it keep their place.
        nodes = [_net(on[n]) if n in on else f"NC_{ref}_{n}" for n in range(1, count + 1)]
        letter = ref[0].upper()
        value = value.strip()
        if letter in "RCLV":
            out.append(" ".join([ref, *nodes, value]).rstrip())
        elif letter in "DQMJ":
            out.append(" ".join([ref, *nodes, value or _DEFAULT_MODEL[letter]]))
        elif letter in "IBEFGHKSTWA":
            out.append(" ".join([ref, *nodes, value or "0"]))  # skipped, and said so
        else:
            # U1, X1, IC1...: a subcircuit. SPICE wants an X in front.
            name = ref if letter == "X" else "X" + ref
            model = re.sub(r"\s+", "_", value) or UNNAMED
            out.append(" ".join([name, *nodes, model]))
    return "\n".join(out) + "\n"
