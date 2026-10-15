"""Tests for the parts that must never be wrong: connectivity and pinouts.

Run with:  python3 -m pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import breadboard as bb
from app import packages as pk
from app.models import Component, ComponentKind, Hole, Net, NetRole, Netlist, Wire
from app.placer import infer_role, place

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.json"))


# --- the breadboard itself -------------------------------------------------


def test_strip_is_one_node_per_half_and_column():
    assert bb.node_id("A", 7) == bb.node_id("E", 7)
    assert bb.node_id("F", 7) == bb.node_id("J", 7)
    assert bb.node_id("E", 7) != bb.node_id("F", 7), "the centre channel separates halves"
    assert bb.node_id("A", 7) != bb.node_id("A", 8), "columns are separate strips"


def test_a_rail_is_one_node_along_its_whole_length():
    assert bb.node_id(bb.RAIL_TOP_POS, 2) == bb.node_id(bb.RAIL_TOP_POS, 60)
    assert bb.node_id(bb.RAIL_TOP_POS, 2) != bb.node_id(bb.RAIL_TOP_NEG, 2)


def test_rail_holes_have_gaps_like_a_real_board():
    assert 7 not in bb.RAIL_COLUMNS
    assert 6 in bb.RAIL_COLUMNS


def test_occupying_a_hole_twice_is_an_error():
    board = bb.Breadboard()
    board.occupy("C", 10, "R1")
    with pytest.raises(ValueError):
        board.occupy("C", 10, "R2")


# --- package pinouts -------------------------------------------------------


def test_dual_opamp_supply_pins():
    assert pk.TL072.pin_map["V+"] == 8
    assert pk.TL072.pin_map["V-"] == 4


def test_quad_opamp_supply_pins_are_not_the_corners():
    assert pk.TL074.pin_map["V+"] == 4
    assert pk.TL074.pin_map["V-"] == 11


def test_to92_lead_order_differs_between_parts():
    assert pk.TO92_EBC_NPN.pin_map == {"E": 1, "B": 2, "C": 3}
    assert pk.TO92_CBE_NPN.pin_map == {"C": 1, "B": 2, "E": 3}


def test_pin_aliases_resolve():
    assert pk.resolve_pin(pk.TL072, "IN-") == 2  # bare name means channel A
    assert pk.resolve_pin(pk.TL072, "VCC") == 8
    assert pk.resolve_pin(pk.TL072, "3") == 3
    assert pk.resolve_pin(pk.TL072, "nonsense") is None


# --- net roles -------------------------------------------------------------


@pytest.mark.parametrize(
    "name,role",
    [
        ("GND", NetRole.GROUND),
        ("0", NetRole.GROUND),
        ("VCC", NetRole.SUPPLY_POS),
        ("+9V", NetRole.SUPPLY_POS),
        ("VEE", NetRole.SUPPLY_NEG),
        ("-12V", NetRole.SUPPLY_NEG),
        ("VOUT", NetRole.SIGNAL),
    ],
)
def test_supply_names_are_recognised(name, role):
    assert infer_role(name) == role


# --- placement -------------------------------------------------------------


def _netlist(path: Path) -> Netlist:
    return Netlist.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_places_with_no_errors(path):
    layout = place(_netlist(path))
    assert layout.warnings == [], layout.warnings
    assert len(layout.components) == len(_netlist(path).components)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_no_hole_is_used_twice(path):
    layout = place(_netlist(path))
    used = []
    for comp in layout.components:
        used += [(p.hole.row, p.hole.col) for p in comp.pins]
    for w in layout.wires:
        used += [(w.from_hole.row, w.from_hole.col), (w.to_hole.row, w.to_hole.col)]
    assert len(used) == len(set(used)), "two leads in one hole"


def test_dip_straddles_the_channel_with_pin_one_bottom_left():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "noninverting_amp")))
    ic = next(c for c in layout.components if c.body.get("form") == "dip")
    anchor = ic.body["anchor_col"]
    pin1 = next(p for p in ic.pins if p.number == 1)
    top = [p for p in ic.pins if p.hole.row == "F"]
    bottom = [p for p in ic.pins if p.hole.row == "E"]
    assert pin1.hole.row == "E" and pin1.hole.col == anchor
    assert all(p.number <= 4 for p in bottom)
    assert all(p.number >= 5 for p in top)
    highest = max(ic.pins, key=lambda p: p.number or 0)
    assert highest.hole.col == anchor, "the last pin sits directly above pin 1"


def test_decoupling_cap_goes_straight_across_the_rails():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "noninverting_amp")))
    c1 = next(c for c in layout.components if c.ref == "C1")
    assert {p.hole.row for p in c1.pins} == {bb.RAIL_TOP_POS, bb.RAIL_TOP_NEG}


def test_ground_rails_are_bonded_together():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "noninverting_amp")))
    bonds = [w for w in layout.wires if w.kind == "rail_bond"]
    assert len(bonds) == 1
    assert {bonds[0].from_hole.row, bonds[0].to_hole.row} == {bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG}


def test_polarised_part_records_which_lead_is_marked():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "common_emitter")))
    ce = next(c for c in layout.components if c.ref == "CE")
    assert ce.body["polarized"] is True
    assert "striped" in ce.orientation or "short lead" in ce.orientation


# --- the verifier has to actually catch mistakes ---------------------------


def _two_part_layout(second_hole: Hole):
    """R1 and R2 that are meant to share net N1."""
    nl = Netlist(
        title="t",
        nets=[Net(name="N1"), Net(name="N2"), Net(name="N3")],
        components=[
            Component(ref="R1", kind=ComponentKind.RESISTOR, pins={"1": "N1", "2": "N2"}),
            Component(ref="R2", kind=ComponentKind.RESISTOR, pins={"1": "N1", "2": "N3"}),
        ],
    )
    # packed style: it always gives the two parts separate strips joined by a
    # jumper, which is the shape these verifier tests need.
    return place(nl, style="packed")


def test_verifier_flags_a_net_left_split():
    layout = _two_part_layout(Hole(row="C", col=40))
    assert bb.verify(layout) == []
    layout.wires = []  # pull every jumper out
    problems = bb.verify(layout)
    assert any("split" in p for p in problems)


def test_verifier_flags_a_short():
    layout = _two_part_layout(Hole(row="C", col=40))
    r2 = next(c for c in layout.components if c.ref == "R2")
    r1 = next(c for c in layout.components if c.ref == "R1")
    # move a pin on N3 into the strip that already carries N2
    victim = r1.pins[1].hole
    other_row = next(r for r in bb.strip_rows(bb.half_of(victim.row)) if r != victim.row)
    r2.pins[1].hole = Hole(row=other_row, col=victim.col)
    assert any("short" in p for p in bb.verify(layout))


def test_verifier_flags_an_overloaded_strip():
    layout = _two_part_layout(Hole(row="C", col=40))
    col = layout.components[0].pins[0].hole.col
    for row in bb.TOP_ROWS:
        layout.wires.append(
            Wire(
                from_hole=Hole(row=row, col=col),
                to_hole=Hole(row=row, col=col + 20),
                net="N1",
            )
        )
    assert any("only has 5" in p for p in bb.verify(layout))


# --- the build timeline ----------------------------------------------------


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_part_and_every_jumper_gets_its_own_step(path):
    layout = place(_netlist(path))
    comp_steps = [s for s in layout.build_order if s.kind == "component"]
    wire_steps = [s for s in layout.build_order if s.kind == "wire"]
    assert {s.ref for s in comp_steps} == {c.ref for c in layout.components}
    assert sorted(s.wire for s in wire_steps) == list(range(len(layout.wires)))
    assert [s.index for s in layout.build_order] == list(range(len(layout.build_order)))


def test_parts_go_in_before_the_jumpers_that_reach_them():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "bridge_rectifier")))
    last_component = max(i for i, s in enumerate(layout.build_order) if s.kind == "component")
    first_wire = min(i for i, s in enumerate(layout.build_order) if s.kind == "wire")
    assert last_component < first_wire


def test_resistor_steps_tell_you_the_colour_bands():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "common_emitter")))
    step = next(s for s in layout.build_order if s.ref == "RE")
    assert "yellow" in (step.detail or "")


def test_rail_holes_are_named_in_plain_words():
    layout = place(_netlist(next(p for p in EXAMPLES if p.stem == "noninverting_amp")))
    rail_steps = [s for s in layout.build_order if s.kind == "wire" and "rail" in s.text]
    assert rail_steps, "this circuit has supply rails to reach"
    assert "RAIL_TOP" not in " ".join(s.text for s in rail_steps)


def test_a_quad_op_amp_is_turned_round_so_its_supply_pins_meet_their_rails():
    """A TL074/OP484 has V+ on pin 4 (bottom row with the notch left) and V-
    on pin 11 (top row). Turned round — notch right — V+ sits beside the top
    + rail and V- beside the bottom one."""
    nl = Netlist.model_validate(
        {
            "title": "quad",
            "nets": [
                {"name": "V+", "role": "supply_positive"},
                {"name": "V-", "role": "supply_negative"},
                {"name": "GND", "role": "ground"},
            ],
            "components": [
                {
                    "ref": "U1",
                    "kind": "opamp",
                    "package": "dip14_quad_opamp",
                    "pins": {"IN+A": "IN", "IN-A": "OUT", "OUT A": "OUT", "V+": "V+", "V-": "V-"},
                },
                {"ref": "R1", "kind": "resistor", "value": "10k", "pins": {"1": "OUT", "2": "GND"}},
                {"ref": "R2", "kind": "resistor", "value": "10k", "pins": {"1": "IN", "2": "GND"}},
            ],
        }
    )
    for style in ("packed", "flow"):
        layout = place(nl, style=style)
        chip = next(c for c in layout.components if c.ref == "U1")
        assert chip.body["notch"] == "right"
        pins = {p.number: p.hole for p in chip.pins}
        assert pins[4].row == "F" and pins[11].row == "E"
        assert pins[1].row == "F" and pins[1].col == chip.body["anchor_col"] + 6
        assert pins[14].col == pins[1].col, "pin 14 sits directly below pin 1"
        assert "RIGHT" in chip.orientation
        assert bb.verify(layout) == []
