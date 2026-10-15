"""Reading pasted SPICE netlists — no model, just the text."""

import pytest

from app.main import parse, PasteRequest
from app.models import ComponentKind
from app.placer import _failed, place
from app.spice import SpiceError, parse as read, spice_value

# What LTspice shows under View -> SPICE Netlist for a common-emitter stage.
LTSPICE_CE = r"""* C:\Users\aj\Documents\LTspice\common_emitter.asc
V1 VCC 0 9
V2 N001 0 SINE(0 10m 1k) AC 1
R1 VCC N002 47k
R2 N002 0 10k
R3 VCC N003 4.7k
R4 N004 0 1k
C1 N001 N002 10µ
C2 N004 0 100µ
Q1 N003 N002 N004 0 2N3904
.model NPN NPN
.model PNP PNP
.lib C:\Users\aj\AppData\Local\LTspice\lib\cmp\standard.bjt
.tran 5m
.backanno
.end
"""


def test_ltspice_netlist_reads_parts_sources_and_title():
    nl = read(LTSPICE_CE)
    assert nl.title == "common emitter"
    refs = {c.ref: c for c in nl.components}
    assert set(refs) == {"R1", "R2", "R3", "R4", "C1", "C2", "Q1"}
    q = refs["Q1"]
    assert q.kind is ComponentKind.NPN
    assert q.pins == {"C": "N003", "B": "N002", "E": "N004"}
    assert q.value == "2N3904"
    assert refs["R2"].pins == {"1": "N002", "2": "GND"}
    assert refs["C1"].value == "10µ"
    src = {s.ref: s for s in nl.sources}
    assert src["V1"].kind == "dc" and src["V1"].value == "9V"
    assert src["V2"].kind == "signal"
    assert not nl.warnings


def test_ltspice_netlist_builds_a_board():
    layout = place(read(LTSPICE_CE))
    assert not _failed(layout)


def test_opamp_subcircuit_is_in_plus_in_minus_v_plus_v_minus_out():
    nl = read(
        """* amp
XU1 IN FB VCC VEE OUT TL072
R1 FB 0 1k
R2 OUT FB 10k
V1 VCC 0 9
V2 VEE 0 -9
V3 IN 0 SINE(0 0.5 1k)
"""
    )
    u = next(c for c in nl.components if c.ref == "U1")
    assert u.kind is ComponentKind.OPAMP
    assert u.pins == {"IN+": "IN", "IN-": "FB", "V+": "VCC", "V-": "VEE", "OUT": "OUT"}
    resp = parse(PasteRequest(text="* amp\nXU1 IN FB VCC VEE OUT TL072\nR1 FB 0 1k\n"))
    assert [q.refs for q in resp.questions] == [["U1"]]


def test_transistor_type_from_model_line_or_part_number():
    nl = read("t\nQ1 c b e MYPART\nQ2 c b e 2N3906\nQ3 c b e ODD\nM1 d g s s BS250\n.model MYPART PNP\n")
    kinds = {c.ref: c.kind for c in nl.components}
    assert kinds == {
        "Q1": ComponentKind.PNP,
        "Q2": ComponentKind.PNP,
        "Q3": ComponentKind.NPN,
        "M1": ComponentKind.PMOS,
    }
    assert any("Q3" in w and "assumed NPN" in w for w in nl.warnings)


def test_simulation_only_lines_are_skipped_and_said_so():
    nl = read("t\nR1 a 0 1k\nI1 a 0 1m\nE1 b 0 a 0 10\n.subckt foo 1 2\nR9 1 2 5\n.ends\n")
    assert [c.ref for c in nl.components] == ["R1"]
    assert any("I1" in w for w in nl.warnings)
    assert any("E1" in w for w in nl.warnings)


def test_continuation_lines_and_inline_comments():
    nl = read("t\nR1 a\n+ 0 1k ; pull-down\n")
    assert nl.components[0].pins == {"1": "a", "2": "GND"}
    assert nl.components[0].value == "1k"


def test_first_line_element_is_not_eaten_as_title():
    nl = read("R1 a 0 1k\nC1 a 0 100n\n")
    assert [c.ref for c in nl.components] == ["R1", "C1"]


def test_editor_spice_export_round_trips_a_pot():
    nl = read("* x\nXRV1 a w RV1_NC3 potentiometer R=10k\n")
    pot = nl.components[0]
    assert pot.ref == "RV1" and pot.kind is ComponentKind.POTENTIOMETER
    assert pot.value == "10k"
    assert pot.pins == {"1": "a", "W": "w", "3": "RV1_NC3"}


def test_json_netlist_is_accepted_too():
    nl = read('{"title": "j", "components": [{"ref": "R1", "kind": "resistor", "pins": {"1": "a", "2": "GND"}}]}')
    assert nl.title == "j"


@pytest.mark.parametrize("text", ["", "   ", "* only a title\n.tran 1m\n"])
def test_nothing_to_place_is_an_error(text):
    with pytest.raises(SpiceError):
        read(text)


@pytest.mark.parametrize(
    "spice, app",
    [("1Meg", "1M"), ("4.7MEG", "4.7M"), ("1M", "1m"), ("10k", "10k"), ("100nF", "100nF"), ("4k7", "4k7"), ("2.2", "2.2")],
)
def test_spice_suffixes(spice, app):
    assert spice_value(spice) == app
