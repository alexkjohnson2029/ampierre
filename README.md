# AMPierre

**Schematic in, breadboard out.**

Draw a schematic on the site the way you would in LTspice, or paste the SPICE netlist
LTspice or PSpice gives you, and get back a top-down breadboard layout: where every part
goes, which way round it faces, and every jumper you have to cut.

The page has two tabs, pinned to the bottom of the window: **Input** (draw or paste the
circuit, pick the real parts) and **Board** (the layout, the build timeline, the parts
list). **About** (top right) explains what the project is for and who made it; the
developer API reference is linked from the bottom of that page.

Everything is ordinary code — no AI model, no API key, nothing sent anywhere. The same
netlist always gives the same board, and a wrong layout is a bug you can reproduce.

```
drawing (editor.js) ─┐
                     ├─► Netlist ──► placer.py ──► Layout ──► breadboard.js ──► SVG
SPICE text (spice.py)┘    (JSON)    (arithmetic)   (JSON)      (renderer)
                                        │
                                        └─► breadboard.verify() — proves the board
                                            is the circuit before you plug it in
```

## Setup

You need Python 3.11+.

```bash
cd schematic2breadboard
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 run.py                # http://127.0.0.1:8000
```

From the terminal:

```bash
python3 -m app.cli examples/three_band_equalizer.json      # build steps
python3 -m pytest -q                                       # 185 tests
```

### Exporting a board without the browser

```bash
python3 -m app.cli examples/common_emitter.json -o layout.json -q
node tools/render_example.mjs layout.json board.svg
```

Needs Node 18+. Handy for dropping a board into a lab report.

## Using it

### Drawing the schematic

**Draw the schematic** (the default on the Input tab) is an LTspice-style editor. A drawing
is already a netlist, so it goes straight to step 2.

- Parts: resistor, capacitor, electrolytic, inductor, potentiometer, diode, LED, NPN, PNP,
  N/P-MOSFET, op-amp, regulator, DC supply, signal generator, ground and net labels.
- Keys follow LTspice: `R` `C` `L` `D` place parts, `G` ground, `V` DC supply, `W` (or F3)
  wire, `N` (or F4) net label, Ctrl+R rotate, Ctrl+E mirror, Delete (or F5) delete, Esc
  back to select, Ctrl+Z / Ctrl+Y undo and redo. Drag to move a part (its wires stretch
  with it), drag empty space to pan, scroll to zoom.
- Connections work like LTspice: wires join at their ends or where an end lands on another
  wire (a dot is drawn), crossing wires don't join, and labels with the same name are the
  same net. A pin connected to nothing gets a small red square.
- A DC supply wired to ground names its net V+ or V- (by the sign of its voltage) and goes
  on a rail; untick "Powers the circuit" for a test voltage. A signal generator's net is VIN.
- The drawing saves itself in the browser. **Save file** / **Open file** keep a copy, and
  **Export SPICE** writes a `.cir` deck you can open in LTspice.

The editor lives in `static/editor.js`; the symbols, connectivity and the netlist and SPICE
conversion are in `static/schematic.js`. `POST /api/netlist` takes the result.

### Pasting a netlist

**Paste a netlist** takes SPICE text: in LTspice, **View → SPICE Netlist**, copy it all and
paste. PSpice `.cir`/`.net` files and hand-written netlists work too, as does a JSON netlist
saved from this app. `app/spice.py` reads it with no guessing where the netlist is explicit:

- `R`, `C`, `L`, `D`, `Q`, `M`, `V` lines become parts and bench instruments; node `0` is GND.
- `X` lines are subcircuits. Five nodes is an op-amp, in LTspice's order (In+ In− V+ V− Out);
  78xx/LM317-style names with three nodes are regulators; anything else becomes a chip whose
  pinout you pick on the next screen.
- NPN or PNP, N- or P-channel: from the netlist's `.model` lines, then the part number
  (2N3906 is PNP, BS250 is P-channel…). Anything still a guess is listed under "Check these".
- SPICE suffixes are read the SPICE way: `1Meg` is a megohm, `1M` is a milliohm.
- Simulation-only lines (`.tran`, `.ac`, `I` sources, controlled sources, `.subckt` bodies)
  are skipped, and the warnings say which.

### Then

1. **Pick the real parts.** Choices on the left, the pinout of whichever one is selected
   on the right, so you can check the two against each other without scrolling. A triangle on a schematic has no pinout. An op-amp could be
   an LM741 (output on pin 6) or a TL072 (output on pin 1), and a TO-92 transistor is
   E–B–C or C–B–E depending on which one you grabbed from the drawer. The app asks about
   every part where the package changes the wiring, and pre-selects a guess from the
   value field.
   Identical parts are asked about once — four 1N4007s in a bridge are one question, not
   four. Each choice shows a datasheet-style pinout drawn from the package's own pin data,
   with the pins your circuit uses picked out and the net names on them. If your part
   isn't in the list, choose **My own part** and type the pinout: name, package, pin count,
   and which physical pin each schematic pin goes to.
2. **Build the board.** Hover anything: rails show what they supply, ICs and transistors
   show their pinout and orientation, passives show their value and colour code. Hovering
   also lights up everything else on the same net, which is the fastest way to check a
   built board against the schematic.
3. **Step through it.** The timeline under the board adds one part or one jumper at a
   time. Drag the slider, press Play, click a chip in the strip, or use the arrow keys.
   Parts already placed are solid and the current one is ringed; anything not placed yet
   is simply absent, so the board looks like your board does. Tick **Ghost upcoming
   parts** to see what's coming, faintly, where it will go. "Show whole board" goes back.
   The last steps hook up the instruments — the bench supply first, then the wave
   generator — after a continuity check.

### The featured build

The first example, marked **AJ's build**, is the three-band audio equalizer AMPierre's
creator designed in LTspice and built on a breadboard: an input amp, bass/mid/treble
filters with a trimmer each, three buffers, a summing amp and a clip LED — eight op-amps
in two OP484s, 34 parts. `/?example=three_band_equalizer` opens it straight on the board,
and the About page shows it with a live preview.

Its board was laid out by hand (`layout` in the example's JSON) and comes out with no
diagonal jumpers, no crossings and nothing lying over a part. See
[Hand-laid boards](#hand-laid-boards).

### Bench instruments

Schematics draw supplies and signal generators as voltage sources. The netlist lists them
in `sources`, and only a **DC source that powers the circuit** — one feeding an op-amp's
or chip's supply pins, or a transistor stage's Vcc — gets a rail. A wave generator, or a
second DC channel used as an input voltage, is an input: it clips onto the strip of the
net it drives, never onto a rail, even if the netlist called that net a supply. The board
shows every clip as a cable from off the board with a tag (`+4.5 V`, `COM`, `GEN`,
`GEN ⏚`), and the build order hooks them up last: supply off, continuity check, supply,
generator, then "supply on first".

A negative supply drawn LTspice-style — the + end on the net with a value of −4.5 — is
recognised as negative and goes on the bottom + rail. A generator whose ground isn't
circuit ground (the AC into a bridge rectifier) gets a note about scope-ground shorts.

### Potentiometers

Trimmers (three pins in a row, 0.1" apart) and panel pots (legs to bend) are in the
library, pins `1`, `W` (wiper), `3`. A pot used as a variable resistor — one end left
unconnected, as on the equalizer — still has three legs in the board; the spare one gets
a strip to itself so nothing else can land on it.

SPICE has no knob, so LTspice users often draw a pot as two resistors with the wiper at
the junction, often a 1 Ω placeholder and a floating end. Draw it with the editor's
potentiometer instead, so it comes through as one part.

### Op-amps drawn one at a time

A schematic draws every op-amp as its own triangle. When several are given a dual or
quad package, `app/gates.py` puts them in shared chips — section A, B, C, D in turn, on
one pair of supply pins — so eight op-amps on a quad become two chips, not eight. Only
op-amps on the same supply nets are combined. A quad is placed **turned round** (notch to
the right) when that puts its V+ pin beside the top + rail and V− beside the bottom one.

## Board conventions

Standard 830-point board, 63 columns, rows A–E below the channel and F–J above.

| Rail | Carries |
| --- | --- |
| top `+` | positive supply |
| top `−` | ground |
| bottom `−` | ground |
| bottom `+` | **negative supply** |

The two ground rails are separate copper, so the placer bonds them whenever both are
used — with one jumper from rail to rail, or through an empty column (a drop from each
rail and a jumper across the channel) when no column is clear all the way. Many boards
also split each rail at the middle — if yours does, bridge it.

Rows are rationed by job, which is what keeps the result readable:

```
J  rail jumpers          F  IC pins (top half)
I  signal jumpers        E  IC pins (bottom half)
H  parts                 D  parts
G  parts                 C  parts
F  IC pins               B  signal jumpers
                         A  rail jumpers
```

## How the board is laid out

The default layout follows the schematic. A schematic reads top to bottom: supply, then
the parts, then ground. On the board that becomes **parts hanging from the supply rail at
the top, the transistors and chips in the middle, and parts standing on the ground rail
at the bottom**, with every other net in its own column so you can read the circuit off
the board the way you read the drawing.

The engine is `app/flow.py`:

1. **Rank the nets** by how many parts away from the supply they are (breadth-first from
   `VCC`/`V+`). Ground is forced to the far end.
2. **Group into blocks.** A transistor or IC is one block — its legs must sit in
   neighbouring strips in pinout order. Every other net is a one-column block.
3. **Order the blocks.** Each net hanging off a transistor or IC goes right beside it, on
   whichever side its connections lean towards — so a common-emitter stage comes out
   *input, then E-B-C, then output*, the way it's drawn. Nets that only connect to each
   other stay together; loose nets drift towards whatever they connect to. A circuit
   with no transistor or chip is arranged around its busiest net. Then each block is
   tried in every other position, keeping any move that shortens the total wiring.
4. **Hand out columns** with a fixed gap between blocks — 5 in **Spacious**, 3 in
   **Compact** — nudging a block over a column or two so its strips line up with real rail
   holes (the rails skip one every sixth column).
5. **Plug parts into the rails.** A part with one end on supply or ground stands upright
   between the rail and the strip of its other net — a pull-up from the top + rail, a
   resistor to ground on the bottom − rail — so that end needs no jumper. These go in
   first, because each has exactly one place it can stand.
6. **Place everything else.** Each remaining part spans its two nets' columns, on the side
   of the channel where more of its nets already have a strip. If its row is crowded it
   slides a few columns, giving its net a second strip joined by a jumper.
7. **Route the jumpers** (`placer.py`). Every jumper is laid like a part: **flat along one
   row or straight down one column**, with the holes it lies across reserved, so no other
   jumper can overlap it and nothing ends underneath it. Drops to the rails go first
   (their column is fixed), then straight drops across the channel, then flat runs along
   the board, longest first. A link between different columns on opposite sides becomes
   an L: a flat run, then a straight drop. Only if none of that fits does a jumper go
   diagonal.
8. **Keep the cleanest.** The board is laid out six ways (parts plugged into the rails
   always, only where the strip keeps room for the rest of its net, or never; with and
   without the rail-gap nudge), each is scored by `app/quality.py` — diagonal jumpers,
   crossings, wires over parts, wire count — and the cleanest wins. Jumpers are planned
   per net as the shortest set of links that no strip has to give more holes to than it
   has left.
9. **Verify.** `breadboard.verify()` proves every net is one node with no shorts. Spare
   pins on a chip get a node of their own, so anything landing in an unused pin's strip
   is caught as a short.

If a circuit can't be laid out this way, the other spacings are tried, then it is packed
tightly instead (the older `placer.py` algorithm) with a note saying so — you never get a
wrong board, only a less pretty one. A jumper that can't lie flat goes corner to corner,
and is drawn **arched**, on top of the parts with a shadow, the way a flexible jumper wire
hops over the board.

Across the five examples in both modes, this took the board from 70 jumpers (19 of them
diagonal, 23 running over a part) to 50 (3 diagonal, none over a part). The remaining
diagonals are real squeezes — seven parts meeting at a transistor's three legs fill every
hole in its strips.

**Spacious vs Compact** (toggle above the board): same shape, different gap between net
columns. Spacious leaves room to see every lead and trace a node by eye; Compact uses
fewer columns and gets more circuit in view. Compact also keeps a circuit with no IC
entirely **above the channel**, unless that would make the wiring worse (diagonals,
crossings or wires over parts the two-half layout doesn't need) — then it uses both
halves. Op-amp circuits always use both, since the chip straddles
the channel. From the terminal: `--style flow`, `--style flow-compact`, or
`--style packed`.

Board conventions that hold in every mode:

- DIP ICs straddle the centre channel, notch to the left with pin 1 in row E — or turned
  round, notch right, when that puts the supply pins beside their rails (quad op-amps).
- Radial parts (LEDs, disc and electrolytic caps) plug into a rail and the first row in;
  axial ones stand 3.5 pitches out, over the holes they cover.
- Parts are drawn at real size — resistors carry their four colour bands worked out from
  the value, ceramics show their three-digit code, electrolytics are cans with the stripe
  on the negative side, diodes have the cathode band, LEDs have the flat. Leads stretch;
  bodies don't.
- Polarised parts are marked on the board itself: `A —[ body ]— K` beside a diode or
  LED, `+` and `−` on an electrolytic, always on the side the lead actually landed.

## Hand-laid boards

A netlist may carry a `layout`: where each part goes and the jumpers, written the way
you'd plan it on paper.

```jsonc
"layout": {
  "parts": {
    "IC1": {"col": 21, "flip": true},          // leftmost column; flip = notch right
    "R6":  {"1": "H22", "2": "H17"},           // a part lying in a row
    "C6":  {"1": "J14", "2": "T-14"},          // plugged into a rail: T+ T- B- B+
    "RV2": {"1": "E4"}                         // a three-lead part: one hole is enough
  },
  "wires": [["J21", "J18"], ["I14", "I33"]]
}
```

`app/handlaid.py` checks every hole before anything goes in it, keeps each strip to one
net, routes whatever the plan left unjoined, drops supply and ground strips to their
rails, and verifies the result. A plan that doesn't fit — because someone picked a
different chip, say — is dropped and the automatic layout is used instead.

## Files

| Path | What it is |
| --- | --- |
| `app/breadboard.py` | The connectivity model: holes, strips, rails, and the verifier |
| `app/packages.py` | Package library — op-amps (incl. OP484), 555, 74HCxx, regulators, TO-92, diodes |
| `app/values.py` | "10k" → 10000 Ω → brown-black-orange-gold; capacitor codes and body styles |
| `app/flow.py` | Schematic-shaped placement (the default): net ranking, block ordering, rail-mounted parts |
| `app/sources.py` | Bench instruments: which sources get a rail, where each lead clips on, hook-up steps |
| `app/gates.py` | Puts op-amps drawn one at a time into shared dual and quad chips |
| `app/handlaid.py` | Places a board from a hand-made plan, checking every hole |
| `app/quality.py` | Scores a layout's wiring — diagonals, crossings, wires over parts — to pick the cleanest |
| `app/placer.py` | Packed placement, routing, build order — and the fallback when flow can't fit |
| `app/spice.py` | Reads a pasted SPICE (or JSON) netlist into a `Netlist` |
| `app/models.py` | Pydantic types shared by all of the above |
| `app/main.py` | FastAPI routes |
| `app/cli.py` | Terminal entry point |
| `static/breadboard.js` | Layout → SVG, whole or partway through the build. Runs in browser and node |
| `static/pinout.js` | Datasheet-style pinout drawings, generated from package data |
| `static/about.html` | About page: purpose, how to learn with it, credits |
| `static/app.js` | Draw/paste switch, package picker, custom pinouts, timeline, hover, net highlighting |
| `static/editor.js` | The LTspice-style drawing editor |
| `static/schematic.js` | Editor symbols, connectivity, drawing → netlist and SPICE |
| `examples/*.json` | Example netlists, one click away on the Input tab |
| `tests/` | pytest suite over the SPICE reader, the pinouts, placement and the verifier |

## Putting it online

GitHub stores the code. It does **not** run it — this is a Python server, so GitHub Pages
(static files only) can't host it.

Running it somewhere other than your laptop needs a host that executes Python — Render,
Railway, Fly.io and Hugging Face Spaces all have free or near-free tiers. The shape is the
same everywhere: point the host at the repo and set the start command to
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. There are no secrets to configure.

## Known limits

- One board, 63 columns. Circuits bigger than that report "no room left" rather than
  spilling onto a second board.
- Big circuits come out correct but busy from the automatic layout: the three-band
  equalizer without its hand plan has around 15 diagonal jumpers. The placer is greedy;
  a circuit with two quad op-amps has more arrangements than it searches.
- Headers, crystals and SIP packages aren't in the library yet; add them to
  `packages.py` and they flow through everything else. In the meantime, "My own part"
  covers anything with a DIP, TO-92 or TO-220 footprint.
- Outputs (a speaker, a scope probe) aren't drawn as instruments yet — only sources.
- Pinouts in the library are the common ones, but second sources differ. Every pinout is
  shown before anything is placed precisely so you can check it against the datasheet.
- Jumper routing is a nearest-neighbour chain, not a shortest-total-length solve. It's
  correct, not optimal.
- A SPICE netlist doesn't always say what a subcircuit is. Op-amps, regulators and pots
  are recognised by pin count and name; anything else comes through as a chip you give a
  pinout to, and every guess is listed under "Check these".

## Next, in rough order

1. Import an LTspice `.asc` file into the editor, so a schematic opens as a drawing.
2. Smarter placement for big circuits: choose which op-amp goes in which section, and
   which way round each chip faces, by searching for the shortest wiring.
3. Output markers (speaker, scope probe) next to the input clips.
4. Export the board as a printable PDF, plus a parts list with values.