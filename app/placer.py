"""Deterministic placement and routing: Netlist -> Layout.

No model calls happen here. Given the same netlist you get the same board,
every time, and `breadboard.verify()` proves the board is the circuit.

The strategy is the one a person uses at the bench:

  1. ICs go down first, straddling the centre channel, left to right.
  2. Every net gets an *anchor strip*. A later lead on the same net lands in
     that same strip instead of needing a jumper.
  3. Discrete parts are placed near the strips they already connect to.
  4. Whatever is still split is joined with jumpers, and rail nets are
     dropped to the rails.
  5. Rows are rationed by job (parts / jumpers / rail jumpers) so the board
     stays readable instead of becoming a bird's nest.
"""

from __future__ import annotations

from collections import defaultdict

from . import breadboard as bb
from . import packages as pk
from . import sources as src_mod
from . import values as val
from .models import (
    BuildStep,
    Component,
    ComponentKind,
    Hole,
    Layout,
    Net,
    NetRole,
    Netlist,
    PlacedComponent,
    PlacedPin,
    Wire,
)

# ---------------------------------------------------------------------------
# Net roles and colours
# ---------------------------------------------------------------------------

_POS_NAMES = {"V+", "VCC", "VDD", "VS+", "VPLUS", "VBAT", "VIN+", "+V"}
_NEG_NAMES = {"V-", "VEE", "VSS", "VS-", "VMINUS", "-V"}
_GND_NAMES = {"GND", "0", "AGND", "DGND", "GROUND", "COM", "VGND"}

COLOR_POS = "#dc2626"
COLOR_NEG = "#2563eb"
COLOR_GND = "#111827"

#: Closest an axial part's leads can be while it lies flat along a row: a
#: quarter-watt resistor or an axial diode has a body about 6 mm long, and
#: three holes are 7.6 mm. Closer than that it has to stand on end.
AXIAL_FLAT_GAP = 3

THREE_LEAD = ("to92", "to220", "pot")
#: How many rows past its leads a three-lead body covers, away from the channel.
BODY_OVERHANG = {"to92": 1, "to220": 1, "pot": 2}
SIGNAL_COLORS = ["#f59e0b", "#059669", "#7c3aed", "#0891b2", "#db2777", "#65a30d"]


def infer_role(name: str) -> NetRole:
    u = name.strip().upper()
    if u in _GND_NAMES:
        return NetRole.GROUND
    if u in _POS_NAMES:
        return NetRole.SUPPLY_POS
    if u in _NEG_NAMES:
        return NetRole.SUPPLY_NEG
    # +9V / -12V style names
    if u.startswith("+") and u.rstrip("V").lstrip("+").replace(".", "").isdigit():
        return NetRole.SUPPLY_POS
    if u.startswith("-") and u.rstrip("V").lstrip("-").replace(".", "").isdigit():
        return NetRole.SUPPLY_NEG
    return NetRole.SIGNAL


def default_voltage(name: str, role: NetRole) -> str | None:
    u = name.strip().upper()
    if u.startswith(("+", "-")) and u.endswith("V"):
        return f"{u[0]}{u[1:-1]} V"
    if role is NetRole.GROUND:
        return "0 V"
    return None


RAIL_FOR_ROLE = {
    NetRole.SUPPLY_POS: [bb.RAIL_TOP_POS],
    NetRole.SUPPLY_NEG: [bb.RAIL_BOT_POS],
    NetRole.GROUND: [bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG],
}


# ---------------------------------------------------------------------------
# Placer
# ---------------------------------------------------------------------------


class Placer:
    IC_START_COL = 4
    IC_GAP = 4  # free columns between ICs

    def __init__(
        self,
        netlist: Netlist,
        custom: dict[str, pk.Package] | None = None,
    ):
        self.custom = custom or {}
        self.nl = self._with_every_lead(netlist)
        self.board = bb.Breadboard()
        self.placed: list[PlacedComponent] = []
        self.wires: list[Wire] = []
        self.component_steps: list[tuple[str, str]] = []  # (ref, instruction)
        self.warnings: list[str] = []  # placement problems
        self.notes: list[str] = list(netlist.warnings)  # caveats from the netlist

        # net name -> Net (roles filled in)
        self.nets: dict[str, Net] = {}
        for name in self._all_net_names():
            declared = next((n for n in netlist.nets if n.name == name), None)
            role = declared.role if declared else infer_role(name)
            voltage = (declared.voltage if declared else None) or default_voltage(name, role)
            self.nets[name] = Net(name=name, role=role, voltage=voltage)

        # Only a DC source that powers the circuit gets a supply rail; inputs
        # (wave generators, test voltages) are wired into their own strips.
        self.sources: list[src_mod.Resolved] = []
        self.leads = []
        self.notes.extend(src_mod.classify(self))

        # (half, col) -> net name. The anchor table that keeps jumper count down.
        self.strip_net: dict[tuple[str, int], str] = {}
        # net name -> list of (half, col) strips it occupies
        self.net_strips: dict[str, list[tuple[str, int]]] = defaultdict(list)

        self._signal_color: dict[str, str] = {}
        #: leftmost column a part spanning two rails may use
        self.rail_part_from = 1

    # -- helpers ------------------------------------------------------------

    def _with_every_lead(self, netlist: Netlist) -> Netlist:
        """A copy of the netlist in which every three-lead part lists all
        three of its leads, under the package's own names.

        A transistor or pot always has three legs on the board, whatever the
        schematic uses. A leg the schematic leaves unconnected — the spare end
        of a pot wired as a variable resistor — still goes in a hole, and that
        hole's strip must stay empty, so it gets a node of its own exactly
        like a spare chip pin.
        """
        nl = netlist.model_copy(deep=True)
        for comp in nl.components:
            pkg = self.package_for(comp)
            if pkg.form not in THREE_LEAD:
                continue
            by_number: dict[int, str] = {}
            for logical, net in comp.pins.items():
                number = pk.resolve_pin(pkg, logical)
                if number is None:
                    by_number = {}
                    break  # names we can't place: leave the part as the schematic has it
                by_number[number] = net
            if not by_number:
                continue
            canonical = {num: name for name, num in pkg.pin_map.items()}
            comp.pins = {
                canonical[n]: by_number.get(n, unused_net(comp.ref, n))
                for n in sorted(canonical)
            }
        # The unused ends are placed like any lead, but they are not nets of
        # the circuit: the hover cards and the role table never list them.
        self._spare_leads = {
            net for c in nl.components for net in c.pins.values() if is_unused(net)
        }
        return nl

    def _all_net_names(self) -> list[str]:
        seen: list[str] = []
        for c in self.nl.components:
            for net in c.pins.values():
                if net not in seen and not is_unused(net):
                    seen.append(net)
        return seen

    def package_for(self, comp: Component) -> pk.Package:
        """The user's own pinout wins over anything in the library."""
        if comp.ref in self.custom:
            return self.custom[comp.ref]
        return pk.get(comp.package, comp.kind)

    def role(self, net: str) -> NetRole:
        if net not in self.nets:  # a spare chip pin's own node
            return NetRole.SIGNAL
        return self.nets[net].role

    def is_rail_net(self, net: str) -> bool:
        return self.role(net) in RAIL_FOR_ROLE

    def color(self, net: str) -> str:
        role = self.role(net)
        if role is NetRole.SUPPLY_POS:
            return COLOR_POS
        if role is NetRole.SUPPLY_NEG:
            return COLOR_NEG
        if role is NetRole.GROUND:
            return COLOR_GND
        if net not in self._signal_color:
            self._signal_color[net] = SIGNAL_COLORS[len(self._signal_color) % len(SIGNAL_COLORS)]
        return self._signal_color[net]

    def claim_strip(self, half: str, col: int, net: str) -> None:
        if (half, col) not in self.strip_net:
            self.strip_net[(half, col)] = net
            self.net_strips[net].append((half, col))

    def strip_ok_for(self, half: str, col: int, net: str) -> bool:
        """Can a lead on `net` land in this strip without shorting anything?"""
        owner = self.strip_net.get((half, col))
        if owner is not None and owner != net:
            return False
        # Keep one hole in reserve: nearly every strip needs a jumper later,
        # and discovering that after the fact means re-placing the board.
        return self.board.strip_has_room(half, col, 2)

    def holes_still_needed(self, net: str, besides: str | None = None) -> int:
        """Strip holes this net will still need: a hole for every lead on it
        not yet placed, plus one for each instrument lead clipped onto it."""
        placed = {c.ref for c in self.placed}
        pins = sum(
            1
            for comp in self.nl.components
            if comp.ref not in placed and comp.ref != besides
            for n in comp.pins.values()
            if n == net
        )
        clips = sum(
            1
            for s in self.sources
            if s.purpose != "power"
            for terminal in (s.pos, s.neg)
            if terminal == net and self.role(net) is not NetRole.GROUND
        )
        return pins + clips

    def pick_row(self, half: str, col: int, preferred: tuple[str, ...]) -> str | None:
        row = self.board.free_hole_in_strip(half, col, preferred)
        if row:
            return row
        row = self.board.free_hole_in_strip(half, col, bb.strip_rows(half))
        if row:
            return row
        return self.board.reclaim_soft(half, col)

    # -- phase A: ICs -------------------------------------------------------

    def place_ics(self) -> None:
        col = self.IC_START_COL
        for comp in self.nl.components:
            pkg = self.package_for(comp)
            if not pkg.straddles_channel:
                continue
            half_pins = pkg.pin_count // 2
            start = self.board.free_run_both_halves(col, half_pins)
            if start is None:
                self.warnings.append(f"{comp.ref}: no room on the channel — not placed.")
                continue
            self._emit_ic(comp, pkg, start)
            col = start + half_pins + self.IC_GAP

    def ic_flipped(self, comp: Component, pkg: pk.Package) -> bool:
        """Should this chip go in turned round, notch to the RIGHT?

        The positive supply rail runs along the top of the board and the
        negative one along the bottom. A dual op-amp or a 555 already has its
        V+ pin on the top row; a quad op-amp (V+ on pin 4) has it on the
        bottom row, and its V− on top — every supply wire would cross the
        whole board. Turned round, both pins sit next to their own rails.
        """
        half_pins = pkg.pin_count // 2
        pull = 0
        for logical, net in comp.pins.items():
            number = pk.resolve_pin(pkg, logical)
            if number is None:
                continue
            top_normally = number > half_pins
            role = self.role(net)
            if role is NetRole.SUPPLY_POS:
                pull += -1 if top_normally else 1
            elif role is NetRole.SUPPLY_NEG:
                pull += 1 if top_normally else -1
        return pull > 0

    @staticmethod
    def ic_slot(pkg: pk.Package, number: int, flipped: bool) -> tuple[str, int]:
        """(half, offset from the chip's leftmost column) for a pin number.

        Notch left: pins 1..n/2 run left to right along the bottom row, the
        rest come back right to left along the top. Notch right is the same
        chip turned through 180°.
        """
        half_pins = pkg.pin_count // 2
        if number <= half_pins:
            half, offset = "bottom", number - 1
        else:
            half, offset = "top", pkg.pin_count - number
        if flipped:
            half = "top" if half == "bottom" else "bottom"
            offset = half_pins - 1 - offset
        return half, offset

    def _emit_ic(
        self, comp: Component, pkg: pk.Package, start: int, flipped: bool | None = None
    ) -> None:
        """Commit a DIP straddling the channel; `start` is its leftmost column."""
        if True:
            half_pins = pkg.pin_count // 2
            if flipped is None:
                flipped = self.ic_flipped(comp, pkg)

            def hole_for(number: int) -> tuple[str, str, int]:
                half, offset = self.ic_slot(pkg, number, flipped)
                row = bb.TOP_IC_ROW if half == "top" else bb.BOTTOM_IC_ROW
                return row, half, start + offset

            pins: list[PlacedPin] = []
            used_numbers: dict[int, str] = {}
            for logical, net in comp.pins.items():
                number = pk.resolve_pin(pkg, logical)
                if number is None:
                    self.warnings.append(
                        f"{comp.ref}: pin '{logical}' is not on {pkg.label} — left unplaced."
                    )
                    continue
                if number in used_numbers:
                    self.warnings.append(
                        f"{comp.ref}: pins '{used_numbers[number]}' and '{logical}' both "
                        f"resolve to physical pin {number}."
                    )
                used_numbers[number] = logical

                row, half, c = hole_for(number)
                self.board.occupy(row, c, comp.ref)
                self.claim_strip(half, c, net)
                pins.append(
                    PlacedPin(
                        name=logical,
                        number=number,
                        net=net,
                        hole=Hole(row=row, col=c),
                        label=pkg.pin_names.get(number, logical),
                    )
                )

            # The pins the circuit doesn't use are still physically in the
            # board. Each gets its strip to itself: anything else landing there
            # would be wired to that pin — harmless on a no-connect, a fight
            # with a live output on an unused op-amp channel. Giving it a node
            # of its own means the verifier calls that out as a short.
            for number in range(1, pkg.pin_count + 1):
                if number in used_numbers:
                    continue
                row, half, c = hole_for(number)
                spare = unused_net(comp.ref, number)
                self.board.occupy(row, c, comp.ref)
                self.claim_strip(half, c, spare)
                pins.append(
                    PlacedPin(
                        name=f"pin {number}",
                        number=number,
                        net=spare,
                        hole=Hole(row=row, col=c),
                        label=pkg.pin_names.get(number, f"Pin {number}"),
                    )
                )

            self.placed.append(
                PlacedComponent(
                    ref=comp.ref,
                    kind=comp.kind,
                    package=pkg.id,
                    value=comp.value or pkg.label,
                    pins=sorted(pins, key=lambda p: p.number or 0),
                    orientation=self._ic_orientation(pkg, start, flipped),
                    body={
                        "form": "dip",
                        "anchor_col": start,
                        "span": half_pins,
                        "notch": "right" if flipped else "left",
                        "pin_names": {str(k): v for k, v in pkg.pin_names.items()},
                        "package_label": pkg.label,
                        "note": pkg.note,
                    },
                )
            )
            pin1_row, _, pin1_col = hole_for(1)
            self.component_steps.append(
                (
                    comp.ref,
                    f"Straddle {comp.ref} ({comp.value or pkg.label}) across the centre "
                    f"channel, notch facing {'RIGHT' if flipped else 'LEFT'} — pin 1 in "
                    f"{pin1_row}{pin1_col}.",
                )
            )

    @staticmethod
    def _ic_orientation(pkg: pk.Package, start: int, flipped: bool) -> str:
        end = start + pkg.pin_count // 2 - 1
        if not flipped:
            return (
                f"Notch / pin-1 dot faces LEFT, at column {start}. "
                f"Pin 1 is {bb.BOTTOM_IC_ROW}{start}; pin {pkg.pin_count} is "
                f"{bb.TOP_IC_ROW}{start} directly above it."
            )
        return (
            f"Turned round: notch / pin-1 dot faces RIGHT, at column {end}. "
            f"Pin 1 is {bb.TOP_IC_ROW}{end}; pin {pkg.pin_count} is "
            f"{bb.BOTTOM_IC_ROW}{end} directly below it. That puts V+ beside the top "
            "+ rail and V− beside the bottom one."
        )

    # -- phase B: discretes -------------------------------------------------

    def preferred_half(self, comp: Component) -> str:
        votes = {"top": 0, "bottom": 0}
        for net in comp.pins.values():
            for half, _ in self.net_strips.get(net, []):
                votes[half] += 2
            role = self.role(net)
            if role is NetRole.SUPPLY_POS:
                votes["top"] += 1
            elif role is NetRole.SUPPLY_NEG:
                votes["bottom"] += 1
        if votes["top"] == votes["bottom"]:
            return "top"
        return "top" if votes["top"] > votes["bottom"] else "bottom"

    def desired_column(self, comp: Component) -> int:
        cols = [c for net in comp.pins.values() for _, c in self.net_strips.get(net, [])]
        return round(sum(cols) / len(cols)) if cols else self.IC_START_COL

    def _column_search_order(self, desired: int) -> list[int]:
        cols = list(range(1, self.board.columns + 1))
        return sorted(cols, key=lambda c: (abs(c - desired), c))

    def place_discretes(self) -> None:
        remaining = [
            c
            for c in self.nl.components
            if not self.package_for(c).straddles_channel
        ]
        # greedy: always place the part with the most already-anchored nets, so
        # placement grows outward from the ICs instead of scattering
        while remaining:
            remaining.sort(
                key=lambda c: -sum(1 for n in c.pins.values() if self.net_strips.get(n))
            )
            comp = remaining.pop(0)
            self.place_one_discrete(comp)

    def place_one_discrete(self, comp: Component) -> None:
        pkg = self.package_for(comp)
        names = self._lead_order(comp, pkg)
        nets = [comp.pins[n] for n in names]

        if len(names) == 2 and self._try_rail_to_rail(comp, pkg, names, nets):
            return

        half = self.preferred_half(comp)
        desired = self.desired_column(comp)
        span = max(pkg.span, len(names))

        other = "bottom" if half == "top" else "top"
        placement = part_rows = None
        # Try the preferred half first, then the other one, and only then give
        # up a row of the jumper lane. Parts stay out of the lanes reserved for
        # wiring unless the board is genuinely tight.
        for candidate_half, rows in (
            (half, self._part_rows(half)),
            (other, self._part_rows(other)),
            (half, self._part_rows(half, relaxed=True)),
            (other, self._part_rows(other, relaxed=True)),
        ):
            placement = self._find_slot(candidate_half, desired, span, nets, rows)
            if placement is not None:
                half, part_rows = candidate_half, rows
                break
        if placement is None:
            self.warnings.append(f"{comp.ref}: no room left on the board — not placed.")
            return
        self._emit_discrete(comp, pkg, names, nets, half, placement, part_rows)

    def _emit_discrete(
        self,
        comp: Component,
        pkg: pk.Package,
        names: list[str],
        nets: list[str],
        half: str,
        cols: list[int],
        part_rows: tuple[str, ...],
        force_row: str | None = None,
    ) -> bool:
        """Commit a part to chosen columns: occupy holes, build the drawing
        hints, write the build step. Every placement strategy ends up here."""
        footprint = list(range(min(cols), max(cols) + 1))
        shared_row = force_row or self._row_free_across(half, footprint, part_rows)
        pins: list[PlacedPin] = []
        for logical, net, c in zip(names, nets, cols):
            row = shared_row or self.pick_row(half, c, tuple(part_rows))
            if row is None:
                self.warnings.append(f"{comp.ref}: strip {half}:{c} is full — not placed.")
                return False
            self.board.occupy(row, c, comp.ref)
            self.claim_strip(half, c, net)
            pins.append(
                PlacedPin(
                    name=logical,
                    number=pk.resolve_pin(pkg, logical) if pkg.form in THREE_LEAD else None,
                    net=net,
                    hole=Hole(row=row, col=c),
                    label=self._lead_label(pkg, logical),
                )
            )

        # The part's body lies across the holes between its leads. Mark them
        # taken so a second part isn't placed in the same physical space --
        # two resistors can share a row, but not the same stretch of it.
        if shared_row:
            for c in range(min(cols) + 1, max(cols)):
                if self.board.is_free(shared_row, c):
                    self.board.occupy(shared_row, c, f"body:{comp.ref}")
            # One clear column at each end: leads need room to bend, and the
            # A/K marks printed beside them need somewhere to go.
            for c in (min(cols) - 1, max(cols) + 1):
                if self.board.is_free(shared_row, c):
                    self.board.occupy(shared_row, c, f"gap:{comp.ref}")
            if pkg.form in THREE_LEAD:
                # A three-lead body is taller than its row: a TO-92 can
                # overhangs the next row out, a trimmer the next two. Nothing
                # else may sit there — rail holes included, if it reaches them.
                i = bb.ROW_ORDER.index(shared_row)
                step = -1 if half == "top" else 1
                for k in range(1, BODY_OVERHANG.get(pkg.form, 1) + 1):
                    j = i + step * k
                    if not 0 <= j < len(bb.ROW_ORDER):
                        break
                    for c in cols:
                        if self.board.valid(bb.ROW_ORDER[j], c) and self.board.is_free(
                            bb.ROW_ORDER[j], c
                        ):
                            self.board.occupy(bb.ROW_ORDER[j], c, f"body:{comp.ref}")

        body = {
            "form": pkg.form,
            "half": half,
            "value_info": val.describe(comp.kind.value, comp.value, pkg.polarized),
            "cols": cols,
            "rows": [p.hole.row for p in pins],
            "polarized": pkg.polarized,
            "marker": pkg.marker,
            "package_label": pkg.label,
            "note": pkg.note,
        }
        if pkg.form in THREE_LEAD:
            body["flat_face"] = "toward viewer"
            body["lead_order"] = [p.name for p in pins]
        if pkg.polarized and len(pins) == 2:
            # From where the leads actually landed, not their order in the
            # netlist: the flow layout may put the cathode on either side.
            marked = next((p for p in pins if self._is_negative_lead(p.name)), pins[-1])
            other = pins[0] if marked is pins[-1] else pins[-1]
            body["marked_end"] = "right" if marked.hole.col > other.hole.col else "left"
        body["label_side"] = self._label_side(half, shared_row, cols)

        orientation = self._orientation_text(comp, pkg, pins)
        gap = abs(cols[0] - cols[-1])
        if pkg.form == "axial" and shared_row and gap < AXIAL_FLAT_GAP:
            body["standing"] = True
            orientation = (
                f"Stand it on end: its leads are only {gap} hole{'s' if gap > 1 else ''} "
                "apart, too close for the body to lie flat. Bend one lead back down "
                "beside the body. " + orientation
            )

        self.placed.append(
            PlacedComponent(
                ref=comp.ref,
                kind=comp.kind,
                package=pkg.id,
                value=comp.value,
                pins=pins,
                orientation=orientation,
                body=body,
            )
        )
        self.component_steps.append((comp.ref, self._step_text(comp, pkg, pins)))
        return True

    def _label_side(self, half: str, row: str | None, cols: list[int]) -> str:
        """Which side of the part its name can be printed on.

        The placer knows what is in the neighbouring rows; the renderer does
        not, so it is decided here. A label with a part under it is worse than
        no label at all.
        """
        if row is None:
            return "above"
        rows = bb.strip_rows(half)
        i = rows.index(row)
        mid = (min(cols) + max(cols)) // 2
        span = [c for c in range(mid - 1, mid + 2) if 1 <= c <= self.board.columns]
        for offset, side in ((-1, "above"), (1, "below")):
            j = i + offset
            if 0 <= j < len(rows) and all(self.board.is_free(rows[j], c) for c in span):
                return side
        return "side"  # print it past the right-hand lead instead

    @staticmethod
    def _part_rows(half: str, relaxed: bool = False) -> tuple[str, ...]:
        rows = bb.TOP_PART_ROWS if half == "top" else bb.BOTTOM_PART_ROWS
        if relaxed:
            rows = rows + ((bb.TOP_JUMPER_ROW,) if half == "top" else (bb.BOTTOM_JUMPER_ROW,))
        return rows

    def _row_free_across(
        self, half: str, cols: list[int], allowed: tuple[str, ...]
    ) -> str | None:
        """A single row with a free hole in every one of these columns.

        Keeping both leads of a part in one row is what makes the finished
        board look like a circuit instead of a thicket.
        """
        for row in allowed:
            if all(self.board.is_free(row, c) for c in cols):
                return row
        return None

    def _find_slot(
        self,
        half: str,
        desired: int,
        span: int,
        nets: list[str],
        part_rows: tuple[str, ...],
    ) -> list[int] | None:
        """Columns for each lead: `span` wide, every strip free or same-net.

        Among the nearby legal slots, prefer the one that drops the most leads
        straight into a strip their net already owns — every one of those is a
        jumper the user doesn't have to cut.
        """
        n = len(nets)
        best: tuple[int, int, list[int]] | None = None
        checked = 0
        for start in self._column_search_order(desired):
            cols = [start] if n == 1 else [start + round(i * (span - 1) / (n - 1)) for i in range(n)]
            if cols[-1] > self.board.columns or len(set(cols)) != n:
                continue
            if not all(self.strip_ok_for(half, c, net) for c, net in zip(cols, nets)):
                continue
            # the body has to physically fit: one row free the whole way across
            footprint = list(range(cols[0], cols[-1] + 1))
            if self._row_free_across(half, footprint, part_rows) is None:
                continue
            reuse = sum(1 for c, net in zip(cols, nets) if self.strip_net.get((half, c)) == net)
            distance = abs(start - desired)
            if best is None or (reuse, -distance) > (best[0], -best[1]):
                best = (reuse, distance, cols)
            checked += 1
            if reuse == n or checked >= 40:
                break
        return best[2] if best else None

    def _try_rail_to_rail(self, comp, pkg, names, nets, at: int | None = None) -> bool:
        """Decoupling caps and the like go straight between two adjacent rails.

        `at` asks for one column (a hand layout); otherwise the first free one
        past the circuit is used."""
        roles = [self.role(n) for n in nets]
        pairs = {
            frozenset({NetRole.SUPPLY_POS, NetRole.GROUND}): (bb.RAIL_TOP_POS, bb.RAIL_TOP_NEG),
            frozenset({NetRole.SUPPLY_NEG, NetRole.GROUND}): (bb.RAIL_BOT_POS, bb.RAIL_BOT_NEG),
        }
        key = frozenset(roles)
        if len(set(roles)) != 2 or key not in pairs:
            return False
        rail_a, rail_b = pairs[key]
        # the "+" rail of the pair carries the supply, the "-" rail is ground
        assign = {}
        for net, role in zip(nets, roles):
            assign[net] = rail_b if role is NetRole.GROUND else rail_a
        col = next(
            (
                c
                for c in bb.RAIL_COLUMNS
                if (c == at if at is not None else c >= self.rail_part_from)
                and self.board.is_free(rail_a, c)
                and self.board.is_free(rail_b, c)
            ),
            None,
        )
        if col is None:
            return False

        # Keep a column clear either side: these bodies are round and fat, and
        # two of them in neighbouring columns would physically collide.
        for rail in (rail_a, rail_b):
            for neighbour in (col - 1, col + 1):
                if self.board.is_free(rail, neighbour):
                    self.board.occupy(rail, neighbour, f"body:{comp.ref}")

        pins = []
        for logical, net in zip(names, nets):
            rail = assign[net]
            self.board.occupy(rail, col, comp.ref)
            pins.append(
                PlacedPin(
                    name=logical,
                    net=net,
                    hole=Hole(row=rail, col=col),
                    label=self._lead_label(pkg, logical),
                )
            )
        self.placed.append(
            PlacedComponent(
                ref=comp.ref,
                kind=comp.kind,
                package=pkg.id,
                value=comp.value,
                pins=pins,
                orientation=self._orientation_text(comp, pkg, pins),
                body={
                    "form": pkg.form,
                    "half": "rail",
                    "value_info": val.describe(comp.kind.value, comp.value, pkg.polarized),
                    "rail_pair": [rail_a, rail_b],
                    "cols": [col, col],
                    "rows": [p.hole.row for p in pins],
                    "polarized": pkg.polarized,
                    "marker": pkg.marker,
                    "package_label": pkg.label,
                    "note": pkg.note,
                    "marked_end": "bottom" if self._is_negative_lead(names[1]) else "top",
                },
            )
        )
        self.component_steps.append(
            (
                comp.ref,
                f"Put {comp.ref} ({comp.value or pkg.label}) straight across the "
                f"{'top' if rail_a == bb.RAIL_TOP_POS else 'bottom'} rails at column "
                f"{col}"
                + (
                    " — decoupling belongs right where the supply enters."
                    if comp.kind
                    in (ComponentKind.CAPACITOR, ComponentKind.POLARIZED_CAPACITOR)
                    else " — it sits straight across the two rails."
                ),
            )
        )
        return True

    # -- phase C: routing ---------------------------------------------------
    #
    # Jumpers are laid like parts. Each one gets a straight path — flat along
    # one row, or straight down one column — and the holes it lies across are
    # reserved, so no other jumper can be laid on top of it and nothing ends
    # underneath it. A diagonal is the last resort, not the default.

    def route(self) -> None:
        # 1. Drops to the rails. Their column is fixed by the strip they serve,
        #    so they go first and everything else routes around them. Strips a
        #    hand-laid jumper already joins share one drop: the one that
        #    reaches its rail without passing over anything.
        for net_name, strips in sorted(self.net_strips.items()):
            if self.is_rail_net(net_name):
                self._route_to_rails(net_name, self._one_per_group(strips))
        for key in [k for k, v in self.board.occupied.items() if v.startswith("railhole:")]:
            del self.board.occupied[key]  # rail holes kept but not needed

        # 2. Plan every other net: which of its strips to join to which. Left
        #    to its own devices that is a chain, left to right along each half
        #    plus one link across the channel — but every link needs a free
        #    hole at both ends, and a strip in the middle of a chain needs two.
        #    Strips already joined by a jumper laid by hand count as one.
        along: list[tuple[str, str, int, int]] = []
        across: list[tuple[str, int, int]] = []
        for net_name, strips in sorted(self.net_strips.items()):
            if self.is_rail_net(net_name) or is_unused(net_name):
                continue
            for (ha, ca), (hb, cb) in self._link_plan(net_name, strips, self._joined()):
                if ha == hb:
                    along.append((net_name, ha, min(ca, cb), max(ca, cb)))
                else:
                    ct, cbot = (ca, cb) if ha == "top" else (cb, ca)
                    across.append((net_name, ct, cbot))

        # 3. Straight drops across the channel, same column both sides. They
        #    are the shortest wires there are, and they claim the holes next to
        #    the channel before anything else can.
        for net_name, ct, cb in across:
            if ct == cb and not self._cross_straight(net_name, ct):
                self._diagonal(net_name, ("top", ct), ("bottom", cb))
        # 4. Flat runs along a row, longest first: a long wire has the fewest
        #    rows it can lie in, so it chooses first.
        for net_name, half, a, b in sorted(along, key=lambda t: (-(t[3] - t[2]), t)):
            if not self._run_along(net_name, half, a, b):
                self._diagonal(net_name, (half, a), (half, b))
        # 5. Links across the channel between different columns: an L shape —
        #    a flat run to the other column, then a straight drop — if there's
        #    room for one. Diagonal only if there isn't.
        for net_name, ct, cb in across:
            if ct != cb and not self._cross_with_turn(net_name, ct, cb):
                self._diagonal(net_name, ("top", ct), ("bottom", cb))

    def _joined(self) -> bb.UnionFind:
        """Which strips and rails the jumpers laid so far already join."""
        return bb.solve_nodes(self.wires)

    def _link_plan(
        self, net: str, strips, joined: bb.UnionFind | None = None
    ) -> list[tuple[tuple[str, int], tuple[str, int]]]:
        """The jumpers that join a net's strips into one node.

        The shortest set of links (a spanning tree), but one no strip has to
        give more holes to than it has left — and with a hole to spare for
        any instrument lead that clips onto this net. A full strip in the
        middle of a chain is how a board ends up one jumper short.
        """
        nodes = sorted(set(strips), key=lambda s: (s[0] != "top", s[1]))
        if joined is not None and len(nodes) > 1:
            # Strips a hand-laid jumper already joins are one node: keep one
            # of each group, the one with most room for the link's end.
            groups: dict[str, list[tuple[str, int]]] = {}
            for n in nodes:
                groups.setdefault(joined.find(f"{n[0]}:{n[1]}"), []).append(n)
            nodes = [
                max(g, key=lambda n: self.board.strip_room(*n)) for g in groups.values()
            ]
            nodes.sort(key=lambda s: (s[0] != "top", s[1]))
        if len(nodes) < 2:
            return []

        def cost(a, b):
            return abs(a[1] - b[1]) + (0 if a[0] == b[0] else 1)

        def chain():
            plan = []
            top = [n for n in nodes if n[0] == "top"]
            bottom = [n for n in nodes if n[0] == "bottom"]
            for side in (top, bottom):
                plan += list(zip(side, side[1:]))
            if top and bottom:
                plan.append(min(((t, b) for t in top for b in bottom), key=lambda p: (cost(*p), p[0][1])))
            return plan

        if len(nodes) > 6:  # never seen in practice; keep it cheap
            return chain()

        room = {n: self.board.strip_room(*n) for n in nodes}
        spare = self.holes_still_needed(net)
        best, best_key = None, None
        k = len(nodes)
        # every labelled tree on k nodes, from its Prüfer sequence
        for code in _product(range(k), k - 2):
            degree = [1] * k
            for i in code:
                degree[i] += 1
            if any(degree[i] > room[nodes[i]] for i in range(k)):
                continue
            if sum(room[nodes[i]] - degree[i] for i in range(k)) < spare:
                continue
            edges = _prufer_edges(list(code), k)
            key = (sum(cost(nodes[a], nodes[b]) for a, b in edges), sorted(edges))
            if best_key is None or key < best_key:
                best, best_key = edges, key
        if best is None:
            return chain()
        return [(nodes[a], nodes[b]) for a, b in best]

    # -- the pieces a route is built from ----------------------------------

    def _end_free(self, row: str, col: int) -> bool:
        """Can a wire end go in this hole? Free, or only kept clear for looks."""
        if not self.board.valid(row, col):
            return False
        owner = self.board.occupied.get((row, col))
        return owner is None or owner.startswith("gap:")

    def _take_end(self, row: str, col: int, net: str) -> None:
        if (row, col) in self.board.occupied:
            del self.board.occupied[(row, col)]  # a "gap:" spacer
        self.board.occupy(row, col, f"wire:{net}")

    def _lay_under(self, holes, net: str, direction: str) -> None:
        """Reserve the holes a wire lies across. direction is "h" or "v"."""
        for row, col in holes:
            if self.board.valid(row, col) and self.board.is_free(row, col):
                self.board.occupy(row, col, f"under:{direction}:{net}")

    def _clear_path(self, holes, crossing_ok: str | None) -> bool:
        """Every hole on the path empty — or, if crossing_ok is "h"/"v", lying
        under a wire running the *other* way (a crossing, not an overlap)."""
        for row, col in holes:
            owner = self.board.occupied.get((row, col))
            if owner is None:
                continue
            if crossing_ok and owner.startswith(f"under:{crossing_ok}:"):
                continue
            return False
        return True

    def _drop_cost(self, half: str, col: int) -> int:
        """How many occupied holes a drop from this strip would pass over."""
        out_to_in = bb.strip_rows(half) if half == "top" else bb.strip_rows(half)[::-1]
        row = next((r for r in out_to_in if self._end_free(r, col)), None)
        if row is None:
            return 99
        rail = bb.RAIL_TOP_NEG if half == "top" else bb.RAIL_BOT_NEG
        between = bb.rows_between(row, rail)
        return sum(1 for r in between if not self.board.is_free(r, col)) + (
            0 if col in bb.RAIL_COLUMNS else 5
        )

    def _one_per_group(self, strips) -> list[tuple[str, int]]:
        joined = self._joined()
        groups: dict[str, list[tuple[str, int]]] = {}
        for s in strips:
            groups.setdefault(joined.find(f"{s[0]}:{s[1]}"), []).append(s)
        return sorted(min(g, key=lambda s: (self._drop_cost(*s), s)) for g in groups.values())

    def _route_to_rails(self, net_name: str, strips) -> None:
        role = self.role(net_name)
        color = self.color(net_name)
        joined = self._joined()
        for half, col in sorted(strips):
            rails = RAIL_FOR_ROLE[role]
            if any(joined.find(f"{half}:{col}") == joined.find(r) for r in rails):
                continue  # a hand-laid jumper already takes this strip to its rail
            rail = next((r for r in rails if bb.half_of_rail_side(r) == half), rails[0])
            outer = bb.TOP_RAIL_JUMPER_ROW if half == "top" else bb.BOTTOM_RAIL_JUMPER_ROW
            if self.board.occupied.get((outer, col)) == f"railhole:{net_name}":
                del self.board.occupied[(outer, col)]  # the hole kept for this wire

            # the strip's outermost free hole: the drop then crosses nothing
            out_to_in = bb.strip_rows(half) if half == "top" else bb.strip_rows(half)[::-1]
            row = next((r for r in out_to_in if self._end_free(r, col)), None)
            if row is None:
                row = self.board.reclaim_soft(half, col)
            if row is None:
                self.warnings.append(f"net '{net_name}': strip {half}:{col} is full.")
                continue
            rail_col = self._free_rail_column(rail, col)
            if rail_col is None:
                self.warnings.append(f"net '{net_name}': no free rail hole near column {col}.")
                continue
            self._take_end(row, col, net_name)
            self.board.occupy(rail, rail_col, f"wire:{net_name}")
            if rail_col == col:
                self._lay_under([(r, col) for r in bb.rows_between(row, rail)], net_name, "v")
            self.wires.append(
                Wire(
                    from_hole=Hole(row=row, col=col),
                    to_hole=Hole(row=rail, col=rail_col),
                    net=net_name,
                    color=color,
                    kind="rail",
                )
            )

    def _free_rail_column(self, rail: str, near: int) -> int | None:
        for c in sorted(bb.RAIL_COLUMNS, key=lambda c: (abs(c - near), c)):
            if self.board.is_free(rail, c):
                return c
        return None

    def _run_along(self, net: str, half: str, a: int, b: int) -> bool:
        """A flat jumper from column a to column b, both ends in one row."""
        lo, hi = sorted((a, b))
        lane = bb.TOP_JUMPER_ROW if half == "top" else bb.BOTTOM_JUMPER_ROW
        out_to_in = bb.strip_rows(half) if half == "top" else bb.strip_rows(half)[::-1]
        order = [lane] + [r for r in out_to_in if r != lane]
        for crossing_ok in (None, "v"):  # first a clear row; then one it may cross
            for row in order:
                if not (self._end_free(row, lo) and self._end_free(row, hi)):
                    continue
                path = [(row, c) for c in range(lo + 1, hi)]
                if not self._clear_path(path, crossing_ok):
                    continue
                self._take_end(row, lo, net)
                self._take_end(row, hi, net)
                self._lay_under(path, net, "h")
                self.wires.append(
                    Wire(
                        from_hole=Hole(row=row, col=lo),
                        to_hole=Hole(row=row, col=hi),
                        net=net,
                        color=self.color(net),
                        kind="signal",
                    )
                )
                return True
        return False

    def _cross_straight(self, net: str, col: int) -> bool:
        """Straight down across the channel in one column, nearest rows first."""
        top_rows = bb.strip_rows("top")[::-1]  # F first
        bottom_rows = bb.strip_rows("bottom")  # E first
        pairs = sorted(
            ((t, b) for t in top_rows for b in bottom_rows),
            key=lambda p: (top_rows.index(p[0]) + bottom_rows.index(p[1]), p),
        )
        for crossing_ok in (None, "h"):
            for rt, rb in pairs:
                if not (self._end_free(rt, col) and self._end_free(rb, col)):
                    continue
                path = [(r, col) for r in bb.rows_between(rt, rb)]
                if not self._clear_path(path, crossing_ok):
                    continue
                self._take_end(rt, col, net)
                self._take_end(rb, col, net)
                self._lay_under(path, net, "v")
                self.wires.append(
                    Wire(
                        from_hole=Hole(row=rt, col=col),
                        to_hole=Hole(row=rb, col=col),
                        net=net,
                        color=self.color(net),
                        kind="cross_channel",
                    )
                )
                return True
        return False

    def _cross_with_turn(self, net: str, ct: int, cb: int) -> bool:
        """Join top:ct to bottom:cb with an L: a flat run on one side to the
        other's column, then a straight drop. Uses one new strip for the net."""
        for half, frm, to in (("bottom", cb, ct), ("top", ct, cb)):
            if not self.strip_ok_for(half, to, net):
                continue
            saved = dict(self.board.occupied), len(self.wires)
            if self._run_along(net, half, frm, to) and self._cross_straight(net, to):
                self.claim_strip(half, to, net)
                return True
            self.board.occupied = saved[0]
            del self.wires[saved[1]:]
        return False

    def _diagonal(self, net: str, a: tuple[str, int], b: tuple[str, int]) -> None:
        """Last resort: any free hole in each strip, joined directly."""
        (half_a, col_a), (half_b, col_b) = a, b
        crossing = half_a != half_b

        def rows_for(half):
            if crossing:
                return bb.strip_rows(half)[::-1] if half == "top" else bb.strip_rows(half)
            return (bb.TOP_JUMPER_ROW if half == "top" else bb.BOTTOM_JUMPER_ROW,)

        row_a = self.pick_row(half_a, col_a, rows_for(half_a))
        row_b = self.pick_row(half_b, col_b, rows_for(half_b))
        if row_a is None or row_b is None:
            self.warnings.append(
                f"net '{net}': ran out of holes joining {half_a}:{col_a} to {half_b}:{col_b}."
            )
            return
        self.board.occupy(row_a, col_a, f"wire:{net}")
        self.board.occupy(row_b, col_b, f"wire:{net}")
        self.wires.append(
            Wire(
                from_hole=Hole(row=row_a, col=col_a),
                to_hole=Hole(row=row_b, col=col_b),
                net=net,
                color=self.color(net),
                kind="cross_channel" if crossing else "signal",
            )
        )

    def bond_ground_rails(self) -> None:
        """Join the top and bottom ground rails.

        They are separate strips of copper — the schematic has one ground, so
        the board needs a wire. Forgetting this is the classic "half my
        circuit has no reference" bug.
        """
        gnd = next((n for n, v in self.nets.items() if v.role is NetRole.GROUND), None)
        if gnd is None:
            return
        joined = self._joined()
        if joined.find(bb.RAIL_TOP_NEG) == joined.find(bb.RAIL_BOT_NEG):
            return  # a ground strip already runs from one rail to the other
        col = next(
            (
                c
                for c in reversed(bb.RAIL_COLUMNS)
                if self.board.is_free(bb.RAIL_TOP_NEG, c)
                and self.board.is_free(bb.RAIL_BOT_NEG, c)
                and self._clear_path(
                    [(r, c) for r in bb.rows_between(bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG)], "h"
                )
            ),
            None,
        )
        if col is None:
            if not self._bond_through_strips(gnd) and not self._bond_over_the_top(gnd):
                self.warnings.append("No free column left to bond the two ground rails.")
            return
        self.board.occupy(bb.RAIL_TOP_NEG, col, "wire:gnd-bond")
        self.board.occupy(bb.RAIL_BOT_NEG, col, "wire:gnd-bond")
        self.wires.append(
            Wire(
                from_hole=Hole(row=bb.RAIL_TOP_NEG, col=col),
                to_hole=Hole(row=bb.RAIL_BOT_NEG, col=col),
                net=gnd,
                color=COLOR_GND,
                kind="rail_bond",
            )
        )

    def _bond_through_strips(self, gnd: str) -> bool:
        """No column is clear from rail to rail: bond through an empty one.

        A strip nobody uses, top and bottom, becomes a ground strip: a short
        drop from each ground rail into it and a jumper straight across the
        channel. Three short wires that cross nothing, instead of one long
        one that would lie across the parts.
        """
        top, bottom = bb.TOP_RAIL_JUMPER_ROW, bb.BOTTOM_RAIL_JUMPER_ROW
        for c in reversed(bb.RAIL_COLUMNS):
            if any(self.strip_net.get((half, c)) for half in ("top", "bottom")):
                continue
            holes = [
                (bb.RAIL_TOP_NEG, c), (top, c), (bb.TOP_IC_ROW, c),
                (bb.BOTTOM_IC_ROW, c), (bottom, c), (bb.RAIL_BOT_NEG, c),
            ]
            if not all(self.board.is_free(r, cc) for r, cc in holes):
                continue
            inner_top = bb.rows_between(top, bb.TOP_IC_ROW)
            inner_bottom = bb.rows_between(bb.BOTTOM_IC_ROW, bottom)
            if not self._clear_path([(r, c) for r in inner_top + inner_bottom], "h"):
                continue
            for half in ("top", "bottom"):
                self.claim_strip(half, c, gnd)
            pairs = [
                (bb.RAIL_TOP_NEG, top, "rail"),
                (bb.TOP_IC_ROW, bb.BOTTOM_IC_ROW, "rail_bond"),
                (bottom, bb.RAIL_BOT_NEG, "rail"),
            ]
            for a, b, kind in pairs:
                self.board.occupy(a, c, f"wire:{gnd}")
                self.board.occupy(b, c, f"wire:{gnd}")
                self.wires.append(
                    Wire(
                        from_hole=Hole(row=a, col=c),
                        to_hole=Hole(row=b, col=c),
                        net=gnd,
                        color=COLOR_GND,
                        kind=kind,
                    )
                )
            return True
        return False

    def _bond_over_the_top(self, gnd: str) -> bool:
        """Last resort for a full board: one long flexible jumper from ground
        rail to ground rail, arched over the parts. It ends in two columns
        side by side, so it is drawn (and reads) as a wire hopping over the
        board rather than one lying along a column it doesn't connect to."""
        free_top = [c for c in bb.RAIL_COLUMNS if self.board.is_free(bb.RAIL_TOP_NEG, c)]
        free_bot = [c for c in bb.RAIL_COLUMNS if self.board.is_free(bb.RAIL_BOT_NEG, c)]
        pairs = sorted(
            ((t, b) for t in free_top for b in free_bot if t != b),
            key=lambda tb: (abs(tb[0] - tb[1]), -max(tb)),
        )
        if not pairs:
            return False
        t, b = pairs[0]
        self.board.occupy(bb.RAIL_TOP_NEG, t, "wire:gnd-bond")
        self.board.occupy(bb.RAIL_BOT_NEG, b, "wire:gnd-bond")
        self.wires.append(
            Wire(
                from_hole=Hole(row=bb.RAIL_TOP_NEG, col=t),
                to_hole=Hole(row=bb.RAIL_BOT_NEG, col=b),
                net=gnd,
                color=COLOR_GND,
                kind="rail_bond",
            )
        )
        return True

    # -- text ---------------------------------------------------------------

    def _lead_order(self, comp: Component, pkg: pk.Package) -> list[str]:
        names = list(comp.pins.keys())
        if pkg.form in THREE_LEAD:
            order = [n for n in pkg.pin_map if n in comp.pins]
            order.sort(key=lambda n: pkg.pin_map[n])
            extra = [n for n in names if n not in order]
            return order + extra
        if len(names) == 2:
            positive_first = {"A": 0, "+": 0, "ANODE": 0, "1": 0, "K": 1, "-": 1, "CATHODE": 1, "2": 1}
            names.sort(key=lambda n: positive_first.get(n.upper(), 0))
        return names

    @staticmethod
    def _is_negative_lead(name: str) -> bool:
        return name.strip().upper() in {"K", "-", "CATHODE", "NEG", "2"}

    @staticmethod
    def _lead_label(pkg: pk.Package, logical: str) -> str:
        n = pkg.pin_map.get(logical)
        if n:
            return f"pin {n} — {pkg.pin_names.get(n, logical)}"
        pretty = {
            "A": "anode (+)",
            "K": "cathode (−, banded end)",
            "+": "positive lead",
            "-": "negative lead (striped side)",
        }
        return pretty.get(logical.upper(), logical)

    def _orientation_text(self, comp: Component, pkg: pk.Package, pins) -> str:
        if pkg.form == "pot":
            used = [p for p in pins if not is_unused(p.net)]
            spare = [p for p in pins if is_unused(p.net)]
            text = (
                f"Adjust screw up, pins toward you: 1–W–3 left to right "
                f"({', '.join(p.hole.key() for p in pins)})."
            )
            if spare and len(used) == 2:
                end = next(p for p in used if p.name != "W")
                text += (
                    f" Wired as a variable resistor between pin {end.name} and the wiper; "
                    f"pin {spare[0].name} is left unconnected, as on the schematic."
                )
            return text
        if pkg.form in THREE_LEAD:
            order = "–".join(p.name for p in pins)
            face = (
                "metal tab AWAY from you"
                if pkg.form == "to220"
                else "FLAT face toward you, half-circle bulging away"
            )
            return (
                f"{face}, leads down: {order} left to right "
                f"({', '.join(p.hole.key() for p in pins)})."
            )
        if pkg.polarized:
            marked = next((p for p in pins if self._is_negative_lead(p.name)), pins[-1])
            cue = "banded end" if comp.kind.value == "diode" else "striped / short lead"
            return f"Polarised — {cue} goes in {hole_label(marked.hole)} (net {marked.net})."
        return "Not polarised — either way round."

    def _step_text(self, comp: Component, pkg: pk.Package, pins) -> str:
        holes = " → ".join(p.hole.key() for p in pins)
        val = comp.value or pkg.label
        tail = ""
        if pkg.polarized:
            marked = next((p for p in pins if self._is_negative_lead(p.name)), pins[-1])
            tail = f" (marked lead in {marked.hole.key()})"
        elif pkg.form == "pot":
            spare = [p for p in pins if is_unused(p.net)]
            tail = " (adjust screw up: 1–W–3"
            if spare:
                tail += f"; pin {spare[0].name} in {spare[0].hole.key()} stays unconnected"
            tail += ")"
        elif pkg.form in THREE_LEAD:
            face = "tab away from you" if pkg.form == "to220" else "flat face toward you"
            tail = f" ({face}: {'–'.join(p.name for p in pins)})"
        if (
            pkg.form == "axial"
            and len(pins) == 2
            and pins[0].hole.row == pins[1].hole.row
            and abs(pins[0].hole.col - pins[1].hole.col) < AXIAL_FLAT_GAP
        ):
            tail += ", standing on end"
        return f"Place {comp.ref} {val}: {holes}{tail}."

    # -- drive --------------------------------------------------------------

    def _settle_labels(self) -> None:
        """Re-decide where each part's name goes, now that every part and
        wire is on the board. Decided at placement time, a label could end up
        under something placed after it."""
        for comp in self.placed:
            body = comp.body
            if body.get("form") in ("dip", "to92", "to220", "pot") or body.get("half") == "rail":
                continue
            rows = {p.hole.row for p in comp.pins}
            if len(comp.pins) != 2 or len(rows) != 1:
                continue
            body["label_side"] = self._label_side(
                body["half"], rows.pop(), [p.hole.col for p in comp.pins]
            )

    def _rails_used(self) -> set[str]:
        holes = [p.hole for c in self.placed for p in c.pins]
        holes += [h for w in self.wires for h in (w.from_hole, w.to_hole)]
        return {h.row for h in holes if bb.is_rail(h.row)}

    def place_components(self) -> None:
        """Strategy hook. The packed placer fills the board tightly; the flow
        placer in flow.py overrides this to mirror the schematic instead."""
        self.place_ics()
        self.place_discretes()

    def run(self) -> Layout:
        self.place_components()
        self.route()
        if self._rails_used() >= {bb.RAIL_TOP_NEG, bb.RAIL_BOT_NEG}:
            # Two separate strips of copper carrying one ground: join them.
            # A circuit that only touches one of them doesn't need the wire.
            self.bond_ground_rails()
        # Where the bench supply and the wave generator clip on.
        self.leads = src_mod.attach(self)
        self._settle_labels()
        # What the schematic says about a part ("U2 = section A") rides along
        # to its hover card.
        said = {c.ref: c.notes for c in self.nl.components if c.notes}
        for comp in self.placed:
            if comp.ref in said:
                comp.body["schematic_note"] = said[comp.ref]

        rails = {}
        used_rails = self._rails_used()
        for rail in bb.RAILS:
            role = {
                bb.RAIL_TOP_POS: NetRole.SUPPLY_POS,
                bb.RAIL_BOT_POS: NetRole.SUPPLY_NEG,
                bb.RAIL_TOP_NEG: NetRole.GROUND,
                bb.RAIL_BOT_NEG: NetRole.GROUND,
            }[rail]
            net = next((n for n, v in self.nets.items() if v.role is role), None)
            rails[rail] = {
                "net": net,
                "polarity": bb.RAIL_POLARITY[rail],
                "voltage": self.nets[net].voltage if net else None,
                "label": {
                    bb.RAIL_TOP_POS: "positive supply",
                    bb.RAIL_TOP_NEG: "ground",
                    bb.RAIL_BOT_NEG: "ground",
                    bb.RAIL_BOT_POS: "negative supply",
                }[rail],
                "in_use": rail in used_rails,
            }

        layout = Layout(
            title=self.nl.title,
            columns=self.board.columns,
            components=self.placed,
            wires=self.wires,
            leads=self.leads,
            nets=list(self.nets.values()),
            rails=rails,
            warnings=self.warnings,
            notes=self.notes,
            build_order=self._build_order(rails),
        )
        layout.warnings.extend(bb.verify(layout))
        return layout

    def _build_order(self, rails) -> list[BuildStep]:
        """One action per step, in the order you'd actually do them."""
        steps: list[BuildStep] = [
            BuildStep(
                index=0,
                kind="note",
                text="Power off. Nothing goes into the board with the supply live.",
            )
        ]
        placed_by_ref = {c.ref: c for c in self.placed}
        for ref, text in self.component_steps:
            comp = placed_by_ref.get(ref)
            steps.append(
                BuildStep(
                    index=len(steps),
                    kind="component",
                    text=text,
                    ref=ref,
                    detail=self._component_detail(comp) if comp else None,
                )
            )
        for i, w in enumerate(self.wires):
            length = abs(w.to_hole.col - w.from_hole.col)
            steps.append(
                BuildStep(
                    index=len(steps),
                    kind="wire",
                    text=(
                        f"Run a {self._wire_word(w)} jumper from {hole_label(w.from_hole)} "
                        f"to {hole_label(w.to_hole)}."
                    ),
                    wire=i,
                    detail=f"net {w.net}"
                    + (
                        f" · spans {length} column{'s' if length != 1 else ''}"
                        if length
                        else " · straight across"
                    ),
                )
            )
        steps.append(
            BuildStep(
                index=len(steps),
                kind="note",
                text="Check continuity against the netlist before connecting any instrument.",
            )
        )
        for text, lead_idx, detail in src_mod.build_steps(self, self.leads):
            steps.append(
                BuildStep(
                    index=len(steps),
                    kind="lead" if lead_idx else "note",
                    text=text,
                    leads=lead_idx,
                    detail=detail,
                )
            )
        return steps

    @staticmethod
    def _component_detail(comp: PlacedComponent) -> str:
        """The one extra line worth reading while you place this part."""
        bands = (comp.body.get("value_info") or {}).get("bands")
        bits = []
        if bands:
            bits.append(f"bands: {bands['text']}")
        code = (comp.body.get("value_info") or {}).get("code")
        style = (comp.body.get("value_info") or {}).get("cap_style")
        if code and style == "ceramic":
            bits.append(f"marked '{code}' on the disc")
        if comp.orientation and comp.orientation != "Not polarised — either way round.":
            bits.append(comp.orientation)
        elif not bits:
            bits.append(comp.orientation)
        return " · ".join(bits)

    @staticmethod
    def _wire_word(w: Wire) -> str:
        return {
            "rail": "power",
            "rail_bond": "ground-bonding",
            "cross_channel": "cross-channel",
        }.get(w.kind, "signal")


UNUSED = " (not connected)"


def _product(values, repeat: int):
    from itertools import product

    return product(values, repeat=repeat)


def _prufer_edges(code: list[int], k: int) -> list[tuple[int, int]]:
    """The tree a Prüfer sequence stands for, as (a, b) pairs with a < b."""
    degree = [1] * k
    for i in code:
        degree[i] += 1
    edges = []
    for i in code:
        leaf = min(j for j in range(k) if degree[j] == 1)
        edges.append(tuple(sorted((leaf, i))))
        degree[leaf] -= 1
        degree[i] -= 1
    a, b = [j for j in range(k) if degree[j] == 1]
    edges.append((a, b))
    return edges


def unused_net(ref: str, number: int) -> str:
    """A node of its own for a chip pin the circuit doesn't use."""
    return f"{ref} pin {number}{UNUSED}"


def is_unused(net: str) -> bool:
    return net.endswith(UNUSED)


def hole_label(hole: Hole) -> str:
    """'A12' for a strip hole, 'top + rail, column 12' for a rail hole."""
    if not bb.is_rail(hole.row):
        return hole.key()
    side = "top" if bb.half_of_rail_side(hole.row) == "top" else "bottom"
    sign = "+" if bb.RAIL_POLARITY[hole.row] == "+" else "−"
    return f"{side} {sign} rail, column {hole.col}"


def place(
    netlist: Netlist,
    custom: dict[str, pk.Package] | None = None,
    style: str = "flow",
) -> Layout:
    """style: "flow" (schematic-shaped, roomy) or "packed".

    Tries the nicest layout first and steps down until one fits; the verifier
    decides what "fits" means, so a fallback is never a wrong board.
    """
    from . import quality
    from .flow import FlowPlacer  # local import: flow.py imports this module
    from .gates import pack_sections

    netlist = _named_as_picked(netlist, custom or {})
    # Op-amps drawn one triangle at a time share dual and quad chips.
    netlist = pack_sections(netlist, custom)

    if style == "packed":
        return Placer(netlist, custom).run()

    # A board someone arranged by hand (the bundled examples) wins, as long as
    # it still fits the parts that were picked and checks out.
    if netlist.layout is not None:
        from .handlaid import hand_place

        by_hand = hand_place(netlist, custom)
        if by_hand is not None and not _failed(by_hand):
            return by_hand

    def flow_once(spacing: int, **options) -> Layout:
        placer = FlowPlacer(netlist, custom, spacing=spacing, **options)
        try:
            layout = placer.run()
        except ValueError as err:  # ran off the end of the board
            return Layout(
                title=netlist.title, columns=bb.COLUMNS, warnings=[f"{err} — not placed."]
            )
        # Supply and ground were given a column up front. If every part on
        # them ended up plugged straight into the rail instead, that column
        # is empty — lay the board out again without it.
        idle = {
            n
            for n in placer.home
            if placer.is_rail_net(n) and not placer.net_strips.get(n)
        }
        if idle and not _failed(layout):
            tighter = FlowPlacer(
                netlist, custom, spacing=spacing, skip_homes=idle, **options
            ).run()
            if not _failed(tighter):
                return tighter
        return layout

    def flow(spacing: int) -> Layout:
        """Lay the board out a few ways and keep the cleanest.

        Placement is greedy, so small choices — nudging a block off a rail
        gap, plugging parts into the rails — can help one circuit and crowd
        another. Each try takes milliseconds; the quality score (diagonal
        jumpers, crossings, wires over parts, wire count) picks the winner.
        The first option listed wins a tie.
        """
        tries = [
            flow_once(spacing, dodge_gaps=dodge, rail_mount=mount)
            for mount in (True, "light", False)
            for dodge in (True, False)
        ]
        good = [t for t in tries if not _failed(t)]
        if not good:
            return tries[0]
        return min(good, key=lambda t: quality.measure(t).score)

    # A big circuit that won't fit may fit with its columns closer together
    # before giving up on the schematic shape.
    for spacing in (4, 3, 2, 1):
        layout = flow(spacing)
        if not _failed(layout):
            return layout

    # The schematic-shaped layout didn't fit. Fall back to packing, which
    # always fits, rather than handing over a board that is wrong.
    packed = Placer(netlist, custom).run()
    if _failed(packed):
        return packed  # the warnings say what didn't fit
    packed.notes.append(
        "This circuit didn't fit the schematic-shaped layout, so it was packed "
        "tightly instead. Everything is still electrically correct."
    )
    return packed


def _named_as_picked(netlist: Netlist, custom: dict) -> Netlist:
    """Call each part what was picked for it, not what the schematic said.

    A diode drawn as a 1N4148 and built with a 1N5819 is a 1N5819 on the
    board, in the hover card and in the build steps; the schematic's name is
    kept in the part's notes.
    """
    out, renamed = [], False
    for comp in netlist.components:
        pkg = pk.BY_ID.get(comp.package or "")
        if pkg is None or comp.kind is ComponentKind.POTENTIOMETER or comp.ref in custom:
            out.append(comp)
            continue
        name = pk.part_name(comp.value, pkg)
        if name == comp.value:
            out.append(comp)
            continue
        said = f"Schematic says {comp.value}; built with {name}." if comp.value else None
        notes = " · ".join(n for n in (said, comp.notes) if n) or None
        out.append(comp.model_copy(update={"value": name, "notes": notes}))
        renamed = True
    return netlist.model_copy(update={"components": out}) if renamed else netlist


def _failed(layout: Layout) -> bool:
    return any(
        "not placed" in w
        or "left unplaced" in w
        or "split across" in w
        or "short" in w
        or "no free hole" in w
        for w in layout.warnings
    )
