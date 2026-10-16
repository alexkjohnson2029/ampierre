# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary:** students learning to build circuits for the first time, typically early
  electrical engineering students in an intro circuits lab (the creator TAs Electric
  Circuits at Rensselaer Polytechnic Institute). Their job: turn a schematic they drew or
  were handed into a correct, working circuit on a real 830-point breadboard.
- **Also:** instructors and TAs, who can use it alongside students (e.g. checking a build
  against the circuit). Hobbyists and other beginners are welcome but not the design target.

## Product Purpose

AMPierre takes a schematic and shows exactly how to wire it on a breadboard: which holes
each part goes in, which way round it faces, every jumper to cut, and where the bench
supply and wave generator clip on. It then walks the student through the build one step at
a time. Success is a student building the circuit correctly on their own board, and
understanding why each part sits where it does.

## Positioning

- **Deterministic, not generative.** The layout is computed by ordinary code: the same
  netlist always gives the same board, a wrong layout is a reproducible bug, and every board
  is verified against the circuit before it is shown. Nothing is sent to an AI service.
- **Real parts, real pinouts.** A schematic symbol has no pinout; the package does. The app
  asks which physical part is going in (LM741 vs TL072, E-B-C vs C-B-E) wherever the package
  changes the wiring, and shows datasheet-style pinouts to check against.
- **Built for learning.** Step-by-step build order, net highlighting to check each node with
  a multimeter, orientation marks drawn on the board, resistor colour bands and capacitor
  codes shown as they look in the drawer.
- **Not a simulator.** It shows how to build a circuit, not whether the circuit works.

## Operating Context

- Used on a laptop at the lab bench, next to a physical breadboard, parts drawer, bench
  supply, wave generator and multimeter. Phone/tablet use is not a requirement.
- Input comes two ways: an LTspice-style schematic editor in the page (keys follow
  LTspice), or a pasted netlist exported from LTspice, PSpice or written by hand.
- Two-tab flow: **Input** (draw or paste, then pick the real parts) and **Board** (layout,
  build timeline, parts list, warnings). An About page explains the project.
- Boards can be downloaded as SVG (e.g. for a lab report); drawings export to SPICE `.cir`.

## Capabilities and Constraints

- Stack in place: Python 3.11+ FastAPI backend (`app/`, placement in `placer.py`) and a
  vanilla JS/SVG frontend (`static/`), no build step. 185 tests.
- Parts: resistor, capacitor, electrolytic, inductor, potentiometer, diode, LED, NPN, PNP,
  N/P-MOSFET, op-amp, regulator, DC supply, signal generator, ground, net labels; other
  subcircuits become chips with a user-picked pinout.
- Rails: top positive rail is the positive supply, bottom positive rail the negative
  supply, both negative rails ground.
- One layout style: one net per column, easiest to trace.
- **AI:** no AI in the product for now. An LLM step (e.g. reading schematic screenshots)
  may be added later; that is undecided, and any such step must not compromise the
  deterministic, verified layout.
- **Undecided:** deployment target (public site, campus lab, or local only).

## Brand Commitments

- Name: **AMPierre**. Tagline: "Schematic in, breadboard out."
- Voice: plain, direct, bench-practical; written like a TA explaining things to a student,
  not marketing copy. Honest about limits (pinouts can vary, datasheet has the final say).
- Created by Alexander Kim Johnson (AJ); credited on the About page.

## Evidence on Hand

- Example circuits in `examples/`: three-band audio equalizer (AJ's own build, featured;
  8 op-amps in two OP484s, 4 trimmer pots, 38 parts, ±4.5 V supply), full-wave bridge
  rectifier, common-emitter amplifier, non-inverting amplifier.
- No testimonials, usage numbers, course adoptions or press exist. Do not invent them.

## Product Principles

1. **The board must be the circuit.** Correctness and verifiability come before
   cleverness; never show a layout that hasn't been checked.
2. **Teach, don't just answer.** Every screen should help a student understand and check
   their own build, not only copy it.
3. **The physical part is the truth.** Orientation, pinout and package are first-class;
   ambiguity is asked about, never silently guessed.
4. **Calm at the bench.** A student with their hands full should find the next step at a
   glance.

## Accessibility & Inclusion

No formal standard has been set. The audience is students in a teaching lab, so keyboard
access and readable contrast matter; a target (e.g. WCAG 2.1 AA) is undecided.
