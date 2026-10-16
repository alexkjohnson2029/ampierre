"""Physical package library.

The schematic tells you a component is "an op-amp". It does not tell you which
pin is pin 3. That gap is why the app stops and asks. Everything the placer
needs to turn a logical pin name into a hole lives here.

Pin numbering conventions used throughout:

  DIP, viewed from above, notch/dot facing LEFT:
      pins 1..n/2    bottom row, left to right   (breadboard row E)
      pins n/2+1..n  top row,    right to left   (breadboard row F)
      so the highest-numbered pin sits directly above pin 1.

  TO-92, viewed with the FLAT FACE toward you and leads pointing down:
      pins 1, 2, 3 left to right.

  Trimmer pot, viewed from above with the adjust screw up and the pins
  toward you: pins 1, W (wiper, 2), 3 left to right.

Pinouts below are the common ones, but silkscreens lie and second sources
differ: check the datasheet before you power anything up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ComponentKind


@dataclass(frozen=True)
class Package:
    id: str
    label: str  # what the picker shows
    kinds: tuple[ComponentKind, ...]
    form: str  # "dip" | "to92" | "to220" | "pot" | "axial" | "radial"
    pin_count: int
    #: logical pin name -> physical pin number. Empty for 2-lead parts, whose
    #: logical names ("1"/"2", "A"/"K", "+"/"-") map positionally.
    pin_map: dict[str, int] = field(default_factory=dict)
    #: physical pin number -> datasheet name, for the hover card.
    pin_names: dict[int, str] = field(default_factory=dict)
    span: int = 2  # columns occupied
    polarized: bool = False
    marker: str = ""  # orientation cue shown on the board and on hover
    note: str = ""

    @property
    def straddles_channel(self) -> bool:
        return self.form == "dip"


def _dip(
    pid: str,
    label: str,
    kinds: tuple[ComponentKind, ...],
    pin_count: int,
    names: dict[int, str],
    note: str = "",
) -> Package:
    """Build a DIP package; pin_map is the inverse of names."""
    pin_map = {v: k for k, v in names.items()}
    return Package(
        id=pid,
        label=label,
        kinds=kinds,
        form="dip",
        pin_count=pin_count,
        pin_map=pin_map,
        pin_names=names,
        span=pin_count // 2,
        marker="notch/dot at pin 1 end (LEFT)",
        note=note,
    )


# --- Op-amps ---------------------------------------------------------------

LM741 = _dip(
    "dip8_lm741",
    "LM741 / TL071 / TL081 / OPA134 — single op-amp, DIP-8",
    (ComponentKind.OPAMP,),
    8,
    {
        1: "OFFSET NULL",
        2: "IN-",
        3: "IN+",
        4: "V-",
        5: "OFFSET NULL",
        6: "OUT",
        7: "V+",
        8: "NC",
    },
    note="Single amplifier. Pin 8 is not connected.",
)

TL072 = _dip(
    "dip8_dual_opamp",
    "TL072 / TL082 / LM358 / NE5532 / OP284 / OPA2134 — dual op-amp, DIP-8",
    (ComponentKind.OPAMP,),
    8,
    {
        1: "OUT A",
        2: "IN-A",
        3: "IN+A",
        4: "V-",
        5: "IN+B",
        6: "IN-B",
        7: "OUT B",
        8: "V+",
    },
    note="Two amplifiers share pins 4 and 8. Unused section: tie as a follower, "
    "don't leave its inputs floating.",
)

TL074 = _dip(
    "dip14_quad_opamp",
    "TL074 / LM324 / OP484 / OPA4134 — quad op-amp, DIP-14",
    (ComponentKind.OPAMP,),
    14,
    {
        1: "OUT A",
        2: "IN-A",
        3: "IN+A",
        4: "V+",
        5: "IN+B",
        6: "IN-B",
        7: "OUT B",
        8: "OUT C",
        9: "IN-C",
        10: "IN+C",
        11: "V-",
        12: "IN+D",
        13: "IN-D",
        14: "OUT D",
    },
    note="Supply pins are 4 (V+) and 11 (V-) — not the corners. Easy to miswire.",
)

NE555 = _dip(
    "dip8_ne555",
    "NE555 / LM555 — timer, DIP-8",
    (ComponentKind.IC,),
    8,
    {
        1: "GND",
        2: "TRIG",
        3: "OUT",
        4: "RESET",
        5: "CTRL",
        6: "THRES",
        7: "DISCH",
        8: "VCC",
    },
    note="Tie RESET (4) to VCC if you aren't using it, and 10nF from CTRL (5) to "
    "ground keeps the timing quiet.",
)

HC00 = _dip(
    "dip14_74hc00",
    "74HC00 / 74LS00 — quad 2-input NAND, DIP-14",
    (ComponentKind.IC,),
    14,
    {
        1: "1A",
        2: "1B",
        3: "1Y",
        4: "2A",
        5: "2B",
        6: "2Y",
        7: "GND",
        8: "3Y",
        9: "3A",
        10: "3B",
        11: "4Y",
        12: "4A",
        13: "4B",
        14: "VCC",
    },
    note="Power is pin 14 (VCC) and pin 7 (GND) — diagonal corners, not the ends.",
)

HC08 = _dip(
    "dip14_74hc08",
    "74HC08 / 74LS08 — quad 2-input AND, DIP-14",
    (ComponentKind.IC,),
    14,
    {
        1: "1A",
        2: "1B",
        3: "1Y",
        4: "2A",
        5: "2B",
        6: "2Y",
        7: "GND",
        8: "3Y",
        9: "3A",
        10: "3B",
        11: "4Y",
        12: "4A",
        13: "4B",
        14: "VCC",
    },
    note="Same footprint as the 74HC00; power on 14 and 7.",
)

HC04 = _dip(
    "dip14_74hc04",
    "74HC04 / 74LS04 — hex inverter, DIP-14",
    (ComponentKind.IC,),
    14,
    {
        1: "1A",
        2: "1Y",
        3: "2A",
        4: "2Y",
        5: "3A",
        6: "3Y",
        7: "GND",
        8: "4Y",
        9: "4A",
        10: "5Y",
        11: "5A",
        12: "6Y",
        13: "6A",
        14: "VCC",
    },
    note="Input/output alternate along the package; power on 14 and 7.",
)

# Generic DIPs are for a chip the library doesn't know, read from a netlist as
# numbered pins ("1".."8"). They are never offered for an op-amp: its pins are
# named (IN+, OUT, V+), and a package that only knows numbers can't place one.
GENERIC_DIP8 = _dip(
    "dip8_generic",
    "Generic DIP-8 (pins by number)",
    (ComponentKind.IC,),
    8,
    {i: f"Pin {i}" for i in range(1, 9)},
)

GENERIC_DIP14 = _dip(
    "dip14_generic",
    "Generic DIP-14 (pins by number)",
    (ComponentKind.IC,),
    14,
    {i: f"Pin {i}" for i in range(1, 15)},
)

GENERIC_DIP16 = _dip(
    "dip16_generic",
    "Generic DIP-16 (pins by number)",
    (ComponentKind.IC,),
    16,
    {i: f"Pin {i}" for i in range(1, 17)},
)


# --- Three-lead parts, TO-92 ----------------------------------------------


def _to92(pid: str, label: str, kinds, order: str, note: str = "") -> Package:
    """order is the left-to-right lead order with the FLAT FACE toward you."""
    names = {i + 1: ch for i, ch in enumerate(order)}
    long_name = {"B": "Base", "C": "Collector", "E": "Emitter", "G": "Gate", "D": "Drain", "S": "Source"}
    return Package(
        id=pid,
        label=label,
        kinds=tuple(kinds),
        form="to92",
        pin_count=3,
        pin_map={ch: i + 1 for i, ch in enumerate(order)},
        pin_names={i + 1: long_name.get(ch, ch) for i, ch in enumerate(order)},
        span=3,
        marker="FLAT face toward you (half-circle bulges AWAY), leads down",
        note=note or f"Flat face toward you, leads down: {' – '.join(order)} left to right.",
    )


TO92_EBC_NPN = _to92(
    "to92_ebc_npn",
    "2N3904 / PN2222 — NPN, TO-92 (E–B–C)",
    [ComponentKind.NPN],
    "EBC",
    note="Flat face toward you, leads down: E – B – C left to right. Careful with "
    "2N2222s: the PN2222A is E–B–C, but onsemi's P2N2222A is C–B–E.",
)
TO92_CBE_NPN = _to92(
    "to92_cbe_npn", "BC547 / BC337 — NPN, TO-92 (C–B–E)", [ComponentKind.NPN], "CBE"
)
TO92_BCE_NPN = _to92(
    "to92_bce_npn", "Generic NPN, TO-92 (B–C–E)", [ComponentKind.NPN], "BCE"
)
TO92_EBC_PNP = _to92(
    "to92_ebc_pnp", "2N3906 — PNP, TO-92 (E–B–C)", [ComponentKind.PNP], "EBC"
)
TO92_CBE_PNP = _to92(
    "to92_cbe_pnp", "BC557 — PNP, TO-92 (C–B–E)", [ComponentKind.PNP], "CBE"
)
TO92_SGD_NMOS = _to92(
    "to92_sgd_nmos", "2N7000 — N-MOSFET, TO-92 (S–G–D)", [ComponentKind.NMOS], "SGD"
)
TO92_DGS_NMOS = _to92(
    "to92_dgs_nmos",
    "BS170 — N-MOSFET, TO-92 (D–G–S)",
    [ComponentKind.NMOS],
    "DGS",
    note="Flat face toward you, leads down: D – G – S left to right — the mirror "
    "image of a 2N7000, so the two don't swap in place.",
)
TO92_GDS_NMOS = _to92(
    "to92_gds_nmos", "Generic N-MOSFET, TO-92 (G–D–S)", [ComponentKind.NMOS], "GDS"
)
TO92_SGD_PMOS = _to92(
    "to92_sgd_pmos", "Generic P-MOSFET, TO-92 (S–G–D)", [ComponentKind.PMOS], "SGD"
)
TO92_GDS_PMOS = _to92(
    "to92_gds_pmos", "Generic P-MOSFET, TO-92 (G–D–S)", [ComponentKind.PMOS], "GDS"
)

def _to220(pid: str, label: str, kinds, order: list[str], names: dict, note: str) -> Package:
    return Package(
        id=pid,
        label=label,
        kinds=tuple(kinds),
        form="to220",
        pin_count=3,
        pin_map={name: i + 1 for i, name in enumerate(order)},
        pin_names=names,
        span=3,
        marker="metal tab AWAY from you, leads down",
        note=note,
    )


REG_78XX = _to220(
    "to220_78xx",
    "LM7805 / 78xx — positive regulator, TO-220 (IN–GND–OUT)",
    [ComponentKind.REGULATOR],
    ["IN", "GND", "OUT"],
    {1: "IN", 2: "GND", 3: "OUT"},
    "Tab is tied to GND on a 78xx. Needs a cap on the input and the output to "
    "stay stable.",
)

REG_79XX = _to220(
    "to220_79xx",
    "LM7905 / 79xx — negative regulator, TO-220 (GND–IN–OUT)",
    [ComponentKind.REGULATOR],
    ["GND", "IN", "OUT"],
    {1: "GND", 2: "IN", 3: "OUT"},
    "Not a mirror of the 78xx — pins 1 and 2 are swapped, and the tab is the "
    "input. This catches people out constantly.",
)

LM317 = _to220(
    "to220_lm317",
    "LM317 — adjustable regulator, TO-220 (ADJ–OUT–IN)",
    [ComponentKind.REGULATOR],
    ["ADJ", "OUT", "IN"],
    {1: "ADJ", 2: "OUT", 3: "IN"},
    "Tab is the output. Output sits 1.25 V above ADJ.",
)

TO220_BCE = Package(
    id="to220_bce",
    label="TO-220 power transistor (B–C–E, tab = collector)",
    kinds=(ComponentKind.NPN, ComponentKind.PNP),
    form="to92",  # drawn like a 3-lead part, wider body
    pin_count=3,
    pin_map={"B": 1, "C": 2, "E": 3},
    pin_names={1: "Base", 2: "Collector", 3: "Emitter"},
    span=3,
    marker="metal tab facing AWAY from you, leads down",
    note="Tab is usually electrically the collector — keep it off other leads.",
)


# --- Potentiometers -----------------------------------------------------------

TRIMPOT = Package(
    id="trimpot_inline",
    label="Trimmer potentiometer — 3 pins in a row, 0.1\" apart (Bourns 3362P style)",
    kinds=(ComponentKind.POTENTIOMETER,),
    form="pot",
    pin_count=3,
    pin_map={"1": 1, "W": 2, "3": 3},
    pin_names={1: "End 1 (CCW)", 2: "Wiper", 3: "End 3 (CW)"},
    span=3,
    marker="adjust screw up, pins toward you: 1 – W – 3 left to right",
    note="Clockwise moves the wiper toward pin 3, so the resistance between pin 1 "
    "and the wiper goes up. Most trimmers mark the CW end; check yours.",
)

PANEL_POT = Package(
    id="panel_pot",
    label="Panel potentiometer with knob — 3 legs in a row (bend legs to 0.1\")",
    kinds=(ComponentKind.POTENTIOMETER,),
    form="pot",
    pin_count=3,
    pin_map={"1": 1, "W": 2, "3": 3},
    pin_names={1: "End 1 (CCW)", 2: "Wiper", 3: "End 3 (CW)"},
    span=3,
    marker="shaft up, legs toward you: 1 – W – 3 left to right",
    note="Panel pots have legs 5 mm apart and won't sit flush in a breadboard. "
    "Bend the legs or solder short wires on. Clockwise moves the wiper toward pin 3.",
)


# --- Two-lead parts --------------------------------------------------------

AXIAL_RESISTOR = Package(
    id="axial_resistor",
    label="Axial resistor (1/4 W)",
    kinds=(ComponentKind.RESISTOR,),
    form="axial",
    pin_count=2,
    span=4,
    marker="not polarized — either way round",
)

AXIAL_INDUCTOR = Package(
    id="axial_inductor",
    label="Axial inductor",
    kinds=(ComponentKind.INDUCTOR,),
    form="axial",
    pin_count=2,
    span=4,
    marker="not polarized — either way round",
)

CERAMIC_CAP = Package(
    id="radial_ceramic",
    label="Ceramic / film capacitor (radial, non-polarized)",
    kinds=(ComponentKind.CAPACITOR,),
    form="radial",
    pin_count=2,
    span=3,
    marker="not polarized — either way round",
)

ELECTROLYTIC_CAP = Package(
    id="radial_electrolytic",
    label="Electrolytic capacitor (radial, POLARIZED)",
    kinds=(ComponentKind.POLARIZED_CAPACITOR, ComponentKind.CAPACITOR),
    form="radial",
    pin_count=2,
    span=3,
    polarized=True,
    marker="stripe = negative lead (shorter lead)",
    note="Backwards electrolytics vent. The striped side goes to the more "
    "negative net.",
)

AXIAL_DIODE = Package(
    id="axial_diode",
    label="Axial diode (1N4148 / 1N400x)",
    kinds=(ComponentKind.DIODE,),
    form="axial",
    pin_count=2,
    span=4,
    polarized=True,
    marker="band = cathode (K)",
)

DIODE_1N4148 = Package(
    id="axial_1n4148",
    label="1N4148 — small-signal diode (axial)",
    kinds=(ComponentKind.DIODE,),
    form="axial",
    pin_count=2,
    span=4,
    polarized=True,
    marker="band = cathode (K)",
    note="Glass body, fast, 200mA. Not for rectifying mains-side current.",
)

DIODE_SCHOTTKY = Package(
    id="axial_schottky",
    label="1N5819 — Schottky diode (axial)",
    kinds=(ComponentKind.DIODE,),
    form="axial",
    pin_count=2,
    span=4,
    polarized=True,
    marker="band = cathode (K)",
    note="Low forward drop (~0.3 V), which matters in a rectifier.",
)

DIODE_ZENER = Package(
    id="axial_zener",
    label="1N47xx — Zener diode (axial)",
    kinds=(ComponentKind.DIODE,),
    form="axial",
    pin_count=2,
    span=4,
    polarized=True,
    marker="band = cathode (K)",
    note="Reverse-biased in use: the banded end goes to the MORE positive node.",
)

LED_5MM = Package(
    id="led_5mm",
    label="5 mm LED",
    kinds=(ComponentKind.LED,),
    form="radial",
    pin_count=2,
    span=3,
    polarized=True,
    marker="flat edge / short lead = cathode (K)",
)


ALL_PACKAGES: list[Package] = [
    TL072,
    LM741,
    TL074,
    NE555,
    HC00,
    HC08,
    HC04,
    GENERIC_DIP8,
    GENERIC_DIP14,
    GENERIC_DIP16,
    TO92_EBC_NPN,
    TO92_CBE_NPN,
    TO92_BCE_NPN,
    TO92_EBC_PNP,
    TO92_CBE_PNP,
    TO92_SGD_NMOS,
    TO92_DGS_NMOS,
    TO92_GDS_NMOS,
    TO92_SGD_PMOS,
    TO92_GDS_PMOS,
    TO220_BCE,
    TRIMPOT,
    PANEL_POT,
    REG_78XX,
    REG_79XX,
    LM317,
    AXIAL_RESISTOR,
    AXIAL_INDUCTOR,
    CERAMIC_CAP,
    ELECTROLYTIC_CAP,
    AXIAL_DIODE,
    DIODE_1N4148,
    DIODE_SCHOTTKY,
    DIODE_ZENER,
    LED_5MM,
]

BY_ID: dict[str, Package] = {p.id: p for p in ALL_PACKAGES}

#: Used when the user never picks. Chosen to be the least surprising option.
DEFAULT_FOR_KIND: dict[ComponentKind, str] = {
    ComponentKind.RESISTOR: AXIAL_RESISTOR.id,
    ComponentKind.INDUCTOR: AXIAL_INDUCTOR.id,
    ComponentKind.POTENTIOMETER: TRIMPOT.id,
    ComponentKind.CAPACITOR: CERAMIC_CAP.id,
    ComponentKind.POLARIZED_CAPACITOR: ELECTROLYTIC_CAP.id,
    ComponentKind.DIODE: AXIAL_DIODE.id,
    ComponentKind.LED: LED_5MM.id,
    ComponentKind.OPAMP: TL072.id,
    ComponentKind.IC: GENERIC_DIP8.id,
    ComponentKind.NPN: TO92_EBC_NPN.id,
    ComponentKind.PNP: TO92_EBC_PNP.id,
    ComponentKind.NMOS: TO92_SGD_NMOS.id,
    ComponentKind.PMOS: TO92_SGD_PMOS.id,
    ComponentKind.REGULATOR: REG_78XX.id,
}


def options_for(kind: ComponentKind) -> list[Package]:
    """Packages offered in the picker for a given component kind."""
    return [p for p in ALL_PACKAGES if kind in p.kinds]


def part_numbers(pkg: Package) -> list[str]:
    """The part numbers a package's label names: "1N5819 — Schottky…" -> ["1N5819"],
    "TL074 / LM324 / OP484 — quad…" -> ["TL074", "LM324", "OP484"]. Empty for a
    generic package ("Axial diode (…)", "Generic DIP-8")."""
    head = re.split(r"\s+[—(]", pkg.label, maxsplit=1)[0]
    names = [n.strip() for n in head.split("/")]
    return [n for n in names if n and re.search(r"\d", n) and " " not in n]


def part_name(value: str | None, pkg: Package) -> str | None:
    """What to call a part once its package is picked.

    The schematic's value says what was simulated; the package is what's in
    your hand. They agree when the package lists the value ("OP484" on the
    TL074 / LM324 / OP484 quad) or names no part at all (a generic DIP). When
    they disagree — a 1N4148 on the schematic, a 1N5819 picked — the board
    should say 1N5819, or the pick looks like it did nothing.
    """
    names = part_numbers(pkg)
    if not names:
        return value
    if value:
        flat = lambda s: re.sub(r"[\s\-]", "", s).upper()  # noqa: E731
        v = flat(value)
        if any(flat(n) in v or v in flat(n) for n in names) or v in flat(pkg.label):
            return value
    return names[0]


def fits(pkg: Package, kind: ComponentKind) -> bool:
    """Can this package hold a part of this kind?"""
    return kind in pkg.kinds


def get(package_id: str | None, kind: ComponentKind) -> Package:
    """The picked package, or the default for the kind when nothing (or a
    package for a different kind of part) was picked."""
    pkg = BY_ID.get(package_id or "")
    if pkg is not None and fits(pkg, kind):
        return pkg
    return BY_ID[DEFAULT_FOR_KIND[kind]]


def resolve_pin(pkg: Package, logical: str) -> int | None:
    """Map a schematic pin name onto a physical pin number.

    Accepts the datasheet name ('IN-A'), a bare number ('3'), or a common
    alias ('IN-' on a dual op-amp means channel A).
    """
    if logical in pkg.pin_map:
        return pkg.pin_map[logical]
    if logical.isdigit() and 1 <= int(logical) <= pkg.pin_count:
        return int(logical)

    alias = {
        "IN-": ["IN-A", "IN-"],
        "IN+": ["IN+A", "IN+"],
        "OUT": ["OUT A", "OUT"],
        "V+": ["V+", "VCC", "VDD"],
        "V-": ["V-", "VEE", "VSS"],
        "VCC": ["V+"],
        "VEE": ["V-"],
        "VDD": ["V+"],
        "VSS": ["V-"],
        "-": ["IN-A", "IN-"],
        "+": ["IN+A", "IN+"],
        "GND": ["V-", "GND"],
        # potentiometers
        "WIPER": ["W"],
        "WIP": ["W"],
        "CCW": ["1"],
        "CW": ["3"],
        "A": ["1"],
        "B": ["3"],
    }
    for candidate in alias.get(logical.upper(), []):
        if candidate in pkg.pin_map:
            return pkg.pin_map[candidate]
    return None


# ---------------------------------------------------------------------------
# User-defined parts
# ---------------------------------------------------------------------------

CUSTOM_FORMS = {
    "dip": "DIP (straddles the centre channel, notch to the left)",
    "to92": "TO-92 (3 leads, flat face toward you)",
    "to220": "TO-220 (3 leads, metal tab away from you)",
    "axial": "Axial (2 leads, body lying flat)",
    "radial": "Radial (2 leads, body standing up)",
}


def make_custom(spec: dict, kind: ComponentKind) -> Package:
    """Build a Package from what the user typed in the custom-part form.

    spec: {"name": "OP484", "form": "dip", "pin_count": 14,
           "pin_map": {"IN+A": 3, ...}, "pin_names": {"3": "+IN A", ...}}

    Nothing here is validated against a datasheet — it is the user's own
    claim about their part, so it is labelled as such everywhere it appears.
    """
    form = spec.get("form", "dip")
    if form not in CUSTOM_FORMS:
        raise ValueError(f"unknown package form '{form}'")

    pin_count = int(spec.get("pin_count") or (3 if form in ("to92", "to220") else 2))
    if form == "dip":
        if pin_count % 2 or not 4 <= pin_count <= 40:
            raise ValueError("a DIP needs an even pin count between 4 and 40")
    pin_map = {str(k): int(v) for k, v in (spec.get("pin_map") or {}).items()}
    for name, number in pin_map.items():
        if not 1 <= number <= pin_count:
            raise ValueError(f"pin '{name}' is {number}, outside 1–{pin_count}")

    pin_names = {int(k): str(v) for k, v in (spec.get("pin_names") or {}).items()}
    for name, number in pin_map.items():
        pin_names.setdefault(number, name)
    if form == "dip":
        for n in range(1, pin_count + 1):
            pin_names.setdefault(n, f"Pin {n}")

    name = (spec.get("name") or "Custom part").strip()[:40]
    marker = {
        "dip": "notch/dot at pin 1 end (LEFT)",
        "to92": "FLAT face toward you (half-circle bulges AWAY), leads down",
        "to220": "metal tab AWAY from you, leads down",
    }.get(form, "")

    return Package(
        id=f"custom::{name}",
        label=f"{name} (your own pinout)",
        kinds=tuple(ComponentKind),
        form=form,
        pin_count=pin_count,
        pin_map=pin_map,
        pin_names=pin_names,
        span=pin_count // 2 if form == "dip" else (3 if pin_count == 3 else 4),
        polarized=bool(spec.get("polarized")),
        marker=marker,
        note="Pinout entered by you — worth checking against the datasheet once.",
    )
