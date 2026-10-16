"""A package that can't hold the part it was picked for is refused up front."""

from __future__ import annotations

import pytest

from app import packages as pk
from app.models import Component, ComponentKind, Net, Netlist, NetRole
from app.service import PlaceRequest, ServiceError, lay_out, questions_for


def _follower(package: str | None = None) -> Netlist:
    return Netlist(
        title="follower",
        nets=[
            Net(name="V+", role=NetRole.SUPPLY_POS),
            Net(name="V-", role=NetRole.SUPPLY_NEG),
            Net(name="GND", role=NetRole.GROUND),
        ],
        components=[
            Component(
                ref="U1",
                kind=ComponentKind.OPAMP,
                value="opamp",
                package=package,
                pins={"IN+": "IN", "IN-": "OUT", "OUT": "OUT", "V+": "V+", "V-": "V-"},
            ),
            Component(ref="R1", kind=ComponentKind.RESISTOR, value="10k", pins={"1": "IN", "2": "GND"}),
        ],
    )


def test_generic_dips_are_not_offered_for_op_amps():
    """An op-amp's pins are named (IN+, OUT, V+); a numbers-only DIP can't place
    any of them, so picking one used to give a chip with nothing wired to it."""
    ids = {p.id for p in pk.options_for(ComponentKind.OPAMP)}
    assert not ids & {"dip8_generic", "dip14_generic", "dip16_generic"}
    assert "dip8_generic" in {p.id for p in pk.options_for(ComponentKind.IC)}


def test_an_op_amp_on_a_generic_dip_is_refused_with_a_reason():
    with pytest.raises(ServiceError, match="can't hold one"):
        lay_out(PlaceRequest(netlist=_follower(), packages={"U1": "dip8_generic"}))


def test_a_saved_generic_pick_falls_back_to_a_real_op_amp():
    """A netlist saved before the change still lays out, on the default dual."""
    nl = _follower("dip8_generic")
    (q,) = [q for q in questions_for(nl) if q.kind == "opamp"]
    assert q.suggested == pk.TL072.id
    layout = lay_out(PlaceRequest(netlist=nl))
    u1 = next(c for c in layout.components if c.ref == "U1")
    assert u1.package == pk.TL072.id
    assert {p.name for p in u1.pins} >= {"IN+", "IN-", "OUT", "V+", "V-"}
    assert layout.warnings == []


def test_pins_missing_from_the_package_are_named():
    nl = _follower()
    nl.components[0] = nl.components[0].model_copy(update={"kind": ComponentKind.IC})
    with pytest.raises(ServiceError, match="no pin called IN\\+, IN-, OUT, V\\+, V-"):
        lay_out(PlaceRequest(netlist=nl, packages={"U1": "dip8_generic"}))


def test_bs170_is_drain_gate_source():
    """The BS170 is the 2N7000's mirror image in a TO-92: D–G–S, not S–G–D."""
    assert "BS170" not in pk.TO92_SGD_NMOS.label
    bs170 = next(p for p in pk.options_for(ComponentKind.NMOS) if "BS170" in p.label)
    assert bs170.pin_map == {"D": 1, "G": 2, "S": 3}
