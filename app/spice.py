"""Reading a SPICE netlist — the text LTspice shows under View → SPICE Netlist,
or PSpice's .cir/.net — straight into a Netlist. Plain parsing, no model.

A netlist already says what connects to what. What it doesn't always say is
what kind of part a line is: an `X` line is any subcircuit, a `Q` line could
be NPN or PNP. Those are worked out from the netlist's own .model lines when
it has them, then from the part number, and anything still a guess is listed
in the warnings so it can be checked on the next screen.
"""

from __future__ import annotations

import json
import re
from pathlib import PureWindowsPath

from . import pinlists
from .models import Component, ComponentKind, Net, Netlist, NetRole, Source


class SpiceError(ValueError):
    """The text can't be read as a netlist at all."""


#: Part numbers whose type a bare Q or M line doesn't give away.
_PNP = re.compile(r"^(2N(3906|4403|2907|5401|4126)|BC(55[6789]|32[78]|640)|TIP(3[24]|42|127|147)|BD(1[34][02468])|MJE(350|2955)|PN2907|S8550|A1015)", re.I)
_NPN = re.compile(r"^(2N(3904|2222|4401|2219|5551|3055|4124)|PN2222|BC(54[6789]|33[78]|639)|TIP(3[13]|41|122|142)|BD(1[34][13579])|MJE(340|3055)|S8050|C1815)", re.I)
_PMOS = re.compile(r"^(BS250|IRF9|ZVP|FQP\d+P|NDP\d+P|SI2301|AO3401|PMOS)", re.I)
_NMOS = re.compile(r"^(2N7000|2N7002|BS170|IRF[0-8Z]|IRL|FQP\d+N|NDP\d+N|SI2302|AO3400|ZVN|NMOS)", re.I)
_LED = re.compile(r"LED|^(NSPW|NSSW|QTLP|LXHL|LUW|LW|LR|LY|LG)\w*", re.I)
_REGULATOR = re.compile(r"^(LM)?(78|79)(L|M)?\d\d|LM317|LM337|LM1117|AMS1117|LT1086|LT1117|LM2940|LD1117", re.I)
_POT = re.compile(r"pot", re.I)

#: Values that are a source changing over time: a wave generator, not a supply.
_SIGNAL = re.compile(r"\b(SINE?|PULSE|PWL|SFFM|EXP|AC|WAVEFILE)\b|wavefile", re.I)


def parse(text: str) -> Netlist:
    """A pasted netlist — SPICE, or AMPierre's own JSON — as a Netlist."""
    stripped = text.strip()
    if not stripped:
        raise SpiceError("Paste a netlist first.")
    if stripped.startswith("{"):
        try:
            return Netlist.model_validate(json.loads(stripped))
        except Exception as e:  # noqa: BLE001 — any bad JSON is the same mistake
            raise SpiceError(f"That looks like JSON but isn't a netlist: {e}") from e
    stripped = _fix_micro(stripped)
    if pinlists.detect(stripped):
        try:
            stripped = pinlists.to_spice(stripped)
        except pinlists.PinListError as e:
            raise SpiceError(str(e)) from e
    return _Reader(stripped).read()


def _fix_micro(text: str) -> str:
    """LTspice saves netlists in Windows-1252, where µ is one byte. Opened as
    UTF-8 that byte turns into '�', and the other way round µ turns into
    'Âµ'. After a number, either one can only have been µ."""
    text = text.replace("\u00c2\u00b5", "µ")
    return re.sub(r"(?<=[0-9.])\ufffd", "µ", text)


def spice_value(text: str | None) -> str | None:
    """SPICE's suffixes as the rest of the app reads them.

    In SPICE both m and M mean milli, and mega is Meg: '1M' is a thousandth of
    an ohm, and '1Meg' is a megohm. The app's values say 'M' for mega, so
    'Meg' becomes 'M' and a lone M becomes m. 'µ' and 'u' both stay micro.
    """
    if text is None:
        return None
    m = re.fullmatch(r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)(meg|mil|[a-zA-Zµμ]+)?(.*)", text.strip())
    if not m:
        return text
    number, suffix, rest = m.groups()
    if not suffix:
        return number + rest
    low = suffix.lower()
    if low.startswith("meg"):
        return f"{number}M{suffix[3:]}{rest}"
    if suffix[0] in "Mm":
        return f"{number}m{suffix[1:]}{rest}"
    return text.strip()


class _Reader:
    def __init__(self, text: str):
        self.lines = self._logical_lines(text)
        self.title = "Pasted netlist"
        self.models: dict[str, str] = {}  # .model name -> type (NPN, PMOS, D...)
        self.ports: dict[str, list[str]] = {}  # .subckt name -> its pin names
        self.warnings: list[str] = []
        self.components: list[Component] = []
        self.sources: list[Source] = []
        self.skipped: dict[str, list[str]] = {}

    @staticmethod
    def _logical_lines(text: str) -> list[str]:
        """Join '+' continuation lines and drop inline ; comments."""
        out: list[str] = []
        for raw in text.splitlines():
            line = raw.split(";", 1)[0].rstrip()
            if not line.strip():
                continue
            if line.lstrip().startswith("+") and out:
                out[-1] += " " + line.lstrip()[1:].strip()
            else:
                out.append(line.strip())
        return out

    # -- the walk -------------------------------------------------------------

    def read(self) -> Netlist:
        lines = self.lines
        # SPICE's first line is always the title. LTspice writes the file path
        # there as a comment; anything that is clearly an element was pasted
        # without one.
        if lines and (lines[0].startswith("*") or not self._looks_like_element(lines[0])):
            self.title = self._title_from(lines[0])
            lines = lines[1:]

        # .model lines first: they decide what Q, M and D lines are.
        for line in lines:
            if line.lower().startswith(".model"):
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    kind = re.match(r"[A-Za-z]+", parts[2])
                    if kind:
                        self.models[parts[1].upper()] = kind.group(0).upper()
            elif line.lower().startswith(".subckt"):
                # .subckt NAME port port... [params: x=1]: a part of the user's
                # own, and its ports are the names its pins go by.
                words = line.split()[1:]
                if words:
                    ports = []
                    for w in words[1:]:
                        if "=" in w or w.lower().startswith("params"):
                            break
                        ports.append(w)
                    self.ports[words[0].upper()] = ports

        in_subckt = 0
        for line in lines:
            low = line.lower()
            if low.startswith(".subckt"):
                in_subckt += 1
                continue
            if low.startswith(".ends"):
                in_subckt = max(0, in_subckt - 1)
                continue
            if in_subckt or line.startswith("*"):
                continue
            if low.startswith(".end") and not low.startswith(".ends"):
                break
            if line.startswith("."):
                continue  # .tran, .ac, .include, .param...: simulation only
            self._element(line)

        for letter, names in self.skipped.items():
            what = {
                "I": "current sources",
                "B": "behavioural sources",
                "E": "controlled sources", "F": "controlled sources",
                "G": "controlled sources", "H": "controlled sources",
                "K": "coupling statements", "T": "transmission lines",
                "S": "switches", "W": "switches", "A": "special functions",
            }.get(letter, f"'{letter}' lines")
            self.warnings.append(
                f"Skipped {', '.join(names)} — {what} are simulation-only and have no breadboard part."
            )

        unnamed = f" ({pinlists.UNNAMED})"
        self.warnings = [w.replace(unnamed, "") for w in self.warnings]

        if not self.components:
            raise SpiceError(
                "No parts found. Paste the netlist itself — lines like 'R1 N001 0 10k'."
            )
        return Netlist(
            title=self.title,
            components=self.components,
            nets=[Net(name="GND", role=NetRole.GROUND, voltage="0 V")],
            sources=self.sources,
            warnings=self.warnings,
        )

    @staticmethod
    def _looks_like_element(line: str) -> bool:
        return bool(re.match(r"^[RCLDQMVXIrcldqmvxi]\S*\s+\S+\s+\S+", line))

    @staticmethod
    def _title_from(line: str) -> str:
        t = line.lstrip("*").strip()
        # LTspice: "* C:\Users\me\Documents\LTspice\filter.asc"
        if re.search(r"\.(asc|cir|net|sch)$", t, re.I):
            t = PureWindowsPath(t).stem.replace("_", " ")
        return t or "Pasted netlist"

    # -- one element ----------------------------------------------------------

    @staticmethod
    def _node(name: str) -> str:
        return "GND" if name in ("0", "gnd", "GND", "Gnd") else name

    def _element(self, line: str) -> None:
        tokens = line.split()
        name = tokens[0]
        letter = name[0].upper()
        nodes = [self._node(t) for t in tokens[1:]]

        def need(n: int) -> bool:
            if len(nodes) < n:
                self.warnings.append(f"Couldn't read '{line}' — skipped.")
                return False
            return True

        if letter in "RCL":
            if not need(2):
                return
            value = spice_value(self._value(tokens[3:]))
            kind = {"R": ComponentKind.RESISTOR, "C": ComponentKind.CAPACITOR, "L": ComponentKind.INDUCTOR}[letter]
            self._add(name, kind, value, {"1": nodes[0], "2": nodes[1]})
        elif letter == "D":
            if not need(3):
                return
            model = tokens[3]
            led = self.models.get(model.upper()) == "LED" or bool(_LED.search(model))
            self._add(name, ComponentKind.LED if led else ComponentKind.DIODE, model, {"A": nodes[0], "K": nodes[1]})
        elif letter == "Q":
            if not need(4):
                return
            # Q C B E [substrate] model [params]
            model = self._model_after(tokens, 3)
            kind = self._transistor(name, model)
            self._add(name, kind, model, {"C": nodes[0], "B": nodes[1], "E": nodes[2]})
        elif letter == "M":
            if not need(4):
                return
            # M D G S [B] model [params]
            model = self._model_after(tokens, 3)
            kind = self._mosfet(name, model)
            self._add(name, kind, model, {"D": nodes[0], "G": nodes[1], "S": nodes[2]})
        elif letter == "V":
            if not need(2):
                return
            value = " ".join(tokens[3:]).strip()
            value = re.sub(r"(?i)^DC\s+", "", value)
            signal = bool(_SIGNAL.search(value))
            if not signal and re.fullmatch(r"[-+]?[0-9.]+", value):
                value += "V"
            self.sources.append(
                Source(ref=name, kind="signal" if signal else "dc", pos=nodes[0], neg=nodes[1], value=value or None)
            )
        elif letter == "X":
            self._subcircuit(name, tokens)
        else:
            self.skipped.setdefault(letter, []).append(name)

    @staticmethod
    def _model_after(tokens: list[str], n_nodes: int) -> str:
        """The model name of a Q or M line: the last word after its nodes that
        isn't a key=value or a number (the optional fourth node is a node)."""
        rest = [t for t in tokens[1 + n_nodes :] if "=" not in t]
        names = [t for t in rest if not re.fullmatch(r"[-+]?[0-9.]+", t)]
        return names[-1] if names else rest[-1]

    @staticmethod
    def _value(rest: list[str]) -> str | None:
        """The value of an R, C or L line: the first token that isn't key=value."""
        for t in rest:
            if "=" not in t:
                return t
        return None

    def _transistor(self, ref: str, model: str) -> ComponentKind:
        declared = self.models.get(model.upper())
        if declared in ("NPN", "PNP"):
            return ComponentKind.NPN if declared == "NPN" else ComponentKind.PNP
        if _PNP.match(model):
            return ComponentKind.PNP
        if not _NPN.match(model):
            self.warnings.append(f"{ref} ({model}): assumed NPN — the netlist doesn't say. Check it.")
        return ComponentKind.NPN

    def _mosfet(self, ref: str, model: str) -> ComponentKind:
        declared = self.models.get(model.upper())
        if declared in ("NMOS", "PMOS", "VDMOS"):
            if declared != "VDMOS":
                return ComponentKind.NMOS if declared == "NMOS" else ComponentKind.PMOS
        if _PMOS.match(model):
            return ComponentKind.PMOS
        if not _NMOS.match(model):
            self.warnings.append(f"{ref} ({model}): assumed N-channel — the netlist doesn't say. Check it.")
        return ComponentKind.NMOS

    def _subcircuit(self, name: str, tokens: list[str]) -> None:
        """X lines: nodes, then the subcircuit name, then any key=value params."""
        args = [t for t in tokens[1:] if "=" not in t]
        if len(args) < 2:
            self.warnings.append(f"Couldn't read '{' '.join(tokens)}' — skipped.")
            return
        model, nodes = args[-1], [self._node(n) for n in args[:-1]]
        ref = name[1:] if len(name) > 1 and name[0] in "Xx" else name
        n = len(nodes)

        if _POT.search(model) and n == 3:
            # AMPierre's own export: X<ref> end wiper end potentiometer R=10k
            value = next((t.split("=", 1)[1] for t in tokens if t.upper().startswith("R=")), None)
            self._add(ref, ComponentKind.POTENTIOMETER, spice_value(value), {"1": nodes[0], "W": nodes[1], "3": nodes[2]})
            self.warnings.append(f"{ref}: read as a potentiometer with the wiper in the middle — check which pin is the wiper.")
        elif _REGULATOR.search(model) and n == 3:
            self._add(ref, ComponentKind.REGULATOR, model, {"IN": nodes[0], "GND": nodes[1], "OUT": nodes[2]})
            self.warnings.append(
                f"{ref} ({model}): read as a regulator with pins IN, GND, OUT in that order — "
                "subcircuits differ, so check against the netlist."
            )
        elif n == 5:
            # LTspice's op-amp symbols: In+ In- V+ V- Out
            self._add(ref, ComponentKind.OPAMP, model, {"IN+": nodes[0], "IN-": nodes[1], "V+": nodes[2], "V-": nodes[3], "OUT": nodes[4]})
            if model == pinlists.UNNAMED:
                self.warnings.append(
                    f"{ref}: the netlist gives no part number, so it was read as an op-amp "
                    "from its five pins (In+, In−, V+, V−, Out). Check it."
                )
        elif n == 3 and re.search(r"opamp|^U?A?741|^TL0|^LM(3[25]8|741)|^LT1|^OP", model, re.I):
            # the ideal three-pin op-amp has no supply pins at all
            self._add(ref, ComponentKind.OPAMP, model, {"IN+": nodes[0], "IN-": nodes[1], "OUT": nodes[2]})
            self.warnings.append(
                f"{ref}: the netlist's op-amp has no supply pins (an ideal model). "
                "Its chip still needs V+ and V- — wire them to the rails yourself."
            )
        elif self._named_ports(model, n):
            # A part the netlist defines itself: its .subckt line names the pins.
            ports = self.ports[model.upper()]
            self._add(ref, ComponentKind.IC, model, dict(zip(ports, nodes)))
            self.warnings.append(
                f"{ref} ({model}): your own part, with pins {', '.join(ports)} from its .subckt line. "
                "Choose My own part on the next screen and give each one's pin number."
            )
        else:
            pins = {str(i + 1): node for i, node in enumerate(nodes)}
            self._add(ref, ComponentKind.IC, model, pins)
            self.warnings.append(
                f"{ref} ({model}): a part AMPierre doesn't know, with {n} pins numbered in netlist order. "
                "Choose My own part on the next screen and give each one's pin number from the datasheet."
            )

    def _named_ports(self, model: str, n: int) -> bool:
        ports = self.ports.get(model.upper())
        return bool(
            ports
            and len(ports) == n
            and len(set(ports)) == n
            and not all(p.isdigit() for p in ports)
        )

    def _add(self, ref: str, kind: ComponentKind, value: str | None, pins: dict[str, str]) -> None:
        if any(c.ref == ref for c in self.components):
            self.warnings.append(f"Two parts are called {ref}; the second was skipped.")
            return
        if value == pinlists.UNNAMED:
            value = None
        self.components.append(Component(ref=ref, kind=kind, value=value, pins=pins))
