/* Breadboard renderer: Layout JSON -> SVG string.
 *
 * Pure function, no DOM access, so the same module renders in the browser and
 * in node (see tools/render_example.mjs). Hover behaviour rides on data-*
 * attributes handled by app.js through event delegation.
 *
 * renderBoard(layout, {upTo, current}) draws the board as it looks partway
 * through the build: everything up to step `upTo` is solid, step `current`
 * is ringed, and later parts are ghosted so you can see where they're going.
 */

export const PITCH = 24;
export const MARGIN_X = 54;
export const MARGIN_Y = 28;

/* Vertical position of every row, in pitch units. */
export const ROW_Y = {
  RAIL_TOP_POS: 0,
  RAIL_TOP_NEG: 1,
  J: 2.6,
  I: 3.6,
  H: 4.6,
  G: 5.6,
  F: 6.6,
  E: 8.6,
  D: 9.6,
  C: 10.6,
  B: 11.6,
  A: 12.6,
  RAIL_BOT_NEG: 14.2,
  RAIL_BOT_POS: 15.2,
};

const CHANNEL_Y = 7.6;
const RAILS = ["RAIL_TOP_POS", "RAIL_TOP_NEG", "RAIL_BOT_NEG", "RAIL_BOT_POS"];
const TOP_ROWS = ["J", "I", "H", "G", "F"];
const BOTTOM_ROWS = ["E", "D", "C", "B", "A"];

export const railColumns = (cols) => {
  const out = [];
  for (let c = 2; c < cols; c++) if ((c - 2) % 6 !== 5) out.push(c);
  return out;
};

const x = (col) => MARGIN_X + (col - 1) * PITCH;
const y = (row) => MARGIN_Y + ROW_Y[row] * PITCH;

const esc = (s) =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

/* Tooltips travel as a JSON blob on the element; app.js renders them. */
const tip = (obj) => `data-tip='${esc(JSON.stringify(obj))}'`;

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

function holes(cols) {
  let s = "";
  for (const row of [...TOP_ROWS, ...BOTTOM_ROWS]) {
    for (let c = 1; c <= cols; c++) {
      s += `<rect class="hole" x="${x(c) - 4}" y="${y(row) - 4}" width="8" height="8" rx="0"/>`;
    }
  }
  for (const rail of RAILS) {
    for (const c of railColumns(cols)) {
      s += `<rect class="hole" x="${x(c) - 4}" y="${y(rail) - 4}" width="8" height="8" rx="0"/>`;
    }
  }
  return s;
}

function railGraphics(layout) {
  const cols = layout.columns;
  const left = x(1) - 22;
  const right = x(cols) + 22;
  let s = "";
  for (const rail of RAILS) {
    const info = layout.rails?.[rail] || {};
    const pos = info.polarity === "+";
    const ry = y(rail);
    const lineY = rail.endsWith("POS")
      ? ry + (rail.startsWith("RAIL_TOP") ? -13 : 13)
      : ry + (rail.startsWith("RAIL_TOP") ? 13 : -13);
    const cls = pos ? "rail-line pos" : "rail-line neg";
    s += `<line class="${cls}" x1="${left}" y1="${lineY}" x2="${right}" y2="${lineY}"/>`;
    const label = pos ? "+" : "−";
    const sign = pos ? "rail-sign pos" : "rail-sign neg";
    s += `<text class="${sign}" x="${left - 10}" y="${ry + 5}" text-anchor="middle">${label}</text>`;
    s += `<text class="${sign}" x="${right + 10}" y="${ry + 5}" text-anchor="middle">${label}</text>`;

    const title = info.label ? info.label.replace(/^./, (m) => m.toUpperCase()) : "Unused rail";
    s += `<rect class="rail-hit" data-net="${esc(info.net || "")}" ${tip({
      title,
      subtitle: info.net ? `net ${info.net}` : "nothing connected to this rail",
      rows: [
        ["Supplies", info.voltage || (info.net ? "voltage not given on the schematic" : "—")],
        ["Polarity", pos ? "+ rail" : "− rail"],
        ["Watch out", "many boards split each rail at the middle — bridge it if yours does"],
      ],
    })} x="${left}" y="${ry - 11}" width="${right - left}" height="22" fill="transparent"/>`;
  }
  return s;
}

function labels(cols) {
  let s = "";
  for (const row of [...TOP_ROWS, ...BOTTOM_ROWS]) {
    s += `<text class="axis" x="${x(1) - 20}" y="${y(row) + 4}" text-anchor="middle">${row}</text>`;
    s += `<text class="axis" x="${x(cols) + 20}" y="${y(row) + 4}" text-anchor="middle">${row}</text>`;
  }
  for (let c = 1; c <= cols; c++) {
    if (c !== 1 && c % 5 !== 0) continue;
    s += `<text class="axis" x="${x(c)}" y="${y("J") - 13}" text-anchor="middle">${c}</text>`;
    s += `<text class="axis" x="${x(c)}" y="${y("A") + 20}" text-anchor="middle">${c}</text>`;
  }
  return s;
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

const leadDot = (p) =>
  `<circle class="lead-dot" data-net="${esc(p.net)}" cx="${x(p.hole.col)}" cy="${y(
    p.hole.row
  )}" r="5"/>`;

const halo = (pins) =>
  pins
    .map(
      (p) =>
        `<circle class="halo" cx="${x(p.hole.col)}" cy="${y(p.hole.row)}" r="13"/>`
    )
    .join("");

/* Short lead marks drawn next to the holes: A/K on a diode or LED, +/− on an
 * electrolytic. The orientation sentence is in the hover card; this is the bit
 * you need while your hand is over the board. */
const LEAD_MARK = { A: "A", K: "K", "+": "+", "-": "−", ANODE: "A", CATHODE: "K" };

function leadMark(pin, px, py) {
  const mark = LEAD_MARK[String(pin.name).toUpperCase()];
  if (!mark) return "";
  const cathodeish = mark === "K" || mark === "−";
  return `<text class="lead-mark${cathodeish ? " neg" : " pos"}" x="${px}" y="${py}" text-anchor="middle">${mark}</text>`;
}

/* The schematic's own remark about a part first, then the package's. */
const noteOf = (b) => [b.schematic_note, b.note].filter(Boolean).join(" ");

/* Small-signal and Zener diodes come in clear orange glass with a black band;
 * rectifiers and Schottkys in black epoxy with a grey one. Drawing them that
 * way is how you tell which one you picked. */
const isGlass = (comp) => /1n4148|zener/i.test(comp.package || "");

function valueRows(comp) {
  const v = comp.body?.value_info || {};
  const rows = [];
  if (v.pretty || v.raw) rows.push([comp.kind === "diode" ? "Part" : "Value", v.pretty || v.raw]);
  if (v.bands) rows.push(["Bands", v.bands.text]);
  if (v.code && v.cap_style === "ceramic") rows.push(["Marking", v.code]);
  return rows;
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

/* A chip pin the circuit doesn't use: placed (it's physically there) but
 * given a node of its own so nothing else can share its strip. */
const spare = (p) => String(p.net).endsWith("(not connected)");

function dip(comp) {
  const b = comp.body;
  const x0 = x(b.anchor_col) - PITCH * 0.5;
  const w = PITCH * b.span;
  const yTop = y("F") - 9;
  const yBot = y("E") + 9;
  const h = yBot - yTop;
  const ordered = comp.pins.slice().sort((p, q) => (p.number || 0) - (q.number || 0));

  let legs = "";
  for (const p of comp.pins) {
    const px = x(p.hole.col);
    const py = y(p.hole.row);
    const up = p.hole.row === "F";
    // the body sits over the holes, so a leg only shows if it pokes out
    const legH = up ? yTop - py : py - yBot;
    if (legH > 0) {
      legs += `<rect class="leg" x="${px - 3}" y="${up ? py : yBot}" width="6" height="${legH}" rx="1"/>`;
    }
    legs += leadDot(p);
  }

  return `<g class="comp ic" data-ref="${esc(comp.ref)}" ${tip({
    title: `${comp.ref} — ${b.package_label || comp.package}`,
    subtitle: comp.orientation,
    rows: ordered.map((p) => [
      `Pin ${p.number} · ${p.label || p.name}`,
      spare(p) ? "not connected" : `${p.net} @ ${p.hole.row}${p.hole.col}`,
    ]),
    note: noteOf(b),
    pinout: {
      form: "dip",
      pin_count: Object.keys(b.pin_names || {}).length,
      names: b.pin_names || {},
      used: Object.fromEntries(ordered.filter((p) => !spare(p)).map((p) => [p.number, p.net])),
      title: comp.value || b.package_label || comp.ref,
    },
  })}>
    ${legs}
    <rect class="ic-body" x="${x0}" y="${yTop}" width="${w}" height="${h}" rx="3"/>
    ${
      b.notch === "right"
        ? /* turned round: notch on the right, pin-1 dot top right */
          `<path class="ic-notch" d="M ${x0 + w} ${yTop + h / 2 + 9} a 9 9 0 0 1 0 -18 z"/>
           <circle class="ic-dot" cx="${x0 + w - 12}" cy="${yTop + 11}" r="3.2"/>`
        : `<path class="ic-notch" d="M ${x0} ${yTop + h / 2 - 9} a 9 9 0 0 1 0 18 z"/>
           <circle class="ic-dot" cx="${x0 + 12}" cy="${yBot - 11}" r="3.2"/>`
    }
    <text class="ic-label" x="${x0 + w / 2}" y="${yTop + h / 2 - 2}" text-anchor="middle">${esc(
      comp.ref
    )}</text>
    <text class="ic-sub" x="${x0 + w / 2}" y="${yTop + h / 2 + 12}" text-anchor="middle">${esc(
      comp.value || ""
    )}</text>
  </g>`;
}

function threeLead(comp) {
  const b = comp.body;
  const pins = comp.pins;
  const cx = (x(b.cols[0]) + x(b.cols[b.cols.length - 1])) / 2;
  const row = b.rows[0];
  const up = b.half === "top"; // body sits away from the channel
  const baseY = y(row) + (up ? -16 : 16);
  const isTab = b.form === "to220";
  const r = PITCH * 1.05;
  const flatY = baseY + (up ? 10 : -10);

  let legs = "";
  for (const p of pins) {
    const px = x(p.hole.col);
    const py = y(p.hole.row);
    legs += `<path class="leg-wire" d="M ${px} ${py} L ${px} ${flatY}"/>`;
    legs += leadDot(p);
    legs += `<text class="pin-tag" x="${px}" y="${py + (up ? 14 : -8)}" text-anchor="middle">${esc(
      p.name
    )}</text>`;
  }

  let body;
  if (isTab) {
    /* TO-220: a slab with a metal tab, tab pointing away from the viewer. */
    const w = r * 2;
    const hBody = 26;
    const top = up ? flatY - hBody : flatY;
    body = `<rect class="to220-body" x="${cx - w / 2}" y="${top}" width="${w}" height="${hBody}" rx="2"/>
      <rect class="to220-tab" x="${cx - w / 2}" y="${up ? top - 9 : top + hBody}" width="${w}" height="9" rx="1.5"/>
      <circle class="to220-hole" cx="${cx}" cy="${up ? top - 4.5 : top + hBody + 4.5}" r="2.6"/>`;
  } else {
    /* TO-92: half-circle bulging away from you, flat face toward you. */
    const path = up
      ? `M ${cx - r} ${flatY} A ${r} ${r} 0 0 1 ${cx + r} ${flatY} Z`
      : `M ${cx + r} ${flatY} A ${r} ${r} 0 0 1 ${cx - r} ${flatY} Z`;
    body = `<path class="to92-body" d="${path}"/>
      <line class="to92-flat" x1="${cx - r}" y1="${flatY}" x2="${cx + r}" y2="${flatY}"/>`;
  }

  return `<g class="comp three-lead" data-ref="${esc(comp.ref)}" ${tip({
    title: `${comp.ref} — ${comp.value || b.package_label}`,
    subtitle: comp.orientation,
    rows: pins.map((p) => [p.label || p.name, `${p.net} @ ${p.hole.row}${p.hole.col}`]),
    note: noteOf(b),
    warn: isTab
      ? "The tab faces away from you in this drawing, and is usually live."
      : "Orientation matters: the flat face is toward you in this drawing.",
    pinout: {
      form: b.form,
      pin_count: 3,
      names: Object.fromEntries(pins.map((p, i) => [p.number || i + 1, p.label || p.name])),
      used: Object.fromEntries(pins.map((p, i) => [p.number || i + 1, p.net])),
      title: comp.value || b.package_label || comp.ref,
    },
  })}>
    ${legs}${body}
    <text class="comp-label on-dark" x="${cx}" y="${flatY + (up ? -9 : 20)}" text-anchor="middle">${esc(
      comp.ref
    )}</text>
  </g>`;
}

/* A trimmer pot from above: a square body with the brass adjust screw in
 * the middle, three pins in a row along the edge nearest the channel. The
 * wiper is always the middle pin, so W is printed on the board beside it. */
function potentiometer(comp) {
  const b = comp.body;
  const info = b.value_info || {};
  const pins = comp.pins.slice().sort((p, q) => (p.number || 0) - (q.number || 0));
  const cols = pins.map((p) => p.hole.col);
  const cx = (x(Math.min(...cols)) + x(Math.max(...cols))) / 2;
  const up = b.half === "top"; // body sits away from the channel
  const py = y(pins[0].hole.row);
  /* Wider than it is deep: the placer keeps the two rows behind the pins
   * clear for it, and the body must not spill past them. */
  const side = 2.55 * PITCH;
  const depth = 1.75 * PITCH;
  const near = py + (up ? -9 : 9); // body edge on the pin side
  const top = up ? near - depth : near;
  const sy = top + depth / 2;
  const r = depth * 0.33;

  let legs = "";
  for (const p of pins) {
    const px = x(p.hole.col);
    const nc = spare(p);
    legs += `<path class="leg-wire" d="M ${px} ${py} L ${px} ${near}"/>`;
    legs += nc
      ? `<circle class="lead-dot spare-dot" cx="${px}" cy="${py}" r="5"/>`
      : leadDot(p);
    legs += `<text class="pin-tag${nc ? " spare-tag" : ""}" x="${px}" y="${py + (up ? 15 : -8)}" text-anchor="middle">${esc(
      p.name
    )}</text>`;
  }

  const body = `<rect class="pot-body" x="${cx - side / 2}" y="${top}" width="${side}" height="${depth}" rx="3"/>
    <circle class="pot-screw" cx="${cx}" cy="${sy}" r="${r}"/>
    <line class="pot-slot" x1="${cx - r * 0.7}" y1="${sy + r * 0.7}" x2="${cx + r * 0.7}" y2="${sy - r * 0.7}"/>
    <text class="pot-code" x="${cx - side / 2 + 4}" y="${top + 10}">${esc(info.code || "")}</text>
    <text class="comp-label on-dark pot-ref" x="${cx + side / 2 - 4}" y="${top + depth - 4}" text-anchor="end">${esc(
      comp.ref
    )}</text>`;

  const short = (p) => String(p.label || p.name).replace(/^pin \d+ — /, "");
  return `<g class="comp pot" data-ref="${esc(comp.ref)}" ${tip({
    title: `${comp.ref} — ${info.pretty || comp.value || ""} potentiometer`,
    subtitle: comp.orientation,
    rows: [
      ...valueRows(comp),
      ...pins.map((p) => [
        `Pin ${p.number} · ${short(p)}`,
        spare(p) ? "not connected" : `${p.net} @ ${p.hole.row}${p.hole.col}`,
      ]),
    ],
    note: noteOf(b),
    pinout: {
      form: "pot",
      pin_count: 3,
      names: Object.fromEntries(pins.map((p) => [p.number, short(p)])),
      used: Object.fromEntries(pins.filter((p) => !spare(p)).map((p) => [p.number, p.net])),
      title: `${comp.ref} — ${info.pretty || comp.value || ""} (${info.code || "pot"})`,
    },
  })}>
    ${legs}${body}
  </g>`;
}

/* --- two-lead parts, each drawn as the real thing looks from above ------- */

/* Real resistors are a fixed size whatever the gap between their holes —
 * the leads stretch, the body doesn't. Bands cluster at one end with the
 * tolerance band apart at the other, which leaves a clear patch for the name. */
const RES_LEN = 3.3 * PITCH;
const DIODE_LEN = 2.6 * PITCH;

function resistorBody(mid, yy, span, info, ref) {
  const bw = Math.min(span, RES_LEN);
  const bh = 15;
  const x0 = mid - bw / 2;
  let s = `<rect class="res-body" x="${x0}" y="${yy - bh / 2}" width="${bw}" height="${bh}" rx="6"/>`;
  const bands = info?.bands?.colors;
  const spots = bw >= 60 ? [8, 15, 22, bw - 12] : [bw * 0.17, bw * 0.31, bw * 0.45, bw * 0.83];
  if (bands) {
    bands.forEach((color, i) => {
      s += `<rect class="res-band" x="${x0 + spots[i] - 2}" y="${yy - bh / 2}" width="4.2" height="${bh}" fill="${esc(
        color
      )}"/>`;
    });
  }
  let labelled = false;
  if (ref && bw >= 66) {
    const from = x0 + spots[2] + 4;
    const to = x0 + spots[3] - 3;
    s += `<text class="comp-label body-label" x="${(from + to) / 2}" y="${yy + 3.6}" text-anchor="middle">${esc(
      ref
    )}</text>`;
    labelled = true;
  }
  return { svg: s, labelled };
}

function capBody(mid, yy, bw, style, info, markedRight) {
  if (style === "electrolytic") {
    /* An electrolytic stands up: from above you see the can's lid, with the
     * manufacturer's stripe running down the negative side. */
    const r = 12;
    const side = markedRight ? 1 : -1;
    return `<circle class="cap-can" cx="${mid}" cy="${yy}" r="${r}"/>
      <circle class="cap-can-lid" cx="${mid}" cy="${yy}" r="${r - 4}"/>
      <path class="cap-stripe" d="M ${mid + side * (r - 1.5)} ${yy - 8} A ${r} ${r} 0 0 ${
        side > 0 ? 1 : 0
      } ${mid + side * (r - 1.5)} ${yy + 8}"/>
      <text class="cap-pol" x="${mid + side * (r + 7)}" y="${yy + 4}" text-anchor="middle">−</text>
      <text class="cap-pol" x="${mid - side * (r + 7)}" y="${yy + 4}" text-anchor="middle">+</text>`;
  }
  if (style === "film") {
    const bh = 20;
    bw = Math.min(bw, 1.9 * PITCH); // a film box is a fixed size; the leads stretch
    return `<rect class="cap-film" x="${mid - bw / 2}" y="${yy - bh / 2}" width="${bw}" height="${bh}" rx="3"/>
      <text class="cap-code" x="${mid}" y="${yy + 4}" text-anchor="middle">${esc(
        info?.pretty || ""
      )}</text>`;
  }
  const r = 12;
  return `<circle class="cap-disc" cx="${mid}" cy="${yy}" r="${r}"/>
    <text class="cap-code" x="${mid}" y="${yy + 4}" text-anchor="middle">${esc(
      info?.code || ""
    )}</text>`;
}

function twoLead(comp) {
  const b = comp.body;
  const info = b.value_info || {};
  const [p1, p2] = comp.pins;
  const x1 = x(p1.hole.col);
  const x2 = x(p2.hole.col);
  const yy = y(p1.hole.row);
  const mid = (x1 + x2) / 2;
  const markedRight = b.marked_end !== "left";

  let legs = `<path class="leg-wire" d="M ${x1} ${yy} L ${x2} ${yy}"/>${leadDot(p1)}${leadDot(p2)}`;

  const bw = Math.max(24, Math.abs(x2 - x1) - 16);
  let body;
  let labelled = false;
  if (comp.kind === "resistor" || comp.kind === "inductor") {
    const r = resistorBody(mid, yy, bw, info, comp.ref);
    body = r.svg;
    labelled = r.labelled;
  } else if (comp.kind === "capacitor" || comp.kind === "polarized_capacitor") {
    body = capBody(mid, yy, bw, info.cap_style || "ceramic", info, markedRight);
  } else if (comp.kind === "led") {
    const r = 11;
    const side = markedRight ? 1 : -1;
    body = `<circle class="led-body" cx="${mid}" cy="${yy}" r="${r}"/>
      <circle class="led-shine" cx="${mid - 3}" cy="${yy - 3}" r="3.4"/>
      <line class="led-flat" x1="${mid + side * r * 0.82}" y1="${yy - r * 0.6}" x2="${
      mid + side * r * 0.82
    }" y2="${yy + r * 0.6}"/>`;
  } else {
    const dw = Math.min(bw, DIODE_LEN);
    const bh = 13;
    const sx = markedRight ? mid + dw / 2 - 7 : mid - dw / 2 + 3;
    const glass = isGlass(comp);
    body = `<rect class="diode-body${glass ? " glass" : ""}" x="${mid - dw / 2}" y="${yy - bh / 2}" width="${dw}" height="${bh}" rx="2.5"/>
      <rect class="diode-band${glass ? " glass" : ""}" x="${sx}" y="${yy - bh / 2}" width="4" height="${bh}"/>`;
    if (dw >= 52) {
      const lx = mid + (markedRight ? -4 : 4);
      body += `<text class="comp-label${glass ? "" : " on-dark"} body-label" x="${lx}" y="${yy + 3.6}" text-anchor="middle">${esc(
        comp.ref
      )}</text>`;
      labelled = true;
    }
  }

  /* The ref goes on the part itself whenever the body is long enough to hold
   * it — which it usually is in the schematic-shaped layouts, where parts
   * stretch between net columns. Short bodies get it just outside, alternating
   * by row so neighbours don't write over each other. */
  const right = Math.max(x1, x2) + (b.polarized ? 20 : 9);
  const caption = labelled
    ? ""
    : b.label_side === "side"
      ? `<text class="comp-label" x="${right}" y="${yy + 4}">${esc(comp.ref)}</text>`
      : `<text class="comp-label" x="${mid}" y="${
          b.label_side === "below" ? yy + 22 : yy - 17
        }" text-anchor="middle">${esc(comp.ref)}</text>`;

  /* Marks sit outboard of the leads, on the same row: "A —[ body ]— K".
   * Above or below the row would land on whatever is in the next row. */
  const outboard = (p, other) => (x(p.hole.col) <= x(other.hole.col) ? -11 : 11);
  const marks = b.polarized
    ? leadMark(p1, x(p1.hole.col) + outboard(p1, p2), yy + 3.5) +
      leadMark(p2, x(p2.hole.col) + outboard(p2, p1), yy + 3.5)
    : "";

  return `<g class="comp passive" data-ref="${esc(comp.ref)}" ${tip({
    title: `${comp.ref} — ${info.pretty || comp.value || b.package_label}`,
    subtitle: comp.orientation,
    rows: [
      ...valueRows(comp),
      ["Package", b.package_label],
      ...comp.pins.map((p) => [p.label || p.name, `${p.net} @ ${p.hole.row}${p.hole.col}`]),
    ],
    note: noteOf(b),
    pinout: portrait(comp),
  })}>
    ${legs}${body}${caption}${marks}
  </g>`;
}

/* The spec for a large labelled drawing of this part, shown on hover. */
function portrait(comp) {
  const b = comp.body || {};
  const info = b.value_info || {};
  const [p1, p2] = comp.pins;
  return {
    form: b.form === "radial" ? "radial" : "axial",
    kind: comp.kind,
    polarized: !!b.polarized,
    bands: info.bands,
    code: info.cap_style === "ceramic" ? info.code : null,
    names: { 1: p1?.label || p1?.name || "1", 2: p2?.label || p2?.name || "2" },
    used: { 1: p1?.net, 2: p2?.net },
    title: `${comp.ref} — ${info.pretty || comp.value || b.package_label || ""}`,
  };
}

/* A rail hole's name in words, for hover cards. */
function holeText(h) {
  if (!h.row.startsWith("RAIL_")) return `${h.row}${h.col}`;
  const side = h.row.startsWith("RAIL_TOP") ? "top" : "bottom";
  const sign = h.row.endsWith("POS") ? "+" : "−";
  return `${side} ${sign} rail, col ${h.col}`;
}

function standingComponent(comp) {
  /* A part standing up and down one column: across the two rails (decoupling
   * caps, bleeders), or from a rail straight into a strip (pull-ups, bias
   * resistors, a diode to ground). Drawn at real size like the flat parts:
   * the leads stretch, the body doesn't. */
  const b = comp.body;
  const info = b.value_info || {};
  const [p1, p2] = comp.pins;
  const cx = x(p1.hole.col);
  const y1 = y(p1.hole.row);
  const y2 = y(p2.hole.row);
  const top = Math.min(y1, y2);
  const mid = (y1 + y2) / 2;
  const span = Math.abs(y2 - y1) - 14;
  const legs = `<path class="leg-wire" d="M ${cx} ${y1} L ${cx} ${y2}"/>${leadDot(p1)}${leadDot(p2)}`;
  const markedTop = b.marked_end === "top";

  let body;
  let labelled = false;
  const rotated = (from, to, cls = "") =>
    `<text class="comp-label body-label${cls}" x="${cx}" y="${(from + to) / 2}" text-anchor="middle" dominant-baseline="central" transform="rotate(-90 ${cx} ${
      (from + to) / 2
    })">${esc(comp.ref)}</text>`;

  if (comp.kind === "resistor" || comp.kind === "inductor") {
    const bh = Math.max(18, Math.min(span, RES_LEN));
    const y0 = mid - bh / 2;
    body = `<rect class="res-body" x="${cx - 7.5}" y="${y0}" width="15" height="${bh}" rx="6"/>`;
    const bands = info.bands?.colors;
    const spots = bh >= 60 ? [8, 15, 22, bh - 12] : [bh * 0.17, bh * 0.31, bh * 0.45, bh * 0.83];
    if (bands) {
      bands.forEach((color, i) => {
        body += `<rect class="res-band" x="${cx - 7.5}" y="${y0 + spots[i] - 2}" width="15" height="4.2" fill="${esc(
          color
        )}"/>`;
      });
    }
    if (bh >= 66) {
      body += rotated(y0 + spots[2] + 4, y0 + spots[3] - 3);
      labelled = true;
    }
  } else if (comp.kind === "diode") {
    const bh = Math.max(18, Math.min(span, DIODE_LEN));
    const y0 = mid - bh / 2;
    const by = markedTop ? y0 + 3 : y0 + bh - 7;
    const glass = isGlass(comp);
    body = `<rect class="diode-body${glass ? " glass" : ""}" x="${cx - 6.5}" y="${y0}" width="13" height="${bh}" rx="2.5"/>
      <rect class="diode-band${glass ? " glass" : ""}" x="${cx - 6.5}" y="${by}" width="13" height="4"/>`;
    if (bh >= 52) {
      body += rotated(markedTop ? y0 + 9 : y0, markedTop ? y0 + bh : y0 + bh - 9, glass ? "" : " on-dark");
      labelled = true;
    }
  } else if (comp.kind === "led") {
    const r = 11;
    const fy = markedTop ? mid - r * 0.82 : mid + r * 0.82;
    body = `<circle class="led-body" cx="${cx}" cy="${mid}" r="${r}"/>
      <circle class="led-shine" cx="${cx - 3}" cy="${mid - 3}" r="3.4"/>
      <line class="led-flat" x1="${cx - r * 0.6}" y1="${fy}" x2="${cx + r * 0.6}" y2="${fy}"/>`;
  } else if (info.cap_style === "electrolytic" || comp.kind === "polarized_capacitor") {
    const r = 11;
    const side = markedTop ? -1 : 1;
    body = `<circle class="cap-can" cx="${cx}" cy="${mid}" r="${r}"/>
      <circle class="cap-can-lid" cx="${cx}" cy="${mid}" r="${r - 4}"/>
      <path class="cap-stripe" d="M ${cx - 8} ${mid + side * (r - 1.5)} A ${r} ${r} 0 0 ${
        side > 0 ? 0 : 1
      } ${cx + 8} ${mid + side * (r - 1.5)}"/>`;
  } else if (info.cap_style === "film") {
    const bh = Math.max(18, Math.min(span, 1.9 * PITCH));
    body = `<rect class="cap-film" x="${cx - 10}" y="${mid - bh / 2}" width="20" height="${bh}" rx="3"/>`;
  } else {
    body = `<circle class="cap-disc" cx="${cx}" cy="${mid}" r="11"/>
      <text class="cap-code" x="${cx}" y="${mid + 4}" text-anchor="middle">${esc(info.code || "")}</text>`;
  }

  const marks = b.polarized
    ? comp.pins
        .map((p) => {
          const mark = LEAD_MARK[String(p.name).toUpperCase()];
          const py = y(p.hole.row) + (y(p.hole.row) === top ? 10 : -4);
          return mark
            ? `<text class="lead-mark ${
                mark === "K" || mark === "−" ? "neg" : "pos"
              }" x="${cx - 14}" y="${py}" text-anchor="middle">${mark}</text>`
            : "";
        })
        .join("")
    : "";

  const railMount = b.half === "railmount";
  const railPin = comp.pins.find((p) => p.hole.row.startsWith("RAIL_"));
  const stripPin = comp.pins.find((p) => !p.hole.row.startsWith("RAIL_"));
  const subtitle = railMount
    ? `Stands between the ${holeText(railPin.hole)} and ${holeText(stripPin.hole)} — that end plugs straight into the rail, no jumper.`
    : "Straight across the two rails — right where the supply enters.";

  return `<g class="comp passive" data-ref="${esc(comp.ref)}" ${tip({
    title: `${comp.ref} — ${info.pretty || comp.value || b.package_label}`,
    subtitle: b.polarized ? `${subtitle} ${comp.orientation}` : subtitle,
    rows: [
      ...valueRows(comp),
      ...comp.pins.map((p) => [p.label || p.name, `${p.net} @ ${holeText(p.hole)}`]),
    ],
    note: noteOf(b),
    pinout: portrait(comp),
  })}>
    ${legs}${body}${marks}
    ${labelled ? "" : `<text class="comp-label" x="${cx + 15}" y="${mid + 4}">${esc(comp.ref)}</text>`}
  </g>`;
}

function component(comp) {
  const form = comp.body?.form;
  if (form === "dip") return dip(comp);
  if (form === "to92" || form === "to220") return threeLead(comp);
  if (form === "pot") return potentiometer(comp);
  if (comp.body?.half === "rail" || comp.body?.half === "railmount") return standingComponent(comp);
  return twoLead(comp);
}

// ---------------------------------------------------------------------------
// Wires
// ---------------------------------------------------------------------------

/* A jumper that can't lie flat — it has to go corner to corner — is drawn
 * the way a flexible jumper wire looks when you push it in: arched up off
 * the board, with its shadow underneath, so it reads as a wire hopping over
 * whatever is between its ends rather than a line drawn through them. */
function archOf(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len;
  let ny = dx / len;
  // Bow upward for a mostly-flat wire, rightward for a mostly-upright one,
  // so every arched jumper on the board leans the same way.
  if (Math.abs(dx) >= Math.abs(dy) ? ny > 0 : nx < 0) {
    nx = -nx;
    ny = -ny;
  }
  const h = Math.max(10, Math.min(46, len * 0.22)); // height of the arch
  const cx = (x1 + x2) / 2 + nx * 2 * h; // a quadratic peaks halfway to its control point
  const cy = (y1 + y2) / 2 + ny * 2 * h;
  return { d: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`, h };
}

function wire(w, i) {
  /* Jumpers are drawn the way a cut-to-length wire lies on a real board:
   * straight, flat along one row or straight down one column, with the holes
   * underneath kept clear so a straight line never hides anything. The odd
   * one that has to go corner to corner is drawn arched (see archOf). */
  const x1 = x(w.from_hole.col);
  const y1 = y(w.from_hole.row);
  const x2 = x(w.to_hole.col);
  const y2 = y(w.to_hole.row);
  const len = Math.hypot(x2 - x1, y2 - y1);
  const flat = w.from_hole.row === w.to_hole.row;
  const upright = w.from_hole.col === w.to_hole.col;
  const arched = !flat && !upright;
  const shape = flat
    ? "flat along the row"
    : upright
      ? "straight down the column"
      : "arched — a flexible jumper, corner to corner";
  const path = arched ? archOf(x1, y1, x2, y2).d : `M ${x1} ${y1} L ${x2} ${y2}`;
  const shadow = arched
    ? `<path class="wire-shadow" d="${path}" transform="translate(2.5 3.5)"/>`
    : "";
  return `<g class="wire${arched ? " arched" : ""}" data-net="${esc(w.net)}" data-wire="${i}" ${tip({
    title: `Jumper — net ${w.net}`,
    subtitle: `${holeText(w.from_hole)} → ${holeText(w.to_hole)}`,
    rows: [
      ["Length", `${Math.max(1, Math.round(len / PITCH))} holes`],
      ["Lies", shape],
      ["Kind", w.kind.replace("_", " ")],
    ],
  })}>
    ${shadow}<path class="wire-path" d="${path}" stroke="${esc(w.color)}"/>
    <circle class="wire-end" cx="${x1}" cy="${y1}" r="4.5" fill="${esc(w.color)}"/>
    <circle class="wire-end" cx="${x2}" cy="${y2}" r="4.5" fill="${esc(w.color)}"/>
  </g>`;
}

const wireHoles = (w) => [
  { hole: w.from_hole },
  { hole: w.to_hole },
];

// ---------------------------------------------------------------------------
// Instrument leads: the bench supply and the wave generator
// ---------------------------------------------------------------------------

/* Room kept above and below the board for the instruments' tags. Each lead
 * is drawn the way it arrives at the bench: a cable from off the board,
 * ending in a clip on a short wire pushed into the hole. */
const LEAD_BAND = 36;
const BOARD_TOP = MARGIN_Y - 18;
const boardBottom = () => y("RAIL_BOT_POS") + 18;

const leadSide = (hole) =>
  hole.row.startsWith("RAIL_TOP") || TOP_ROWS.includes(hole.row) ? "top" : "bottom";

const TERMINAL_TEXT = {
  "+": "+ lead (red)",
  "−": "− lead",
  COM: "COM lead (black)",
  signal: "signal clip",
  ground: "ground clip",
};

/* Tag centres along one edge: as close above/below their holes as they can
 * get without overlapping each other. */
function placeTags(items, left, right) {
  items.sort((a, b) => a.hx - b.hx || a.order - b.order);
  let edge = left;
  for (const it of items) {
    it.tx = Math.max(it.hx, edge + it.w / 2);
    edge = it.tx + it.w / 2 + 6;
  }
  let limit = right;
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    it.tx = Math.min(it.tx, limit - it.w / 2);
    limit = it.tx - it.w / 2 - 6;
  }
}

function leadGraphics(layout, stateOf) {
  const leads = layout.leads || [];
  const cols = layout.columns;
  const left = x(1) - 30;
  const right = x(cols) + 30;
  const items = leads.map((lead, i) => ({
    lead,
    i,
    order: i,
    side: leadSide(lead.hole),
    hx: x(lead.hole.col),
    hy: y(lead.hole.row),
    w: Math.max(34, 7 * [...lead.tag].length + 16),
  }));
  for (const side of ["top", "bottom"]) {
    placeTags(
      items.filter((it) => it.side === side),
      left,
      right
    );
  }

  return items
    .map((it) => {
      const cls = stateOf(it.i);
      if (cls === null) return "";
      const { lead, hx, hy, tx, w } = it;
      const up = it.side === "top";
      const dir = up ? -1 : 1; // from the hole towards the tag
      const tagY = up ? BOARD_TOP - LEAD_BAND / 2 - 2 : boardBottom() + LEAD_BAND / 2 + 2;
      const tagEdge = tagY - dir * 9;
      const stubEnd = hy + dir * 7; // the short wire pushed into the hole
      const clipEnd = stubEnd + dir * 12;
      const midY = (clipEnd + tagEdge) / 2;
      const dark = lead.color === "#111827";
      const hot = !dark;
      const halo = cls === " current" ? `<circle class="halo" cx="${hx}" cy="${hy}" r="13"/>` : "";
      return `<g class="lead${cls}" data-net="${esc(lead.net)}" data-lead="${it.i}" ${tip({
        title: `${lead.instrument} — ${TERMINAL_TEXT[lead.terminal] || lead.terminal}`,
        subtitle: `Clip onto a short wire pushed into ${holeText(lead.hole)}.`,
        rows: [
          ["Net", lead.net],
          [lead.instrument === "Wave generator" ? "Set to" : "Voltage", hot ? lead.value : ""],
          ["Source", `${lead.source} on the schematic`],
        ],
        note:
          lead.instrument === "Wave generator"
            ? "The generator's output is an input to the circuit, not a supply: it goes into the strip it drives, never onto a rail."
            : lead.terminal === "COM"
            ? "Every instrument's ground goes to the circuit's ground."
            : "The bench supply powers the circuit through the rails.",
      })}>
        ${halo}
        <path class="lead-cable" d="M ${tx} ${tagEdge} C ${tx} ${midY} ${hx} ${midY} ${hx} ${clipEnd}" stroke="${esc(
          lead.color
        )}"/>
        <line class="lead-stub" x1="${hx}" y1="${hy}" x2="${hx}" y2="${stubEnd}"/>
        <rect class="lead-clip" x="${hx - 4.5}" y="${Math.min(stubEnd, clipEnd)}" width="9" height="12" fill="${esc(
          lead.color
        )}"/>
        <circle class="lead-ring" cx="${hx}" cy="${hy}" r="6.5" stroke="${esc(lead.color)}"/>
        <rect class="lead-tag" x="${tx - w / 2}" y="${tagY - 9}" width="${w}" height="18" fill="${esc(
          lead.color
        )}"/>
        <text class="lead-tag-text" x="${tx}" y="${tagY + 4}" text-anchor="middle">${esc(lead.tag)}</text>
      </g>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------

/* Styles live inside the SVG so the drawing is self-contained: the same
 * markup renders in the app, in a saved .svg file, and in node. */
export const BOARD_CSS = `
  .board { fill: #fdfdfb; stroke: #cfccc4; stroke-width: 1.4; }
  .channel { fill: #f0efea; stroke: #d8d5cc; stroke-width: 1; }
  .hole { fill: #eceae3; stroke: #c3bfb4; stroke-width: 0.8; }
  .rail-line { stroke-width: 2; opacity: 0.85; }
  .rail-line.pos { stroke: #d2444a; }
  .rail-line.neg { stroke: #3a62c0; }
  .rail-sign { font: 600 13px ui-sans-serif, system-ui, sans-serif; }
  .rail-sign.pos { fill: #d2444a; }
  .rail-sign.neg { fill: #3a62c0; }
  .rail-hit { cursor: help; }
  .axis { font: 500 10px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #9a948a; }
  .leg { fill: #b9bec7; stroke: #8f949d; stroke-width: 0.6; }
  .leg-wire { stroke: #9aa0a8; stroke-width: 2.4; fill: none; stroke-linecap: round; }
  .lead-dot { fill: #6f7681; stroke: #ffffff; stroke-width: 1.2; }
  .ic-body { fill: #2c2d33; stroke: #15161a; stroke-width: 1; }
  .ic-notch { fill: #fdfdfb; stroke: #15161a; stroke-width: 1; }
  .ic-dot { fill: #8e9099; }
  .ic-label { font: 600 13px ui-sans-serif, system-ui, sans-serif; fill: #f4f4f5; }
  .ic-sub { font: 500 10px ui-monospace, Menlo, monospace; fill: #a9abb4; }
  .to92-body { fill: #1f2126; stroke: #0e0f12; stroke-width: 1; }
  .to92-flat { stroke: #6b7280; stroke-width: 2.5; stroke-linecap: round; }
  .to220-body { fill: #1f2126; stroke: #0e0f12; stroke-width: 1; }
  .to220-tab { fill: #aeb4bd; stroke: #7e848c; stroke-width: 1; }
  .to220-hole { fill: #fdfdfb; stroke: #7e848c; stroke-width: 1; }
  .res-body { fill: #e3d2a8; stroke: #ab9668; stroke-width: 1; }
  .res-band { stroke: rgba(0,0,0,0.18); stroke-width: 0.4; }
  .diode-body { fill: #30343c; stroke: #16181c; stroke-width: 1; }
  .diode-band { fill: #e6e6e8; }
  .diode-body.glass { fill: #e9a25a; fill-opacity: 0.85; stroke: #a8642a; }
  .diode-band.glass { fill: #1d1d1f; }
  .cap-disc { fill: #d9a441; stroke: #a87a22; stroke-width: 1; }
  .cap-film { fill: #a53333; stroke: #7a2424; stroke-width: 1; }
  .cap-film ~ .cap-code { fill: #ffffff; }
  .cap-code { font: 600 9px ui-monospace, Menlo, monospace; fill: #3a2f17; }
  .cap-can { fill: #23262c; stroke: #0f1115; stroke-width: 1; }
  .cap-can-lid { fill: none; stroke: #4b515b; stroke-width: 1.2; }
  .cap-stripe { fill: none; stroke: #e9eaec; stroke-width: 4; stroke-linecap: butt; }
  .cap-pol { font: 700 11px ui-sans-serif, system-ui, sans-serif; fill: #4b4f57; }
  .led-body { fill: #e04f4f; stroke: #a53333; stroke-width: 1; opacity: 0.93; }
  .led-shine { fill: #ffffff; opacity: 0.45; }
  .led-flat { stroke: #7e2222; stroke-width: 3; stroke-linecap: round; }
  .comp-label { font: 600 11px ui-sans-serif, system-ui, sans-serif; fill: #3b3a36; }
  .comp-label.on-dark { fill: #f3f4f6; }
  .body-label { font-size: 10px; }
  .pin-tag { font: 600 9px ui-monospace, Menlo, monospace; fill: #4b4f57; }
  .wire-path { fill: none; stroke-width: 3.4; stroke-linecap: round; opacity: 0.92; }
  .wire-end { stroke: #ffffff; stroke-width: 1.1; }
  .wire-shadow { fill: none; stroke: #1f2126; stroke-width: 4; stroke-linecap: round; opacity: 0.13; }
  .wire.arched .wire-path { stroke-width: 3.6; opacity: 0.96; }
  .comp, .wire { cursor: help; }
  .dimmed { opacity: 0.22; }
  .future { opacity: 0.09; }
  .lit .wire-path { stroke-width: 4.6; }
  .halo { fill: none; stroke: #b4552d; stroke-width: 2.6; opacity: 0.85; }
  .lead-mark { font: 700 10px ui-sans-serif, system-ui, sans-serif; }
  .lead-mark.pos { fill: #b4552d; }
  .lead-mark.neg { fill: #1f2937; }
  .pot-body { fill: #2f5fa8; stroke: #1d3c6e; stroke-width: 1; }
  .pot-screw { fill: #d9bd63; stroke: #8a6d1d; stroke-width: 1.2; }
  .pot-slot { stroke: #6b5313; stroke-width: 2.6; stroke-linecap: round; }
  .pot-code { font: 600 9px ui-monospace, Menlo, monospace; fill: #dbe6f7; }
  .pot-ref { font-size: 10px; }
  .spare-dot { fill: #ffffff; stroke: #9aa0a8; stroke-width: 1.4; }
  .pin-tag.spare-tag { fill: #9aa0a8; }
  .lead { cursor: help; }
  .lead-cable { fill: none; stroke-width: 3; stroke-linecap: round; opacity: 0.9; }
  .lead-stub { stroke: #9aa0a8; stroke-width: 2.4; stroke-linecap: round; }
  .lead-clip { stroke: #1f2126; stroke-width: 0.8; }
  .lead-ring { fill: none; stroke-width: 2.2; }
  .lead-tag { stroke: #1f2126; stroke-width: 0.6; }
  .lead-tag-text { font: 700 10.5px ui-sans-serif, system-ui, sans-serif; fill: #ffffff; }
  .instrument-band { font: 600 10px ui-sans-serif, system-ui, sans-serif; fill: #8a8375; }
`;

export function renderBoard(layout, opts = {}) {
  const cols = layout.columns;
  const leads = layout.leads || [];
  /* Extra room above or below the board only where an instrument clips on. */
  const topBand = leads.some((l) => leadSide(l.hole) === "top") ? LEAD_BAND : 0;
  const bottomBand = leads.some((l) => leadSide(l.hole) === "bottom") ? LEAD_BAND : 0;
  const width = x(cols) + MARGIN_X + 30;
  const height = y("RAIL_BOT_POS") + MARGIN_Y + 24 + topBand + bottomBand;
  const bx = x(1) - 30;
  const bw = x(cols) + 30 - bx;

  /* Which build step each thing belongs to, so the timeline can reveal them
   * one at a time. With no timeline, everything is simply visible. */
  const stepOfRef = {};
  const stepOfWire = {};
  const stepOfLead = {};
  for (const s of layout.build_order || []) {
    if (s.ref) stepOfRef[s.ref] = s.index;
    if (s.wire !== null && s.wire !== undefined) stepOfWire[s.wire] = s.index;
    for (const i of s.leads || []) stepOfLead[i] = s.index;
  }
  const upTo = opts.upTo === undefined || opts.upTo === null ? Infinity : opts.upTo;
  const current = opts.current;
  /* "ghost" leaves what's coming faintly in place; "hidden" draws only what
   * you have actually plugged in so far. */
  const ghostUpcoming = opts.upcoming !== "hidden";

  const stateClass = (step) => {
    if (step === undefined) return "";
    if (step > upTo) return ghostUpcoming ? " future" : null; // null = don't draw
    return step === current ? " current" : "";
  };

  const isArched = (w) =>
    w.from_hole.row !== w.to_hole.row && w.from_hole.col !== w.to_hole.col;
  const drawWire = (w, i) => {
    const cls = stateClass(stepOfWire[i]);
    if (cls === null) return "";
    const markup = wire(w, i);
    const withHalo =
      cls === " current"
        ? markup.replace(/<path class="wire-path"/, `${halo(wireHoles(w))}<path class="wire-path"`)
        : markup;
    // "wire" -> "wire current" / "wire future", flat or arched alike
    return cls ? withHalo.replace(/^<g class="wire/, `<g class="wire${cls}`) : withHalo;
  };
  /* Flat jumpers lie on the board, under the parts; an arched one hops
   * over everything, so it is drawn last. */
  const wires = (layout.wires || []).map((w, i) => (isArched(w) ? "" : drawWire(w, i))).join("");
  const hops = (layout.wires || []).map((w, i) => (isArched(w) ? drawWire(w, i) : "")).join("");

  const comps = (layout.components || [])
    .map((c) => {
      const cls = stateClass(stepOfRef[c.ref]);
      if (cls === null) return "";
      let markup = component(c);
      if (cls === " current") {
        markup = markup.replace(/^(<g class="comp[^"]*"[^>]*>)/, `$1${halo(c.pins)}`);
      }
      return cls ? markup.replace(/^<g class="comp([^"]*)"/, `<g class="comp$1${cls}"`) : markup;
    })
    .join("");

  const instruments = leadGraphics(layout, (i) => stateClass(stepOfLead[i]));

  const parts = [
    `<style>${BOARD_CSS}</style>`,
    `<g transform="translate(0 ${topBand})">`,
    `<rect class="board" x="${bx}" y="${MARGIN_Y - 18}" width="${bw}" height="${
      y("RAIL_BOT_POS") + 18 - MARGIN_Y + 18
    }"/>`,
    `<rect class="channel" x="${bx}" y="${MARGIN_Y + CHANNEL_Y * PITCH - 13}" width="${bw}" height="26"/>`,
    railGraphics(layout),
    holes(cols),
    labels(cols),
    wires,
    comps,
    hops,
    instruments,
    "</g>",
  ];

  return `<svg class="bb" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">${parts.join(
    ""
  )}</svg>`;
}
