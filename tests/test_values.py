"""Value parsing, colour codes, part grouping and user-defined pinouts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import packages as pk
from app import values as val
from app.main import questions_for
from app.models import ComponentKind, Netlist

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("10k", 10_000),
        ("4.7k", 4_700),
        ("4k7", 4_700),
        ("470", 470),
        ("2.2M", 2_200_000),
        ("100nF", 1e-7),
        ("4u7", 4.7e-6),
        ("0.1uF", 1e-7),
        ("1Meg", 1e6),
        ("47R", 47),
    ],
)
def test_value_parsing(text, expected):
    assert val.parse_value(text) == pytest.approx(expected)


def test_unreadable_values_are_none_not_guesses():
    assert val.parse_value("about 10k ish") is None
    assert val.parse_value("") is None
    assert val.parse_value(None) is None


@pytest.mark.parametrize(
    "ohms,names",
    [
        (10_000, ["brown", "black", "orange", "gold"]),
        (4_700, ["yellow", "violet", "red", "gold"]),
        (470, ["yellow", "violet", "brown", "gold"]),
        (1_000_000, ["brown", "black", "green", "gold"]),
        (2.2, ["red", "red", "gold", "gold"]),
    ],
)
def test_resistor_colour_code(ohms, names):
    assert val.resistor_bands(ohms)["names"] == names


def test_three_digit_values_get_no_four_band_code():
    assert val.resistor_bands(1_230) is None  # needs 3 significant digits


def test_ceramic_code():
    assert val.ceramic_code(1e-7) == "104"  # 100nF
    assert val.ceramic_code(2.2e-8) == "223"


def test_capacitor_body_follows_the_value():
    assert val.capacitor_style(1e-9, False) == "ceramic"
    assert val.capacitor_style(1e-7, False) == "film"
    assert val.capacitor_style(1e-6, False) == "film"  # non-polarised is never a can
    assert val.capacitor_style(1e-4, True) == "electrolytic"


# --- part picker -----------------------------------------------------------


def _example(name: str) -> Netlist:
    return Netlist.model_validate(json.loads((EXAMPLES / f"{name}.json").read_text()))


def test_identical_parts_are_one_question():
    questions = questions_for(_example("bridge_rectifier"))
    diode_q = next(q for q in questions if q.kind == "diode")
    assert diode_q.refs == ["D1", "D2", "D3", "D4"]
    assert len(questions) == 1, "the LED has only one footprint, so nothing to ask"


def test_question_suggests_the_part_named_in_the_value():
    questions = questions_for(_example("noninverting_amp"))
    assert questions[0].suggested == pk.TL072.id
    quads = questions_for(_example("three_band_equalizer"))
    assert next(q for q in quads if q.kind == "opamp").suggested == pk.TL074.id


def test_op484_is_in_the_library():
    labels = " ".join(p.label for p in pk.options_for(ComponentKind.OPAMP))
    assert "OP484" in labels
    quad = next(p for p in pk.ALL_PACKAGES if "OP484" in p.label)
    assert quad.pin_map["V+"] == 4 and quad.pin_map["V-"] == 11


def test_negative_regulator_is_not_a_mirror_of_the_positive_one():
    assert pk.REG_78XX.pin_map == {"IN": 1, "GND": 2, "OUT": 3}
    assert pk.REG_79XX.pin_map == {"GND": 1, "IN": 2, "OUT": 3}


# --- user-defined pinouts --------------------------------------------------


def test_custom_package_round_trip():
    pkg = pk.make_custom(
        {"name": "OP484", "form": "dip", "pin_count": 14, "pin_map": {"OUT A": 1, "V-": 11}},
        ComponentKind.OPAMP,
    )
    assert pkg.span == 7
    assert pkg.pin_map["V-"] == 11
    assert pkg.pin_names[1] == "OUT A"
    assert "your own" in pkg.label


@pytest.mark.parametrize(
    "spec,message",
    [
        ({"name": "X", "form": "dip", "pin_count": 7}, "even pin count"),
        ({"name": "X", "form": "dip", "pin_count": 8, "pin_map": {"V+": 99}}, "outside"),
        ({"name": "X", "form": "sot23"}, "unknown package form"),
    ],
)
def test_custom_package_rejects_impossible_pinouts(spec, message):
    with pytest.raises(ValueError, match=message):
        pk.make_custom(spec, ComponentKind.IC)
