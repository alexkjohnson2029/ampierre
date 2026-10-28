"""Netlists that list pins instead of SPICE lines, and parts AMPierre doesn't know."""

import pytest

from app.breadboard import verify
from app.main import PasteRequest, parse
from app.models import ComponentKind
from app.placer import _failed
from app.service import CustomPackage, PlaceRequest, lay_out
from app.spice import SpiceError, parse as read

# LTspice, View -> Export Netlist -> ExpressPCB, for a made-up circuit: an
# inverting amp on an op-amp symbol with no part number, a comparator from a
# library AMPierre doesn't carry, and a MOSFET it drives. Windows line ends,
# as LTspice writes them.
EXPRESSPCB = "\r\n".join(
    [
        '"ExpressPCB Netlist"',
        '"LTspice"',
        "1",
        "0",
        "0",
        '""',
        '""',
        '""',
        '"Part IDs Table"',
        '"V1" "12" ""',
        '"V2" "-12" ""',
        '"V3" "SINE(0 1 1k)" ""',
        '"R1" "10k" ""',
        '"R2" "47k" ""',
        '"C1" "2.2µ" ""',
        '"U1" "" ""',
        '"U2" "LT1011" ""',
        '"M1" "ZVN3306A" ""',
        '"R3" "1k" ""',
        "",
        '"Net Names Table"',
        '"VCC" 1',
        '"0" 2',
        '"VEE" 3',
        '"IN" 4',
        '"N001" 5',
        '"N002" 6',
        '"OUT" 7',
        '"GATE" 8',
        '"DRAIN" 9',
        "",
        '"Net Connections Table"',
        "1 1 1 0",
        "1 7 3 0",
        "1 8 3 0",
        "1 10 1 0",
        "2 1 2 0",
        "2 2 2 0",
        "2 3 2 0",
        "2 7 1 0",
        "2 8 6 0",
        "2 8 2 0",
        "2 9 3 0",
        "3 2 1 0",
        "3 7 4 0",
        "3 8 4 0",
        "4 3 1 0",
        "4 6 1 0",
        "5 6 2 0",
        "5 4 1 0",
        "6 4 2 0",
        "6 7 2 0",
        "6 5 1 0",
        "7 5 2 0",
        "7 7 5 0",
        "7 8 1 0",
        "8 8 7 0",
        "8 9 2 0",
        "9 9 1 0",
        "9 10 2 0",
        "",
    ]
)


def test_expresspcb_export_reads_every_part_and_source():
    nl = read(EXPRESSPCB)
    refs = {c.ref: c for c in nl.components}
    assert set(refs) == {"R1", "R2", "C1", "U1", "U2", "M1", "R3"}
    assert refs["R1"].pins == {"1": "N001", "2": "N002"}
    assert refs["C1"].value == "2.2µ"
    m = refs["M1"]
    assert m.kind is ComponentKind.NMOS and m.pins == {"D": "DRAIN", "G": "GATE", "S": "GND"}
    src = {s.ref: s for s in nl.sources}
    assert src["V1"].pos == "VCC" and src["V1"].neg == "GND" and src["V1"].value == "12V"
    assert src["V2"].pos == "VEE" and src["V2"].value == "-12V"
    assert src["V3"].kind == "signal"


def test_op_amp_symbol_with_no_part_number_is_an_op_amp():
    nl = read(EXPRESSPCB)
    u1 = next(c for c in nl.components if c.ref == "U1")
    assert u1.kind is ComponentKind.OPAMP and u1.value is None
    assert u1.pins == {"IN+": "GND", "IN-": "N002", "V+": "VCC", "V-": "VEE", "OUT": "OUT"}
    assert any(w.startswith("U1:") and "no part number" in w for w in nl.warnings)
    assert not any("__unnamed__" in w for w in nl.warnings)


def test_unknown_chip_keeps_its_pins_in_netlist_order_and_asks():
    nl = read(EXPRESSPCB)
    u2 = next(c for c in nl.components if c.ref == "U2")
    assert u2.kind is ComponentKind.IC and u2.value == "LT1011"
    # pin 8 is on no net in the export, so pins stop at 7
    assert list(u2.pins) == ["1", "2", "3", "4", "5", "6", "7"]
    assert u2.pins["7"] == "GATE"
    resp = parse(PasteRequest(text=EXPRESSPCB))
    assert ["U2"] in [q.refs for q in resp.questions]
    assert any("U2 (LT1011)" in w and "My own part" in w for w in nl.warnings)


def test_a_skipped_pin_keeps_the_ones_after_it_in_place():
    text = EXPRESSPCB.replace("2 8 2 0", "")  # U2 pin 2 on no net
    u2 = next(c for c in read(text).components if c.ref == "U2")
    assert u2.pins["2"] == "NC_U2_2" and u2.pins["3"] == "VCC"


@pytest.mark.parametrize("style", ["flow", "packed"])
def test_expresspcb_export_builds_a_board_with_the_users_own_pinout(style):
    nl = read(EXPRESSPCB)
    layout = lay_out(
        PlaceRequest(
            netlist=nl,
            style=style,
            custom_packages={
                # LT1011 in LTspice's order (IN+ IN- V+ V- BAL GND OUT) onto its DIP-8
                "U2": CustomPackage(
                    name="LT1011",
                    pin_count=8,
                    pin_map={"1": 2, "2": 3, "3": 8, "4": 4, "5": 5, "6": 1, "7": 7},
                )
            },
        )
    )
    assert not _failed(layout), layout.warnings
    assert verify(layout) == []


def test_windows_1252_micro_survives_a_wrong_decode():
    as_utf8_bytes_read_as_1252 = EXPRESSPCB.encode("utf-8").decode("cp1252")
    as_1252_bytes_read_as_utf8 = EXPRESSPCB.encode("cp1252").decode("utf-8", errors="replace")
    for text in (as_utf8_bytes_read_as_1252, as_1252_bytes_read_as_utf8):
        c1 = next(c for c in read(text).components if c.ref == "C1")
        assert c1.value == "2.2µ"


def test_broken_expresspcb_says_what_is_wrong():
    with pytest.raises(SpiceError, match="Part IDs"):
        read('"ExpressPCB Netlist"\n"LTspice"\n')
    with pytest.raises(SpiceError, match="isn't listed"):
        read('"ExpressPCB Netlist"\n"Part IDs Table"\n"R1" "1k" ""\n"Net Names Table"\n"A" 1\n"Net Connections Table"\n1 5 1 0\n')


def test_a_subckt_in_the_netlist_names_its_parts_pins():
    nl = read(
        """* my own comparator
XU1 IN REF VCC 0 OUT 0 MYCOMP
R1 OUT VCC 10k
.subckt MYCOMP INP INN VDD GND Q LATCH params: hyst=5m
R9 INP INN 1Meg
.ends MYCOMP
"""
    )
    u1 = nl.components[0]
    assert u1.kind is ComponentKind.IC and u1.value == "MYCOMP"
    assert u1.pins == {"INP": "IN", "INN": "REF", "VDD": "VCC", "GND": "GND", "Q": "OUT", "LATCH": "GND"}
    assert [c.ref for c in nl.components] == ["U1", "R1"]  # R9 is inside the subckt


def test_a_subckt_with_numbered_ports_stays_numbered():
    nl = read("* x\nXU1 a b c d e f FOO\n.subckt FOO 1 2 3 4 5 6\n.ends\n")
    assert list(nl.components[0].pins) == ["1", "2", "3", "4", "5", "6"]
