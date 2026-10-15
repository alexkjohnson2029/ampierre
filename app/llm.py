"""The LLM wrapper: schematic image -> netlist.

This is the only non-deterministic step in the app, and it is deliberately
the *smallest* step. The model is asked for one thing — what is connected to
what — and never for hole positions. Placement is arithmetic; let arithmetic
do it.
"""

from __future__ import annotations

import base64
import json
import os

from anthropic import Anthropic

from .models import Netlist

DEFAULT_MODEL = os.environ.get("BREADBOARD_MODEL", "claude-sonnet-5-5")

SYSTEM = """You read electronic schematics and return netlists.

You will be shown a screenshot of a schematic, usually from LTspice, PSpice, \
KiCad or a similar tool. Return the circuit as a netlist using the \
emit_netlist tool. Rules:

1. Report only what is drawn. Never add a component that is not in the image \
   (no invented decoupling caps, no invented pull-ups). If the schematic has \
   no explicit ground symbol but clearly has a reference node, say so in \
   warnings rather than inventing one.
2. Give every node a name. Use the schematic's own net labels when they exist. \
   Otherwise invent short readable ones (VIN, VOUT, FB, VB, N1...). Every pin \
   of every component must name a net, and two pins connected by a plain wire \
   must name the SAME net.
3. Supply and ground naming matters: use V+ / VCC for the positive supply, \
   V- / VEE for a negative supply, and GND for the reference — also when the \
   schematic labels the rails just "+" and "-". Put the numeric voltage in the \
   net's voltage field when the schematic shows it (e.g. "+9 V").
4. Voltage sources are not components; list each one in `sources`, with the \
   net on its + terminal as pos, the net on its - terminal as neg, and its value \
   exactly as written ("4.5", "-4.5", "SINE(0 1 1k)", "AC 1", a wavefile). \
   kind is "dc" for a plain DC value and "signal" for anything that varies \
   (SINE, PULSE, AC, PWL, a wavefile). purpose is "power" for a DC source that \
   feeds the op-amp, chip or transistor supply rails, and "input" for one the \
   circuit processes. Only a "power" source becomes a supply rail: an input \
   voltage must never be named or treated as the positive supply. Leave out a \
   source whose terminal connects to nothing (left over from an AC sweep) and \
   say so in warnings. Current sources, probes and .tran/.ac directives are \
   simulation-only: skip them.
5. Use schematic-level pin names, not package pin numbers — you cannot know \
   the package. Op-amps: IN+, IN-, OUT, V+, V-. Three-terminal regulators: IN, OUT, GND. For a dual op-amp drawn as two \
   triangles use IN+A/IN-A/OUT A and IN+B/IN-B/OUT B. BJTs: B, C, E. MOSFETs: \
   G, D, S. Diodes and LEDs: A (anode), K (cathode). Polarised capacitors: + \
   and -. Potentiometers: 1 and 3 for the ends, W for the wiper; leave out an \
   end that connects to nothing. Everything else two-terminal: "1" and "2".
8. SPICE has no knob, so people draw a potentiometer as two resistors in \
   series with the wiper at their junction — often a 1 Ω placeholder for a \
   pot turned fully one way, and often with one end left unconnected. When \
   two resistors meet at a node with nothing else on it but the wiper's \
   connection, or a resistor's far end is left floating next to a 1 Ω \
   resistor, emit ONE potentiometer whose value is their sum (rounded to a \
   stock value: 10k, not 10.001k), and say in warnings which resistors it \
   replaced. Do not emit the floating resistor.
6. Values go in the value field as written on the schematic (10k, 4.7uF, \
   100nF, 2N3904, TL072).
7. If something is genuinely unreadable — a blurry value, a wire you cannot \
   trace, an ambiguous junction — still emit your best netlist and add a \
   specific warning naming the component or net. Do not silently guess.
"""

NETLIST_TOOL = {
    "name": "emit_netlist",
    "description": "Return the circuit shown in the schematic as a netlist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short name for the circuit."},
            "nets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": [
                                "supply_positive",
                                "supply_negative",
                                "ground",
                                "signal",
                                "input",
                                "output",
                            ],
                        },
                        "voltage": {
                            "type": "string",
                            "description": "e.g. '+9 V'. Omit for signal nets.",
                        },
                    },
                    "required": ["name", "role"],
                },
            },
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "R1, C3, U1, Q2"},
                        "kind": {
                            "type": "string",
                            "enum": [
                                "resistor",
                                "capacitor",
                                "polarized_capacitor",
                                "inductor",
                                "potentiometer",
                                "diode",
                                "led",
                                "npn",
                                "pnp",
                                "nmos",
                                "pmos",
                                "opamp",
                                "ic",
                                "regulator",
                            ],
                        },
                        "value": {"type": "string"},
                        "pins": {
                            "type": "object",
                            "description": "logical pin name -> net name",
                            "additionalProperties": {"type": "string"},
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["ref", "kind", "pins"],
                },
            },
            "sources": {
                "type": "array",
                "description": "The voltage sources drawn on the schematic.",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "V1, V3, VIN"},
                        "kind": {"type": "string", "enum": ["dc", "signal"]},
                        "pos": {"type": "string", "description": "net on the + terminal"},
                        "neg": {"type": "string", "description": "net on the - terminal"},
                        "value": {"type": "string", "description": "as written"},
                        "purpose": {"type": "string", "enum": ["power", "input"]},
                    },
                    "required": ["ref", "kind", "pos", "neg"],
                },
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Anything you could not read with confidence.",
            },
        },
        "required": ["title", "nets", "components"],
    },
}


class LLMError(RuntimeError):
    pass


def _client() -> Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMError(
            "ANTHROPIC_API_KEY is not set. Put it in a .env file next to run.py "
            "(see .env.example) or export it in your shell."
        )
    return Anthropic()


def extract_netlist(
    image_bytes: bytes,
    media_type: str = "image/png",
    hint: str | None = None,
    model: str = DEFAULT_MODEL,
) -> Netlist:
    """Read a schematic screenshot and return a Netlist."""
    content: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        {
            "type": "text",
            "text": "Read this schematic and emit its netlist."
            + (f"\n\nExtra context from the user: {hint}" if hint else ""),
        },
    ]

    resp = _client().messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM,
        tools=[NETLIST_TOOL],
        tool_choice={"type": "tool", "name": "emit_netlist"},
        messages=[{"role": "user", "content": content}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_netlist":
            return Netlist.model_validate(block.input)

    text = " ".join(b.text for b in resp.content if b.type == "text")
    raise LLMError(f"The model did not return a netlist. It said: {text[:400]}")


def netlist_from_spice(text: str, model: str = DEFAULT_MODEL) -> Netlist:
    """Same job, but from a pasted SPICE netlist / .asc file instead of a picture."""
    resp = _client().messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM,
        tools=[NETLIST_TOOL],
        tool_choice={"type": "tool", "name": "emit_netlist"},
        messages=[
            {
                "role": "user",
                "content": "Convert this SPICE source into a netlist:\n\n" + text[:40000],
            }
        ],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return Netlist.model_validate(block.input)
    raise LLMError("The model did not return a netlist.")


def dump_schema() -> str:
    return json.dumps(NETLIST_TOOL["input_schema"], indent=2)
