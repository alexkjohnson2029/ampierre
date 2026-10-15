"""Putting op-amps drawn one at a time into dual and quad chips.

A schematic draws every op-amp as its own triangle — U1 to U8 in the
three-band equalizer — but at the bench they come four to a TL074 or OP484
and two to a TL072. When several single op-amps are given a dual or quad
package, they share chips: the first goes in section A, the next in B, and
so on, all on the chip's one pair of supply pins.

Only op-amps whose supply nets match are put together, and only ones that use
a single section's pin names; a netlist that already says which section is
which (IN+B, OUT C...) is left as it is.
"""

from __future__ import annotations

import string

from . import packages as pk
from .models import Component, ComponentKind, Netlist

_SINGLE = {"IN+", "IN-", "OUT", "V+", "V-", "IN+A", "IN-A", "OUT A"}
_ROLE = {"IN+": "IN+", "IN+A": "IN+", "IN-": "IN-", "IN-A": "IN-", "OUT": "OUT", "OUT A": "OUT"}


def sections(pkg: pk.Package) -> list[str]:
    """The section letters a package has: ['A', 'B', 'C', 'D'] for a quad."""
    found = [
        letter
        for letter in string.ascii_uppercase[:8]
        if f"OUT {letter}" in pkg.pin_map and f"IN+{letter}" in pkg.pin_map
    ]
    return found


def pack_sections(netlist: Netlist, custom: dict | None = None) -> Netlist:
    custom = custom or {}
    groups: dict[tuple, list[Component]] = {}
    for comp in netlist.components:
        if comp.kind is not ComponentKind.OPAMP or comp.ref in custom or not comp.package:
            continue
        pkg = pk.BY_ID.get(comp.package)
        if pkg is None or len(sections(pkg)) < 2:
            continue
        if not set(comp.pins) <= _SINGLE:
            continue
        key = (pkg.id, comp.pins.get("V+"), comp.pins.get("V-"))
        groups.setdefault(key, []).append(comp)

    merged: dict[str, Component] = {}  # first member's ref -> the chip
    absorbed: set[str] = set()
    for (pkg_id, vpos, vneg), members in groups.items():
        if len(members) < 2:
            continue
        pkg = pk.BY_ID[pkg_id]
        letters = sections(pkg)
        for start in range(0, len(members), len(letters)):
            chunk = members[start : start + len(letters)]
            if len(chunk) < 2:
                continue  # one op-amp left over keeps a chip to itself
            pins: dict[str, str] = {}
            for letter, comp in zip(letters, chunk):
                for name, net in comp.pins.items():
                    role = _ROLE.get(name)
                    if role == "OUT":
                        pins[f"OUT {letter}"] = net
                    elif role:
                        pins[f"{role}{letter}"] = net
            if vpos:
                pins["V+"] = vpos
            if vneg:
                pins["V-"] = vneg
            refs = [c.ref for c in chunk]
            chip = Component(
                ref="/".join(refs),
                kind=ComponentKind.OPAMP,
                value=chunk[0].value,
                pins=pins,
                package=pkg_id,
                notes=" · ".join(
                    f"Section {letter} = {c.ref}" + (f" ({c.notes})" if c.notes else "")
                    for letter, c in zip(letters, chunk)
                ),
            )
            merged[chunk[0].ref] = chip
            absorbed.update(refs)

    if not merged:
        return netlist
    components: list[Component] = []
    for comp in netlist.components:
        if comp.ref in merged:
            components.append(merged[comp.ref])
        elif comp.ref not in absorbed:
            components.append(comp)
    return netlist.model_copy(update={"components": components})
