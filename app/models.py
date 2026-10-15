"""Data model for the schematic -> breadboard pipeline.

Three stages, three shapes:

    Schematic image  --(LLM)-->  Netlist  --(placer)-->  Layout  --(JS)--> SVG

Only the first arrow is probabilistic. Netlist and Layout are plain data, so
everything after the LLM is testable without an API key.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Nets
# ---------------------------------------------------------------------------


class NetRole(str, Enum):
    """What a net is *for*. Drives rail assignment and wire colour."""

    SUPPLY_POS = "supply_positive"  # V+, VCC, VDD   -> top positive rail
    SUPPLY_NEG = "supply_negative"  # V-, VEE, VSS   -> bottom positive rail
    GROUND = "ground"  # GND, 0, AGND   -> both negative rails
    SIGNAL = "signal"  # everything else -> terminal strips
    INPUT = "input"  # signal, but marked as a board input
    OUTPUT = "output"  # signal, but marked as a board output


class Net(BaseModel):
    name: str
    role: NetRole = NetRole.SIGNAL
    voltage: str | None = Field(
        default=None,
        description="Text shown when hovering a rail, e.g. '+9 V', '-9 V', '0 V'.",
    )


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


class ComponentKind(str, Enum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    POLARIZED_CAPACITOR = "polarized_capacitor"
    INDUCTOR = "inductor"
    POTENTIOMETER = "potentiometer"
    DIODE = "diode"
    LED = "led"
    NPN = "npn"
    PNP = "pnp"
    NMOS = "nmos"
    PMOS = "pmos"
    OPAMP = "opamp"
    IC = "ic"
    REGULATOR = "regulator"


#: Kinds whose physical pinout is ambiguous from the schematic alone. The UI
#: stops and asks the user to pick a package for every component of these kinds
#: before anything is placed -- this is the "ask which part" step in the spec.
AMBIGUOUS_KINDS: set[ComponentKind] = {
    ComponentKind.OPAMP,
    ComponentKind.IC,
    ComponentKind.NPN,
    ComponentKind.PNP,
    ComponentKind.NMOS,
    ComponentKind.PMOS,
    ComponentKind.REGULATOR,
    ComponentKind.DIODE,
    ComponentKind.POTENTIOMETER,  # trimmer (fits the board) or panel pot (doesn't)
}


class Component(BaseModel):
    ref: str = Field(description="Reference designator from the schematic: R1, C3, U1, Q2.")
    kind: ComponentKind
    value: str | None = Field(
        default=None, description="10k, 100nF, 2N3904, TL072 - shown on hover."
    )
    pins: dict[str, str] = Field(
        description=(
            "Logical pin name -> net name. Logical names are schematic-level "
            "('IN+', 'OUT', 'V+', 'B', 'C', 'E', '1', '2', 'A', 'K'); the chosen "
            "package maps them onto physical pin numbers."
        )
    )
    package: str | None = Field(
        default=None,
        description="Package id from packages.py. None until the user picks one.",
    )
    notes: str | None = None


class Source(BaseModel):
    """Something on the bench that drives the circuit: a DC power supply or a
    wave (function) generator. Schematics draw these as voltage sources; they
    are not parts that go in the board, but their leads clip onto it."""

    ref: str = Field(description="V1, VCC, VSIG — the schematic's name for the source.")
    kind: Literal["dc", "signal"] = Field(
        description="dc: a bench DC supply channel. signal: a wave/function generator "
        "(sine, square, pulse, AC)."
    )
    pos: str = Field(description="Net on the + / signal terminal.")
    neg: str = Field(description="Net on the − / ground terminal (usually GND).")
    value: str | None = Field(
        default=None, description="'9V', '-9V', '1 kHz sine, 0.5 Vpk' — as on the schematic."
    )
    purpose: Literal["power", "input"] | None = Field(
        default=None,
        description="power: it powers the circuit (op-amp supply, transistor Vcc) and "
        "goes on a rail. input: it's the signal or voltage the circuit acts on. "
        "Worked out from the circuit when left empty.",
    )


class LayoutHints(BaseModel):
    """A board laid out by hand: where each part goes, and the jumpers.

    Used for the bundled examples, where a person has arranged the board the
    way they'd build it. The placer still checks every hole, routes anything
    left unjoined, drops supply and ground strips to their rails, and the
    verifier proves the result is the circuit — a hint can't make a wrong
    board, only a tidier one.

    Holes are written the way they're printed on the board: "G12". Rail holes
    are "T+12" (top + rail, column 12), "T-12", "B-12" and "B+12".
    """

    note: str | None = None
    #: ref -> {pin name: hole} for discrete parts; {"col": n, "flip": bool}
    #: for a chip, where col is its leftmost column and flip means notch right.
    parts: dict[str, dict] = Field(default_factory=dict)
    #: jumpers as [from hole, to hole]; the net comes from what's in the strip
    wires: list[list[str]] = Field(default_factory=list)


class Netlist(BaseModel):
    """What the LLM produces and the placer consumes."""

    title: str = "Untitled circuit"
    components: list[Component] = []
    nets: list[Net] = []
    sources: list[Source] = Field(
        default_factory=list,
        description="DC supplies and wave generators driving the circuit.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Things the LLM was unsure about in the schematic image.",
    )
    layout: LayoutHints | None = Field(
        default=None, description="A hand-made arrangement (bundled examples only)."
    )

    def net(self, name: str) -> Net:
        for n in self.nets:
            if n.name == name:
                return n
        return Net(name=name, role=NetRole.SIGNAL)

    def component(self, ref: str) -> Component | None:
        return next((c for c in self.components if c.ref == ref), None)


# ---------------------------------------------------------------------------
# Layout (placer output -> renderer input)
# ---------------------------------------------------------------------------

Half = Literal["top", "bottom", "rail"]


class Hole(BaseModel):
    """A single tie point. row is 'A'-'J' or a rail id; col is 1..63."""

    row: str
    col: int

    def key(self) -> str:
        return f"{self.row}{self.col}"


class PlacedPin(BaseModel):
    name: str  # logical name, e.g. "IN+"
    number: int | None = None  # physical pin number, e.g. 3
    net: str
    hole: Hole
    label: str | None = None  # what the hover card shows for this pin


class PlacedComponent(BaseModel):
    ref: str
    kind: ComponentKind
    package: str
    value: str | None = None
    pins: list[PlacedPin]
    orientation: str = Field(
        default="",
        description="Human-readable orientation instruction shown on hover, e.g. "
        "'Notch / pin-1 dot faces LEFT (column 12).'",
    )
    body: dict = Field(
        default_factory=dict,
        description="Drawing hints for the renderer: span, rows, marker side.",
    )


class Wire(BaseModel):
    """A jumper the user has to cut and place."""

    from_hole: Hole
    to_hole: Hole
    net: str
    color: str = "#6b7280"
    kind: Literal["signal", "rail", "cross_channel", "rail_bond"] = "signal"


class ExternalLead(BaseModel):
    """Where one lead of a bench instrument clips onto the board."""

    source: str  # Source.ref
    instrument: str  # "DC supply", "Wave generator"
    terminal: str  # "+", "−", "COM", "signal", "ground"
    net: str
    hole: Hole
    color: str
    tag: str  # the short label drawn on the board: "+9 V", "GEN", "COM"
    value: str | None = None


class BuildStep(BaseModel):
    """One action in the assembly timeline the UI scrubs through."""

    index: int
    kind: Literal["note", "component", "wire", "lead"]
    text: str
    ref: str | None = None  # which component this step places
    wire: int | None = None  # index into Layout.wires
    leads: list[int] = Field(default_factory=list)  # indexes into Layout.leads
    detail: str | None = None  # orientation reminder, value, etc.


class Layout(BaseModel):
    title: str
    columns: int
    components: list[PlacedComponent] = []
    wires: list[Wire] = []
    nets: list[Net] = []
    leads: list[ExternalLead] = Field(
        default_factory=list, description="Where the bench instruments clip on."
    )
    rails: dict[str, dict] = Field(
        default_factory=dict,
        description="rail id -> {net, label, voltage, polarity} for hover text.",
    )
    warnings: list[str] = Field(
        default_factory=list, description="Problems the placer or the verifier found."
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Caveats carried over from the netlist itself — what the model "
        "could not read, or what the circuit's author flagged.",
    )
    build_order: list[BuildStep] = Field(
        default_factory=list, description="Step-by-step assembly instructions."
    )
