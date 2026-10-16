"""Would the bundled examples work if you built them exactly as drawn?

breadboard.verify() checks the board against the netlist using the app's own
idea of where every pin is. This file checks it again from the outside: its
own copy of the datasheet pinouts, its own model of the breadboard's strips,
and the physical rules a real bench adds (every pin of a chip is in the board,
not only the ones the schematic uses; a hole takes one lead; a polarised part
goes the right way round; supply pins land on the right rail).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import Netlist, NetRole
from app.placer import is_unused, place

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.json"))

#: From the datasheets, written out again on purpose rather than imported.
DATASHEET = {
    # TI TL072 / ST TL082 / TI LM358 / NE5532 / OP284 / OPA2134
    "dip8_dual_opamp": {1: "OUT A", 2: "IN-A", 3: "IN+A", 4: "V-", 5: "IN+B", 6: "IN-B", 7: "OUT B", 8: "V+"},
    # TI TL074 / LM324 / ADI OP484 / OPA4134
    "dip14_quad_opamp": {
        1: "OUT A", 2: "IN-A", 3: "IN+A", 4: "V+", 5: "IN+B", 6: "IN-B", 7: "OUT B",
        8: "OUT C", 9: "IN-C", 10: "IN+C", 11: "V-", 12: "IN+D", 13: "IN-D", 14: "OUT D",
    },
    "dip8_lm741": {1: "OFFSET NULL", 2: "IN-", 3: "IN+", 4: "V-", 5: "OFFSET NULL", 6: "OUT", 7: "V+", 8: "NC"},
    # 2N3904 / 2N3906, flat face toward you, leads down
    "to92_ebc_npn": {1: "E", 2: "B", 3: "C"},
    "to92_ebc_pnp": {1: "E", 2: "B", 3: "C"},
    "trimpot_inline": {1: "1", 2: "W", 3: "3"},
}

TOP, BOTTOM = "JIHGF", "EDCBA"


def node(row: str, col: int) -> str:
    if row.startswith("RAIL"):
        return row
    return f"{'top' if row in TOP else 'bottom'}:{col}"


class Nodes:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            x = self.parent[x]
        return x

    def join(self, a, b):
        self.parent[self.find(b)] = self.find(a)


def dip_holes(comp) -> dict[int, tuple[str, int]]:
    """Every pin of a DIP, from where its body sits and which way it faces."""
    n = len(comp.body["pin_names"])
    half = n // 2
    left = comp.body["anchor_col"]
    holes = {}
    for pin in range(1, n + 1):
        if comp.body["notch"] == "left":  # pin 1 bottom left, counter-clockwise
            holes[pin] = ("E", left + pin - 1) if pin <= half else ("F", left + n - pin)
        else:  # turned round: pin 1 top right
            holes[pin] = ("F", left + half - pin) if pin <= half else ("E", left + pin - half - 1)
    return holes


def _load(path):
    return Netlist.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(params=EXAMPLES, ids=lambda p: p.stem)
def built(request):
    netlist = _load(request.param)
    return netlist, place(netlist)


def test_chip_pinouts_match_the_datasheet(built):
    _, layout = built
    for comp in layout.components:
        sheet = DATASHEET.get(comp.package)
        if not sheet:
            continue
        for pin in comp.pins:
            if pin.number is None or is_unused(pin.net):
                continue
            assert sheet[pin.number].replace(" ", "") == pin.name.replace(" ", ""), (
                f"{comp.ref} pin {pin.number} is {sheet[pin.number]} on the datasheet, "
                f"but the board wires it as {pin.name}"
            )


def test_every_chip_pin_is_where_the_body_says(built):
    _, layout = built
    for comp in layout.components:
        if comp.body.get("form") != "dip":
            continue
        holes = dip_holes(comp)
        for pin in comp.pins:
            assert (pin.hole.row, pin.hole.col) == holes[pin.number], f"{comp.ref} pin {pin.number}"


def _occupants(layout):
    """hole -> what's in it: every lead, every spare chip pin, every jumper end."""
    used: dict[tuple[str, int], list[str]] = {}
    for comp in layout.components:
        if comp.body.get("form") == "dip":
            for number, hole in dip_holes(comp).items():
                used.setdefault(hole, []).append(f"{comp.ref}.{number}")
        else:
            for pin in comp.pins:
                used.setdefault((pin.hole.row, pin.hole.col), []).append(f"{comp.ref}.{pin.name}")
    for i, w in enumerate(layout.wires):
        for h in (w.from_hole, w.to_hole):
            used.setdefault((h.row, h.col), []).append(f"wire{i}")
    for lead in layout.leads:
        used.setdefault((lead.hole.row, lead.hole.col), []).append(f"{lead.source}{lead.terminal}")
    return used


def test_one_lead_per_hole(built):
    _, layout = built
    for hole, who in _occupants(layout).items():
        if hole[0].startswith("RAIL"):
            continue
        assert len(who) == 1, f"{hole} holds {who}"


def _solve(layout):
    nodes = Nodes()
    for w in layout.wires:
        nodes.join(node(w.from_hole.row, w.from_hole.col), node(w.to_hole.row, w.to_hole.col))
    return nodes


def test_the_board_is_the_circuit(built):
    """Each schematic net is one node, two nets never share one, and a chip pin
    the schematic leaves unused sits in a strip nothing else touches."""
    netlist, layout = built
    nodes = _solve(layout)
    by_ref = {c.ref: c for c in layout.components}
    net_nodes: dict[str, set[str]] = {}
    for comp in netlist.components:
        placed = by_ref[comp.ref]
        for name, net in comp.pins.items():
            pin = next(p for p in placed.pins if p.name == name)
            net_nodes.setdefault(net, set()).add(nodes.find(node(pin.hole.row, pin.hole.col)))
    for net, found in net_nodes.items():
        assert len(found) == 1, f"net {net} is in {len(found)} pieces"
    owner = {}
    for net, found in net_nodes.items():
        (n,) = found
        assert n not in owner, f"{net} is shorted to {owner.get(n)}"
        owner[n] = net
    for comp in layout.components:
        if comp.body.get("form") != "dip":
            continue
        wired = {p.number for p in comp.pins}
        for number, (row, col) in dip_holes(comp).items():
            if number in wired:
                continue
            n = nodes.find(node(row, col))
            assert n not in owner, f"{comp.ref} pin {number} (unused) is shorted to {owner[n]}"
            others = [
                who
                for (r, c), who in _occupants(layout).items()
                if not r.startswith("RAIL") and nodes.find(node(r, c)) == n
            ]
            assert others == [[f"{comp.ref}.{number}"]], f"{comp.ref} pin {number} shares a strip: {others}"


def test_rails_carry_the_supplies_the_spec_asks_for(built):
    netlist, layout = built
    nodes = _solve(layout)
    by_ref = {c.ref: c for c in layout.components}
    roles = {n.name: n.role for n in netlist.nets}
    net_node = {}
    for comp in netlist.components:
        for name, net in comp.pins.items():
            pin = next(p for p in by_ref[comp.ref].pins if p.name == name)
            net_node[net] = nodes.find(node(pin.hole.row, pin.hole.col))
    want = {
        "RAIL_TOP_POS": NetRole.SUPPLY_POS,
        "RAIL_TOP_NEG": NetRole.GROUND,
        "RAIL_BOT_NEG": NetRole.GROUND,
        "RAIL_BOT_POS": NetRole.SUPPLY_NEG,
    }
    for rail, role in want.items():
        on_it = [net for net, n in net_node.items() if n == nodes.find(rail)]
        for net in on_it:
            assert roles.get(net) is role, f"{rail} carries {net}"


def test_op_amp_supply_pins_reach_the_supplies(built):
    netlist, layout = built
    roles = {n.name: n.role for n in netlist.nets}
    for comp in netlist.components:
        if comp.kind.value != "opamp":
            continue
        assert roles.get(comp.pins.get("V+")) is NetRole.SUPPLY_POS, comp.ref
        assert roles.get(comp.pins.get("V-")) in (NetRole.SUPPLY_NEG, NetRole.GROUND), comp.ref


def test_polarised_parts_face_the_right_way(built):
    """The striped lead of an electrolytic and the cathode of an LED go to the
    lower voltage. In these circuits that's always ground or the − supply."""
    netlist, _ = built
    low = {n.name for n in netlist.nets if n.role in (NetRole.GROUND, NetRole.SUPPLY_NEG)}
    for comp in netlist.components:
        if comp.kind.value == "polarized_capacitor":
            assert comp.pins["-"] in low, comp.ref
        if comp.kind.value == "led":
            assert comp.pins["K"] in low, comp.ref


def test_every_op_amp_chip_is_decoupled(built):
    """A 100 nF cap from each supply pin's rail to ground, or a fast op-amp on a
    breadboard can oscillate."""
    netlist, _ = built
    roles = {n.name: n.role for n in netlist.nets}
    caps = [
        set(c.pins.values())
        for c in netlist.components
        if c.kind.value == "capacitor"
    ]
    supplies = {
        net for c in netlist.components if c.kind.value == "opamp" for net in (c.pins.get("V+"), c.pins.get("V-"))
        if roles.get(net) in (NetRole.SUPPLY_POS, NetRole.SUPPLY_NEG)
    }
    for net in supplies:
        assert any(net in pins and any(roles.get(p) is NetRole.GROUND for p in pins) for pins in caps), (
            f"no decoupling cap on {net}"
        )


def test_unused_op_amp_sections_are_tied_off(built):
    """An op-amp section with floating inputs can oscillate and warm the chip."""
    netlist, layout = built
    for comp in netlist.components:
        if comp.kind.value != "opamp":
            continue
        letters = {name[-1] for name in DATASHEET.get(comp.package, {}).values() if name.startswith("OUT ")}
        for letter in letters:
            assert f"IN+{letter}" in comp.pins, f"{comp.ref} section {letter} has floating inputs"


def test_a_flat_axial_part_has_room_for_its_body(built):
    """A resistor or axial diode is about 6 mm long: lying flat, its leads
    need three holes between them. Closer, the board must say to stand it up."""
    _, layout = built
    for comp in layout.components:
        if comp.body.get("form") != "axial" or len(comp.pins) != 2:
            continue
        a, b = comp.pins
        if a.hole.row == b.hole.row and abs(a.hole.col - b.hole.col) < 3:
            assert comp.body.get("standing"), f"{comp.ref} is squeezed flat into {a.hole.key()}–{b.hole.key()}"
