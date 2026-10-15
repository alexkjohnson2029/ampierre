"""The three-band equalizer: potentiometers, op-amp sections sharing chips,
the hand-arranged board, and the bench instruments clipped onto it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import breadboard as bb
from app import packages as pk
from app import quality
from app import values as val
from app.gates import pack_sections
from app.handlaid import HandPlacer, PlanError, parse_hole
from app.models import Hole, Netlist, NetRole
from app.placer import _failed, is_unused, place

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "three_band_equalizer.json"


def _eq(**changes) -> Netlist:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data.update(changes)
    return Netlist.model_validate(data)


def _pins(layout, ref):
    comp = next(c for c in layout.components if c.ref == ref)
    return {p.name: p for p in comp.pins}


# --- the circuit itself ------------------------------------------------------


def test_the_netlist_matches_the_schematic():
    nl = _eq()
    refs = {c.ref for c in nl.components}
    # every part on AJ's schematic, with the 1-ohm pot models as pots and the
    # three idle bridge diodes gone (see the netlist's warnings for why)
    expected = {f"R{i}" for i in (1, 2, 5, 6, 7, 8, 11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28)}
    expected |= {f"C{i}" for i in range(1, 7)} | {"D2", "D5", "IC1", "IC2"}
    expected |= {"RV1", "RV2", "RV3", "RV4"}
    assert refs == expected
    for gone in ("R3", "R4", "R9", "R10", "R13", "R14", "R17", "R18", "D1", "D3", "D4"):
        assert gone not in refs
    by = {c.ref: c for c in nl.components}
    assert by["R7"].value == "5.1k" and by["R20"].value == "300k"
    assert by["C4"].kind.value == "polarized_capacitor" and by["C4"].pins["+"] == "Compare"
    assert by["D2"].pins == {"A": "DC", "K": "Compare"}
    assert by["IC2"].pins["IN+D"] == "Compare" and by["IC2"].pins["IN-D"] == "+3.375V"


def test_every_op_amp_runs_off_the_4v5_rails():
    nl = _eq()
    chips = [c for c in nl.components if c.kind.value == "opamp"]
    assert all(c.pins["V+"] == "V+" and c.pins["V-"] == "V-" for c in chips)
    sections = [k for c in chips for k in c.pins if k.startswith("OUT")]
    assert len(sections) == 8, "U1-U8"


def test_the_supplies_are_plus_and_minus_4v5_and_the_audio_is_an_input():
    layout = place(_eq())
    roles = {n.name: n for n in layout.nets}
    assert roles["V+"].role is NetRole.SUPPLY_POS and roles["V+"].voltage == "+4.5 V"
    assert roles["V-"].role is NetRole.SUPPLY_NEG and roles["V-"].voltage == "−4.5 V"
    assert roles["In"].role is NetRole.INPUT
    assert roles["+3.375V"].role is NetRole.SIGNAL, "a divider tap is not a supply"


# --- potentiometers -----------------------------------------------------------


def test_pot_value_and_marking():
    info = val.describe("potentiometer", "10k")
    assert info["pretty"] == "10kΩ" and info["code"] == "103"


@pytest.mark.parametrize("name,number", [("1", 1), ("W", 2), ("wiper", 2), ("2", 2), ("3", 3), ("CW", 3)])
def test_pot_pin_names(name, number):
    assert pk.resolve_pin(pk.TRIMPOT, name) == number


def test_a_pot_used_as_a_variable_resistor_keeps_its_spare_end_on_its_own_strip():
    layout = place(_eq())
    for ref in ("RV1", "RV2", "RV3", "RV4"):
        pins = _pins(layout, ref)
        assert set(pins) == {"1", "W", "3"}, "all three legs go in the board"
        spare = [p for p in pins.values() if is_unused(p.net)]
        assert len(spare) == 1
        cols = sorted(p.hole.col for p in pins.values())
        assert cols == list(range(cols[0], cols[0] + 3)), "legs side by side"
        assert len({p.hole.row for p in pins.values()}) == 1
        # nothing else lands in the spare leg's strip
        hole = spare[0].hole
        others = [
            q
            for c in layout.components
            for q in c.pins
            if q is not spare[0] and q.hole.col == hole.col and bb.half_of(q.hole.row) == bb.half_of(hole.row)
        ]
        assert others == []
    assert bb.verify(layout) == []


def test_pots_are_asked_about_like_other_parts_with_choices():
    from app.main import questions_for

    q = next(q for q in questions_for(_eq()) if q.kind == "potentiometer")
    assert sorted(q.refs) == ["RV1", "RV2", "RV3", "RV4"]
    assert {o.id for o in q.options} >= {"trimpot_inline", "panel_pot"}


# --- the hand-arranged board -------------------------------------------------


@pytest.mark.parametrize("style", ["flow", "flow-compact"])
def test_the_example_uses_its_hand_layout_and_it_is_spotless(style):
    layout = place(_eq(), style=style)
    assert any("Laid out by hand" in n for n in layout.notes)
    assert layout.warnings == []
    assert bb.verify(layout) == []
    q = quality.measure(layout)
    assert q.diagonal == q.crossings == q.over_part == 0, q


def test_the_quads_are_turned_round_so_their_supply_pins_meet_the_rails():
    layout = place(_eq())
    for ref in ("IC1", "IC2"):
        chip = next(c for c in layout.components if c.ref == ref)
        pins = {p.number: p.hole for p in chip.pins}
        assert chip.body["notch"] == "right"
        assert pins[4].row == "F" and pins[11].row == "E"


def test_ground_rails_are_joined():
    layout = place(_eq())
    nodes = bb.solve_nodes(layout.wires)
    assert nodes.find(bb.RAIL_TOP_NEG) == nodes.find(bb.RAIL_BOT_NEG)


def test_hole_names():
    assert parse_hole("G12") == Hole(row="G", col=12)
    assert parse_hole("T+3") == Hole(row=bb.RAIL_TOP_POS, col=3)
    assert parse_hole("b−7") == Hole(row=bb.RAIL_BOT_NEG, col=7)
    with pytest.raises(ValueError):
        parse_hole("K4")


def test_a_plan_that_does_not_fit_is_refused_not_half_built():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["layout"]["parts"]["R6"] = {"1": "H22", "2": "G18"}  # leads in two rows
    with pytest.raises(PlanError):
        HandPlacer(Netlist.model_validate(data)).run()
    data["layout"]["parts"]["R6"] = {"1": "G22", "2": "G17"}  # on top of R7's lead
    with pytest.raises(PlanError):
        HandPlacer(Netlist.model_validate(data)).run()


def test_a_broken_plan_falls_back_to_the_automatic_layout():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["layout"]["parts"]["R6"] = {"1": "G22", "2": "G17"}
    layout = place(Netlist.model_validate(data))
    assert not any("Laid out by hand" in n for n in layout.notes)
    assert not _failed(layout)
    assert bb.verify(layout) == []


def test_picking_a_different_chip_drops_the_plan_rather_than_miswiring_it():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for comp in data["components"]:
        if comp["ref"] == "IC1":
            comp["package"] = "dip8_dual_opamp"  # sections C and D don't exist on it
    layout = place(Netlist.model_validate(data))
    assert not any("Laid out by hand" in n for n in layout.notes)


def test_without_the_plan_the_automatic_layout_still_proves_correct():
    layout = place(_eq(layout=None))
    assert not _failed(layout), layout.warnings
    assert bb.verify(layout) == []


# --- op-amps drawn one at a time ---------------------------------------------


def _eight_single_op_amps(package="dip14_quad_opamp", vneg="V-") -> Netlist:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data.pop("layout")
    comps = [c for c in data["components"] if c["kind"] != "opamp"]
    wiring = {
        "U2": ("In", "AmpFB", "AmpIn"), "U3": ("HP", "HPbuf", "HPbuf"),
        "U4": ("BP", "BPbuf", "BPbuf"), "U5": ("LP", "LPbuf", "LPbuf"),
        "U6": ("Sum", "OutFB", "Out"), "U1": ("Out", "Speaker", "Speaker"),
        "U8": ("Out", "DC", "DC"), "U7": ("Compare", "+3.375V", "LED"),
    }
    for ref, (inp, inn, out) in wiring.items():
        comps.append(
            {
                "ref": ref, "kind": "opamp", "value": "OP484", "package": package,
                "pins": {"IN+": inp, "IN-": inn, "OUT": out, "V+": "V+", "V-": vneg if ref != "U7" else "V-"},
            }
        )
    data["components"] = comps
    return Netlist.model_validate(data)


def test_eight_op_amps_on_quads_become_two_chips():
    packed = pack_sections(_eight_single_op_amps())
    chips = [c for c in packed.components if c.kind.value == "opamp"]
    assert [c.ref for c in chips] == ["U2/U3/U4/U5", "U6/U1/U8/U7"]
    first = chips[0]
    assert first.pins["IN+A"] == "In" and first.pins["OUT A"] == "AmpIn"
    assert first.pins["IN+D"] == "LP" and first.pins["V-"] == "V-"
    assert "Section A = U2" in first.notes


def test_eight_op_amps_on_duals_become_four_chips():
    packed = pack_sections(_eight_single_op_amps("dip8_dual_opamp"))
    assert len([c for c in packed.components if c.kind.value == "opamp"]) == 4


def test_op_amps_on_different_supplies_are_not_put_in_one_chip():
    packed = pack_sections(_eight_single_op_amps(vneg="GND"))
    refs = [c.ref for c in packed.components if c.kind.value == "opamp"]
    assert "U7" in refs, "U7 is on V-, the rest on GND: it gets a chip of its own"


def test_a_netlist_that_already_names_sections_is_left_alone():
    nl = _eq()
    assert pack_sections(nl).components == nl.components


def test_eight_op_amps_still_make_a_correct_board():
    layout = place(_eight_single_op_amps())
    chips = [c for c in layout.components if c.body.get("form") == "dip"]
    assert len(chips) == 2
    assert not _failed(layout)
    assert bb.verify(layout) == []
