"""A netlist drawn in the schematic editor goes straight to the part
questions and the placer — no model involved."""

import pytest
from fastapi import HTTPException

from app.main import netlist_route
from app.models import Netlist
from app.placer import place

# What static/schematic.js makes of its sample drawing (sampleDoc()).
DRAWN = {
    "title": "Non-inverting amplifier",
    "components": [
        {
            "ref": "U1",
            "kind": "opamp",
            "value": "TL072",
            "pins": {"IN-": "N001", "IN+": "VIN", "OUT": "VOUT", "V+": "V+", "V-": "V-"},
        },
        {"ref": "R2", "kind": "resistor", "value": "10k", "pins": {"1": "VOUT", "2": "N001"}},
        {"ref": "R1", "kind": "resistor", "value": "1k", "pins": {"1": "N001", "2": "GND"}},
    ],
    "nets": [{"name": "GND", "role": "ground", "voltage": "0 V"}],
    "sources": [
        {"ref": "V1", "kind": "dc", "pos": "V+", "neg": "GND", "value": "9V", "purpose": "power"},
        {"ref": "V2", "kind": "dc", "pos": "V-", "neg": "GND", "value": "-9V", "purpose": "power"},
        {
            "ref": "V3",
            "kind": "signal",
            "pos": "VIN",
            "neg": "GND",
            "value": "SINE(0 0.5 1k)",
            "purpose": "input",
        },
    ],
    "warnings": [],
}


def test_drawn_netlist_asks_about_the_op_amp():
    resp = netlist_route(Netlist.model_validate(DRAWN))
    assert [q.refs for q in resp.questions] == [["U1"]]
    assert resp.questions[0].suggested  # TL072 in the value picks a package


def test_drawn_netlist_places_cleanly():
    nl = Netlist.model_validate(DRAWN)
    nl.components[0].package = netlist_route(nl).questions[0].suggested
    layout = place(nl)
    assert not [w for w in layout.warnings if "not placed" in w or "short" in w]
    assert {c.ref for c in layout.components} == {"U1", "R1", "R2"}


def test_empty_drawing_is_refused():
    with pytest.raises(HTTPException):
        netlist_route(Netlist(title="nothing"))
