/* The drawing editor: an LTspice-style schematic canvas.
 *
 * Shortcuts follow LTspice where it has one: R, C, L, D, G for parts and
 * ground, W (or F3) for a wire, N (or F4) for a net label, Ctrl+R rotate,
 * Ctrl+E mirror, Delete (or F5) to delete, Esc to stop. The drawing turns
 * into a Netlist (schematic.js) and goes to the same part picker as a
 * screenshot would, with no model in between.
 */
import {
  G, SYMBOLS, PALETTE, pinsOf, bboxOf, transform, connectivity, isConnected,
  distToSegment, onSegmentInterior, toNetlist, toSpice, sampleDoc,
} from "./schematic.js";

const STORE = "ampierre.schematic.v1";
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function emptyDoc() {
  return { title: "My circuit", parts: [], wires: [], nextId: 1 };
}

function loadSaved() {
  try {
    const raw = localStorage.getItem(STORE);
    if (raw) {
      const doc = JSON.parse(raw);
      if (Array.isArray(doc.parts) && Array.isArray(doc.wires)) return doc;
    }
  } catch {}
  return emptyDoc();
}

export function mountEditor(root, { onUse }) {
  let doc = loadSaved();
  const undo = [];
  const redo = [];
  const ui = {
    tool: "select", // select | wire | place | delete
    placing: null, // { type, rot, mirror }
    wireFrom: null, // [x, y] while drawing a wire
    hover: [0, 0],
    sel: null, // { kind: "part" | "wire", id }
    drag: null,
    pan: null,
    view: { x: -2 * G, y: -2 * G, w: 60 * G, h: 32 * G },
  };

  root.innerHTML = `
    <div class="sch-head">
      <input type="text" class="sch-title" id="sch-title" aria-label="Circuit name" />
      <div class="sch-actions">
        <button class="ghost" id="sch-undo" title="Undo (Ctrl+Z)">Undo</button>
        <button class="ghost" id="sch-redo" title="Redo (Ctrl+Y)">Redo</button>
        <button class="ghost" id="sch-sample">Load a sample</button>
        <button class="ghost" id="sch-open">Open file</button>
        <button class="ghost" id="sch-save">Save file</button>
        <button class="ghost" id="sch-spice">Export SPICE</button>
        <button class="ghost" id="sch-clear">Clear</button>
        <input type="file" id="sch-file" accept=".json,application/json" hidden />
      </div>
    </div>
    <div class="sch-body">
      <div class="sch-tools" id="sch-tools" role="toolbar" aria-label="Parts"></div>
      <div class="sch-canvas-wrap">
        <svg class="sch-canvas" id="sch-svg" xmlns="http://www.w3.org/2000/svg" tabindex="0"></svg>
        <div class="sch-status" id="sch-status"></div>
      </div>
      <aside class="sch-props" id="sch-props"></aside>
    </div>
    <div class="sch-foot">
      <ul class="sch-problems" id="sch-problems"></ul>
      <div class="row tight">
        <span class="hint" id="sch-summary"></span>
        <button class="primary" id="sch-use">Use this schematic</button>
      </div>
    </div>`;

  const $ = (id) => root.querySelector(`#${id}`);
  const svg = $("sch-svg");

  // -- toolbar --------------------------------------------------------------

  const tools = $("sch-tools");
  const toolButton = (id, label, keyHint, icon) => {
    const b = document.createElement("button");
    b.className = "sch-tool";
    b.dataset.tool = id;
    b.title = keyHint ? `${label} (${keyHint})` : label;
    b.innerHTML = `${icon}<span>${esc(label)}</span>${keyHint ? `<kbd>${esc(keyHint)}</kbd>` : ""}`;
    tools.append(b);
    return b;
  };
  toolButton("select", "Select / move", "Esc", `<svg viewBox="0 0 16 16"><path d="M3 2l9 6-4 1 2 5-2 1-2-5-3 3z"/></svg>`);
  toolButton("wire", "Wire", "W", `<svg viewBox="0 0 16 16"><path d="M2 13h6V3h6" fill="none"/></svg>`);
  toolButton("delete", "Delete", "F5", `<svg viewBox="0 0 16 16"><path d="M3 3l10 10M13 3L3 13" fill="none"/></svg>`);
  const sep = document.createElement("div");
  sep.className = "sch-sep";
  tools.append(sep);
  for (const type of PALETTE) {
    const s = SYMBOLS[type];
    toolButton(`place:${type}`, s.name, s.key, iconFor(type));
  }
  tools.onclick = (e) => {
    const b = e.target.closest(".sch-tool");
    if (!b) return;
    const t = b.dataset.tool;
    if (t.startsWith("place:")) startPlacing(t.slice(6));
    else setTool(t);
    svg.focus({ preventScroll: true });
  };

  // -- doc changes ----------------------------------------------------------

  function snapshot() {
    undo.push(JSON.stringify(doc));
    if (undo.length > 200) undo.shift();
    redo.length = 0;
  }
  function changed() {
    try {
      localStorage.setItem(STORE, JSON.stringify(doc));
    } catch {}
    render();
  }
  function restore(from, to) {
    if (!from.length) return;
    to.push(JSON.stringify(doc));
    doc = JSON.parse(from.pop());
    ui.sel = null;
    changed();
  }

  const newId = (p) => `${p}${doc.nextId++}`;

  function nextRef(prefix) {
    if (!prefix) return "";
    const taken = new Set(doc.parts.map((p) => p.ref));
    let n = 1;
    while (taken.has(`${prefix}${n}`)) n++;
    return `${prefix}${n}`;
  }

  function setTool(tool) {
    ui.tool = tool;
    ui.placing = null;
    ui.wireFrom = null;
    render();
  }

  function startPlacing(type) {
    const prev = ui.placing;
    ui.tool = "place";
    ui.placing = { type, rot: prev?.type === type ? prev.rot : 0, mirror: false };
    ui.wireFrom = null;
    render();
  }

  // -- coordinates ----------------------------------------------------------

  function world(e) {
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [p.x / G, p.y / G];
  }
  const snap = ([x, y]) => [Math.round(x), Math.round(y)];

  function partAt(x, y) {
    for (let i = doc.parts.length - 1; i >= 0; i--) {
      const [x0, y0, x1, y1] = bboxOf(doc.parts[i]);
      if (x >= x0 && x <= x1 && y >= y0 && y <= y1) return doc.parts[i];
    }
    return null;
  }
  function wireAt(x, y) {
    let best = null;
    let bestD = 0.45;
    for (const w of doc.wires) {
      const d = distToSegment(w, x, y);
      if (d < bestD) [best, bestD] = [w, d];
    }
    return best;
  }

  /** Is there already something to connect to at this grid point? */
  function connectsAt(x, y) {
    for (const p of doc.parts) for (const pin of pinsOf(p)) if (pin.x === x && pin.y === y) return true;
    for (const w of doc.wires) {
      if ((w.x1 === x && w.y1 === y) || (w.x2 === x && w.y2 === y)) return true;
      if (onSegmentInterior(w, x, y)) return true;
    }
    return false;
  }

  /** The L a wire takes from a to b: along first, then down. */
  function corner(a, b) {
    return [b[0], a[1]];
  }

  function addWire(a, b) {
    if (a[0] === b[0] && a[1] === b[1]) return;
    doc.wires.push({ id: newId("w"), x1: a[0], y1: a[1], x2: b[0], y2: b[1] });
  }

  // -- mouse ----------------------------------------------------------------

  svg.addEventListener("contextmenu", (e) => e.preventDefault());

  svg.addEventListener("mousedown", (e) => {
    svg.focus({ preventScroll: true });
    const w = world(e);
    const g = snap(w);
    if (e.button === 1 || (e.button === 0 && e.shiftKey && ui.tool === "select")) {
      ui.pan = { sx: e.clientX, sy: e.clientY, view: { ...ui.view } };
      return;
    }
    if (e.button === 2) {
      // Right click ends a wire or puts the tool down, like LTspice.
      if (ui.tool === "wire" && ui.wireFrom) ui.wireFrom = null;
      else setTool("select");
      render();
      return;
    }
    if (e.button !== 0) return;

    if (ui.tool === "place") {
      snapshot();
      const { type, rot, mirror } = ui.placing;
      const sym = SYMBOLS[type];
      const part = {
        id: newId("p"), type, x: g[0], y: g[1], rot, mirror,
        ref: nextRef(sym.prefix), value: sym.value,
      };
      if (type === "dc_source") part.power = true;
      doc.parts.push(part);
      ui.sel = { kind: "part", id: part.id };
      if (type === "label") {
        // A label is nothing without its name: ask for it straight away.
        ui.tool = "select";
        ui.placing = null;
        changed();
        const input = root.querySelector("#sch-p-value");
        input?.focus();
        input?.select();
        return;
      }
      changed();
      return;
    }

    if (ui.tool === "wire") {
      if (!ui.wireFrom) {
        ui.wireFrom = g;
      } else if (g[0] === ui.wireFrom[0] && g[1] === ui.wireFrom[1]) {
        ui.wireFrom = null; // clicking the same point twice ends the wire
      } else {
        // Landing on a pin or another wire finishes it; open space carries on.
        const lands = connectsAt(g[0], g[1]);
        snapshot();
        const c = corner(ui.wireFrom, g);
        addWire(ui.wireFrom, c);
        addWire(c, g);
        ui.wireFrom = lands ? null : g;
        changed();
      }
      render();
      return;
    }

    if (ui.tool === "delete") {
      const p = partAt(...w);
      const wr = p ? null : wireAt(...w);
      if (p || wr) {
        snapshot();
        if (p) doc.parts = doc.parts.filter((x) => x !== p);
        else doc.wires = doc.wires.filter((x) => x !== wr);
        ui.sel = null;
        changed();
      }
      return;
    }

    // select
    const p = partAt(...w);
    if (p) {
      ui.sel = { kind: "part", id: p.id };
      // Wires ending on this part's pins stretch with it, as LTspice's drag does.
      const ends = [];
      for (const pin of pinsOf(p)) {
        for (const wr of doc.wires) {
          if (wr.x1 === pin.x && wr.y1 === pin.y) ends.push([wr, 1]);
          if (wr.x2 === pin.x && wr.y2 === pin.y) ends.push([wr, 2]);
        }
      }
      ui.drag = { part: p, start: g, origin: [p.x, p.y], ends, before: JSON.stringify(doc), moved: false };
      render();
      return;
    }
    const wr = wireAt(...w);
    if (wr) {
      ui.sel = { kind: "wire", id: wr.id };
      ui.drag = { wire: wr, start: g, origin: [wr.x1, wr.y1, wr.x2, wr.y2], before: JSON.stringify(doc), moved: false };
      render();
      return;
    }
    ui.sel = null;
    ui.pan = { sx: e.clientX, sy: e.clientY, view: { ...ui.view } };
    render();
  });

  window.addEventListener("mousemove", (e) => {
    if (ui.pan) {
      const r = svg.getBoundingClientRect();
      const k = ui.view.w / r.width;
      ui.view.x = ui.pan.view.x - (e.clientX - ui.pan.sx) * k;
      ui.view.y = ui.pan.view.y - (e.clientY - ui.pan.sy) * k;
      applyView();
      return;
    }
    if (!root.isConnected || root.closest("[hidden]")) return;
    const g = snap(world(e));
    if (ui.drag) {
      const dx = g[0] - ui.drag.start[0];
      const dy = g[1] - ui.drag.start[1];
      if (dx || dy) ui.drag.moved = true;
      if (ui.drag.part) {
        const p = ui.drag.part;
        const [ox, oy] = ui.drag.origin;
        const mx = ox + dx - p.x;
        const my = oy + dy - p.y;
        p.x += mx;
        p.y += my;
        for (const [wr, end] of ui.drag.ends) {
          wr[`x${end}`] += mx;
          wr[`y${end}`] += my;
        }
      } else {
        const [x1, y1, x2, y2] = ui.drag.origin;
        Object.assign(ui.drag.wire, { x1: x1 + dx, y1: y1 + dy, x2: x2 + dx, y2: y2 + dy });
      }
      render();
      return;
    }
    if (g[0] !== ui.hover[0] || g[1] !== ui.hover[1]) {
      ui.hover = g;
      if (ui.tool === "place" || ui.tool === "wire") render();
    }
  });

  window.addEventListener("mouseup", () => {
    if (ui.drag) {
      if (ui.drag.moved) {
        undo.push(ui.drag.before);
        redo.length = 0;
        // A wire dragged to nothing is just gone.
        doc.wires = doc.wires.filter((w) => w.x1 !== w.x2 || w.y1 !== w.y2);
        changed();
      }
      ui.drag = null;
    }
    ui.pan = null;
  });

  svg.addEventListener("dblclick", () => {
    const input = root.querySelector("#sch-p-value");
    if (input) {
      input.focus();
      input.select();
    }
  });

  svg.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const [wx, wy] = world(e).map((v) => v * G);
      const k = Math.exp(Math.sign(e.deltaY) * 0.12);
      const w = Math.max(16 * G, Math.min(240 * G, ui.view.w * k));
      const f = w / ui.view.w;
      ui.view = {
        x: wx - (wx - ui.view.x) * f,
        y: wy - (wy - ui.view.y) * f,
        w,
        h: ui.view.h * f,
      };
      applyView();
    },
    { passive: false }
  );

  // -- keyboard -------------------------------------------------------------

  root.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") {
      if (e.key === "Escape" || e.key === "Enter") svg.focus({ preventScroll: true });
      return;
    }
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    let handled = true;
    if (ctrl && k === "z") restore(undo, redo);
    else if (ctrl && (k === "y" || (e.shiftKey && k === "z"))) restore(redo, undo);
    else if (ctrl && k === "r") rotate();
    else if (ctrl && k === "e") mirror();
    else if (ctrl) handled = false;
    else if (k === "escape") setTool("select");
    else if (k === "delete" || k === "backspace") deleteSelected();
    else if (k === "f5") setTool("delete");
    else if (k === "w" || k === "f3") setTool("wire");
    else if (k === "n" || k === "f4") startPlacing("label");
    else {
      const type = PALETTE.find((p) => SYMBOLS[p].key && SYMBOLS[p].key.toLowerCase() === k);
      if (type) startPlacing(type);
      else handled = false;
    }
    if (handled) e.preventDefault();
  });

  function selectedPart() {
    return ui.sel?.kind === "part" ? doc.parts.find((p) => p.id === ui.sel.id) : null;
  }

  function rotate() {
    if (ui.tool === "place") {
      ui.placing.rot = (ui.placing.rot + 1) & 3;
      render();
      return;
    }
    const p = selectedPart();
    if (!p) return;
    snapshot();
    p.rot = ((p.rot || 0) + 1) & 3;
    changed();
  }

  function mirror() {
    if (ui.tool === "place") {
      ui.placing.mirror = !ui.placing.mirror;
      render();
      return;
    }
    const p = selectedPart();
    if (!p) return;
    snapshot();
    p.mirror = !p.mirror;
    changed();
  }

  function deleteSelected() {
    if (!ui.sel) return;
    snapshot();
    if (ui.sel.kind === "part") doc.parts = doc.parts.filter((p) => p.id !== ui.sel.id);
    else doc.wires = doc.wires.filter((w) => w.id !== ui.sel.id);
    ui.sel = null;
    changed();
  }

  // -- header buttons -------------------------------------------------------

  $("sch-title").value = doc.title || "";
  $("sch-title").oninput = (e) => {
    doc.title = e.target.value;
    changed();
  };
  $("sch-undo").onclick = () => restore(undo, redo);
  $("sch-redo").onclick = () => restore(redo, undo);
  $("sch-clear").onclick = () => {
    if (!doc.parts.length && !doc.wires.length) return;
    if (!confirm("Clear the whole drawing? You can undo this.")) return;
    snapshot();
    const title = doc.title;
    doc = emptyDoc();
    doc.title = title;
    ui.sel = null;
    changed();
  };
  $("sch-sample").onclick = () => {
    if ((doc.parts.length || doc.wires.length) && !confirm("Replace your drawing with the sample? You can undo this.")) return;
    snapshot();
    doc = sampleDoc();
    $("sch-title").value = doc.title;
    ui.sel = null;
    fitView();
    changed();
  };
  $("sch-save").onclick = () =>
    download(`${slug(doc.title)}.schematic.json`, JSON.stringify(doc, null, 2), "application/json");
  $("sch-spice").onclick = () => download(`${slug(doc.title)}.cir`, toSpice(doc), "text/plain");
  $("sch-open").onclick = () => $("sch-file").click();
  $("sch-file").onchange = async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const loaded = JSON.parse(await f.text());
      if (!Array.isArray(loaded.parts) || !Array.isArray(loaded.wires)) throw new Error();
      snapshot();
      doc = { ...emptyDoc(), ...loaded };
      $("sch-title").value = doc.title || "";
      ui.sel = null;
      fitView();
      changed();
    } catch {
      alert("That file isn't a schematic saved from AMPierre.");
    }
  };
  $("sch-use").onclick = () => {
    const { netlist, errors } = toNetlist(doc);
    if (errors.length) {
      render();
      $("sch-problems").querySelector(".bad")?.scrollIntoView({ block: "nearest" });
      return;
    }
    onUse(netlist);
  };

  // -- drawing --------------------------------------------------------------

  function applyView() {
    const v = ui.view;
    svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  }

  function fitView() {
    const boxes = [
      ...doc.parts.map(bboxOf),
      ...doc.wires.map((w) => [Math.min(w.x1, w.x2), Math.min(w.y1, w.y2), Math.max(w.x1, w.x2), Math.max(w.y1, w.y2)]),
    ];
    if (!boxes.length) return;
    const x0 = Math.min(...boxes.map((b) => b[0])) - 3;
    const y0 = Math.min(...boxes.map((b) => b[1])) - 3;
    const x1 = Math.max(...boxes.map((b) => b[2])) + 3;
    const y1 = Math.max(...boxes.map((b) => b[3])) + 3;
    const r = svg.getBoundingClientRect();
    const aspect = r.width && r.height ? r.height / r.width : ui.view.h / ui.view.w;
    let w = Math.max((x1 - x0) * G, 30 * G);
    let h = w * aspect;
    if (h < (y1 - y0) * G) {
      h = (y1 - y0) * G;
      w = h / aspect;
    }
    ui.view = { x: ((x0 + x1) / 2) * G - w / 2, y: ((y0 + y1) / 2) * G - h / 2, w, h };
    applyView();
  }

  function symbolSvg(part, cls = "") {
    const s = SYMBOLS[part.type];
    const tr = `translate(${part.x * G} ${part.y * G}) rotate(${(part.rot || 0) * 90}) scale(${(part.mirror ? -1 : 1) * G} ${G})`;
    let body = s.paths.map((d) => `<path d="${d}"/>`).join("");
    if (s.fills) body += s.fills.map((d) => `<path class="fill" d="${d}"/>`).join("");
    if (s.circle) body += `<circle cx="${s.circle[0]}" cy="${s.circle[1]}" r="${s.circle[2]}"/>`;
    // invisible hit area so the whole symbol is easy to grab
    const [bx0, by0, bx1, by1] = s.box;
    body = `<rect class="hit" x="${bx0}" y="${by0}" width="${bx1 - bx0}" height="${by1 - by0}"/>` + body;
    let text = "";
    if (part.type === "label") {
      const [px, py] = transform(part, 0, 0);
      text = `<text class="sch-net" x="${px * G + 5}" y="${py * G - 5}">${esc(part.value)}</text>`;
    } else if (s.label) {
      const [lx, ly] = transform(part, s.label[0], s.label[1]);
      const [bx0, by0, bx1] = bboxOf(part);
      let tx, ty, anchor = "start";
      if (s.labelFixed) {
        [tx, ty] = [lx * G, ly * G]; // chips: the text sits in a set place
      } else if ((part.rot || 0) % 2) {
        // lying down: name and value above the middle
        [tx, ty, anchor] = [((bx0 + bx1) / 2) * G, by0 * G - 15, "middle"];
      } else {
        // standing up: to the right, clear of the leads
        [tx, ty] = [Math.max(lx, bx1 - 0.1) * G + 2, ly * G];
      }
      text =
        `<text class="sch-ref" text-anchor="${anchor}" x="${tx}" y="${ty}">${esc(part.ref)}</text>` +
        `<text class="sch-val" text-anchor="${anchor}" x="${tx}" y="${ty + 13}">${esc(part.value)}</text>`;
    }
    return `<g class="sch-part ${cls}" data-id="${part.id}"><g transform="${tr}">${body}</g>${text}</g>`;
  }

  function render({ props = true } = {}) {
    applyView();
    const conn = connectivity(doc);
    const selId = ui.sel?.id;
    const parts = doc.parts.map((p) => symbolSvg(p, p.id === selId ? "sel" : "")).join("");
    const wires = doc.wires
      .map(
        (w) =>
          `<line class="sch-wire${w.id === selId ? " sel" : ""}" x1="${w.x1 * G}" y1="${w.y1 * G}" x2="${w.x2 * G}" y2="${w.y2 * G}"/>`
      )
      .join("");
    const dots = conn.junctions
      .map(([x, y]) => `<circle class="sch-dot" cx="${x * G}" cy="${y * G}" r="3.6"/>`)
      .join("");
    // Loose pins get LTspice's little open square, so a gap is obvious.
    let loose = "";
    for (const p of doc.parts) {
      if (p.type === "label" || p.type === "ground") continue;
      for (const pin of pinsOf(p)) {
        if (!isConnected(conn, pin.x, pin.y)) {
          loose += `<rect class="sch-loose" x="${pin.x * G - 3}" y="${pin.y * G - 3}" width="6" height="6"/>`;
        }
      }
    }

    let ghost = "";
    const [hx, hy] = ui.hover;
    if (ui.tool === "place" && ui.placing) {
      ghost = symbolSvg(
        { id: "ghost", type: ui.placing.type, x: hx, y: hy, rot: ui.placing.rot, mirror: ui.placing.mirror,
          ref: "", value: ui.placing.type === "label" ? SYMBOLS.label.value : "" },
        "ghost"
      );
    } else if (ui.tool === "wire") {
      if (ui.wireFrom) {
        const c = corner(ui.wireFrom, ui.hover);
        ghost = `<polyline class="sch-wire ghost" points="${ui.wireFrom[0] * G},${ui.wireFrom[1] * G} ${c[0] * G},${c[1] * G} ${hx * G},${hy * G}"/>`;
      }
      ghost += `<path class="sch-cross" d="M${hx * G - 7} ${hy * G}h14M${hx * G} ${hy * G - 7}v14"/>`;
    }

    svg.innerHTML = `
      <defs><pattern id="sch-grid" width="${G}" height="${G}" patternUnits="userSpaceOnUse">
        <circle cx="0" cy="0" r="0.9" class="sch-griddot"/><circle cx="${G}" cy="0" r="0.9" class="sch-griddot"/>
        <circle cx="0" cy="${G}" r="0.9" class="sch-griddot"/><circle cx="${G}" cy="${G}" r="0.9" class="sch-griddot"/>
      </pattern></defs>
      <rect x="${ui.view.x - 4000}" y="${ui.view.y - 4000}" width="${ui.view.w + 8000}" height="${ui.view.h + 8000}" fill="url(#sch-grid)"/>
      ${wires}${parts}${dots}${loose}${ghost}`;
    svg.dataset.tool = ui.tool;

    for (const b of tools.querySelectorAll(".sch-tool")) {
      const t = b.dataset.tool;
      b.classList.toggle(
        "active",
        t === ui.tool || (ui.tool === "place" && t === `place:${ui.placing?.type}`)
      );
    }
    $("sch-undo").disabled = !undo.length;
    $("sch-redo").disabled = !redo.length;

    $("sch-status").textContent =
      ui.tool === "wire"
        ? ui.wireFrom
          ? "Click to bend or finish the wire. Ending on a pin or wire finishes it; right-click stops."
          : "Click where the wire starts."
        : ui.tool === "place"
          ? `Click to place a ${SYMBOLS[ui.placing.type].name.toLowerCase()}. Ctrl+R rotates, Ctrl+E mirrors, Esc stops.`
          : ui.tool === "delete"
            ? "Click a part or wire to delete it. Esc stops."
            : "Click a part to select it, drag to move it. Drag empty space to pan, scroll to zoom.";

    if (props) renderProps();
    renderProblems();
  }

  function renderProps() {
    const box = $("sch-props");
    const p = selectedPart();
    const w = ui.sel?.kind === "wire" ? doc.wires.find((x) => x.id === ui.sel.id) : null;
    if (!p && !w) {
      box.innerHTML = `<h3>Shortcuts</h3>
        <dl class="sch-keys">
          <dt>R C L D</dt><dd>resistor, capacitor, inductor, diode</dd>
          <dt>G</dt><dd>ground</dd>
          <dt>V</dt><dd>DC supply</dd>
          <dt>W</dt><dd>wire</dd>
          <dt>N</dt><dd>net label</dd>
          <dt>Ctrl+R / E</dt><dd>rotate / mirror</dd>
          <dt>Del</dt><dd>delete selected</dd>
          <dt>Ctrl+Z / Y</dt><dd>undo / redo</dd>
          <dt>Esc</dt><dd>back to select</dd>
        </dl>
        <p class="hint">Labels with the same name are the same net, as in LTspice. Name the supply
        nets V+ and V- (or wire a DC supply to them) so they go on the rails.</p>`;
      return;
    }
    if (w) {
      box.innerHTML = `<h3>Wire</h3><p class="hint">From (${w.x1}, ${w.y1}) to (${w.x2}, ${w.y2}).</p>
        <button class="ghost" id="sch-p-del">Delete wire</button>`;
      box.querySelector("#sch-p-del").onclick = deleteSelected;
      return;
    }
    const s = SYMBOLS[p.type];
    const isMarker = p.type === "label" || p.type === "ground";
    const valueLabel =
      p.type === "label" ? "Net name"
      : p.type === "dc_source" ? "Voltage (V)"
      : p.type === "signal_source" ? "Signal (as in SPICE)"
      : ["opamp", "npn", "pnp", "nmos", "pmos", "regulator", "diode"].includes(p.type) ? "Part number"
      : "Value";
    box.innerHTML = `<h3>${esc(s.name)}</h3>
      ${isMarker ? "" : `<label class="sch-field">Name<input type="text" id="sch-p-ref" value="${esc(p.ref)}"></label>`}
      ${p.type === "ground" ? "" : `<label class="sch-field">${valueLabel}<input type="text" id="sch-p-value" value="${esc(p.value)}"></label>`}
      ${p.type === "dc_source" ? `<label class="sch-check"><input type="checkbox" id="sch-p-power" ${p.power !== false ? "checked" : ""}>
        Powers the circuit (goes on a rail)</label>` : ""}
      ${p.type === "signal_source" ? `<p class="hint">e.g. SINE(0 1 1k) — 1 V peak at 1 kHz.</p>` : ""}
      <div class="sch-pbtns">
        <button class="ghost" id="sch-p-rot" title="Ctrl+R">Rotate</button>
        <button class="ghost" id="sch-p-mir" title="Ctrl+E">Mirror</button>
        <button class="ghost" id="sch-p-del" title="Delete">Delete</button>
      </div>
      ${pinTable(p)}`;
    const ref = box.querySelector("#sch-p-ref");
    const val = box.querySelector("#sch-p-value");
    const pow = box.querySelector("#sch-p-power");
    // Typing edits in place; one undo step per field visit.
    let typed = false;
    const edit = (field) => (e) => {
      if (!typed) {
        snapshot();
        typed = true;
      }
      p[field] = e.target.value;
      try {
        localStorage.setItem(STORE, JSON.stringify(doc));
      } catch {}
      redrawOnly();
    };
    if (ref) {
      ref.oninput = edit("ref");
      ref.onblur = () => (typed = false);
    }
    if (val) {
      val.oninput = edit("value");
      val.onblur = () => (typed = false);
    }
    if (pow) {
      pow.onchange = (e) => {
        snapshot();
        p.power = e.target.checked;
        changed();
      };
    }
    box.querySelector("#sch-p-rot").onclick = rotate;
    box.querySelector("#sch-p-mir").onclick = mirror;
    box.querySelector("#sch-p-del").onclick = deleteSelected;
  }

  function pinTable(p) {
    if (p.type === "label" || p.type === "ground") return "";
    const { netlist } = toNetlist(doc);
    const all = [...netlist.components, ...netlist.sources.map((s) => ({ ref: s.ref, pins: { "+": s.pos, "-": s.neg } }))];
    const c = all.find((x) => x.ref === (p.ref || "").trim());
    if (!c) return "";
    const rows = Object.entries(c.pins)
      .map(([pin, net]) => `<tr><td>${esc(pin)}</td><td>${esc(net)}</td></tr>`)
      .join("");
    return `<h3 class="sch-pins-h">Pins</h3><table class="sch-pins">${rows}</table>`;
  }

  /* Redraw the canvas and problem list but leave the property inputs alone,
   * so typing in them doesn't lose focus. */
  function redrawOnly() {
    render({ props: false });
    const table = $("sch-props").querySelector(".sch-pins");
    const p = selectedPart();
    if (table && p) {
      const fresh = document.createElement("div");
      fresh.innerHTML = pinTable(p);
      const t = fresh.querySelector(".sch-pins");
      if (t) table.replaceWith(t);
    }
  }

  function renderProblems() {
    const { netlist, errors, warnings } = toNetlist(doc);
    const list = $("sch-problems");
    list.innerHTML =
      errors.map((e) => `<li class="bad">${esc(e)}</li>`).join("") +
      warnings.map((w) => `<li>${esc(w)}</li>`).join("");
    const nets = new Set(netlist.components.flatMap((c) => Object.values(c.pins)));
    $("sch-summary").textContent = netlist.components.length
      ? `${netlist.components.length} part${netlist.components.length === 1 ? "" : "s"}, ${nets.size} nets` +
        (netlist.sources.length ? `, ${netlist.sources.length} source${netlist.sources.length === 1 ? "" : "s"}` : "")
      : "";
    $("sch-use").disabled = errors.length > 0;
  }

  // -- go -------------------------------------------------------------------

  render();
  requestAnimationFrame(() => {
    const r = svg.getBoundingClientRect();
    if (r.width) ui.view.h = (ui.view.w * r.height) / r.width;
    if (doc.parts.length) fitView();
    render();
  });

  return {
    /** Call when the editor is shown, so the view matches its real size. */
    shown() {
      const r = svg.getBoundingClientRect();
      if (r.width) ui.view.h = (ui.view.w * r.height) / r.width;
      if (doc.parts.length) fitView();
      render();
      svg.focus({ preventScroll: true });
    },
  };
}

function slug(s) {
  return (s || "circuit").replace(/[^\w]+/g, "_").replace(/^_|_$/g, "").toLowerCase() || "circuit";
}

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** The palette icon: the symbol itself, fitted into a small square. */
function iconFor(type) {
  const s = SYMBOLS[type];
  const [x0, y0, x1, y1] = s.box;
  const pad = 0.4;
  const w = x1 - x0 + 2 * pad;
  const h = y1 - y0 + 2 * pad;
  const size = Math.max(w, h);
  const vx = x0 - pad - (size - w) / 2;
  const vy = y0 - pad - (size - h) / 2;
  let body = s.paths.map((d) => `<path d="${d}"/>`).join("");
  if (s.fills) body += s.fills.map((d) => `<path class="fill" d="${d}"/>`).join("");
  if (s.circle) body += `<circle cx="${s.circle[0]}" cy="${s.circle[1]}" r="${s.circle[2]}"/>`;
  if (type === "label") body += `<text x=".3" y="-.3" font-size="1.1">A</text>`;
  return `<svg class="sym" viewBox="${vx} ${vy} ${size} ${size}">${body}</svg>`;
}
