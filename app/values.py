"""Reading component values off a schematic label, and turning them into the
markings a real part would carry.

A schematic says "10k". The resistor in the drawer says brown-black-orange-gold.
Showing the bands is what lets you find the part in a bin without a meter.
"""

from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_SI = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "meg": 1e6,
    "MEG": 1e6,
    "G": 1e9,
    "R": 1.0,
    "r": 1.0,
}

_VALUE = re.compile(
    r"^\s*([0-9]*\.?[0-9]+)\s*(meg|MEG|[pnuµμmkKMGRr])?\s*([a-zA-ZΩ]*)\s*$"
)
#: "4k7", "1R0", "2u2" — the European style where the prefix is the decimal point.
_EMBEDDED = re.compile(r"^\s*([0-9]+)(meg|MEG|[pnuµμmkKMGRr])([0-9]+)\s*$")


def parse_value(text: str | None) -> float | None:
    """'10k' -> 10000.0, '4u7' -> 4.7e-6, '100nF' -> 1e-7. None if unreadable."""
    if not text:
        return None
    text = text.strip().replace("Ω", "").replace("ohm", "").replace("Ohm", "")

    m = _EMBEDDED.match(text)
    if m:
        whole, prefix, frac = m.groups()
        return float(f"{whole}.{frac}") * _SI[prefix]

    m = _VALUE.match(text)
    if not m:
        return None
    number, prefix, _unit = m.groups()
    return float(number) * (_SI[prefix] if prefix else 1.0)


def format_ohms(ohms: float) -> str:
    for limit, suffix, div in ((1e6, "M", 1e6), (1e3, "k", 1e3), (0, "", 1)):
        if ohms >= limit:
            v = ohms / div
            return f"{v:g}{suffix}Ω"
    return f"{ohms:g}Ω"


def format_farads(f: float) -> str:
    for limit, suffix, div in ((1e-3, "mF", 1e-3), (1e-6, "µF", 1e-6), (1e-9, "nF", 1e-9), (0, "pF", 1e-12)):
        if f >= limit:
            return f"{f / div:g}{suffix}"
    return f"{f / 1e-12:g}pF"


# ---------------------------------------------------------------------------
# Resistor colour bands
# ---------------------------------------------------------------------------

BAND_COLORS = [
    "#1a1a1a",  # 0 black
    "#6b4423",  # 1 brown
    "#c62828",  # 2 red
    "#ef6c00",  # 3 orange
    "#f9d423",  # 4 yellow
    "#2e7d32",  # 5 green
    "#1565c0",  # 6 blue
    "#7b1fa2",  # 7 violet
    "#9e9e9e",  # 8 grey
    "#fafafa",  # 9 white
]
BAND_NAMES = [
    "black",
    "brown",
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "violet",
    "grey",
    "white",
]
GOLD = "#c9a227"
SILVER = "#c0c0c0"


def resistor_bands(ohms: float, tolerance: float = 5.0) -> dict | None:
    """Four-band code for a resistance. Returns colours plus their names.

    Two significant digits and a power-of-ten multiplier, which is what a
    standard 5% part carries. Values that don't fit (0 Ω, 1.23 kΩ) come back
    as None and the part is drawn plain.
    """
    if ohms is None or ohms <= 0:
        return None

    exponent = math.floor(math.log10(ohms)) - 1
    significand = round(ohms / (10**exponent))
    if significand >= 100:  # rounding pushed it over, e.g. 99.6 -> 100
        significand //= 10
        exponent += 1
    if significand < 10:
        return None
    if abs(significand * 10**exponent - ohms) > ohms * 0.01:
        return None  # needs three digits; not a standard 4-band part
    if not -2 <= exponent <= 9:
        return None

    d1, d2 = divmod(significand, 10)
    multiplier_color = GOLD if exponent == -1 else SILVER if exponent == -2 else BAND_COLORS[exponent]
    multiplier_name = (
        "gold" if exponent == -1 else "silver" if exponent == -2 else BAND_NAMES[exponent]
    )
    tol_color, tol_name = (GOLD, "gold") if tolerance == 5.0 else (SILVER, "silver")

    return {
        "colors": [BAND_COLORS[d1], BAND_COLORS[d2], multiplier_color, tol_color],
        "names": [BAND_NAMES[d1], BAND_NAMES[d2], multiplier_name, tol_name],
        "text": f"{BAND_NAMES[d1]} · {BAND_NAMES[d2]} · {multiplier_name} · {tol_name} ({tolerance:g}%)",
    }


# ---------------------------------------------------------------------------
# Capacitor markings
# ---------------------------------------------------------------------------


def ceramic_code(farads: float) -> str | None:
    """The three-digit code stamped on a ceramic disc: 100 nF -> '104'."""
    if not farads or farads <= 0:
        return None
    pf = farads * 1e12
    if pf < 10:
        return f"{pf:g}"
    exponent = int(math.floor(math.log10(pf))) - 1
    significand = round(pf / (10**exponent))
    if significand >= 100:
        significand //= 10
        exponent += 1
    if not 0 <= exponent <= 9 or significand < 10:
        return None
    return f"{significand}{exponent}"


def resistance_code(ohms: float) -> str | None:
    """The three-digit code printed on a trimmer: 10 kΩ -> '103'."""
    if not ohms or ohms < 10:
        return None
    exponent = int(math.floor(math.log10(ohms))) - 1
    significand = round(ohms / (10**exponent))
    if significand >= 100:
        significand //= 10
        exponent += 1
    return f"{significand}{exponent}"


def capacitor_style(farads: float | None, polarized: bool) -> str:
    """Which body to draw: a disc, a film box, or an electrolytic can.

    Roughly how the parts bin sorts itself — small values are ceramic discs,
    mid values film boxes, anything big and polarised is a can.
    """
    if polarized:
        return "electrolytic"  # only a polarised part gets drawn as a can
    if farads is None:
        return "ceramic"
    if farads >= 1e-7:
        return "film"  # a 1µF non-polarised part is a film box, not an electrolytic
    return "ceramic"


def describe(kind: str, value: str | None, polarized: bool = False) -> dict:
    """Everything the renderer and the hover card need about a value."""
    magnitude = parse_value(value)
    out: dict = {"raw": value, "magnitude": magnitude}
    if kind == "resistor" and magnitude:
        out["pretty"] = format_ohms(magnitude)
        out["bands"] = resistor_bands(magnitude)
    elif kind in ("capacitor", "polarized_capacitor") and magnitude:
        out["pretty"] = format_farads(magnitude)
        out["cap_style"] = capacitor_style(magnitude, polarized)
        out["code"] = ceramic_code(magnitude)
    elif kind == "potentiometer" and magnitude:
        out["pretty"] = format_ohms(magnitude)
        out["code"] = resistance_code(magnitude)
    elif kind == "inductor" and magnitude:
        out["pretty"] = f"{magnitude * 1e3:g}mH" if magnitude < 1 else f"{magnitude:g}H"
    if kind in ("capacitor", "polarized_capacitor") and "cap_style" not in out:
        out["cap_style"] = capacitor_style(magnitude, polarized)
    return out
