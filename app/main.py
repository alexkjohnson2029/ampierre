"""FastAPI backend.

    POST /api/parse     schematic image (or SPICE text) -> netlist + questions
    POST /api/netlist   netlist drawn in the editor     -> the same, no model
    POST /api/place     netlist with packages chosen    -> breadboard layout
    GET  /api/packages  the package catalogue for the picker
    GET  /api/examples  built-in netlists, so the app is usable with no API key
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import packages as pk
from .llm import LLMError, extract_netlist, netlist_from_spice
from .models import AMBIGUOUS_KINDS, ComponentKind, Layout, Netlist
from .placer import place

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
EXAMPLES = ROOT / "examples"


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    import os

    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

#: Set BREADBOARD_FAKE_LLM=1 to click through the whole app with no API key.
#: /api/parse then ignores what you uploaded and hands back a stored netlist,
#: clearly labelled as such, so the upload → questions → place → draw path can
#: be exercised end to end for free.
FAKE_LLM = os.environ.get("BREADBOARD_FAKE_LLM") == "1"

app = FastAPI(title="AMPierre — schematic to breadboard")


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


def _option(p: pk.Package) -> PackageOption:
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
                options=[_option(p) for p in pk.options_for(kind)],
                suggested=first.package or _suggest(first),
            )
        )
    return out


class ParseResponse(BaseModel):
    netlist: Netlist
    questions: list[PackageQuestion]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/api/parse", response_model=ParseResponse)
async def parse(
    image: UploadFile | None = File(default=None),
    spice: str | None = Form(default=None),
    hint: str | None = Form(default=None),
):
    if FAKE_LLM:
        netlist = Netlist.model_validate_json(
            (EXAMPLES / "three_band_equalizer.json").read_text()
        )
        netlist.warnings.insert(
            0,
            "FAKE MODEL MODE: this netlist is a stored example, not a reading of "
            "the file you uploaded. Unset BREADBOARD_FAKE_LLM to use the real model.",
        )
        return ParseResponse(netlist=netlist, questions=questions_for(netlist))

    try:
        if image is not None:
            data = await image.read()
            if not data:
                raise HTTPException(400, "That file was empty.")
            media = image.content_type or "image/png"
            if media not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                raise HTTPException(400, f"Unsupported image type: {media}")
            netlist = extract_netlist(data, media, hint)
        elif spice:
            netlist = netlist_from_spice(spice)
        else:
            raise HTTPException(400, "Send either an image or SPICE text.")
    except LLMError as e:
        raise HTTPException(400, str(e)) from e

    return ParseResponse(netlist=netlist, questions=questions_for(netlist))


@app.post("/api/netlist", response_model=ParseResponse)
def netlist_route(netlist: Netlist):
    """A netlist that needs no reading — drawn in the editor, or saved earlier.
    Straight to the part questions, no model involved."""
    if not netlist.components:
        raise HTTPException(400, "The netlist has no components.")
    return ParseResponse(netlist=netlist, questions=questions_for(netlist))


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


@app.post("/api/place", response_model=Layout)
def place_route(req: PlaceRequest):
    custom = {}
    for comp in req.netlist.components:
        spec = req.custom_packages.get(comp.ref)
        if spec:
            try:
                custom[comp.ref] = pk.make_custom(spec.model_dump(), comp.kind)
            except ValueError as e:
                raise HTTPException(400, f"{comp.ref}: {e}") from e
            continue
        chosen = req.packages.get(comp.ref)
        if chosen and chosen not in pk.BY_ID:
            raise HTTPException(400, f"Unknown package '{chosen}' for {comp.ref}")
        comp.package = chosen or comp.package
    if not req.netlist.components:
        raise HTTPException(400, "The netlist has no components.")
    if req.style not in ("flow", "flow-compact", "packed"):
        raise HTTPException(400, f"Unknown layout style '{req.style}'")
    return place(req.netlist, custom, style=req.style)


@app.get("/api/packages")
def packages_route():
    return {
        "packages": [_option(p).model_dump() for p in pk.ALL_PACKAGES],
        "custom_forms": pk.CUSTOM_FORMS,
        "by_kind": {
            k.value: [p.id for p in pk.options_for(k)] for k in pk.DEFAULT_FOR_KIND
        },
        "defaults": {k.value: v for k, v in pk.DEFAULT_FOR_KIND.items()},
    }


@app.get("/api/examples")
def examples_route():
    out = []
    for f in sorted(EXAMPLES.glob("*.json")):
        data = json.loads(f.read_text())
        entry = {"id": f.stem, "title": data.get("title", f.stem)}
        if data.get("about"):  # a featured build: who made it and why it's here
            entry["about"] = data["about"]
        out.append(entry)
    # featured builds first
    return sorted(out, key=lambda e: "about" not in e)


@app.get("/api/examples/{name}", response_model=ParseResponse)
def example_route(name: str):
    f = EXAMPLES / f"{Path(name).name}.json"
    if not f.exists():
        raise HTTPException(404, "No such example.")
    netlist = Netlist.model_validate_json(f.read_text())
    return ParseResponse(netlist=netlist, questions=questions_for(netlist))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/about")
def about():
    return FileResponse(STATIC / "about.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
