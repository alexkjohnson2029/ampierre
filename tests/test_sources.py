"""Bench instruments: only a DC supply that powers the circuit gets a rail;
wave generators and input voltages clip onto the strip they drive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import breadboard as bb
from app.models import NetRole, Netlist
from app.placer import place

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.json"))


def _example(stem: str) -> Netlist:
    return Netlist.model_validate(json.loads(next(p for p in EXAMPLES if p.stem == stem).read_text(encoding="utf-8")))


def _follower(sources, nets=None) -> Netlist:
    """An op-amp follower: VIN in, VOUT out, powered from V+ / V-."""
    return Netlist.model_validate(
        {
            "title": "follower",
            "nets": nets or [],
            "components": [
                {
                    "ref": "U1",
                    "kind": "opamp",
                    "package": "dip8_dual_opamp",
                    "pins": {"IN+A": "VIN", "IN-A": "VOUT", "OUT A": "VOUT", "V+": "V+", "V-": "V-"},
                },
                {"ref": "R1", "kind": "resistor", "value": "10k", "pins": {"1": "VOUT", "2": "GND"}},
                {"ref": "R2", "kind": "resistor", "value": "100k", "pins": {"1": "VIN", "2": "GND"}},
            ],
            "sources": sources,
        }
    )


POWER = [
    {"ref": "V1", "kind": "dc", "pos": "V+", "neg": "GND", "value": "9V"},
    {"ref": "V2", "kind": "dc", "pos": "GND", "neg": "V-", "value": "9V"},
]


def _role(layout, net):
    return next(n.role for n in layout.nets if n.name == net)


def _rail_nets(layout):
    return {r: info["net"] for r, info in layout.rails.items() if info.get("in_use")}


def test_a_wave_generator_never_gets_a_rail_even_if_its_net_is_called_a_supply():
    nl = _follower(
        POWER + [{"ref": "V3", "kind": "signal", "pos": "VIN", "neg": "GND", "value": "1 kHz"}],
        nets=[{"name": "VIN", "role": "supply_positive"}],
    )
    layout = place(nl)
    assert _role(layout, "VIN") is NetRole.INPUT
    assert layout.rails[bb.RAIL_TOP_POS]["net"] == "V+"
    assert any("not put on a supply rail" in n for n in layout.notes)


def test_a_dc_input_called_vin_is_not_a_supply():
    nl = _follower(POWER + [{"ref": "V3", "kind": "dc", "pos": "VIN", "neg": "GND", "value": "2V"}])
    layout = place(nl)
    assert _role(layout, "VIN") is NetRole.INPUT
    lead = next(l for l in layout.leads if l.source == "V3" and l.terminal == "+")
    assert not bb.is_rail(lead.hole.row), "an input voltage goes into its strip"


def test_a_dc_source_feeding_an_op_amp_supply_pin_is_power_without_being_told():
    layout = place(_follower(POWER))
    assert layout.rails[bb.RAIL_TOP_POS]["net"] == "V+"
    assert layout.rails[bb.RAIL_BOT_POS]["net"] == "V-"


def test_a_negative_supply_drawn_ltspice_style_goes_on_the_bottom_rail():
    """LTspice users draw -4.5 V as a source with its + end on the net and a
    value of -4.5. That is the negative supply, not a second positive one."""
    nl = _follower(
        [
            {"ref": "V3", "kind": "dc", "pos": "V+", "neg": "GND", "value": "4.5"},
            {"ref": "V5", "kind": "dc", "pos": "V-", "neg": "GND", "value": "-4.5"},
        ]
    )
    layout = place(nl)
    assert _role(layout, "V-") is NetRole.SUPPLY_NEG
    minus = next(l for l in layout.leads if l.source == "V5" and l.net == "V-")
    assert minus.hole.row == bb.RAIL_BOT_POS and minus.terminal == "−"
    com = next(l for l in layout.leads if l.source == "V5" and l.terminal == "COM")
    assert com.net == "GND"
    assert bb.verify(layout) == []


@pytest.mark.parametrize("stem", [p.stem for p in EXAMPLES])
def test_every_lead_lands_on_its_own_net(stem):
    layout = place(_example(stem))
    assert layout.leads, "every example says where the instruments clip on"
    nodes = bb.solve_nodes(layout.wires)
    pin_node = {}
    for comp in layout.components:
        for p in comp.pins:
            pin_node.setdefault(p.net, nodes.find(bb.node_id(p.hole.row, p.hole.col)))
    for lead in layout.leads:
        node = nodes.find(bb.node_id(lead.hole.row, lead.hole.col))
        if lead.net in pin_node:
            assert node == pin_node[lead.net], (lead.source, lead.terminal, lead.net)
    assert bb.verify(layout) == []


def test_the_bridge_is_driven_by_a_floating_generator_across_its_inputs():
    layout = place(_example("bridge_rectifier"))
    gen = {l.terminal: l for l in layout.leads if l.instrument == "Wave generator"}
    assert gen["signal"].net == "AC1" and gen["ground"].net == "AC2"
    assert all(not bb.is_rail(l.hole.row) for l in gen.values())
    assert any("not on circuit ground" in n for n in layout.notes)
    assert layout.rails[bb.RAIL_TOP_POS]["net"] is None, "nothing powers a rectifier"


def test_hook_up_steps_come_after_the_continuity_check_and_power_comes_first():
    layout = place(_example("three_band_equalizer"))
    texts = [s.text for s in layout.build_order]
    check = next(i for i, t in enumerate(texts) if t.startswith("Check continuity"))
    leads = [s for s in layout.build_order if s.kind == "lead"]
    assert [s.index for s in leads] == sorted(s.index for s in leads)
    assert all(s.index > check for s in leads)
    assert "+4.5 V" in leads[0].text and "−4.5 V" in leads[1].text
    assert "wave generator" in leads[2].text
    assert texts[-1].startswith("Switch on the DC supply first")


# ---------------------------------------------------------------------------
# Supply terminals go on the rails
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, role",
    [
        ("VCC", NetRole.SUPPLY_POS), ("Vcc", NetRole.SUPPLY_POS), ("+VCC", NetRole.SUPPLY_POS),
        ("VCC1", NetRole.SUPPLY_POS), ("VCC_5V", NetRole.SUPPLY_POS), ("V+15", NetRole.SUPPLY_POS),
        ("VDDA", NetRole.SUPPLY_POS), ("+15V", NetRole.SUPPLY_POS),
        ("VEE", NetRole.SUPPLY_NEG), ("-VEE", NetRole.SUPPLY_NEG), ("VEE_15", NetRole.SUPPLY_NEG),
        ("-VCC", NetRole.SUPPLY_NEG), ("V-12", NetRole.SUPPLY_NEG), ("-15V", NetRole.SUPPLY_NEG),
        ("Vsaw", NetRole.SIGNAL), ("Vsum", NetRole.SIGNAL), ("VIN", NetRole.SIGNAL), ("N001", NetRole.SIGNAL),
    ],
)
def test_supply_names_with_signs_and_suffixes(name, role):
    from app.placer import infer_role

    assert infer_role(name) is role


def _leads(text):
    from app.breadboard import verify
    from app.spice import parse

    layout = place(parse(text))
    assert verify(layout) == []
    return {(l.terminal, l.net): l.hole.row for l in layout.leads}


def test_vcc_and_vee_sources_reach_the_rails_when_no_part_touches_ground():
    leads = _leads("* divider\nV1 VCC 0 12\nV2 0 VEE 12\nR1 VCC a 10k\nR2 a VEE 10k\n")
    assert leads[("+", "VCC")] == bb.RAIL_TOP_POS
    assert leads[("−", "VEE")] == bb.RAIL_BOT_POS
    assert leads[("COM", "GND")] in (bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG)


def test_a_vcc_label_with_no_source_still_gets_its_rail_and_a_supply():
    # a wave generator is listed, VCC and VEE are only labels
    leads = _leads("* buffer\nV3 in 0 SINE(0 1 1k)\nR1 in a 1k\nXU1 a out VCC VEE out TL072\n")
    assert leads[("+", "VCC")] == bb.RAIL_TOP_POS
    assert leads[("−", "VEE")] == bb.RAIL_BOT_POS
