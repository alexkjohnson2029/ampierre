"""How clean a finished board looks — so the placer can compare layouts.

Correctness is breadboard.verify()'s job. This module scores the things that
make a correct board hard to follow:

  diagonal   a jumper that isn't flat along a row or straight down a column
  crossings  two jumpers whose paths cross or lie on top of each other
  over_part  a jumper running across a hole that holds a part's lead or body
  wires      how many jumpers there are at all
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from . import breadboard as bb
from .models import Layout


@dataclass(frozen=True)
class Quality:
    wires: int
    diagonal: int
    crossings: int
    over_part: int

    @property
    def score(self) -> int:
        """Lower is cleaner. A messy wire costs more than an extra tidy one."""
        return 4 * self.diagonal + 4 * self.crossings + 3 * self.over_part + self.wires


def _pt(hole) -> tuple[float, float]:
    return (hole.col, bb.ROW_POS[hole.row])


def _touches(a, b, c, d) -> bool:
    """Do segments ab and cd meet anywhere except at a shared end?"""

    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 == o2 == o3 == o4 == 0:  # on one line: do they overlap?
        axis = 1 if a[0] == b[0] else 0
        lo1, hi1 = sorted((a[axis], b[axis]))
        lo2, hi2 = sorted((c[axis], d[axis]))
        return min(hi1, hi2) - max(lo1, lo2) > 1e-9
    if {a, b} & {c, d}:
        return False
    return o1 != o2 and o3 != o4


def _part_points(layout: Layout) -> set[tuple[float, float]]:
    pts: set[tuple[float, float]] = set()
    for comp in layout.components:
        for pin in comp.pins:
            pts.add(_pt(pin.hole))
        if len(comp.pins) != 2:
            continue
        a, b = comp.pins
        if a.hole.row == b.hole.row:  # lying along a row
            lo, hi = sorted((a.hole.col, b.hole.col))
            pts.update((c, bb.ROW_POS[a.hole.row]) for c in range(lo + 1, hi))
        elif a.hole.col == b.hole.col:  # standing in a column
            pts.update(
                (a.hole.col, bb.ROW_POS[r]) for r in bb.rows_between(a.hole.row, b.hole.row)
            )
    return pts


def _runs_over(a, b, points) -> bool:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if not length2:
        return False
    for q in points:
        if q in (a, b):
            continue
        t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / length2
        if 0 < t < 1:
            px, py = a[0] + t * dx, a[1] + t * dy
            if (px - q[0]) ** 2 + (py - q[1]) ** 2 < 0.09:
                return True
    return False


def measure(layout: Layout) -> Quality:
    wires = [w for w in layout.wires if w.kind != "rail_bond"]
    segs = [(_pt(w.from_hole), _pt(w.to_hole)) for w in wires]
    parts = _part_points(layout)
    return Quality(
        wires=len(layout.wires),
        diagonal=sum(
            1
            for w in wires
            if w.from_hole.row != w.to_hole.row and w.from_hole.col != w.to_hole.col
        ),
        crossings=sum(1 for (a, b), (c, d) in combinations(segs, 2) if _touches(a, b, c, d)),
        over_part=sum(1 for a, b in segs if _runs_over(a, b, parts)),
    )
