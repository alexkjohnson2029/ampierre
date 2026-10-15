/* The schematic model behind the drawing editor: symbols, connectivity, and
 * the two things a drawing turns into — a Netlist for the placer, and a SPICE
 * deck you can open elsewhere.
 *
 * Everything is in grid units (one grid step = G pixels on screen). Nothing
 * here touches the DOM, so the same code could run in node.
 */

export const G = 16;

/* Each symbol is drawn LTspice-style in its own grid coordinates, pins on grid
 * points. `paths` are stroked; `fills` are stroked and filled. `label` is
 * where the ref and value text go, before rotation. */
export const SYMBOLS = {
  resistor: {
    name: "Resistor", key: "R", prefix: "R", kind: "resistor", value: "1k",
    pins: [["1", 0, 0], ["2", 0, 4]],
    paths: ["M0 0V1l.4 .167l-.8 .333l.8 .333l-.8 .333l.8 .333l-.8 .333l.4 .167V4"],
    box: [-0.6, 0, 0.6, 4], label: [0.9, 1.6],
  },
  capacitor: {
    name: "Capacitor", key: "C", prefix: "C", kind: "capacitor", value: "100n",
    pins: [["1", 0, 0], ["2", 0, 4]],
    paths: ["M0 0V1.8M-.8 1.8H.8M-.8 2.2H.8M0 2.2V4"],
    box: [-0.9, 0, 0.9, 4], label: [1.1, 1.6],
  },
  polarized_capacitor: {
    name: "Electrolytic cap", key: "", prefix: "C", kind: "polarized_capacitor", value: "10u",
    pins: [["+", 0, 0], ["-", 0, 4]],
    paths: ["M0 0V1.8M-.8 1.8H.8M-.8 2.45Q0 2.05 .8 2.45M0 2.25V4", "M-.95 1.15h.45M-.725 .925v.45"],
    box: [-0.9, 0, 0.9, 4], label: [1.1, 1.6],
  },
  inductor: {
    name: "Inductor", key: "L", prefix: "L", kind: "inductor", value: "10m",
    pins: [["1", 0, 0], ["2", 0, 4]],
    paths: ["M0 0V1a.25 .25 0 0 1 0 .5a.25 .25 0 0 1 0 .5a.25 .25 0 0 1 0 .5a.25 .25 0 0 1 0 .5V4"],
    box: [-0.3, 0, 0.6, 4], label: [0.9, 1.6],
  },
  potentiometer: {
    name: "Potentiometer", key: "", prefix: "RV", kind: "potentiometer", value: "10k",
    pins: [["1", 0, 0], ["3", 0, 4], ["W", 2, 2]],
    paths: ["M0 0V1l.4 .167l-.8 .333l.8 .333l-.8 .333l.8 .333l-.8 .333l.4 .167V4", "M2 2H.75"],
    fills: ["M.45 2L.85 1.8V2.2Z"],
    box: [-0.6, 0, 2, 4], label: [0.9, 0.2],
  },
  diode: {
    name: "Diode", key: "D", prefix: "D", kind: "diode", value: "1N4148",
    pins: [["A", 0, 0], ["K", 0, 4]],
    paths: ["M0 0V1.5M0 2.5V4M-.7 2.5H.7"],
    fills: ["M-.7 1.5H.7L0 2.5Z"],
    box: [-0.8, 0, 0.8, 4], label: [1.0, 1.6],
  },
  led: {
    name: "LED", key: "", prefix: "D", kind: "led", value: "red",
    pins: [["A", 0, 0], ["K", 0, 4]],
    paths: ["M0 0V1.5M0 2.5V4M-.7 2.5H.7", "M.85 1.75l.6 -.45M.95 2.25l.6 -.45"],
    fills: ["M-.7 1.5H.7L0 2.5Z", "M1.55 1.22l-.3 .02l.17 .22Z", "M1.65 1.72l-.3 .02l.17 .22Z"],
    box: [-0.8, 0, 1.6, 4], label: [1.6, 2.4],
  },
  npn: {
    name: "NPN transistor", key: "", prefix: "Q", kind: "npn", value: "2N3904",
    pins: [["C", 2, 0], ["B", 0, 2], ["E", 2, 4]],
    paths: ["M0 2H1M1 1.2V2.8M1 1.6L2 1V0M1 2.4L2 3V4"],
    fills: ["M1.86 2.92L1.47 2.86L1.63 2.6Z"],
    box: [0, 0, 2, 4], label: [2.3, 1.6],
  },
  pnp: {
    name: "PNP transistor", key: "", prefix: "Q", kind: "pnp", value: "2N3906",
    pins: [["E", 2, 0], ["B", 0, 2], ["C", 2, 4]],
    paths: ["M0 2H1M1 1.2V2.8M1 1.6L2 1V0M1 2.4L2 3V4"],
    fills: ["M1.14 1.52L1.37 1.2L1.53 1.46Z"],
    box: [0, 0, 2, 4], label: [2.3, 1.6],
  },
  nmos: {
    name: "N-MOSFET", key: "", prefix: "M", kind: "nmos", value: "2N7000",
    pins: [["D", 2, 0], ["G", 0, 2], ["S", 2, 4]],
    paths: ["M0 2H.75M.75 1.2V2.8M1.1 1.1V2.9M1.1 1.4H2V0M1.1 2.6H2V4M1.1 2H2V2.6"],
    fills: ["M1.15 2L1.5 1.84V2.16Z"],
    box: [0, 0, 2, 4], label: [2.3, 1.6],
  },
  pmos: {
    name: "P-MOSFET", key: "", prefix: "M", kind: "pmos", value: "BS250",
    pins: [["S", 2, 0], ["G", 0, 2], ["D", 2, 4]],
    paths: ["M0 2H.75M.75 1.2V2.8M1.1 1.1V2.9M1.1 1.4H2V0M1.1 2.6H2V4M1.1 2H2V1.4"],
    fills: ["M1.85 2L1.5 1.84V2.16Z"],
    box: [0, 0, 2, 4], label: [2.3, 1.6],
  },
  opamp: {
    name: "Op-amp", key: "", prefix: "U", kind: "opamp", value: "TL072",
    pins: [["IN-", 0, 2], ["IN+", 0, 4], ["OUT", 6, 3], ["V+", 3, 0], ["V-", 3, 6]],
    paths: ["M1 0V6L5 3Z", "M0 2H1M0 4H1M5 3H6M3 0V1.5M3 6V4.5", "M1.25 2h.45M1.25 4h.45M1.475 3.775v.45"],
    box: [0, 0, 6, 6], label: [3.6, 0.6], labelFixed: true,
  },
  regulator: {
    name: "Voltage regulator", key: "", prefix: "U", kind: "regulator", value: "LM7805",
    pins: [["IN", 0, 1], ["OUT", 6, 1], ["GND", 3, 3]],
    paths: ["M1 0H5V2H1Z", "M0 1H1M5 1H6M3 2V3"],
    box: [0, 0, 6, 3], label: [1.2, -1.2], labelFixed: true,
  },
  dc_source: {
    name: "DC supply", key: "V", prefix: "V", kind: "source_dc", value: "9",
    pins: [["+", 0, 0], ["-", 0, 4]],
    paths: ["M0 0V1M0 3V4", "M-.22 1.5h.44M0 1.28v.44M-.22 2.55h.44"],
    circle: [0, 2, 1],
    box: [-1, 0, 1, 4], label: [1.3, 1.6],
  },
  signal_source: {
    name: "Signal generator", key: "", prefix: "V", kind: "source_signal", value: "SINE(0 1 1k)",
    pins: [["+", 0, 0], ["-", 0, 4]],
    paths: ["M0 0V1M0 3V4", "M-.55 2q.275 -.7 .55 0t.55 0", "M.35 .55h.4M.55 .35v.4"],
    circle: [0, 2, 1],
    box: [-1, 0, 1, 4], label: [1.3, 1.6],
  },
  ground: {
    name: "Ground", key: "G", prefix: "", kind: "ground", value: "",
    pins: [["", 0, 0]],
    paths: ["M0 0V.5"],
    fills: ["M-.8 .5H.8L0 1.3Z"],
    box: [-0.8, 0, 0.8, 1.3], label: null,
  },
  label: {
    name: "Net label", key: "N", prefix: "", kind: "label", value: "VOUT",
    pins: [["", 0, 0]],
    paths: ["M-.2 -.2h.4v.4h-.4Z"],
    box: [-0.3, -1.2, 3, 0.3], label: null,
  },
};

/** Parts the editor places, in palette order. */
export const PALETTE = [
  "resistor", "capacitor", "polarized_capacitor", "inductor", "potentiometer",
  "diode", "led", "npn", "pnp", "nmos", "pmos", "opamp", "regulator",
  "dc_source", "signal_source", "ground", "label",
];

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/** Local symbol point -> schematic point: mirror, rotate (90° steps, clockwise
 *  on screen), then move. Matches SVG `translate rotate scale(-1,1)`. */
export function transform(part, lx, ly) {
  let x = part.mirror ? -lx : lx;
  let y = ly;
  for (let i = 0; i < ((part.rot || 0) & 3); i++) [x, y] = [-y, x];
  return [part.x + x, part.y + y];
}

export function pinsOf(part) {
  return SYMBOLS[part.type].pins.map(([name, lx, ly]) => {
    const [x, y] = transform(part, lx, ly);
    return { name, x, y };
  });
}

export function bboxOf(part) {
  const [x0, y0, x1, y1] = SYMBOLS[part.type].box;
  const pts = [[x0, y0], [x1, y0], [x0, y1], [x1, y1]].map(([x, y]) => transform(part, x, y));
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const pad = part.type === "label" ? 0 : 0.2;
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

/** Does point (x, y) lie on the segment, strictly between its ends? */
export function onSegmentInterior(w, x, y) {
  if ((x === w.x1 && y === w.y1) || (x === w.x2 && y === w.y2)) return false;
  const cross = (w.x2 - w.x1) * (y - w.y1) - (w.y2 - w.y1) * (x - w.x1);
  if (Math.abs(cross) > 1e-9) return false;
  return (
    Math.min(w.x1, w.x2) <= x && x <= Math.max(w.x1, w.x2) &&
    Math.min(w.y1, w.y2) <= y && y <= Math.max(w.y1, w.y2)
  );
}

export function distToSegment(w, x, y) {
  const dx = w.x2 - w.x1;
  const dy = w.y2 - w.y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((x - w.x1) * dx + (y - w.y1) * dy) / len2)) : 0;
  return Math.hypot(w.x1 + t * dx - x, w.y1 + t * dy - y);
}

// ---------------------------------------------------------------------------
// Connectivity
// ---------------------------------------------------------------------------

class UnionFind {
  constructor() { this.parent = new Map(); }
  find(a) {
    if (!this.parent.has(a)) this.parent.set(a, a);
    let r = a;
    while (this.parent.get(r) !== r) r = this.parent.get(r);
    this.parent.set(a, r);
    return r;
  }
  union(a, b) {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra !== rb) this.parent.set(ra, rb);
  }
}

const key = (x, y) => `${x},${y}`;
const GROUND_NAMES = new Set(["GND", "0", "AGND", "GROUND"]);

/** The name a label gives its net, with ground spelled one way. */
function labelName(part) {
  if (part.type === "ground") return "GND";
  const n = (part.value || "").trim();
  return GROUND_NAMES.has(n.toUpperCase()) ? "GND" : n;
}

/**
 * Work out which pins are joined, the way LTspice does: wires join at their
 * ends, a wire end or pin landing on the middle of another wire joins it,
 * wires that merely cross don't, and labels with the same name are one net.
 *
 * Returns { netOf(x, y), junctions: [[x, y]...], degree: Map }
 */
export function connectivity(doc) {
  const uf = new UnionFind();
  const degree = new Map(); // point -> how many things meet there
  const bump = (k, n = 1) => degree.set(k, (degree.get(k) || 0) + n);

  const points = [];
  for (const w of doc.wires) {
    uf.union(key(w.x1, w.y1), key(w.x2, w.y2));
    bump(key(w.x1, w.y1));
    bump(key(w.x2, w.y2));
    points.push([w.x1, w.y1], [w.x2, w.y2]);
  }
  for (const p of doc.parts) {
    for (const pin of pinsOf(p)) {
      uf.find(key(pin.x, pin.y));
      bump(key(pin.x, pin.y));
      points.push([pin.x, pin.y]);
      if (p.type === "ground" || p.type === "label") {
        const name = labelName(p);
        if (name) uf.union(key(pin.x, pin.y), `name:${name}`);
      }
    }
  }
  // T-junctions: anything landing part-way along a wire.
  const seen = new Set();
  for (const [x, y] of points) {
    const k = key(x, y);
    if (seen.has(k)) continue;
    seen.add(k);
    for (const w of doc.wires) {
      if (onSegmentInterior(w, x, y)) {
        uf.union(k, key(w.x1, w.y1));
        bump(k, 2);
      }
    }
  }
  const junctions = [...degree.entries()]
    .filter(([, n]) => n >= 3)
    .map(([k]) => k.split(",").map(Number));
  return { uf, degree, junctions };
}

/** Is anything other than this one pin at (x, y)? Used to mark loose pins. */
export function isConnected(conn, x, y) {
  return (conn.degree.get(key(x, y)) || 0) >= 2;
}

// ---------------------------------------------------------------------------
// Drawing -> netlist
// ---------------------------------------------------------------------------

const SOURCE_TYPES = new Set(["dc_source", "signal_source"]);
const MARKER_TYPES = new Set(["ground", "label"]);

function voltsText(value) {
  const v = String(value || "").trim();
  return /^[-+]?\d+(\.\d+)?$/.test(v) ? `${v}V` : v;
}

/**
 * The drawing as the Netlist the placer reads, plus the problems worth
 * fixing before it goes anywhere.
 *
 * Returns { netlist, errors: [...], warnings: [...] }. Errors stop the build
 * (nothing to place, two parts called R1); warnings ride along to the board.
 */
export function toNetlist(doc) {
  const conn = connectivity(doc);
  const errors = [];
  const warnings = [];

  // Every net gets a name: its label, else a power source's V+ / V-, else N001...
  const names = new Map(); // root -> name
  for (const p of doc.parts) {
    if (!MARKER_TYPES.has(p.type)) continue;
    const name = labelName(p);
    if (!name) continue;
    const root = conn.uf.find(`name:${name}`);
    const had = names.get(root);
    if (had && had !== name) {
      const keep = had === "GND" || name === "GND" ? "GND" : [had, name].sort()[0];
      warnings.push(`Labels "${had}" and "${name}" are wired together — treated as one net, "${keep}".`);
      names.set(root, keep);
    } else {
      names.set(root, name);
    }
  }

  const rootAt = (x, y) => conn.uf.find(key(x, y));

  for (const p of doc.parts) {
    if (p.type !== "dc_source" || p.power === false) continue;
    const [plus, minus] = pinsOf(p);
    const rp = rootAt(plus.x, plus.y);
    const rm = rootAt(minus.x, minus.y);
    const negative = String(p.value || "").trim().startsWith("-");
    if (names.get(rm) === "GND" && !names.has(rp)) names.set(rp, negative ? "V-" : "V+");
    if (names.get(rp) === "GND" && !names.has(rm)) names.set(rm, negative ? "V+" : "V-");
  }
  // A signal generator's hot side is the circuit's input: VIN, VIN2...
  let inputs = 0;
  for (const p of doc.parts) {
    if (p.type !== "signal_source" && !(p.type === "dc_source" && p.power === false)) continue;
    const [plus, minus] = pinsOf(p);
    const rp = rootAt(plus.x, plus.y);
    if (names.get(rootAt(minus.x, minus.y)) === "GND" && !names.has(rp)) {
      let n;
      do n = ++inputs === 1 ? "VIN" : `VIN${inputs}`;
      while ([...names.values()].includes(n));
      names.set(rp, n);
    }
  }

  let counter = 0;
  const netName = (x, y) => {
    const root = rootAt(x, y);
    if (!names.has(root)) {
      let n;
      do n = `N${String(++counter).padStart(3, "0")}`;
      while ([...names.values()].includes(n));
      names.set(root, n);
    }
    return names.get(root);
  };

  // How many pins land on each net, to spot loose ends.
  const pinCount = new Map();
  for (const p of doc.parts) {
    if (MARKER_TYPES.has(p.type)) continue;
    for (const pin of pinsOf(p)) {
      const r = rootAt(pin.x, pin.y);
      pinCount.set(r, (pinCount.get(r) || 0) + 1);
    }
  }
  const labelled = (x, y) => names.has(rootAt(x, y)) && !/^N\d{3}$/.test(names.get(rootAt(x, y)));

  const components = [];
  const sources = [];
  const refs = new Map();
  for (const p of doc.parts) {
    if (MARKER_TYPES.has(p.type)) continue;
    const sym = SYMBOLS[p.type];
    const ref = (p.ref || "").trim();
    if (!ref) {
      errors.push(`A ${sym.name.toLowerCase()} has no name — give it one (like ${sym.prefix}1).`);
      continue;
    }
    if (refs.has(ref)) {
      errors.push(`Two parts are both called ${ref}. Rename one of them.`);
      continue;
    }
    refs.set(ref, p);

    const pins = {};
    for (const pin of pinsOf(p)) {
      const loose = (pinCount.get(rootAt(pin.x, pin.y)) || 0) < 2 && !labelled(pin.x, pin.y);
      if (loose) {
        // A pot used as a variable resistor leaves one end free; that's normal.
        if (p.type === "potentiometer" && pin.name !== "W") continue;
        const what = pin.name ? `pin ${pin.name}` : "a pin";
        warnings.push(`${ref} ${what} isn't connected to anything.`);
      }
      pins[pin.name] = netName(pin.x, pin.y);
    }

    if (SOURCE_TYPES.has(p.type)) {
      const dc = p.type === "dc_source";
      sources.push({
        ref,
        kind: dc ? "dc" : "signal",
        pos: pins["+"],
        neg: pins["-"],
        value: dc ? voltsText(p.value) : p.value || null,
        purpose: dc ? (p.power === false ? "input" : "power") : "input",
      });
      continue;
    }
    components.push({ ref, kind: sym.kind, value: (p.value || "").trim() || null, pins });
  }

  if (!components.length) errors.push("There's nothing to put on a breadboard yet — add some parts.");
  const used = new Set(components.flatMap((c) => Object.values(c.pins)));
  if (components.length && !used.has("GND")) {
    warnings.push("Nothing is connected to ground. Add a ground symbol (press G).");
  }

  const nets = [...new Set([...names.values()])]
    .filter((n) => used.has(n) || sources.some((s) => s.pos === n || s.neg === n))
    .map((n) => (n === "GND" ? { name: n, role: "ground", voltage: "0 V" } : null))
    .filter(Boolean);

  return {
    netlist: {
      title: (doc.title || "").trim() || "My circuit",
      components,
      nets,
      sources,
      warnings: [...warnings],
    },
    errors,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// Drawing -> SPICE
// ---------------------------------------------------------------------------

/** A SPICE deck in LTspice's dialect. Ground is node 0; op-amps are
 *  subcircuit calls in the usual In+ In- V+ V- Out order. */
export function toSpice(doc) {
  const { netlist } = toNetlist(doc);
  const n = (net) => (net === "GND" ? "0" : net.replace(/\s+/g, "_"));
  const lines = [`* ${netlist.title}`, "* drawn in AMPierre"];
  const prefixed = (ref, letter) => (ref.toUpperCase().startsWith(letter) ? ref : `${letter}${ref}`);
  for (const c of netlist.components) {
    const p = c.pins;
    const v = c.value || "";
    switch (c.kind) {
      case "resistor":
        lines.push(`${prefixed(c.ref, "R")} ${n(p["1"])} ${n(p["2"])} ${v}`);
        break;
      case "capacitor":
        lines.push(`${prefixed(c.ref, "C")} ${n(p["1"])} ${n(p["2"])} ${v}`);
        break;
      case "polarized_capacitor":
        lines.push(`${prefixed(c.ref, "C")} ${n(p["+"])} ${n(p["-"])} ${v}`);
        break;
      case "inductor":
        lines.push(`${prefixed(c.ref, "L")} ${n(p["1"])} ${n(p["2"])} ${v}`);
        break;
      case "diode":
      case "led":
        lines.push(`${prefixed(c.ref, "D")} ${n(p.A)} ${n(p.K)} ${v || "D"}`);
        break;
      case "npn":
      case "pnp":
        lines.push(`${prefixed(c.ref, "Q")} ${n(p.C)} ${n(p.B)} ${n(p.E)} ${v || c.kind.toUpperCase()}`);
        break;
      case "nmos":
      case "pmos":
        lines.push(`${prefixed(c.ref, "M")} ${n(p.D)} ${n(p.G)} ${n(p.S)} ${n(p.S)} ${v || c.kind.toUpperCase()}`);
        break;
      case "opamp":
        lines.push(`X${c.ref} ${n(p["IN+"])} ${n(p["IN-"])} ${n(p["V+"])} ${n(p["V-"])} ${n(p.OUT)} ${v || "opamp"}`);
        break;
      case "regulator":
        lines.push(`X${c.ref} ${n(p.IN)} ${n(p.GND)} ${n(p.OUT)} ${v || "regulator"}`);
        break;
      case "potentiometer":
        // end, wiper, end — an unconnected end gets a node of its own
        lines.push(
          `X${c.ref} ${n(p["1"] || `${c.ref}_NC1`)} ${n(p.W)} ${n(p["3"] || `${c.ref}_NC3`)} potentiometer R=${v}`
        );
        break;
    }
  }
  for (const s of netlist.sources) {
    const value = s.kind === "dc" ? String(s.value || "").replace(/V$/i, "") : s.value || "";
    lines.push(`${prefixed(s.ref, "V")} ${n(s.pos)} ${n(s.neg)} ${value}`);
  }
  lines.push(".end");
  return lines.join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// A starter drawing
// ---------------------------------------------------------------------------

/** A non-inverting amplifier, gain 11, on ±9 V — something to poke at. */
export function sampleDoc() {
  let id = 0;
  const part = (type, x, y, extra = {}) => ({
    id: `p${++id}`, type, x, y, rot: 0, mirror: false,
    value: SYMBOLS[type].value, ...extra,
  });
  const wire = (x1, y1, x2, y2) => ({ id: `w${++id}`, x1, y1, x2, y2 });
  return {
    title: "Non-inverting amplifier",
    parts: [
      part("dc_source", 4, 4, { ref: "V1", value: "9", power: true }),
      part("label", 4, 4, { value: "V+" }),
      part("ground", 4, 8),
      part("dc_source", 10, 4, { ref: "V2", value: "-9", power: true }),
      part("label", 10, 4, { value: "V-" }),
      part("ground", 10, 8),
      part("signal_source", 19, 12, { ref: "V3", value: "SINE(0 0.5 1k)" }),
      part("ground", 19, 16),
      part("opamp", 20, 6, { ref: "U1", value: "TL072" }),
      part("label", 23, 6, { value: "V+" }),
      part("label", 23, 12, { value: "V-" }),
      part("resistor", 26, 4, { ref: "R2", value: "10k", rot: 1 }),
      part("resistor", 16, 8, { ref: "R1", value: "1k" }),
      part("ground", 16, 12),
      part("label", 28, 9, { value: "VOUT" }),
    ],
    wires: [
      wire(19, 12, 19, 10),
      wire(19, 10, 20, 10),
      wire(22, 4, 16, 4),
      wire(16, 4, 16, 8),
      wire(16, 8, 20, 8),
      wire(26, 4, 26, 9),
      wire(26, 9, 28, 9),
    ],
    nextId: id + 1,
  };
}
