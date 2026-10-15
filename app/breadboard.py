"""The breadboard connectivity model.

A breadboard is not a drawing, it is an equivalence relation on holes. Two
holes are the same electrical node if they are in the same five-hole terminal
strip, on the same power rail, or joined by a jumper. Everything the placer
does is bookkeeping on top of that.

Geometry (standard full-size 830 tie-point board, top-down view):

    rail  + + + + + + + + + +      <- top positive rail      (V+)
    rail  - - - - - - - - - -      <- top negative rail      (GND)
      J . . . . . . . . . . .   \\
      I . . . . . . . . . . .    |  top half: each column is
      H . . . . . . . . . . .    |  one 5-hole terminal strip
      G . . . . . . . . . . .    |  (rows F..J shorted together)
      F . . . . . . . . . . .   /
        =====  centre channel  =====   (DIP ICs straddle this)
      E . . . . . . . . . . .   \\
      D . . . . . . . . . . .    |  bottom half: rows A..E
      C . . . . . . . . . . .    |  shorted per column
      B . . . . . . . . . . .    |
      A . . . . . . . . . . .   /
    rail  - - - - - - - - - -      <- bottom negative rail   (GND)
    rail  + + + + + + + + + +      <- bottom positive rail   (V-)

Rail usage follows the convention in the project spec: top positive rail is
the positive supply, bottom positive rail is the *negative* supply, and both
negative rails are ground.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COLUMNS = 63

TOP_ROWS = ("J", "I", "H", "G", "F")  # outer -> inner (F touches the channel)
BOTTOM_ROWS = ("E", "D", "C", "B", "A")  # inner -> outer (E touches the channel)

#: Row reserved for each job, so the layout stays readable instead of a nest.
TOP_IC_ROW = "F"
TOP_PART_ROWS = ("G", "H")
TOP_JUMPER_ROW = "I"
TOP_RAIL_JUMPER_ROW = "J"

BOTTOM_IC_ROW = "E"
BOTTOM_PART_ROWS = ("D", "C")
BOTTOM_JUMPER_ROW = "B"
BOTTOM_RAIL_JUMPER_ROW = "A"

RAIL_TOP_POS = "RAIL_TOP_POS"
RAIL_TOP_NEG = "RAIL_TOP_NEG"
RAIL_BOT_NEG = "RAIL_BOT_NEG"
RAIL_BOT_POS = "RAIL_BOT_POS"

RAILS = (RAIL_TOP_POS, RAIL_TOP_NEG, RAIL_BOT_NEG, RAIL_BOT_POS)

#: Every row, top of the board to bottom. A wire or a standing part that runs
#: between two rows in one column passes over everything listed between them.
ROW_ORDER = (
    RAIL_TOP_POS,
    RAIL_TOP_NEG,
    *TOP_ROWS,
    *BOTTOM_ROWS,
    RAIL_BOT_NEG,
    RAIL_BOT_POS,
)


#: Vertical position of each row, in hole pitches — the same numbers the
#: renderer draws with. Used to give a standing part a real body length.
ROW_POS = {
    RAIL_TOP_POS: 0.0,
    RAIL_TOP_NEG: 1.0,
    "J": 2.6,
    "I": 3.6,
    "H": 4.6,
    "G": 5.6,
    "F": 6.6,
    "E": 8.6,
    "D": 9.6,
    "C": 10.6,
    "B": 11.6,
    "A": 12.6,
    RAIL_BOT_NEG: 14.2,
    RAIL_BOT_POS: 15.2,
}


def rows_between(a: str, b: str) -> list[str]:
    """Rows strictly between a and b, in the same column."""
    i, j = sorted((ROW_ORDER.index(a), ROW_ORDER.index(b)))
    return list(ROW_ORDER[i + 1 : j])


def crosses_channel(a: str, b: str) -> bool:
    i, j = sorted((ROW_ORDER.index(a), ROW_ORDER.index(b)))
    return i <= ROW_ORDER.index("F") < ROW_ORDER.index("E") <= j


RAIL_POLARITY = {
    RAIL_TOP_POS: "+",
    RAIL_TOP_NEG: "-",
    RAIL_BOT_NEG: "-",
    RAIL_BOT_POS: "+",
}

#: Real boards print the rail in groups of five with a gap. Cosmetic, but the
#: layout should never ask you to use a hole that isn't there.
RAIL_COLUMNS = [c for c in range(2, COLUMNS) if (c - 2) % 6 != 5]


def is_rail(row: str) -> bool:
    return row in RAILS


def half_of(row: str) -> str:
    if is_rail(row):
        return "rail"
    return "top" if row in TOP_ROWS else "bottom"


def half_of_rail_side(rail: str) -> str:
    """Which half of the board a rail sits against."""
    return "top" if rail in (RAIL_TOP_POS, RAIL_TOP_NEG) else "bottom"


def node_id(row: str, col: int) -> str:
    """Canonical electrical node for a hole, before any jumpers are applied."""
    if is_rail(row):
        return row  # a rail is one node for its whole length
    return f"{half_of(row)}:{col}"


def strip_rows(half: str) -> tuple[str, ...]:
    return TOP_ROWS if half == "top" else BOTTOM_ROWS


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------


@dataclass
class Breadboard:
    """Tracks which holes are taken and by what."""

    columns: int = COLUMNS
    occupied: dict[tuple[str, int], str] = field(default_factory=dict)

    # -- holes --------------------------------------------------------------

    def valid(self, row: str, col: int) -> bool:
        if not (1 <= col <= self.columns):
            return False
        if is_rail(row):
            return col in RAIL_COLUMNS
        return row in TOP_ROWS or row in BOTTOM_ROWS

    def is_free(self, row: str, col: int) -> bool:
        return self.valid(row, col) and (row, col) not in self.occupied

    def occupy(self, row: str, col: int, owner: str) -> None:
        if not self.valid(row, col):
            raise ValueError(f"no hole at {row}{col}")
        if (row, col) in self.occupied:
            raise ValueError(f"{row}{col} already used by {self.occupied[(row, col)]}")
        self.occupied[(row, col)] = owner

    # -- strips -------------------------------------------------------------

    #: Reservations that block another *part* from landing in a hole without
    #: using up the strip's electrical capacity: the hole under a resistor's
    #: body, or the clear column kept beside a lead.
    #: "cover:" is a hole a standing part passes over; "under:" is a hole a
    #: jumper lies across. Neither is a connection, and neither may be handed
    #: to a wire end — something is physically on top of it.
    SOFT = ("body:", "gap:", "cover:", "under:")

    def strip_load(self, half: str, col: int) -> int:
        """How many of a terminal strip's five holes carry a connection."""
        return sum(
            1
            for r in strip_rows(half)
            if (r, col) in self.occupied and not self.occupied[(r, col)].startswith(self.SOFT)
        )

    def strip_is_free(self, half: str, col: int) -> bool:
        """True if nothing at all is landed in this column's strip."""
        return self.strip_load(half, col) == 0

    def reclaim_soft(self, half: str, col: int) -> str | None:
        """Free a spacing reservation in this strip for a wire to use.

        A clear hole kept beside a part's lead is there for looks, not for
        physics — a jumper end fits in it fine. Prefer those; a hole under a
        part's body comes second, since it hides the wire end in the drawing.
        """
        for prefix in ("gap:", "body:"):
            for r in strip_rows(half):
                owner = self.occupied.get((r, col))
                if owner and owner.startswith(prefix):
                    del self.occupied[(r, col)]
                    return r
        return None

    #: Spacing reservations a wire end may still take (see reclaim_soft).
    RECLAIMABLE = ("body:", "gap:")

    def strip_has_room(self, half: str, col: int, needed: int = 1) -> bool:
        """Are there `needed` holes in this strip a lead or wire end can use?

        A hole a standing part passes over, or a jumper lies across, carries no
        connection — but nothing else can be pushed into it either, so it
        counts against the strip's room just as a lead does.
        """
        return self.strip_room(half, col) >= needed

    def strip_room(self, half: str, col: int) -> int:
        """How many holes in this strip a lead or wire end could still take."""
        return sum(
            1
            for r in strip_rows(half)
            if (r, col) not in self.occupied or self.occupied[(r, col)].startswith(self.RECLAIMABLE)
        )

    def free_run(self, half: str, start: int, length: int) -> int | None:
        """Leftmost column >= start where `length` untouched strips sit in a row."""
        col = start
        while col + length - 1 <= self.columns:
            if all(self.strip_is_free(half, c) for c in range(col, col + length)):
                return col
            col += 1
        return None

    def free_hole_in_strip(self, half: str, col: int, rows: tuple[str, ...]) -> str | None:
        """First free row from `rows` in this column's strip."""
        for r in rows:
            if self.is_free(r, col):
                return r
        return None

    def free_run_both_halves(self, start: int, length: int) -> int | None:
        """Leftmost column where `length` columns are untouched in BOTH halves.

        This is what a DIP needs: it lands in row E and row F at once.
        """
        col = start
        while col + length - 1 <= self.columns:
            if all(
                self.strip_is_free("top", c) and self.strip_is_free("bottom", c)
                for c in range(col, col + length)
            ):
                return col
            col += 1
        return None

    def nearest_rail_column(self, col: int) -> int:
        return min(RAIL_COLUMNS, key=lambda c: (abs(c - col), c))


# ---------------------------------------------------------------------------
# Electrical verification
# ---------------------------------------------------------------------------


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def solve_nodes(wires) -> UnionFind:
    """Collapse strips and rails joined by jumpers into single nodes."""
    uf = UnionFind()
    for w in wires:
        uf.union(
            node_id(w.from_hole.row, w.from_hole.col),
            node_id(w.to_hole.row, w.to_hole.col),
        )
    return uf


def verify(layout) -> list[str]:
    """Check the built board is electrically the circuit that was asked for.

    Returns a list of human-readable problems; empty list means the layout is
    exactly the netlist. This is the safety net under the whole pipeline: a
    placement bug shows up here instead of as smoke on the bench.
    """
    errors: list[str] = []
    uf = solve_nodes(layout.wires)

    # net name -> set of electrical nodes its pins landed on
    nodes_by_net: dict[str, set[str]] = {}
    pins_by_net: dict[str, list[str]] = {}
    for comp in layout.components:
        for pin in comp.pins:
            nid = uf.find(node_id(pin.hole.row, pin.hole.col))
            nodes_by_net.setdefault(pin.net, set()).add(nid)
            pins_by_net.setdefault(pin.net, []).append(
                f"{comp.ref}.{pin.name}@{pin.hole.key()}"
            )

    # 1. every net must be one node (nothing left unconnected)
    for net, nodes in sorted(nodes_by_net.items()):
        if len(nodes) > 1:
            errors.append(
                f"net '{net}' is split across {len(nodes)} separate nodes: "
                + ", ".join(sorted(pins_by_net[net]))
            )

    # 2. two different nets must never share a node (nothing shorted)
    owner: dict[str, str] = {}
    for net, nodes in sorted(nodes_by_net.items()):
        for nid in nodes:
            if nid in owner and owner[nid] != net:
                errors.append(
                    f"short: nets '{owner[nid]}' and '{net}' both land on node {nid}"
                )
            owner.setdefault(nid, net)

    # 2b. every instrument lead lands on the node of the net it's meant to drive
    for lead in getattr(layout, "leads", []):
        nid = uf.find(node_id(lead.hole.row, lead.hole.col))
        expected = nodes_by_net.get(lead.net)
        if expected and nid not in expected:
            errors.append(
                f"the {lead.instrument.lower()}'s {lead.terminal} lead at "
                f"{lead.hole.key()} isn't connected to net '{lead.net}'"
            )
        for net, nodes in nodes_by_net.items():
            if net != lead.net and nid in nodes:
                errors.append(
                    f"short: the {lead.instrument.lower()}'s {lead.terminal} lead "
                    f"({lead.net}) lands on net '{net}'"
                )

    # 3. a wire that goes nowhere
    for w in layout.wires:
        a = node_id(w.from_hole.row, w.from_hole.col)
        b = node_id(w.to_hole.row, w.to_hole.col)
        if a == b:
            errors.append(
                f"pointless jumper on net '{w.net}': {w.from_hole.key()} and "
                f"{w.to_hole.key()} are already the same strip"
            )

    # 4. strips can only hold five leads
    load: dict[str, int] = {}
    for comp in layout.components:
        for pin in comp.pins:
            if not is_rail(pin.hole.row):
                load[node_id(pin.hole.row, pin.hole.col)] = (
                    load.get(node_id(pin.hole.row, pin.hole.col), 0) + 1
                )
    for w in layout.wires:
        for h in (w.from_hole, w.to_hole):
            if not is_rail(h.row):
                load[node_id(h.row, h.col)] = load.get(node_id(h.row, h.col), 0) + 1
    for nid, n in sorted(load.items()):
        if n > 5:
            errors.append(f"strip {nid} needs {n} holes but only has 5")

    return errors
