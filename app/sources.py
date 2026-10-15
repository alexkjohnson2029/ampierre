"""Bench instruments: which nets get a supply rail, and where the leads go.

A breadboard's + rails mean one thing to the person building: "the bench DC
supply clips on here". So only a DC source that *powers* the circuit — an
op-amp's supply, a transistor stage's Vcc — earns a rail. Everything else that
a schematic draws as a voltage source is an input the circuit acts on: a wave
generator, a second DC channel used as a test voltage, the AC into a
rectifier. Those connect to the strip of the net they drive, and the board
shows the exact hole for each lead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import breadboard as bb
from .models import ExternalLead, Hole, NetRole, Source

#: Pin names that draw power. A DC source wired to one of these is a supply.
POWER_PINS = {"V+", "V-", "VCC", "VEE", "VDD", "VSS", "VS+", "VS-"}
POWER_PIN_KINDS = {"opamp", "ic", "regulator"}

_SUPPLY_NAME = re.compile(r"^(VCC|VDD|VEE|VSS|V\+|V-|VS\+|VS-|[+-]?\d+(\.\d+)?V)$")
_INPUT_NAME = re.compile(r"^(V?IN|INPUT|SIG(NAL)?|V?SIG|V?AC\d*|.*_IN|IN[+-]?|VIN\d*)$")

COLOR_SIGNAL_LEAD = "#9333ea"
COLOR_COM = "#111827"
COLOR_POS = "#dc2626"
COLOR_NEG = "#2563eb"


@dataclass
class Resolved:
    ref: str
    kind: str  # "dc" | "signal"
    pos: str
    neg: str
    value: str | None
    purpose: str  # "power" | "input"
    implied: bool = False


def _supply_name(net: str) -> bool:
    return bool(_SUPPLY_NAME.match(net.strip().upper()))


def input_name(net: str) -> bool:
    return bool(_INPUT_NAME.match(net.strip().upper()))


def _feeds_power_pin(netlist, net: str) -> bool:
    for comp in netlist.components:
        if comp.kind.value not in POWER_PIN_KINDS:
            continue
        for logical, n in comp.pins.items():
            if n != net:
                continue
            if logical.upper() in POWER_PINS:
                return True
            if comp.kind.value == "regulator" and logical.upper() == "IN":
                return True
    return False


def _is_negative(value: str | None) -> bool:
    m = re.search(r"[-+−]?\s*\d", value or "")
    return bool(m) and m.group(0).lstrip()[0] in "-−"


def _volts(value: str | None, negative: bool) -> str | None:
    """'9V' -> '+9 V'; a negative rail -> '−9 V', whichever way the value is signed."""
    if not value:
        return None
    m = re.search(r"[-+−]?\s*\d+(\.\d+)?", value)
    if not m:
        return value
    number = m.group(0).replace(" ", "").replace("−", "-").lstrip("+")
    magnitude = number.lstrip("-")
    return f"{'−' if negative else '+'}{magnitude} V"


def classify(placer) -> list[str]:
    """Settle each net's role from the sources driving it. Returns notes for
    anything that had to be corrected."""
    nl = placer.nl
    nets = placer.nets
    grounds = {n for n, v in nets.items() if v.role is NetRole.GROUND}
    notes: list[str] = []
    resolved: list[Resolved] = []

    for src in nl.sources:
        purpose = src.purpose
        if src.kind == "signal":
            purpose = "input"  # a wave generator never powers anything
        hot = src.pos if src.neg in grounds else src.neg if src.pos in grounds else None
        if purpose is None:
            purpose = (
                "power"
                if hot and (_feeds_power_pin(nl, hot) or (_supply_name(hot) and not input_name(hot)))
                else "input"
            )
        if purpose == "power" and hot is None:
            purpose = "input"  # a floating supply can't be a rail
        resolved.append(
            Resolved(src.ref, src.kind, src.pos, src.neg, src.value, purpose)
        )

        if purpose == "power":
            if hot in nets:
                # A negative supply can be drawn either way: + terminal on
                # ground with 4.5 V, or + terminal on the net with −4.5 V (how
                # LTspice users usually draw it). Both make the net negative.
                negative = (hot == src.neg) != _is_negative(src.value)
                nets[hot].role = NetRole.SUPPLY_NEG if negative else NetRole.SUPPLY_POS
                nets[hot].voltage = _volts(src.value, negative) or nets[hot].voltage
        else:
            for net in (src.pos, src.neg):
                if net in nets and net not in grounds:
                    if nets[net].role in (NetRole.SUPPLY_POS, NetRole.SUPPLY_NEG):
                        notes.append(
                            f"{net} is driven by {src.ref} ({'wave generator' if src.kind == 'signal' else 'an input source'}), "
                            "so it is wired as an input, not put on a supply rail."
                        )
                    nets[net].role = NetRole.INPUT

    # A net declared as a supply but named like an input (VIN, AC1) and not
    # backed by a power source is an input someone mislabelled.
    powered = {r.pos for r in resolved if r.purpose == "power"} | {
        r.neg for r in resolved if r.purpose == "power"
    }
    for net, info in nets.items():
        if (
            info.role in (NetRole.SUPPLY_POS, NetRole.SUPPLY_NEG)
            and net not in powered
            and input_name(net)
        ):
            info.role = NetRole.INPUT
            notes.append(
                f"{net} looks like an input, not a power supply, so it is wired as an "
                "input rather than put on a rail."
            )

    # Netlists with no sources listed (older ones, hand-written ones): assume
    # a bench supply for each supply net and a wave generator on each input.
    if not resolved:
        ground = next(iter(sorted(grounds)), None)
        for net, info in nets.items():
            if info.role is NetRole.SUPPLY_POS and ground:
                resolved.append(Resolved(f"DC {net}", "dc", net, ground, info.voltage, "power", True))
            elif info.role is NetRole.SUPPLY_NEG and ground:
                resolved.append(Resolved(f"DC {net}", "dc", ground, net, info.voltage, "power", True))
            elif info.role is NetRole.INPUT and ground:
                resolved.append(Resolved(f"GEN {net}", "signal", net, ground, None, "input", True))

    placer.sources = resolved
    return notes


# ---------------------------------------------------------------------------
# Where the leads go
# ---------------------------------------------------------------------------


def _strip_hole(placer, net: str) -> Hole | None:
    """The outermost free hole in one of this net's strips, top half first."""
    for half, col in sorted(placer.net_strips.get(net, []), key=lambda s: (s[0] != "top", s[1])):
        out_to_in = bb.strip_rows(half) if half == "top" else bb.strip_rows(half)[::-1]
        for row in out_to_in:
            if placer._end_free(row, col):
                return Hole(row=row, col=col)
    return None


def _rail_hole(placer, rail: str, near: int) -> Hole | None:
    col = placer._free_rail_column(rail, near)
    return Hole(row=rail, col=col) if col is not None else None


def _ground_hole(placer, ground: str, near: int, prefer_top: bool) -> Hole | None:
    """A ground rail that's actually carrying ground, nearest the other lead."""
    used = placer._rails_used()
    order = [bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG] if prefer_top else [bb.RAIL_BOT_NEG, bb.RAIL_TOP_NEG]
    for rail in order:
        if rail in used:
            hole = _rail_hole(placer, rail, near)
            if hole:
                return hole
    return _strip_hole(placer, ground)


def attach(placer) -> list[ExternalLead]:
    leads: list[ExternalLead] = []

    def take(hole: Hole, src: Resolved, terminal: str) -> None:
        placer.board.occupied[(hole.row, hole.col)] = f"lead:{src.ref}:{terminal}"

    def add(src, instrument, terminal, net, hole, color, tag):
        if hole is None:
            placer.warnings.append(
                f"{src.ref}: no free hole for the {instrument.lower()}'s {terminal} lead on {net}."
            )
            return
        take(hole, src, terminal)
        leads.append(
            ExternalLead(
                source=src.ref,
                instrument=instrument,
                terminal=terminal,
                net=net,
                hole=hole,
                color=color,
                tag=tag,
                value=src.value,
            )
        )

    left_end = 2
    for src in placer.sources:
        is_ground = lambda n: placer.role(n) is NetRole.GROUND  # noqa: E731
        if src.purpose == "power":
            hot = src.neg if is_ground(src.pos) else src.pos
            com = src.pos if hot == src.neg else src.neg
            if placer.role(hot) is NetRole.SUPPLY_POS:
                rail, terminal, color = bb.RAIL_TOP_POS, "+", COLOR_POS
            else:
                rail, terminal, color = bb.RAIL_BOT_POS, "−", COLOR_NEG
            hot_hole = _rail_hole(placer, rail, left_end)
            add(src, "DC supply", terminal, hot, hot_hole, color, placer.nets[hot].voltage or f"{terminal}V")
            add(
                src,
                "DC supply",
                "COM",
                com,
                _ground_hole(placer, com, left_end, prefer_top=rail == bb.RAIL_TOP_POS),
                COLOR_COM,
                "COM",
            )
        else:
            instrument = "Wave generator" if src.kind == "signal" else "DC supply"
            sig_hole = _strip_hole(placer, src.pos)
            add(
                src,
                instrument,
                "signal" if src.kind == "signal" else "+",
                src.pos,
                sig_hole,
                COLOR_SIGNAL_LEAD,
                "GEN" if src.kind == "signal" else "IN",
            )
            near = sig_hole.col if sig_hole else left_end
            if is_ground(src.neg):
                gnd_hole = _ground_hole(placer, src.neg, near, prefer_top=True)
            else:
                gnd_hole = _strip_hole(placer, src.neg)
            add(
                src,
                instrument,
                "ground" if src.kind == "signal" else "COM",
                src.neg,
                gnd_hole,
                COLOR_COM,
                "GEN ⏚" if src.kind == "signal" else "COM",
            )
            if not is_ground(src.neg):
                placer.notes.append(
                    f"{src.ref}'s ground clip goes on {src.neg}, not on circuit ground. "
                    "A wave generator's ground is usually tied to mains earth: if anything "
                    "else earthed — a scope's ground clip — also touches circuit ground, "
                    "part of the circuit is shorted out. Measure with two probes "
                    "(differential) or use a floating source."
                )
    return leads


def build_steps(placer, leads: list[ExternalLead]) -> list[tuple[str, list[int], str | None]]:
    """(text, lead indexes, detail) for each instrument, in hook-up order."""
    from .placer import hole_label  # noqa: avoid an import cycle at load time

    by_source: dict[str, list[int]] = {}
    for i, lead in enumerate(leads):
        by_source.setdefault(lead.source, []).append(i)
    src_of = {s.ref: s for s in placer.sources}

    steps = []
    power = [s for s in placer.sources if s.purpose == "power" and s.ref in by_source]
    inputs = [s for s in placer.sources if s.purpose != "power" and s.ref in by_source]
    for src in power + inputs:
        idx = by_source[src.ref]
        parts = [leads[i] for i in idx]
        hot = next((l for l in parts if l.terminal not in ("COM", "ground")), parts[0])
        gnd = next((l for l in parts if l.terminal in ("COM", "ground")), None)
        if src.purpose == "power":
            volts = placer.nets[hot.net].voltage
            if hot.terminal == "+":
                text = (
                    f"Set the bench supply's + output{' to ' + volts if volts else ''} and "
                    f"leave it switched off. Clip + (red) to the {hole_label(hot.hole)}"
                    + (f" and COM (black) to the {hole_label(gnd.hole)}" if gnd else "")
                    + "."
                )
            else:
                text = (
                    f"Set the − output{' to ' + volts if volts else ''}, still off. Clip − to "
                    f"the {hole_label(hot.hole)} — on this board the bottom + rail carries "
                    "the negative supply"
                    + (f" — and COM to the {hole_label(gnd.hole)}" if gnd else "")
                    + "."
                )
            detail = f"{hot.net} · {placer.nets[hot.net].voltage or 'voltage not given on the schematic'}"
        elif src.kind == "signal":
            text = (
                f"Connect the wave generator, output off: signal clip to {hole_label(hot.hole)}"
                + (f", ground clip to the {hole_label(gnd.hole)}" if gnd else "")
                + ". Push a short wire into each hole to clip onto."
            )
            detail = f"drives {hot.net}" + (f" · {src.value}" if src.value else "")
        else:
            text = (
                f"Connect the second DC channel (the input voltage): + to {hole_label(hot.hole)}"
                + (f", COM to {hole_label(gnd.hole)}" if gnd else "")
                + "."
            )
            detail = f"drives {hot.net}" + (f" · {src.value}" if src.value else "")
        steps.append((text, idx, detail))

    if power and inputs:
        steps.append(
            (
                "Switch on the DC supply first, then the generator's output. A signal into "
                "an unpowered chip or transistor stage can damage its inputs.",
                [],
                None,
            )
        )
    return steps
