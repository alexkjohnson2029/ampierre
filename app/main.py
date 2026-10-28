"""FastAPI backend — the app run locally. The work itself is in service.py,
which the GitHub Pages site runs in the browser instead.

    POST /api/parse     pasted SPICE (or JSON) netlist  -> netlist + questions
    POST /api/netlist   netlist drawn in the editor     -> netlist + questions
    POST /api/place     netlist with packages chosen    -> breadboard layout
    GET  /api/packages  the package catalogue for the picker
    GET  /api/examples  built-in netlists
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import packages as pk
from . import service
from .models import Layout, Netlist
from .service import (  # noqa: F401 — re-exported for tests and callers
    CustomPackage,
    PackageOption,
    PackageQuestion,
    ParseResponse,
    PasteRequest,
    PlaceRequest,
    questions_for,
    supply_choices,
)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
EXAMPLES = ROOT / "examples"

app = FastAPI(title="AMPierre — schematic to breadboard")


def _http(fn, *args):
    try:
        return fn(*args)
    except service.ServiceError as e:
        raise HTTPException(e.status, str(e)) from e


@app.post("/api/parse", response_model=ParseResponse)
def parse(req: PasteRequest):
    """A pasted netlist: SPICE as LTspice or PSpice writes it, or JSON."""
    return _http(service.from_text, req)


@app.post("/api/netlist", response_model=ParseResponse)
def netlist_route(netlist: Netlist):
    """A netlist drawn in the editor: straight to the part questions."""
    return _http(service.from_netlist, netlist)


@app.post("/api/place", response_model=Layout)
def place_route(req: PlaceRequest):
    return _http(service.lay_out, req)


@app.get("/api/packages")
def packages_route():
    return {
        "packages": [service.option(p).model_dump() for p in pk.ALL_PACKAGES],
        "custom_forms": pk.CUSTOM_FORMS,
        "by_kind": {
            k.value: [p.id for p in pk.options_for(k)] for k in pk.DEFAULT_FOR_KIND
        },
        "defaults": {k.value: v for k, v in pk.DEFAULT_FOR_KIND.items()},
    }


@app.get("/api/examples")
def examples_route():
    return service.examples_index(
        {f.stem: f.read_text(encoding="utf-8") for f in EXAMPLES.glob("*.json")}
    )


@app.get("/api/examples/{name}", response_model=ParseResponse)
def example_route(name: str):
    f = EXAMPLES / f"{Path(name).name}.json"
    if not f.exists():
        raise HTTPException(404, "No such example.")
    netlist = Netlist.model_validate_json(f.read_text(encoding="utf-8"))
    return ParseResponse(netlist=netlist, questions=questions_for(netlist), supplies=supply_choices(netlist))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/about")
@app.get("/about.html")
def about():
    return FileResponse(STATIC / "about.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
