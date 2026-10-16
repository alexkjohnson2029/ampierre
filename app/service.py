"""What the app's routes do, without a web server.

`main.py` serves these over HTTP with FastAPI. The GitHub Pages site has no
server: it runs this same module in the browser with Pyodide, through
`call()`, so the website and the local app give the same board.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from . import packages as pk
from .models import AMBIGUOUS_KINDS, ComponentKind, Layout, Netlist
from .placer import place
from .spice import SpiceError
from .spice import parse as parse_spice


class ServiceError(ValueError):
    """A request that can't be done, with a message worth showing as is."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Package questions
# ---------------------------------------------------------------------------


class PackageOption(BaseModel):
    id: str
    label: str
    form: str = "dip"
    pin_count: int = 0
    pin_map: dict[str, int] = {}
    pin_names: dict[int, str] = {}
    marker: str = ""
    note: str = ""
    span: int


class PackageQuestion(BaseModel):
    id: str
    refs: list[str]  # identical parts are asked about once, together
    kind: str
    value: str | None = None
    pins: list[str]
    options: list[PackageOption]
    suggested: str


def option(p: pk.Package) -> PackageOption:
    return PackageOption(
        id=p.id,
        label=p.label,
        form=p.form,
        pin_count=p.pin_count,
        pin_map=p.pin_map,
        pin_names=p.pin_names,
        marker=p.marker,
        note=p.note,
        span=p.span,
    )


def _suggest(comp) -> str:
    """Guess a package from the value text before asking the user."""
    value = (comp.value or "").upper().replace("-", "").replace(" ", "")
    for p in pk.options_for(comp.kind):
        tokens = [
            t.strip().upper().replace("-", "")
            for t in p.label.replace("/", ",").split(",")
        ]
        for t in tokens:
            head = t.split("—")[0].strip()
            if head and len(head) >= 4 and head in value:
                return p.id
    if comp.kind.value == "opamp" and "741" in value:
        return pk.LM741.id
    return pk.DEFAULT_FOR_KIND[comp.kind]


def questions_for(netlist: Netlist) -> list[PackageQuestion]:
    """One question per *kind* of part, not per part.

    Four 1N4007s in a bridge are the same question asked four times, so they
    are grouped: same kind, same value, same set of pins.
    """
    groups: dict[tuple, list] = {}
    for comp in netlist.components:
        if comp.kind not in AMBIGUOUS_KINDS:
            continue
        # A pot wired between the wiper and either end is the same part.
        pins = () if comp.kind is ComponentKind.POTENTIOMETER else tuple(sorted(comp.pins))
        key = (comp.kind, comp.value or "", pins)
        groups.setdefault(key, []).append(comp)

    out: list[PackageQuestion] = []
    for (kind, _value, _pins), comps in groups.items():
        first = comps[0]
        out.append(
            PackageQuestion(
                id="+".join(c.ref for c in comps),
                refs=[c.ref for c in comps],
                kind=kind.value,
                value=first.value,
                pins=list(first.pins.keys()),
                options=[option(p) for p in pk.options_for(kind)],
                suggested=first.package or _suggest(first),
            )
        )
    return out


class ParseResponse(BaseModel):
    netlist: Netlist
    questions: list[PackageQuestion]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class PasteRequest(BaseModel):
    text: str


class CustomPackage(BaseModel):
    """A pinout the user typed in, for a part that isn't in the library."""

    name: str
    form: str = "dip"
    pin_count: int | None = None
    pin_map: dict[str, int] = {}
    pin_names: dict[str, str] = {}
    polarized: bool = False


class PlaceRequest(BaseModel):
    netlist: Netlist
    packages: dict[str, str] = {}  # ref -> package id
    custom_packages: dict[str, CustomPackage] = {}  # ref -> user-defined pinout
    #: "flow" = schematic-shaped and roomy, "flow-compact" = schematic-shaped
    #: and tight, "packed" = fill the board regardless of what it looks like.
    style: str = "flow"


def from_text(req: PasteRequest) -> ParseResponse:
    """A pasted netlist: SPICE as LTspice or PSpice writes it, or JSON."""
    try:
        netlist = parse_spice(req.text)
    except SpiceError as e:
        raise ServiceError(str(e)) from e
    return ParseResponse(netlist=netlist, questions=questions_for(netlist))


def from_netlist(netlist: Netlist) -> ParseResponse:
    """A netlist drawn in the editor (or an example): straight to the questions."""
    if not netlist.components:
        raise ServiceError("The netlist has no components.")
    return ParseResponse(netlist=netlist, questions=questions_for(netlist))


def lay_out(req: PlaceRequest) -> Layout:
    custom = {}
    for comp in req.netlist.components:
        spec = req.custom_packages.get(comp.ref)
        if spec:
            try:
                custom[comp.ref] = pk.make_custom(spec.model_dump(), comp.kind)
            except ValueError as e:
                raise ServiceError(f"{comp.ref}: {e}") from e
            continue
        chosen = req.packages.get(comp.ref)
        if chosen and chosen not in pk.BY_ID:
            raise ServiceError(f"Unknown package '{chosen}' for {comp.ref}")
        comp.package = chosen or comp.package
    if not req.netlist.components:
        raise ServiceError("The netlist has no components.")
    if req.style not in ("flow", "flow-compact", "packed"):
        raise ServiceError(f"Unknown layout style '{req.style}'")
    return place(req.netlist, custom, style=req.style)


def examples_index(files: dict[str, str]) -> list[dict]:
    """The example list: {stem: json text} -> [{id, title, about?}], featured first."""
    out = []
    for stem in sorted(files):
        data = json.loads(files[stem])
        entry = {"id": stem, "title": data.get("title", stem)}
        if data.get("about"):  # a featured build: who made it and why it's here
            entry["about"] = data["about"]
        out.append(entry)
    return sorted(out, key=lambda e: "about" not in e)


# ---------------------------------------------------------------------------
# The browser's way in
# ---------------------------------------------------------------------------


def call(route: str, body: str) -> str:
    """One API route, JSON in and JSON out, for the static site.

    Errors come back as {"detail": message} with "error": true, the same
    shape FastAPI gives, so the page shows them the same way.
    """
    try:
        if route == "parse":
            result = from_text(PasteRequest.model_validate_json(body))
        elif route == "netlist":
            result = from_netlist(Netlist.model_validate_json(body))
        elif route == "place":
            result = lay_out(PlaceRequest.model_validate_json(body))
        else:
            raise ServiceError(f"No such route: {route}", 404)
    except ServiceError as e:
        return json.dumps({"error": True, "detail": str(e)})
    except ValidationError as e:
        return json.dumps({"error": True, "detail": f"Bad request: {e.errors()[0]['msg']}"})
    return result.model_dump_json()
