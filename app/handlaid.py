"""Boards arranged by hand.

The automatic layouts are good on small circuits. A big one — two quad op-amps
and thirty-odd parts — has far more ways to go wrong than a greedy placer can
search, and the bundled examples are the first thing a student sees. So an
example may carry a `layout`: where each part goes, and the jumpers, written
the way a person would plan it on paper.

Nothing here is trusted. Every hole is checked before anything goes in it,
every strip keeps to one net, anything the plan leaves unjoined is routed by
the normal router, supply and ground strips are dropped to their rails, and
the verifier proves the finished board is the circuit. A plan that doesn't
check out is thrown away and the automatic layout is used instead.
"""

from __future__ import annotations

import re

from . import breadboard as bb
from .flow import FlowPlacer, rail_mount_row
from .models import Hole, Layout, NetRole, Wire
from .placer import THREE_LEAD, Placer, is_unused

_RAIL = {
    ("T", "+"): bb.RAIL_TOP_POS,
    ("T", "-"): bb.RAIL_TOP_NEG,
    ("B", "-"): bb.RAIL_BOT_NEG,
    ("B", "+"): bb.RAIL_BOT_POS,
}


def parse_hole(text: str) -> Hole:
    """'G12' -> row G, column 12. 'T+12' -> top + rail, column 12."""
    t = text.strip().upper().replace("−", "-")
    m = re.fullmatch(r"([TB])([+-])(\d+)", t)
    if m:
        return Hole(row=_RAIL[(m.group(1), m.group(2))], col=int(m.group(3)))
    m = re.fullmatch(r"([A-J])(\d+)", t)
    if m:
        return Hole(row=m.group(1), col=int(m.group(2)))
    raise ValueError(f"'{text}' is not a hole (write G12, or T+12 / T-12 / B-12 / B+12)")


class PlanError(ValueError):
    pass


class HandPlacer(FlowPlacer):
    def __init__(self, netlist, custom=None, partial: bool = False):
        super().__init__(netlist, custom, spacing=4)
        self.plan = netlist.layout
        #: leave parts the plan doesn't mention off the board (for drafting a plan)
        self.partial = partial

    # -- parts --------------------------------------------------------------

    def place_components(self) -> None:
        by_ref = {c.ref: c for c in self.nl.components}
        for ref, spec in self.plan.parts.items():
            comp = by_ref.get(ref)
            if comp is None:
                raise PlanError(f"the layout places {ref}, which isn't in the circuit")
            pkg = self.package_for(comp)
            if pkg.straddles_channel:
                if "col" not in spec:
                    raise PlanError(f"{ref}: a chip needs its leftmost column")
                start = int(spec["col"])
                half_pins = pkg.pin_count // 2
                for c in range(start, start + half_pins):
                    for row in (bb.TOP_IC_ROW, bb.BOTTOM_IC_ROW):
                        self._check_free(ref, Hole(row=row, col=c))
                self._emit_ic(comp, pkg, start, spec.get("flip"))
            else:
                self._place_by_hand(comp, pkg, spec)
        missing = [c.ref for c in self.nl.components if c.ref not in self.plan.parts]
        if missing and not self.partial:
            raise PlanError(f"the layout doesn't place {', '.join(missing)}")
        self.unplaced = missing

    def _check_free(self, ref: str, hole: Hole) -> None:
        if not self.board.valid(hole.row, hole.col):
            raise PlanError(f"{ref}: {hole.key()} isn't a hole on this board")
        owner = self.board.occupied.get((hole.row, hole.col))
        if owner is None or owner.startswith("gap:"):
            self.board.occupied.pop((hole.row, hole.col), None)
            return
        raise PlanError(f"{ref}: {hole.key()} is already taken by {owner}")

    def _check_strip(self, ref: str, hole: Hole, net: str) -> None:
        if bb.is_rail(hole.row):
            return
        owner = self.strip_net.get((bb.half_of(hole.row), hole.col))
        if owner is not None and owner != net:
            raise PlanError(
                f"{ref}: {hole.key()} is in the strip of {owner}, but this lead is on {net}"
            )

    def _place_by_hand(self, comp, pkg, spec: dict) -> None:
        names = self._lead_order(comp, pkg)
        nets = [comp.pins[n] for n in names]
        holes: dict[str, Hole] = {}
        for name in names:
            text = spec.get(name)
            if text is None:
                # the schematic's own pin name, if the plan used that
                text = next((v for k, v in spec.items() if self._same_pin(pkg, k, name)), None)
            if text is not None:
                holes[name] = parse_hole(text)

        if pkg.form in THREE_LEAD:
            # One hole is enough to place a three-lead part: the others are
            # its neighbours in the same row, in pin order.
            known = next(iter(holes.items()), None)
            if known is None:
                raise PlanError(f"{comp.ref}: no hole given")
            name0, hole0 = known
            index0 = names.index(name0)
            for i, name in enumerate(names):
                want = Hole(row=hole0.row, col=hole0.col + (i - index0))
                if name in holes and holes[name] != want:
                    raise PlanError(f"{comp.ref}: its legs must sit side by side in one row")
                holes[name] = want
            for name, net in zip(names, nets):
                self._check_free(comp.ref, holes[name])
                self._check_strip(comp.ref, holes[name], net)
            row = hole0.row
            half = bb.half_of(row)
            cols = [holes[n].col for n in names]
            self._emit_discrete(comp, pkg, names, nets, half, cols, (row,), force_row=row)
            return

        if len(names) != 2 or set(holes) != set(names):
            raise PlanError(f"{comp.ref}: give a hole for each of {', '.join(names)}")
        a, b = holes[names[0]], holes[names[1]]
        on_rail = [bb.is_rail(h.row) for h in (a, b)]
        if all(on_rail):
            # Straight across two neighbouring rails: decoupling beside a chip.
            if a.col != b.col:
                raise PlanError(f"{comp.ref}: a part across the rails stands in one column")
            if not self._try_rail_to_rail(comp, pkg, names, nets, at=a.col):
                raise PlanError(f"{comp.ref}: can't go across the rails at column {a.col}")
            placed = {p.name: p.hole for p in self.placed[-1].pins}
            if placed != holes:
                raise PlanError(f"{comp.ref}: its nets aren't on the rails at {a.key()} and {b.key()}")
            return
        if any(on_rail):
            ri = on_rail.index(True)
            rail_hole, strip_hole = (a, b) if ri == 0 else (b, a)
            if rail_hole.col != strip_hole.col:
                raise PlanError(f"{comp.ref}: a part plugged into a rail stands in one column")
            half = bb.half_of(strip_hole.row)
            land = rail_mount_row(rail_hole.row, half, pkg.form)
            if strip_hole.row != land:
                raise PlanError(
                    f"{comp.ref}: standing from that rail it lands in row {land}, "
                    f"not {strip_hole.row}"
                )
            if self._rail_for(nets[ri], half) != rail_hole.row:
                raise PlanError(f"{comp.ref}: {nets[ri]} isn't on the rail at {rail_hole.row}")
            for r in [rail_hole.row, strip_hole.row, *bb.rows_between(rail_hole.row, land)]:
                self._check_free(comp.ref, Hole(row=r, col=strip_hole.col))
            self._check_strip(comp.ref, strip_hole, nets[1 - ri])
            if not self._rail_mount_at(comp, pkg, names, nets, ri, half, strip_hole.col):
                raise PlanError(f"{comp.ref}: can't stand it at column {strip_hole.col}")
            return

        if a.row != b.row:
            raise PlanError(f"{comp.ref}: both leads must be in one row")
        for h, net in ((a, nets[0]), (b, nets[1])):
            self._check_free(comp.ref, h)
            self._check_strip(comp.ref, h, net)
        lo, hi = sorted((a.col, b.col))
        for c in range(lo + 1, hi):
            owner = self.board.occupied.get((a.row, c))
            if owner and not owner.startswith(("gap:", "body:")):
                raise PlanError(f"{comp.ref}: its body would lie on {owner} at {a.row}{c}")
        self._emit_discrete(
            comp, pkg, names, nets, bb.half_of(a.row), [a.col, b.col], (a.row,), force_row=a.row
        )

    @staticmethod
    def _same_pin(pkg, given: str, name: str) -> bool:
        from . import packages as pk

        if given == name:
            return True
        n = pk.resolve_pin(pkg, given)
        return n is not None and n == pkg.pin_map.get(name)

    # -- jumpers ------------------------------------------------------------

    def _net_at(self, hole: Hole) -> str | None:
        if bb.is_rail(hole.row):
            role = {
                bb.RAIL_TOP_POS: NetRole.SUPPLY_POS,
                bb.RAIL_BOT_POS: NetRole.SUPPLY_NEG,
                bb.RAIL_TOP_NEG: NetRole.GROUND,
                bb.RAIL_BOT_NEG: NetRole.GROUND,
            }[hole.row]
            return next((n for n, v in self.nets.items() if v.role is role), None)
        return self.strip_net.get((bb.half_of(hole.row), hole.col))

    def lay_planned_wires(self) -> None:
        for pair in self.plan.wires:
            if len(pair) != 2:
                raise PlanError(f"a jumper needs two holes, not {pair}")
            a, b = parse_hole(pair[0]), parse_hole(pair[1])
            nets = {n for n in (self._net_at(a), self._net_at(b)) if n}
            if len(nets) != 1:
                raise PlanError(
                    f"jumper {pair[0]}–{pair[1]} joins "
                    + (" and ".join(sorted(nets)) if nets else "nothing")
                )
            net = nets.pop()
            for h in (a, b):
                if not bb.is_rail(h.row):
                    self.claim_strip(bb.half_of(h.row), h.col, net)
                if not self._end_free(h.row, h.col):
                    raise PlanError(
                        f"jumper {pair[0]}–{pair[1]}: {h.key()} is taken by "
                        f"{self.board.occupied.get((h.row, h.col))}"
                    )
            if a.row == b.row:
                lo, hi = sorted((a.col, b.col))
                path, direction = [(a.row, c) for c in range(lo + 1, hi)], "h"
            elif a.col == b.col:
                path, direction = [(r, a.col) for r in bb.rows_between(a.row, b.row)], "v"
            else:
                path, direction = [], ""
            if path and not self._clear_path(path, "v" if direction == "h" else "h"):
                raise PlanError(f"jumper {pair[0]}–{pair[1]} would lie across a part or a lead")
            self._take_end(a.row, a.col, net)
            self._take_end(b.row, b.col, net)
            if path:
                self._lay_under(path, net, direction)
            kind = (
                "rail"
                if bb.is_rail(a.row) or bb.is_rail(b.row)
                else "cross_channel"
                if bb.half_of(a.row) != bb.half_of(b.row)
                else "signal"
            )
            self.wires.append(
                Wire(from_hole=a, to_hole=b, net=net, color=self.color(net), kind=kind)
            )

    def route(self) -> None:
        self.lay_planned_wires()
        super().route()

    def run(self) -> Layout:
        layout = Placer.run(self)
        layout.notes.append(
            self.plan.note
            or "This example was laid out by hand. The app still checked every hole and "
            "proved the board matches the circuit."
        )
        return layout


def hand_place(netlist, custom=None) -> Layout | None:
    """The hand-made board, or None if the plan doesn't fit this circuit
    (a different package picked, a part added) — the caller then lays the
    board out automatically."""
    if netlist.layout is None or not netlist.layout.parts:
        return None
    try:
        return HandPlacer(netlist, custom).run()
    except (PlanError, ValueError) as err:
        print(f"hand layout not used: {err}")
        return None


__all__ = ["HandPlacer", "PlanError", "hand_place", "parse_hole", "is_unused"]
