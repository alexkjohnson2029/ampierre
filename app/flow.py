"""Schematic-shaped placement.

The packed placer in placer.py fills the board tightly. That is efficient and
unreadable: nothing about where a part sits tells you what it does.

This one lays the board out the way the schematic reads, top to bottom:

    schematic                       breadboard (top view)

      Vcc ──────────               + rail ═══╤═══╤═══════════
       │      │                             R1  Rc            parts hang from
      R1     Rc                             │   │             the supply rail
       │      │                          ┌──┴───┴──┐
       ├───── Q1                         │ E  B  C │  Q1      transistor in
       │      │                          └──┬──┬───┘          the middle
      R2     Re                    ── channel │  │ ─────────
       │      │                             Re  R2            parts stand on
      GND ──────────               − rail ═══╧═══╧═══════════  the ground rail

Every net gets its own column. A transistor or chip keeps its legs in
neighbouring strips; nets hanging off it sit beside it on the side their
connections lean towards (input, then E-B-C, then output). A part with one end
on supply or ground plugs straight into that rail instead of needing a strip
and a jumper; every other part spans the two columns its nets live in.

Two spacings. Compact puts the net columns three apart and keeps a simple
circuit above the channel; Spacious puts them five apart so every lead can be
traced by eye.

Correctness is unchanged: this only chooses *where*. The same verifier runs
afterwards, and if a circuit can't be laid out this way the caller falls back
to packing it.
"""

from __future__ import annotations

from collections import defaultdict, deque

from . import breadboard as bb
from . import packages as pk
from . import values as val
from .models import Component, Hole, NetRole, PlacedComponent, PlacedPin
from .placer import THREE_LEAD, Placer

#: Rows a part may use, nearest the channel first. Hubs (transistors, ICs) take
#: the inner rows; two-lead parts stack outward from there.
TOP_HUB_ROW = "G"
TOP_PART_ROWS = ("H", "I", "J")
BOTTOM_HUB_ROW = "D"
BOTTOM_PART_ROWS = ("C", "B", "A")

#: Compact mode keeps a circuit with no IC entirely above the channel. The
#: transistor goes in the outermost row so all four rows under it are free for
#: parts that run across its legs' columns.
TOP_ONLY_HUB_ROW = "J"
TOP_ONLY_PART_ROWS = ("I", "H", "G", "F")

#: How far a part plugged into a rail stands, in hole pitches: about the
#: length of a quarter-watt resistor with its leads bent down, and enough body
#: to print its name on.
RAIL_MOUNT_SPAN = 3.5
#: A radial part — LED, disc or electrolytic capacitor — has both leads coming
#: out of the bottom of its body. It sits in the rail and the first row in,
#: covering nothing, the way it would at the bench.
RADIAL_MOUNT_SPAN = 1.5


def rail_mount_row(rail: str, half: str, form: str = "axial") -> str:
    """The first row in from the board's edge that's far enough from the rail."""
    span = RADIAL_MOUNT_SPAN if form == "radial" else RAIL_MOUNT_SPAN
    edge_in = bb.strip_rows(half) if half == "top" else bb.strip_rows(half)[::-1]
    for row in edge_in:
        if abs(bb.ROW_POS[row] - bb.ROW_POS[rail]) >= span:
            return row
    return edge_in[-1]


class FlowPlacer(Placer):
    START_COL = 3

    def __init__(
        self,
        netlist,
        custom=None,
        spacing: int = 4,
        top_only: bool = False,
        skip_homes: set[str] | None = None,
        dodge_gaps: bool = True,
        rail_mount: bool | str = True,
    ):
        super().__init__(netlist, custom)
        self.dodge_gaps = dodge_gaps
        #: True: plug every part with one end on supply/ground into the rail.
        #: "light": only where the strip it lands in keeps room for the rest
        #: of that net — a standing part covers the holes it stands over.
        #: False: never.
        self.rail_mount = rail_mount
        #: supply/ground nets that need no column: every part on them plugs
        #: straight into the rail (worked out by a first pass — see place())
        self.skip_homes = skip_homes or set()
        self.step = spacing + 1  # columns between one net's strip and the next
        # An IC straddles the channel whatever happens, so "top half only" is
        # only on offer for circuits without one.
        self.top_only = top_only and not any(
            self.package_for(c).straddles_channel for c in netlist.components
        )
        #: net name -> the strip that net "lives" in
        self.home: dict[str, tuple[str, int]] = {}
        self.rank: dict[str, int] = {}
        self.chip_nets: set[str] = set()  # nets on a pin of a DIP chip
        self.cursor = self.START_COL

    # -- ranking ------------------------------------------------------------

    def _net_graph(self) -> dict[str, set[str]]:
        """Two nets are neighbours if some component bridges them."""
        graph: dict[str, set[str]] = defaultdict(set)
        for comp in self.nl.components:
            nets = list(dict.fromkeys(comp.pins.values()))
            for a in nets:
                graph[a].update(n for n in nets if n != a)
        return graph

    def rank_nets(self) -> dict[str, int]:
        """How far each net sits from the supply, in components.

        Breadth-first from the supply rails. Ground is forced to the far end
        however short its path, because that is where the eye expects it.
        """
        graph = self._net_graph()
        all_nets = list(self.nets)
        supplies = [n for n in all_nets if self.role(n) is NetRole.SUPPLY_POS]
        inputs = [n for n in all_nets if self.role(n) in (NetRole.INPUT, NetRole.SIGNAL)]
        grounds = [n for n in all_nets if self.role(n) is NetRole.GROUND]
        negatives = [n for n in all_nets if self.role(n) is NetRole.SUPPLY_NEG]

        seeds = supplies or inputs[:1] or all_nets[:1]
        rank: dict[str, int] = {n: 0 for n in seeds}
        queue = deque(seeds)
        while queue:
            net = queue.popleft()
            for other in sorted(graph[net]):
                if other in rank or other in grounds:
                    continue
                rank[other] = rank[net] + 1
                queue.append(other)

        far = max(rank.values(), default=0)
        for net in all_nets:  # anything the walk never reached
            rank.setdefault(net, far + 1)
        far = max(rank.values(), default=0)
        for net in negatives:
            rank[net] = far + 1
        for net in grounds:
            rank[net] = max(rank.values(), default=0) + 1
        return rank

    # -- column assignment --------------------------------------------------

    def _first_seen(self) -> dict[str, int]:
        order: dict[str, int] = {}
        for i, comp in enumerate(self.nl.components):
            for net in comp.pins.values():
                order.setdefault(net, i)
        return order

    def assign_columns(self) -> list[tuple[Component, int]]:
        """Decide the left-to-right order of everything, then hand out columns.

        The board is built from *blocks*: a multi-leg part (transistor, IC) is
        one block whose legs must sit in neighbouring strips; every other net
        is a one-column block of its own. Blocks are ordered so that

          * the supply sits at the far left and ground at the far right,
          * each net that hangs off a transistor or IC sits right beside it —
            on whichever side its connections pull it towards — so the parts
            joining them stay short,
          * nets that only connect to each other stay together.

        That ordering is what makes the board read like the schematic: input
        on one side of the transistor, output on the other.
        """
        self.rank = self.rank_nets()
        blocks = self._build_blocks()
        hubs: list[tuple[Component, int]] = []
        for blk in self._shorten(self._order_blocks(blocks)):
            start = (
                self._clear_of_rail_gaps(self.cursor, blk) if self.dodge_gaps else self.cursor
            )
            for net, half, offset in blk["slots"]:
                self.home.setdefault(net, (half, start + offset))
            if blk["hub"] is not None:
                hubs.append((blk["hub"], start))
            self.cursor = start + blk["width"] - 1 + self.step
        return hubs

    @staticmethod
    def _clear_of_rail_gaps(start: int, blk: dict) -> int:
        """Nudge a block right until none of its columns sits on a rail gap.

        The rails skip a hole every sixth column. A net whose strip sits on one
        of those columns can't have a part plugged straight into the rail
        beside it, so it's worth moving the block over a column or two. A chip
        wider than the gap spacing can't dodge them all; it stays put.
        """
        cols = [off for _, _, off in blk["slots"]]
        for shift in range(6):
            if all(start + shift + off in bb.RAIL_COLUMNS for off in cols):
                return start + shift
        return start

    def _build_blocks(self) -> list[dict]:
        claimed: set[str] = set()
        blocks: list[dict] = []
        for comp in self.nl.components:
            pkg = self.package_for(comp)
            if pkg.straddles_channel:
                half_pins = pkg.pin_count // 2
                flipped = self.ic_flipped(comp, pkg)
                slots = []
                for logical, net in comp.pins.items():
                    number = pk.resolve_pin(pkg, logical)
                    if number is None or net in claimed:
                        continue
                    claimed.add(net)
                    self.chip_nets.add(net)
                    half, offset = self.ic_slot(pkg, number, flipped)
                    slots.append((net, half, offset))
                blocks.append({"id": comp.ref, "hub": comp, "slots": slots, "width": half_pins})
            elif pkg.form in THREE_LEAD:
                names = self._lead_order(comp, pkg)
                slots = []
                for i, logical in enumerate(names):
                    net = comp.pins[logical]
                    if net not in claimed:
                        claimed.add(net)
                        slots.append((net, "top", i))
                blocks.append({"id": comp.ref, "hub": comp, "slots": slots, "width": len(names)})
        for net in self.nets:
            if net not in claimed and net not in self.skip_homes:
                blocks.append(
                    {"id": f"net:{net}", "hub": None, "slots": [(net, "top", 0)], "width": 1}
                )
        return blocks

    def _order_blocks(self, blocks: list[dict]) -> list[dict]:
        rank = self.rank
        seen = self._first_seen()
        by_id = {b["id"]: b for b in blocks}

        def role_of(b):
            if b["hub"] is not None or not b["slots"]:
                return None
            return self.role(b["slots"][0][0])

        first = [b for b in blocks if role_of(b) is NetRole.SUPPLY_POS]
        last = [b for b in blocks if role_of(b) is NetRole.SUPPLY_NEG] + [
            b for b in blocks if role_of(b) is NetRole.GROUND
        ]
        pinned = {b["id"] for b in first + last}
        hubs = [b for b in blocks if b["hub"] is not None]
        free = [b for b in blocks if b["hub"] is None and b["id"] not in pinned]

        def depth(b):
            nets = [n for n, _, _ in b["slots"]]
            return (
                min((rank.get(n, 99) for n in nets), default=99),
                min((seen.get(n, 99) for n in nets), default=99),
                b["id"],
            )

        hubs.sort(key=depth)
        free.sort(key=depth)

        # Which blocks each two-lead part joins, and at which leg of a hub.
        net_block = {n: b["id"] for b in blocks for n, _, _ in b["slots"]}
        leg_offset = {n: off for b in blocks for n, _, off in b["slots"]}
        links: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        legs: dict[tuple[str, str], list[int]] = defaultdict(list)
        for comp in self.nl.components:
            pkg = self.package_for(comp)
            if pkg.straddles_channel or pkg.form in THREE_LEAD:
                continue
            nets = list(dict.fromkeys(comp.pins.values()))
            if self.rail_mount and any(self.is_rail_net(n) for n in nets):
                continue  # it plugs into a rail: where it sits doesn't pull on order
            for a in nets:
                for b in nets:
                    ba, bb_ = net_block.get(a), net_block.get(b)
                    if a == b or ba is None or bb_ is None or ba == bb_:
                        continue
                    links[ba][bb_] += 1
                    legs[(ba, bb_)].append(leg_offset.get(b, 0))

        # No transistor or chip to arrange things around (a bridge, an RC
        # network): the most-connected net becomes the centrepiece, and the
        # others sit either side of it — AC1, VDC, AC2 for a bridge.
        if not hubs and len(free) >= 3:
            pivot = max(free, key=lambda b: (sum(links[b["id"]].values()), -free.index(b)))
            if sum(links[pivot["id"]].values()) >= 2:
                free.remove(pivot)
                hubs.append(pivot)

        # Free nets that only connect to each other travel as one group.
        free_ids = {b["id"] for b in free}
        groups: list[list[str]] = []
        grouped: set[str] = set()
        for b in free:
            if b["id"] in grouped:
                continue
            group, queue = [], deque([b["id"]])
            grouped.add(b["id"])
            while queue:
                cur = queue.popleft()
                group.append(cur)
                for other in sorted(links[cur], key=lambda o: depth(by_id[o])):
                    if other in free_ids and other not in grouped:
                        grouped.add(other)
                        queue.append(other)
            groups.append(group)

        # Hang each group off the hub it is most connected to, on the side
        # its connections lean towards.
        sides = {h["id"]: {"left": [], "right": []} for h in hubs}
        orphans: list[list[str]] = []
        for group in groups:
            pull: dict[str, int] = defaultdict(int)
            for member in group:
                for other, n in links[member].items():
                    if other in sides:
                        pull[other] += n
            if not pull:
                orphans.append(group)
                continue
            hub_id = max(pull, key=lambda h: (pull[h], -hubs.index(by_id[h])))
            hub = by_id[hub_id]
            offsets = [o for m in group for o in legs[(m, hub_id)]]
            centre = (hub["width"] - 1) / 2
            lean = (sum(offsets) / len(offsets) - centre) if offsets else 0.0
            left_w = sum(len(g) for g in sides[hub_id]["left"])
            right_w = sum(len(g) for g in sides[hub_id]["right"])
            if lean < -0.25 or (abs(lean) <= 0.25 and left_w <= right_w):
                side = "left"
            else:
                side = "right"
            group.sort(key=lambda m: -links[m].get(hub_id, 0))  # wired-to-hub goes nearest
            sides[hub_id][side].append(group)

        middle: list[str] = []
        for hub in hubs:
            for group in reversed(sides[hub["id"]]["left"]):
                middle.extend(reversed(group))
            middle.append(hub["id"])
            for group in sides[hub["id"]]["right"]:
                middle.extend(group)

        # Loose nets with no transistor or IC to hang off: a few passes of the
        # barycentre heuristic, each net drifting towards the average position
        # of whatever it connects to.
        loose = [m for g in orphans for m in g]
        head = [b["id"] for b in first]
        tail = [b["id"] for b in last]
        order = head + middle + loose + tail
        for _ in range(4):
            pos = {bid: i for i, bid in enumerate(order)}

            def pull_to(bid, pos=pos):
                ns = links[bid]
                if not ns:
                    return pos[bid]
                return sum(pos[o] * n for o, n in ns.items()) / sum(ns.values())

            loose.sort(key=lambda bid: (pull_to(bid), depth(by_id[bid])))
            order = head + middle + loose + tail
        return [by_id[bid] for bid in order]

    # -- shortening the wiring ----------------------------------------------

    def _wiring_length(self, order: list[dict]) -> int:
        """Roughly how far apart the parts' leads land, for one block order.

        Columns are handed out the way assign_columns will hand them out.
        Every two-lead part costs the distance between the columns its nets
        live in; a transistor, pot or chip leg whose net lives in another
        block costs the distance to that block. Parts that will plug straight
        into a rail cost nothing — where they sit is decided by their other
        end. Crossing the channel costs a few columns extra.
        """
        home: dict[str, tuple[str, int]] = {}
        legs: list[tuple[str, str, int]] = []  # (net, half, column) of hub legs
        cursor = self.START_COL
        for blk in order:
            for net, half, off in blk["slots"]:
                home.setdefault(net, (half, cursor + off))
            hub = blk["hub"]
            if hub is not None and not self.package_for(hub).straddles_channel:
                pkg = self.package_for(hub)
                for i, name in enumerate(self._lead_order(hub, pkg)):
                    legs.append((hub.pins[name], "top", cursor + i))
            cursor += blk["width"] - 1 + self.step

        def far(a, b):
            return abs(a[1] - b[1]) + (3 if a[0] != b[0] else 0)

        total = 0
        for net, half, col in legs:
            if net in home and not self.is_rail_net(net) and home[net] != (half, col):
                total += far(home[net], (half, col))
        for comp in self.nl.components:
            pkg = self.package_for(comp)
            if pkg.straddles_channel or pkg.form in THREE_LEAD:
                continue
            nets = list(dict.fromkeys(comp.pins.values()))
            if len(nets) != 2:
                continue
            if self.rail_mount and any(self.is_rail_net(n) for n in nets):
                continue
            if all(n in home for n in nets):
                total += far(home[nets[0]], home[nets[1]])
        # A board wider than the board is no use however short its wires.
        overflow = max(0, cursor - self.step - self.board.columns)
        return total + 50 * overflow

    def _shorten(self, order: list[dict]) -> list[dict]:
        """Move blocks along the board while that shortens the wiring.

        The ordering rules put a small circuit in a good order on their own.
        A big one — two chips, a dozen nets of filter parts — leaves nets far
        from the parts that use them. So: take each block in turn, try it in
        every other position, keep any move that makes the wiring shorter, and
        repeat until nothing improves. Supply stays first and ground last.
        """
        pinned_head = 0
        while pinned_head < len(order) and self._is_pinned(order[pinned_head], first=True):
            pinned_head += 1
        pinned_tail = len(order)
        while pinned_tail > pinned_head and self._is_pinned(order[pinned_tail - 1], first=False):
            pinned_tail -= 1
        head, middle, tail = order[:pinned_head], order[pinned_head:pinned_tail], order[pinned_tail:]
        if len(middle) < 3:
            return order

        best = self._wiring_length(head + middle + tail)
        for _ in range(8):
            improved = False
            for blk in list(middle):
                i = middle.index(blk)
                rest = middle[:i] + middle[i + 1 :]
                choice, choice_cost = None, best
                for j in range(len(rest) + 1):
                    if j == i:
                        continue
                    trial = rest[:j] + [blk] + rest[j:]
                    cost = self._wiring_length(head + trial + tail)
                    if cost < choice_cost:
                        choice, choice_cost = trial, cost
                if choice is not None:
                    middle, best, improved = choice, choice_cost, True
            if not improved:
                break
        return head + middle + tail

    def _is_pinned(self, blk: dict, first: bool) -> bool:
        if blk["hub"] is not None or not blk["slots"]:
            return False
        role = self.role(blk["slots"][0][0])
        if first:
            return role is NetRole.SUPPLY_POS
        return role in (NetRole.SUPPLY_NEG, NetRole.GROUND)

    # -- placement ----------------------------------------------------------

    def _strip_for(self, net: str, want: tuple[str, int], needed: int = 1) -> tuple[str, int] | None:
        """A strip this net may use, as near `want` as possible.

        Its own column if that still has room; otherwise the nearest column
        that is free or already carries this net. A second strip on the same
        net is fine — the router jumpers them together.
        """
        half, col = want
        if self.strip_ok_for(half, col, net) and self.board.strip_has_room(half, col, needed):
            return half, col
        for delta in range(1, 12):
            for candidate in (col - delta, col + delta):
                if not 1 <= candidate <= self.board.columns:
                    continue
                if self.strip_ok_for(half, candidate, net) and self.board.strip_has_room(
                    half, candidate, needed
                ):
                    return half, candidate
        return None

    def place_components(self) -> None:
        hubs = self.assign_columns()
        # Decoupling caps and bleeders go across the rails past the end of the
        # circuit, leaving the supply column clear for its rail wire.
        self.rail_part_from = self.cursor

        hub_row = TOP_ONLY_HUB_ROW if self.top_only else TOP_HUB_ROW
        for hub, start in hubs:
            pkg = self.package_for(hub)
            if pkg.straddles_channel:
                self._emit_ic(hub, pkg, start)
            else:
                names = self._lead_order(hub, pkg)
                nets = [hub.pins[n] for n in names]
                cols = [start + i for i in range(len(names))]
                self._emit_discrete(hub, pkg, names, nets, "top", cols, (hub_row,))

        # Hold the outermost hole of each supply and ground column for the wire
        # that runs to the rail, so it drops straight in instead of having to
        # arch over the parts' leads to reach an inner row.
        for net, (half, col) in self.home.items():
            if not self.is_rail_net(net):
                continue
            row = bb.TOP_RAIL_JUMPER_ROW if half == "top" else bb.BOTTOM_RAIL_JUMPER_ROW
            if self.board.is_free(row, col):
                self.board.occupy(row, col, f"railhole:{net}")

        # two-lead parts, left to right, so rows fill in reading order
        two_lead = [
            c
            for c in self.nl.components
            if not self.package_for(c).straddles_channel
            and self.package_for(c).form not in THREE_LEAD
        ]
        two_lead.sort(
            key=lambda c: min((self.home[n][1] for n in c.pins.values() if n in self.home), default=0)
        )
        # Parts that plug into a rail go first: each has exactly one column and
        # one pair of rows it can use, while a part between two nets can slide.
        # Placed the other way round, the flexible parts take the fixed ones'
        # holes and the rail ones get pushed onto jumpers.
        for comp in two_lead:
            pkg = self.package_for(comp)
            names = self._lead_order(comp, pkg)
            nets = [comp.pins[n] for n in names]
            if len(nets) == 2 and sum(self.is_rail_net(n) for n in nets) == 1:
                self._try_rail_mount(comp, pkg, names, nets)
        placed = {c.ref for c in self.placed}
        for comp in two_lead:
            if comp.ref not in placed:
                self._place_spanning(comp)

    def _place_spanning(self, comp: Component) -> None:
        pkg = self.package_for(comp)
        names = self._lead_order(comp, pkg)
        nets = [comp.pins[n] for n in names]
        if len(nets) != 2:
            self.warnings.append(f"{comp.ref}: {len(nets)} leads — flow layout handles two.")
            return
        # Decoupling still belongs straight across the rails, whatever the
        # layout style: that is where it does its job.
        if self._try_rail_to_rail(comp, pkg, names, nets):
            return
        # One end on supply or ground: plug that end straight into the rail.
        if self._try_rail_mount(comp, pkg, names, nets):
            return
        if any(n not in self.home for n in nets):
            self.warnings.append(f"{comp.ref}: no rail hole free for it — not placed.")
            return

        home = [self.home[n][1] for n in nets]

        # Which side of the channel: the schematic's supply end sits above it,
        # the ground end below, so the board reads top-to-bottom the way the
        # drawing does.
        far = max(self.rank.values(), default=1) or 1
        depth = sum(self.rank.get(n, 0) for n in nets) / (2 * far)
        # Which side already has a strip for more of this part's nets? Going
        # there means its leads land in strips that exist, instead of starting
        # new ones that need a jumper back across the channel.
        votes = {
            half: sum(1 for n in nets if any(h == half for h, _ in self.net_strips.get(n, [])))
            for half in ("top", "bottom")
        }
        rows = {"top": TOP_PART_ROWS, "bottom": BOTTOM_PART_ROWS}
        if self.top_only:
            # Everything above the channel; the lower half only if it runs out.
            halves = (("top", TOP_ONLY_PART_ROWS), ("bottom", BOTTOM_PART_ROWS))
        elif votes["top"] != votes["bottom"]:
            side = "top" if votes["top"] > votes["bottom"] else "bottom"
            other = "bottom" if side == "top" else "top"
            halves = ((side, rows[side]), (other, rows[other]))
        elif depth < 0.5:
            halves = (("top", TOP_PART_ROWS), ("bottom", BOTTOM_PART_ROWS))
        else:
            halves = (("bottom", BOTTOM_PART_ROWS), ("top", TOP_PART_ROWS))

        def attempt(half, rows) -> bool:
            if half == "top":
                hub_row = TOP_ONLY_HUB_ROW if self.top_only else TOP_HUB_ROW
            else:
                hub_row = BOTTOM_HUB_ROW
            allowed = rows + (hub_row,)
            for cols in self._column_candidates(home):
                if not all(self.strip_ok_for(half, c, n) for c, n in zip(cols, nets)):
                    continue
                footprint = list(range(min(cols) - 1, max(cols) + 2))
                if self._row_free_across(half, footprint, allowed) is None:
                    continue
                if self._emit_discrete(comp, pkg, names, nets, half, list(cols), allowed):
                    return True
            return False

        preferred_half, preferred_rows = halves[0]
        if attempt(preferred_half, preferred_rows):
            return
        # Before sending the part to the other side of the channel, let it have
        # the holes kept for rail wires — a supply wire that has to reach one
        # row further in is a far smaller price than a part on the wrong side.
        released = self._release_railholes(preferred_half)
        if attempt(preferred_half, preferred_rows):
            return
        self._restore_railholes(released)
        for half, rows in halves[1:]:
            if attempt(half, rows):
                return
        self.warnings.append(
            f"{comp.ref}: no clear row between columns {min(home)} and {max(home)} "
            "— not placed."
        )

    # -- parts plugged straight into a rail ---------------------------------

    def _rail_for(self, net: str, half: str) -> str | None:
        """The rail on this side of the board that carries this net."""
        role = self.role(net)
        if role is NetRole.SUPPLY_POS:
            return bb.RAIL_TOP_POS if half == "top" else None
        if role is NetRole.SUPPLY_NEG:
            return bb.RAIL_BOT_POS if half == "bottom" else None
        if role is NetRole.GROUND:
            return bb.RAIL_TOP_NEG if half == "top" else bb.RAIL_BOT_NEG
        return None

    def _try_rail_mount(self, comp, pkg, names, nets) -> bool:
        """Stand a part between a rail and the strip of its other net.

        A part with one end on supply or ground doesn't need a strip and a
        jumper for that end — it plugs into the rail directly, the way you'd
        put in a pull-up resistor at the bench. Supply parts hang from the top
        rail and ground parts from the bottom one, so the board reads like the
        schematic: supply above, ground below.
        """
        rail_ends = [i for i, n in enumerate(nets) if self.is_rail_net(n)]
        if not self.rail_mount or len(rail_ends) != 1:
            return False
        ri = rail_ends[0]
        rail_net, x_net = nets[ri], nets[1 - ri]
        role = self.role(rail_net)
        if self.top_only or role is NetRole.SUPPLY_POS:
            halves = ("top",)
        elif role is NetRole.SUPPLY_NEG:
            halves = ("bottom",)
        else:  # ground: the bottom rail, like the schematic; the top if that's taken
            halves = ("bottom", "top")

        candidates: list[tuple[str, int]] = []
        home = self.home.get(x_net)
        for half in halves:
            for strip in [home] + list(self.net_strips.get(x_net, [])):
                if strip and strip[0] == half and strip not in candidates:
                    candidates.append(strip)
            # the home column on this side: a new strip, joined by one short drop
            if home and (half, home[1]) not in candidates:
                candidates.append((half, home[1]))
        return any(self._rail_mount_at(comp, pkg, names, nets, ri, h, c) for h, c in candidates)

    def _rail_mount_at(self, comp, pkg, names, nets, ri, half, col) -> bool:
        rail = self._rail_for(nets[ri], half)
        if rail is None or col not in bb.RAIL_COLUMNS:
            return False
        x_net = nets[1 - ri]
        land = rail_mount_row(rail, half, pkg.form)
        between = bb.rows_between(rail, land)  # what the part stands over
        holes = [(rail, col), (land, col)] + [(r, col) for r in between]
        if not all(self.board.is_free(r, c) for r, c in holes):
            return False
        if not self.strip_ok_for(half, col, x_net):
            return False
        if self.rail_mount == "light":
            taken = sum(1 for r, _ in holes if not bb.is_rail(r))
            if self.board.strip_room(half, col) - taken < self.holes_still_needed(x_net, comp.ref):
                return False

        self.board.occupy(rail, col, comp.ref)
        self.board.occupy(land, col, comp.ref)
        for r in between:
            self.board.occupy(r, col, f"cover:{comp.ref}")
        self.claim_strip(half, col, x_net)

        where = {ri: Hole(row=rail, col=col), 1 - ri: Hole(row=land, col=col)}
        pins = [
            PlacedPin(
                name=names[i],
                net=nets[i],
                hole=where[i],
                label=self._lead_label(pkg, names[i]),
            )
            for i in (0, 1)
        ]
        marked = next((p for p in pins if self._is_negative_lead(p.name)), pins[-1])
        other = pins[0] if marked is pins[-1] else pins[-1]
        above = bb.ROW_ORDER.index(marked.hole.row) < bb.ROW_ORDER.index(other.hole.row)
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
                    "half": "railmount",
                    "rail": rail,
                    "value_info": val.describe(comp.kind.value, comp.value, pkg.polarized),
                    "cols": [col, col],
                    "rows": [p.hole.row for p in pins],
                    "polarized": pkg.polarized,
                    "marker": pkg.marker,
                    "package_label": pkg.label,
                    "note": pkg.note,
                    "marked_end": "top" if above else "bottom",
                },
            )
        )
        side = "top" if bb.half_of_rail_side(rail) == "top" else "bottom"
        sign = "+" if bb.RAIL_POLARITY[rail] == "+" else "−"
        step = (
            f"Stand {comp.ref} ({comp.value or pkg.label}) upright in column {col}: one lead "
            f"in the {side} {sign} rail, the other in {land}{col}. No jumper needed for that end."
        )
        if pkg.polarized:
            cue = {
                "diode": "Banded end",
                "led": "Flat side (short lead)",
            }.get(comp.kind.value, "Striped lead")
            step += f" {cue} goes {'in the rail' if marked.hole.row == rail else 'in ' + land + str(col)}."
        self.component_steps.append((comp.ref, step))
        return True

    def _release_railholes(self, half: str) -> list[tuple[tuple[str, int], str]]:
        rows = set(bb.strip_rows(half))
        held = [
            (key, owner)
            for key, owner in self.board.occupied.items()
            if owner.startswith("railhole:") and key[0] in rows
        ]
        for key, _ in held:
            del self.board.occupied[key]
        return held

    def _restore_railholes(self, held) -> None:
        for key, owner in held:
            if key not in self.board.occupied:
                self.board.occupied[key] = owner

    def _column_candidates(self, home: list[int]):
        """Where this part's two leads could go, best first.

        Straight into both nets' own columns if that fits. Otherwise either end
        may slide a few columns: landing on a free column gives that net a
        second strip, and the router jumpers the two together. A part that has
        shuffled sideways is still on the right nets — it just stops fighting
        its neighbours for a row.
        """
        seen: set[tuple[int, int]] = set()

        def offer(a: int, b: int):
            if a == b or (a, b) in seen:
                return None
            if not (1 <= a <= self.board.columns and 1 <= b <= self.board.columns):
                return None
            if abs(a - b) > 10:  # a lead can only stretch so far
                return None
            seen.add((a, b))
            return (a, b)

        shifts = sorted(
            ((a, b) for a in range(-4, 5) for b in range(-4, 5)),
            key=lambda s: (abs(s[0]) + abs(s[1]), abs(s[0]), abs(s[1])),
        )
        for da, db in shifts:
            cols = offer(home[0] + da, home[1] + db)
            if cols:
                yield cols

        # Nets too far apart to bridge with one part: anchor the part beside
        # one of them and let a jumper cover the rest of the distance.
        for reach in range(3, 9):
            for cols in (
                offer(home[0], home[0] + reach),
                offer(home[0] - reach, home[0]),
                offer(home[1] - reach, home[1]),
                offer(home[1], home[1] + reach),
            ):
                if cols:
                    yield cols

    # -- build order --------------------------------------------------------

    def run(self):
        layout = super().run()
        layout.notes.append(
            "Laid out to follow the schematic: each net has its own column, and parts "
            "that connect to supply or ground plug straight into that rail where they can."
        )
        return layout


def flow_place(netlist, custom=None, spacing: int = 4):
    return FlowPlacer(netlist, custom, spacing=spacing).run()
