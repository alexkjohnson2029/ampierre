"""The schematic-shaped layout: it has to look like the circuit, not just work."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import breadboard as bb
from app.flow import FlowPlacer
from app.models import Netlist
from app import quality
from app.placer import place

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.json"))
STYLES = ("flow", "flow-compact")


def _netlist(stem: str) -> Netlist:
    path = next(p for p in EXAMPLES if p.stem == stem)
    return Netlist.model_validate(json.loads(path.read_text()))


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_lays_out_schematic_shaped(path, style):
    layout = place(Netlist.model_validate(json.loads(path.read_text())), style=style)
    assert layout.warnings == [], layout.warnings
    assert not any("packed tightly" in n for n in layout.notes), "fell back to packing"
    assert bb.verify(layout) == []


def test_supply_on_the_left_ground_on_the_right():
    fp = FlowPlacer(_netlist("pn2222_bias"))
    fp.run()
    cols = {net: col for net, (_, col) in fp.home.items()}
    assert cols["VCC"] == min(cols.values())
    assert cols["GND"] == max(cols.values())


def test_transistor_legs_sit_in_neighbouring_strips_in_order():
    layout = place(_netlist("pn2222_bias"))
    q1 = next(c for c in layout.components if c.ref == "Q1")
    cols = [p.hole.col for p in q1.pins]
    assert [p.name for p in q1.pins] == ["E", "B", "C"]
    assert cols == list(range(cols[0], cols[0] + 3))
    assert len({p.hole.row for p in q1.pins}) == 1


def test_the_bias_network_has_no_signal_jumpers_along_the_board():
    """In the photo the resistors land straight in the transistor's strips.
    The only jumpers should be power, ground, and the short drops across the
    channel to the lower resistors."""
    layout = place(_netlist("pn2222_bias"))
    for w in layout.wires:
        if w.kind in ("signal",):
            pytest.fail(f"unexpected jumper along the board on net {w.net}")


def test_supply_end_above_the_channel_ground_end_below():
    layout = place(_netlist("pn2222_bias"))

    def strip_half(comp):
        pin = next(p for p in comp.pins if not bb.is_rail(p.hole.row))
        return bb.half_of(pin.hole.row)

    half = {c.ref: strip_half(c) for c in layout.components}
    assert half["R1"] == half["RC"] == "top"  # Vcc side
    assert half["R2"] == half["RE"] == "bottom"  # ground side


def test_compact_is_narrower_than_spacious():
    def width(style):
        layout = place(_netlist("common_emitter"), style=style)
        cols = [p.hole.col for c in layout.components for p in c.pins]
        return max(cols) - min(cols)

    assert width("flow-compact") < width("flow")


@pytest.mark.parametrize("style", STYLES)
def test_diode_band_is_drawn_at_the_cathode_wherever_it_landed(style):
    layout = place(_netlist("bridge_rectifier"), style=style)
    for comp in layout.components:
        if comp.kind.value != "diode":
            continue
        k = next(p for p in comp.pins if p.name == "K")
        a = next(p for p in comp.pins if p.name == "A")
        if k.hole.col == a.hole.col:  # standing in a column
            k_above = bb.ROW_ORDER.index(k.hole.row) < bb.ROW_ORDER.index(a.hole.row)
            expected = "top" if k_above else "bottom"
        else:
            expected = "right" if k.hole.col > a.hole.col else "left"
        assert comp.body["marked_end"] == expected, comp.ref


def test_packed_style_is_still_available():
    layout = place(_netlist("pn2222_bias"), style="packed")
    assert layout.warnings == []
    assert not any("follow the schematic" in n for n in layout.notes)


# --- compact mode keeps simple circuits above the channel -------------------


def _halves(layout):
    return {bb.half_of(p.hole.row) for c in layout.components for p in c.pins} - {"rail"}


def test_compact_puts_a_circuit_without_an_ic_on_the_top_half():
    layout = place(_netlist("pn2222_bias"), style="flow-compact")
    assert _halves(layout) == {"top"}
    assert bb.verify(layout) == []


def test_compact_spreads_out_when_the_top_half_would_need_untidy_wires():
    """The bridge's output node meets five parts and both inputs need a hole
    for the wave generator. Five rows can't hold that without a diagonal, so
    it gets the bottom half too."""
    layout = place(_netlist("bridge_rectifier"), style="flow-compact")
    assert "bottom" in _halves(layout)
    q = quality.measure(layout)
    assert q.diagonal == q.crossings == q.over_part == 0, q


def test_compact_still_uses_both_halves_for_an_op_amp():
    layout = place(_netlist("noninverting_amp"), style="flow-compact")
    assert _halves(layout) == {"top", "bottom"}


def test_compact_uses_both_halves_when_one_would_need_extra_jumpers():
    """Seven parts meet at Q1's three legs in the common-emitter stage — five
    rows can't hold them without parts sliding off their nets."""
    layout = place(_netlist("common_emitter"), style="flow-compact")
    assert "bottom" in _halves(layout)


def test_ground_rails_are_only_bonded_when_both_are_used():
    top_only = place(_netlist("pn2222_bias"), style="flow-compact")
    assert not any(w.kind == "rail_bond" for w in top_only.wires)
    both = place(_netlist("noninverting_amp"), style="flow-compact")
    assert any(w.kind == "rail_bond" for w in both.wires)


def test_the_bias_network_in_compact_is_just_two_wires():
    """Supply in, ground out — every resistor lands straight in Q1's strips."""
    layout = place(_netlist("pn2222_bias"), style="flow-compact")
    assert sorted(w.kind for w in layout.wires) == ["rail", "rail"]


# --- parts plugged straight into the rails ----------------------------------


def _rail_pin(comp):
    return next((p for p in comp.pins if bb.is_rail(p.hole.row)), None)


def test_bias_resistors_plug_straight_into_the_rails():
    """Like the lab build: R1 and Rc hang from Vcc, R2 and Re stand on ground."""
    layout = place(_netlist("pn2222_bias"))
    by_ref = {c.ref: c for c in layout.components}
    assert _rail_pin(by_ref["R1"]).hole.row == bb.RAIL_TOP_POS
    assert _rail_pin(by_ref["RC"]).hole.row == bb.RAIL_TOP_POS
    assert _rail_pin(by_ref["R2"]).hole.row == bb.RAIL_BOT_NEG
    assert _rail_pin(by_ref["RE"]).hole.row == bb.RAIL_BOT_NEG
    assert not any(w.kind == "rail" for w in layout.wires), "no jumpers to the rails needed"


def test_a_rail_mounted_part_stands_straight_and_long_enough_to_fit():
    layout = place(_netlist("pn2222_bias"))
    for comp in layout.components:
        if comp.body.get("half") != "railmount":
            continue
        a, b = comp.pins
        assert a.hole.col == b.hole.col, f"{comp.ref} isn't standing straight"
        assert abs(bb.ROW_POS[a.hole.row] - bb.ROW_POS[b.hole.row]) >= 3.5, comp.ref


def test_nothing_else_lands_where_a_rail_mounted_part_stands():
    layout = place(_netlist("bridge_rectifier"))
    for comp in layout.components:
        if comp.body.get("half") != "railmount":
            continue
        a, b = comp.pins
        covered = {(r, a.hole.col) for r in bb.rows_between(a.hole.row, b.hole.row)}
        used = {(p.hole.row, p.hole.col) for c in layout.components for p in c.pins}
        used |= {(h.row, h.col) for w in layout.wires for h in (w.from_hole, w.to_hole)}
        assert not covered & used, f"something is under {comp.ref}"


def test_rail_mounting_avoids_the_rail_gaps():
    layout = place(_netlist("bridge_rectifier"))
    for comp in layout.components:
        pin = _rail_pin(comp)
        if pin is not None:
            assert pin.hole.col in bb.RAIL_COLUMNS


# --- clean wiring ------------------------------------------------------------


@pytest.mark.parametrize("stem", ["pn2222_bias", "bridge_rectifier", "noninverting_amp"])
@pytest.mark.parametrize("style", STYLES)
def test_simple_circuits_have_only_straight_wires_that_never_cross(stem, style):
    q = quality.measure(place(_netlist(stem), style=style))
    assert q.diagonal == 0, q
    assert q.crossings == 0, q
    assert q.over_part == 0, q


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
@pytest.mark.parametrize("style", STYLES)
def test_no_wire_ever_runs_over_a_part(path, style):
    layout = place(Netlist.model_validate(json.loads(path.read_text())), style=style)
    assert quality.measure(layout).over_part == 0


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
@pytest.mark.parametrize("style", STYLES)
def test_busy_circuits_still_need_at_most_one_untidy_wire(path, style):
    q = quality.measure(place(Netlist.model_validate(json.loads(path.read_text())), style=style))
    assert q.diagonal + q.crossings <= 1, q


def test_jumpers_along_the_board_lie_flat_in_one_row():
    layout = place(_netlist("three_band_equalizer"))
    flat = [w for w in layout.wires if w.kind == "signal" and w.from_hole.row == w.to_hole.row]
    signal = [w for w in layout.wires if w.kind == "signal"]
    assert len(flat) >= len(signal) - 1


def test_two_jumpers_never_share_a_row_segment():
    layout = place(_netlist("three_band_equalizer"))
    spans: dict[str, list[tuple[int, int]]] = {}
    for w in layout.wires:
        if w.from_hole.row == w.to_hole.row and not bb.is_rail(w.from_hole.row):
            spans.setdefault(w.from_hole.row, []).append(
                tuple(sorted((w.from_hole.col, w.to_hole.col)))
            )
    for row, segs in spans.items():
        segs.sort()
        for (a1, b1), (a2, b2) in zip(segs, segs[1:]):
            assert b1 < a2, f"two jumpers overlap in row {row}"


# --- spare chip pins ----------------------------------------------------------


def test_every_pin_of_a_chip_is_placed_even_the_unused_ones():
    layout = place(_netlist("noninverting_amp"))
    u1 = next(c for c in layout.components if c.ref == "U1")
    assert sorted(p.number for p in u1.pins) == list(range(1, 9))


def test_landing_in_an_unused_pins_strip_is_caught_as_a_short():
    from app.models import Hole

    layout = place(_netlist("noninverting_amp"), style="packed")
    u1 = next(c for c in layout.components if c.ref == "U1")
    spare = next(p for p in u1.pins if p.net.endswith("(not connected)"))
    r2 = next(c for c in layout.components if c.ref == "R2")
    other_row = next(
        r for r in bb.strip_rows(bb.half_of(spare.hole.row)) if r != spare.hole.row
    )
    r2.pins[0].hole = Hole(row=other_row, col=spare.hole.col)
    assert any("short" in problem for problem in bb.verify(layout))
