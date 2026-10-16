/* App wiring: draw or paste -> pick packages -> place -> render -> step through. */
import { renderBoard } from "./breadboard.js";
import { pinoutDiagram } from "./pinout.js";
import { mountEditor } from "./editor.js";
import { api, isStatic } from "./api.js";

const $ = (id) => document.getElementById(id);
const state = {
  netlist: null,
  questions: [],
  picks: {}, // ref -> package id, or "__custom__"
  custom: {}, // ref -> {name, form, pin_count, pin_map}
  filters: {}, // ref -> search text
  layout: null,
  step: null, // null = whole board
  upcoming: "hidden", // or "ghost" — what to do with parts not placed yet
  style: "flow", // or "flow-compact"
  playing: null,
};

const CUSTOM = "__custom__";

/* Smooth scrolling only for people who haven't asked their OS for less motion. */
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const scrollBehavior = () => (reduceMotion.matches ? "auto" : "smooth");

/* Show a message in one of the page's inline error slots (role="alert"). */
function showError(id, message) {
  const el = $(id);
  el.textContent = message;
  el.hidden = !message;
}

const escapeHtml = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* On the GitHub Pages site the layout engine runs in the browser; start it
 * loading now so it's ready by the time anyone clicks. */
if (isStatic()) import("./engine.js").then((e) => e.boot()).catch(() => {});

/* The little spinner bottom-right: it is only ever on while the server is
 * actually doing something, and it says which something. */
function busy(on, label) {
  if (label) $("busy-text").textContent = label;
  $("busy").hidden = !on;
}

// ---------------------------------------------------------------------------
// Tabs — input and board are two panes, switched from the bar at the bottom
// ---------------------------------------------------------------------------

function showPane(name) {
  for (const pane of ["input", "board"]) {
    $(`pane-${pane}`).hidden = pane !== name;
    $(`tab-${pane}`).classList.toggle("active", pane === name);
    if (pane === name) $(`tab-${pane}`).setAttribute("aria-current", "true");
    else $(`tab-${pane}`).removeAttribute("aria-current");
  }
  window.scrollTo({ top: 0, behavior: scrollBehavior() });
}

for (const name of ["input", "board"]) {
  $(`tab-${name}`).onclick = () => showPane(name);
}

// ---------------------------------------------------------------------------
// Step 1 — paste a netlist
// ---------------------------------------------------------------------------

/* What's in the box survives a reload, like the drawing does. */
try {
  $("spice").value = localStorage.getItem("ampierre.pasted") || "";
} catch {}
$("spice").oninput = () => {
  try {
    localStorage.setItem("ampierre.pasted", $("spice").value);
  } catch {}
};

$("spice-file-btn").onclick = () => $("spice-file").click();
$("spice-file").onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  $("spice").value = await f.text();
  $("spice").oninput();
};

$("parse").onclick = async () => {
  const err = $("parse-error");
  err.hidden = true;
  const text = $("spice").value.trim();
  if (!text) {
    err.textContent = "Paste a netlist first, or open an example.";
    err.hidden = false;
    return;
  }
  busy(true, "reading the netlist…");
  try {
    showParse(
      await api("/api/parse", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      })
    );
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    busy(false);
  }
};

async function loadExamples() {
  try {
    const list = await api("/api/examples");
    $("examples").innerHTML = "";
    for (const ex of list) {
      const b = document.createElement("button");
      b.className = ex.about ? "chip featured" : "chip";
      b.dataset.example = ex.id;
      b.textContent = ex.title.split("(")[0].replace(/,.*$/, "").trim();
      if (ex.about?.badge) {
        const badge = document.createElement("span");
        badge.className = "ex-badge";
        badge.textContent = ex.about.badge;
        b.prepend(badge);
      }
      b.title = ex.title;
      b.onclick = async () => {
        showError("input-error", "");
        busy(true, "loading the example…");
        try {
          showParse(await api(`/api/examples/${ex.id}`), ex.about || null);
        } catch (e) {
          showError("input-error", `Couldn't load that example: ${e.message}`);
        } finally {
          busy(false);
        }
      };
      $("examples").append(b);
    }
    return list;
  } catch {
    $("examples-label").hidden = true;
    return [];
  }
}

/* /?example=three_band_equalizer opens that example straight on the board —
 * the About page links to the featured build this way. */
loadExamples().then(async (list) => {
  const want = new URLSearchParams(location.search).get("example");
  const ex = want && list.find((e) => e.id === want);
  if (!ex) return;
  busy(true, "loading the example…");
  try {
    showParse(await api(`/api/examples/${ex.id}`), ex.about || null);
  } catch (e) {
    showError("input-error", `Couldn't load that example: ${e.message}`);
    return;
  } finally {
    busy(false);
  }
  $("build").click();
});

// ---------------------------------------------------------------------------
// Step 1, the other way — draw the schematic
// ---------------------------------------------------------------------------

const editor = mountEditor($("editor"), {
  onUse: async (netlist) => {
    showError("input-error", "");
    busy(true, "reading the drawing…");
    try {
      showParse(
        await api("/api/netlist", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(netlist),
        })
      );
    } catch (e) {
      showError("input-error", `Couldn't read the drawing: ${e.message}`);
    } finally {
      busy(false);
    }
  },
});

function setInputMode(mode) {
  $("step-draw").hidden = mode !== "draw";
  $("step-input").hidden = mode !== "paste";
  for (const id of ["mode-draw", "mode-paste"]) {
    $(id).classList.toggle("active", $(id).dataset.mode === mode);
    $(id).setAttribute("aria-pressed", String($(id).dataset.mode === mode));
  }
  try {
    localStorage.setItem("ampierre.inputMode", mode);
  } catch {}
  if (mode === "draw") editor.shown();
}
for (const id of ["mode-draw", "mode-paste"]) {
  $(id).onclick = () => setInputMode($(id).dataset.mode);
}
try {
  if (localStorage.getItem("ampierre.inputMode") === "paste") setInputMode("paste");
} catch {}

// ---------------------------------------------------------------------------
// Step 2 — part picker
// ---------------------------------------------------------------------------

function showParse(data, about = null) {
  state.netlist = data.netlist;
  state.about = about; // a featured build's story, shown over its board
  state.questions = data.questions;
  state.picks = Object.fromEntries(data.questions.map((q) => [q.id, q.suggested]));
  state.custom = {};
  state.filters = {};

  const nets = new Set();
  for (const c of data.netlist.components) for (const n of Object.values(c.pins)) nets.add(n);
  const nComp = data.netlist.components.length;
  const nWarn = data.netlist.warnings?.length || 0;
  $("netsummary").textContent =
    `${nComp} ${nComp === 1 ? "component" : "components"}, ${nets.size} ${nets.size === 1 ? "net" : "nets"}` +
    (nWarn ? `. ${nWarn} ${nWarn === 1 ? "thing" : "things"} to check on the board.` : "");

  renderQuestions();
  $("step-parts").hidden = false;
  showPane("input");
  $("step-parts").scrollIntoView({ behavior: scrollBehavior(), block: "start" });
}

function optionUsedMap(q, opt) {
  /* Which physical pin each schematic pin lands on, for the diagram. */
  const used = {};
  for (const logical of q.pins) {
    const n = opt.pin_map?.[logical];
    if (n) used[n] = logical;
  }
  return used;
}

function renderQuestions() {
  const box = $("questions");
  box.innerHTML = "";
  if (!state.questions.length) {
    box.innerHTML =
      '<p class="hint">Nothing ambiguous here — every part in this circuit has only one sensible footprint.</p>';
    return;
  }

  for (const q of state.questions) {
    const el = document.createElement("div");
    el.className = "question";
    el.innerHTML = `<header><span class="ref">${escapeHtml(q.refs.join(", "))}</span>
      <span class="kind">${escapeHtml(q.kind)}${q.value ? ` · ${escapeHtml(q.value)}` : ""} · pins used: ${q.pins
      .map(escapeHtml)
      .join(", ")}${q.refs.length > 1 ? " · same part, asked once" : ""}</span></header>`;

    if (q.options.length > 5) {
      const search = document.createElement("input");
      search.type = "text";
      search.className = "filter";
      search.placeholder = "Search, e.g. OP484, 555, Schottky";
      search.setAttribute("aria-label", `Search parts for ${q.refs.join(", ")}`);
      search.value = state.filters[q.id] || "";
      search.oninput = () => {
        state.filters[q.id] = search.value;
        renderQuestions();
        const again = document.querySelector(`[data-filter-for="${CSS.escape(q.id)}"]`);
        if (again) {
          again.focus();
          again.setSelectionRange(again.value.length, again.value.length);
        }
      };
      search.setAttribute("data-filter-for", q.id);
      q._filterEl = search;
    }

    const needle = (state.filters[q.id] || "").toLowerCase().trim();
    const shown = q.options.filter((o) => !needle || o.label.toLowerCase().includes(needle));

    /* Choices on the left, the pinout of whatever is selected on the right,
     * so you can compare the two without scrolling. */
    const body = document.createElement("div");
    body.className = "q-body";
    const left = document.createElement("div");
    if (q._filterEl) left.append(q._filterEl);

    const opts = document.createElement("div");
    opts.className = "options";
    for (const o of shown) {
      opts.append(optionCard(q, o));
    }
    opts.append(customCard(q));
    left.append(opts);
    body.append(left);

    if (needle && !shown.length) {
      const none = document.createElement("p");
      none.className = "hint";
      none.textContent = "No part in the library matches. Choose My own part below and enter its pinout.";
      left.prepend(none);
    }

    /* The pinout of whatever is currently selected, full size. */
    const sel = state.picks[q.id];
    const chosen = q.options.find((o) => o.id === sel);
    const preview = document.createElement("div");
    preview.className = "pinout-col";
    if (sel === CUSTOM) {
      const spec = state.custom[q.id] || {};
      preview.innerHTML = pinoutDiagram({
        form: spec.form || "dip",
        pin_count: Number(spec.pin_count) || 8,
        names: Object.fromEntries(
          Object.entries(spec.pin_map || {}).map(([logical, n]) => [n, logical])
        ),
        used: Object.fromEntries(
          Object.entries(spec.pin_map || {}).map(([logical, n]) => [n, logical])
        ),
        title: spec.name || "Your part",
      });
    } else if (chosen) {
      const twoLead = chosen.form === "axial" || chosen.form === "radial";
      preview.innerHTML = pinoutDiagram({
        form: chosen.form,
        kind: q.kind,
        pin_count: chosen.pin_count,
        /* A two-lead package has no numbered pins, so label the ends with the
         * schematic's own names (A / K, + / −). */
        names: twoLead ? { 1: q.pins[0] || "1", 2: q.pins[1] || "2" } : chosen.pin_names,
        used: twoLead ? {} : optionUsedMap(q, chosen),
        polarized:
          chosen.marker?.includes("band") ||
          chosen.marker?.includes("stripe") ||
          chosen.marker?.includes("cathode"),
        title: chosen.label,
      });
      // Two-lead parts go in by their ends (A/K, +/−), never by pin name.
      const unmapped = twoLead
        ? []
        : q.pins.filter((pin) => !chosen.pin_map?.[pin] && !/^\d+$/.test(pin));
      if (unmapped.length) {
        const warn = document.createElement("p");
        warn.className = "pin-warn";
        warn.textContent =
          unmapped.length === 1
            ? `${unmapped[0]} isn't a pin name on this package, so AMPierre will match it loosely or skip it. If that's wrong, choose My own part.`
            : `${unmapped.join(", ")} aren't pin names on this package, so AMPierre will match them loosely or skip them. If that's wrong, choose My own part.`;
        preview.append(warn);
      }
    }
    body.append(preview);
    el.append(body);
    box.append(el);
  }
}

function optionCard(q, o) {
  const lab = document.createElement("label");
  lab.className = "option" + (state.picks[q.id] === o.id ? " sel" : "");
  lab.innerHTML = `<input type="radio" name="pkg-${escapeHtml(q.id)}" value="${escapeHtml(o.id)}" ${
    state.picks[q.id] === o.id ? "checked" : ""
  }>
    <span><span class="label">${escapeHtml(o.label)}</span>
    <span class="meta">${escapeHtml(o.marker || "")}</span></span>`;
  lab.querySelector("input").onchange = () => {
    state.picks[q.id] = o.id;
    renderQuestions();
  };
  return lab;
}

function customCard(q) {
  const wrap = document.createElement("div");
  wrap.className = "option custom" + (state.picks[q.id] === CUSTOM ? " sel" : "");
  const defaultForm =
    { npn: "to92", pnp: "to92", nmos: "to92", pmos: "to92", regulator: "to220", diode: "axial" }[
      q.kind
    ] || "dip";
  const spec = (state.custom[q.id] ||= {
    name: q.value || "",
    form: defaultForm,
    pin_count: defaultForm === "dip" ? 8 : defaultForm === "axial" ? 2 : 3,
    pin_map: {},
  });

  const head = document.createElement("label");
  head.innerHTML = `<input type="radio" name="pkg-${escapeHtml(q.id)}" value="${CUSTOM}" ${
    state.picks[q.id] === CUSTOM ? "checked" : ""
  }>
    <span><span class="label">My own part</span>
    <span class="meta">For anything not in the list. You enter the pinout.</span></span>`;
  head.querySelector("input").onchange = () => {
    state.picks[q.id] = CUSTOM;
    renderQuestions();
  };
  wrap.append(head);

  if (state.picks[q.id] !== CUSTOM) return wrap;

  const form = document.createElement("div");
  form.className = "custom-form";
  form.innerHTML = `
    <div class="cf-row">
      <label>Part name<input type="text" id="cf-name-${escapeHtml(q.id)}" value="${escapeHtml(
        spec.name || ""
      )}" placeholder="OP484"></label>
      <label>Package<select id="cf-form-${escapeHtml(q.id)}">
        <option value="dip">DIP — straddles the channel</option>
        <option value="to92">TO-92 — 3 leads, flat face to you</option>
        <option value="to220">TO-220 — 3 leads, tab away</option>
        <option value="axial">Axial — 2 leads</option>
        <option value="radial">Radial — 2 leads</option>
      </select></label>
      <label class="narrow">Pins<input type="number" id="cf-count-${escapeHtml(q.id)}" min="2" max="40" step="1" value="${
        spec.pin_count || 8
      }"></label>
    </div>
    <p class="hint">Which physical pin number does each schematic pin go to? Count from the notch, pin 1 first, anticlockwise — exactly as the datasheet draws it.</p>
    <div class="cf-pins"></div>`;

  const pins = form.querySelector(".cf-pins");
  for (const logical of q.pins) {
    const row = document.createElement("label");
    row.className = "cf-pin";
    row.innerHTML = `<span>${escapeHtml(logical)}</span>
      <input type="number" min="1" max="40" step="1" value="${spec.pin_map?.[logical] ?? ""}" placeholder="pin #">`;
    row.querySelector("input").onchange = (e) => {
      const v = parseInt(e.target.value, 10);
      if (Number.isFinite(v)) spec.pin_map[logical] = v;
      else delete spec.pin_map[logical];
      renderQuestions();
    };
    pins.append(row);
  }

  wrap.append(form);
  form.querySelector(`#cf-form-${CSS.escape(q.id)}`).value = spec.form || "dip";
  form.querySelector(`#cf-name-${CSS.escape(q.id)}`).oninput = (e) => (spec.name = e.target.value);
  form.querySelector(`#cf-form-${CSS.escape(q.id)}`).onchange = (e) => {
    spec.form = e.target.value;
    renderQuestions();
  };
  form.querySelector(`#cf-count-${CSS.escape(q.id)}`).onchange = (e) => {
    spec.pin_count = parseInt(e.target.value, 10) || 8;
    renderQuestions();
  };
  return wrap;
}

// ---------------------------------------------------------------------------
// Step 3 — place and draw
// ---------------------------------------------------------------------------

$("build").onclick = async () => {
  showError("build-error", "");
  busy(true, "placing parts and routing jumpers…");
  try {
    const packages = {};
    const custom_packages = {};
    for (const q of state.questions) {
      const pick = state.picks[q.id];
      for (const ref of q.refs) {
        if (pick === CUSTOM) custom_packages[ref] = state.custom[q.id];
        else packages[ref] = pick;
      }
    }
    const layout = await api("/api/place", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        netlist: state.netlist,
        packages,
        custom_packages,
        style: state.style,
      }),
    });
    showLayout(layout);
  } catch (e) {
    showError("build-error", `Couldn't build the board: ${e.message}`);
  } finally {
    busy(false);
  }
};

function showLayout(layout) {
  state.layout = layout;
  state.step = null;
  $("board-title").textContent = layout.title;
  showProjectCard(state.about);
  drawBoard();

  const bom = $("bom");
  bom.innerHTML = "";
  for (const c of layout.components) {
    const info = c.body?.value_info || {};
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="ref">${escapeHtml(c.ref)}</td>
      <td>${escapeHtml(info.pretty || c.value || "")}
        <div class="hint">${escapeHtml(info.bands ? info.bands.text : c.orientation)}</div></td>
      <td class="holes">${c.pins.map((p) => `${p.hole.row}${p.hole.col}`).join(" ")}</td>`;
    tr.tabIndex = 0;
    tr.onmouseenter = tr.onfocus = () => highlight(c.pins.map((p) => p.net));
    tr.onmouseleave = tr.onblur = () => highlight(null);
    bom.append(tr);
  }

  /* The timeline shows one step at a time; this is the whole list, for
   * printing or ticking off at the bench. */
  const steps = $("steps");
  steps.innerHTML = "";
  for (const step of layout.build_order) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.className = "step-btn";
    btn.textContent = step.text;
    if (step.detail) {
      const small = document.createElement("span");
      small.className = "hint";
      small.textContent = step.detail;
      btn.append(small);
    }
    li.append(btn);
    btn.onmouseenter = btn.onfocus = () => {
      if (step.ref) {
        const c = layout.components.find((x) => x.ref === step.ref);
        if (c) highlight(c.pins.map((p) => p.net));
      } else if (step.wire !== null && step.wire !== undefined) {
        highlight([layout.wires[step.wire].net]);
      } else if (step.leads?.length) {
        highlight(step.leads.map((i) => layout.leads[i].net));
      }
    };
    btn.onmouseleave = btn.onblur = () => highlight(null);
    btn.onclick = () => gotoStep(step.index);
    steps.append(li);
  }

  buildTimeline();

  const warnings = layout.warnings || [];
  const notes = layout.notes || [];
  $("warnbox").hidden = warnings.length === 0 && notes.length === 0;
  $("warnings").innerHTML =
    warnings.map((w) => `<li class="bad">${escapeHtml(w)}</li>`).join("") +
    notes.map((n) => `<li class="note">${escapeHtml(n)}</li>`).join("");

  $("step-board").hidden = false;
  $("board-empty").hidden = true;
  $("tab-board").disabled = false;
  const nParts = layout.components.length;
  const nWires = layout.wires.length;
  $("tab-board-sub").textContent =
    `${nParts} ${nParts === 1 ? "part" : "parts"} · ${nWires} ${nWires === 1 ? "jumper" : "jumpers"}`;
  showPane("board");
}

/* The story behind a featured build: whose project it was, and what it does. */
function showProjectCard(about) {
  const card = $("project-card");
  card.hidden = !about;
  if (!about) return;
  const facts = (about.facts || []).map((f) => `<li>${escapeHtml(f)}</li>`).join("");
  const link = about.link
    ? `<a class="primary-link" href="${escapeHtml(about.link.href)}" target="_blank" rel="noopener">${escapeHtml(
        about.link.text
      )}</a>`
    : "";
  card.innerHTML = `<div class="credit-mark" aria-hidden="true">AJ</div>
    <div class="project-body">
      <h3>${escapeHtml(about.headline || "")}</h3>
      <p>${escapeHtml(about.blurb || "")}</p>
      ${facts ? `<ul class="project-facts">${facts}</ul>` : ""}
      ${link}
    </div>`;
}

/* Which board element has keyboard focus, as something that survives a redraw. */
function boardKey(el) {
  if (!el?.matches?.("#board [data-tip]")) return null;
  if (el.dataset.ref) return `[data-ref="${CSS.escape(el.dataset.ref)}"]`;
  if (el.dataset.wire) return `[data-wire="${el.dataset.wire}"]`;
  if (el.dataset.lead) return `[data-lead="${el.dataset.lead}"]`;
  const all = [...$("board").querySelectorAll("[data-tip]")];
  return all.indexOf(el);
}

/* Everything with a tooltip is reachable with Tab, and a screen reader hears
 * the same summary the tooltip shows. */
function tipLabel(d) {
  const rows = (d.rows || []).filter((r) => r && r[1]).map((r) => `${r[0]}: ${r[1]}`);
  return [d.title, d.subtitle, ...rows, d.note, d.warn].filter(Boolean).join(". ");
}

function drawBoard() {
  const opts =
    state.step === null
      ? {}
      : { upTo: state.step, current: state.step, upcoming: state.upcoming };
  const key = boardKey(document.activeElement);
  $("board").innerHTML = renderBoard(state.layout, opts);
  const hosts = [...$("board").querySelectorAll("[data-tip]")];
  for (const el of hosts) {
    if (el.closest(".future")) continue; // not on the board yet
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "img");
    try {
      el.setAttribute("aria-label", tipLabel(JSON.parse(el.getAttribute("data-tip"))));
    } catch {}
  }
  const again = typeof key === "number" ? hosts[key] : key && $("board").querySelector(key);
  again?.focus({ preventScroll: true });
}

$("tl-ghost").onchange = (e) => {
  state.upcoming = e.target.checked ? "ghost" : "hidden";
  drawBoard();
};

// ---------------------------------------------------------------------------
// The build timeline
// ---------------------------------------------------------------------------

/* What a timeline chip calls an instrument hook-up step. */
function leadWord(step) {
  const lead = state.layout?.leads?.[step.leads?.[0]];
  if (!lead) return "hook up";
  if (lead.instrument === "Wave generator") return "wave gen";
  return lead.tag === "IN" ? "input" : "supply";
}

function buildTimeline() {
  const steps = state.layout.build_order || [];
  const strip = $("tl-strip");
  const range = $("tl-range");
  strip.innerHTML = "";
  range.max = String(Math.max(0, steps.length - 1));
  range.value = "0";

  steps.forEach((s) => {
    const chip = document.createElement("button");
    chip.className = `tl-chip ${s.kind}`;
    chip.dataset.step = String(s.index);
    chip.innerHTML = `<span class="n">${s.index}</span><span class="t">${escapeHtml(
      s.ref || (s.kind === "wire" ? "jumper" : s.kind === "lead" ? leadWord(s) : "note")
    )}</span>`;
    chip.title = s.text;
    chip.onclick = () => gotoStep(s.index);
    strip.append(chip);
  });

  gotoStep(null);
}

function gotoStep(i) {
  const steps = state.layout.build_order || [];
  if (i !== null) i = Math.max(0, Math.min(steps.length - 1, i));
  state.step = i;
  drawBoard();

  const showingAll = i === null;
  $("tl-count").textContent = showingAll
    ? `${steps.length} steps`
    : `step ${i + 1} of ${steps.length}`;
  $("tl-text").textContent = showingAll
    ? "Whole board. Drag the slider or press Play to build it one step at a time."
    : steps[i].text;
  $("tl-detail").textContent = showingAll ? "" : steps[i].detail || "";
  $("tl-range").value = String(showingAll ? steps.length - 1 : i);
  $("tl-range").setAttribute(
    "aria-valuetext",
    showingAll ? "Whole board" : `Step ${i + 1} of ${steps.length}: ${steps[i].text}`
  );

  for (const chip of $("tl-strip").children) {
    const n = Number(chip.dataset.step);
    chip.classList.toggle("active", !showingAll && n === i);
    // On the whole board every pad is soldered.
    chip.classList.toggle("done", showingAll || n < i);
  }
  requestAnimationFrame(updateSpan);
  if (!showingAll) {
    const active = $("tl-strip").querySelector(".tl-chip.active");
    active?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest", inline: "center" });
  }
}

/* Like the guide words at the head of a dictionary page: which steps the
 * strip is showing right now, so a long build never loses its place. */
function updateSpan() {
  const strip = $("tl-strip");
  const box = strip.getBoundingClientRect();
  const seen = [...strip.children].filter((c) => {
    const r = c.getBoundingClientRect();
    return r.right > box.left + 4 && r.left < box.right - 4;
  });
  const all = strip.children.length;
  $("tl-span").textContent =
    seen.length && seen.length < all
      ? `showing ${seen[0].dataset.step}–${seen[seen.length - 1].dataset.step} ·`
      : "";
}
$("tl-strip").addEventListener("scroll", updateSpan, { passive: true });
window.addEventListener("resize", updateSpan);

$("tl-range").oninput = (e) => {
  stopPlaying();
  gotoStep(Number(e.target.value));
};
$("tl-prev").onclick = () => {
  stopPlaying();
  gotoStep(state.step === null ? 0 : state.step - 1);
};
$("tl-next").onclick = () => {
  stopPlaying();
  gotoStep(state.step === null ? 0 : state.step + 1);
};
$("tl-all").onclick = () => {
  stopPlaying();
  gotoStep(null);
};
$("tl-play").onclick = () => {
  if (state.playing) return stopPlaying();
  const steps = state.layout?.build_order || [];
  if (!steps.length) return;
  $("tl-play").innerHTML = `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path class="fill" d="M4 3h3v10H4zM9 3h3v10H9z"/></svg> Pause`;
  if (state.step === null) gotoStep(0);
  state.playing = setInterval(() => {
    if (state.step >= steps.length - 1) return stopPlaying();
    gotoStep(state.step + 1);
  }, 1400);
};

function stopPlaying() {
  if (state.playing) clearInterval(state.playing);
  state.playing = null;
  $("tl-play").innerHTML = `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path class="fill" d="M5 3l8 5-8 5z"/></svg> Play`;
}

/* Left/Right step through the build, but only on the Board tab and never
 * while a form control, or a modified key combination, wants the arrows. */
document.addEventListener("keydown", (e) => {
  if ($("pane-board").hidden || $("step-board").hidden) return;
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
  if (e.key === "ArrowRight") $("tl-next").click();
  else if (e.key === "ArrowLeft") $("tl-prev").click();
  else return;
  e.preventDefault();
});

// ---------------------------------------------------------------------------
// Download / restart
// ---------------------------------------------------------------------------

$("download").onclick = () => {
  if (!state.layout) return;
  const blob = new Blob([renderBoard(state.layout)], { type: "image/svg+xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${state.layout.title.replace(/[^\w]+/g, "_").toLowerCase()}.svg`;
  a.click();
  URL.revokeObjectURL(a.href);
};

for (const id of ["style-flow", "style-compact"]) {
  $(id).onclick = async () => {
    const style = $(id).dataset.style;
    if (style === state.style || !state.layout) return;
    state.style = style;
    for (const other of ["style-flow", "style-compact"]) {
      $(other).classList.toggle("active", other === id);
      $(other).setAttribute("aria-pressed", String(other === id));
    }
    $("build").click(); // same parts, same picks, new layout
  };
}

// Drop any ?example=… so a featured build opened from the About page doesn't
// load itself straight back onto the board.
$("restart").onclick = () => location.assign(location.pathname);

showPane("input");

// ---------------------------------------------------------------------------
// Hover: tooltips, pinout cards, net highlighting
// ---------------------------------------------------------------------------

const tooltip = $("tooltip");

function tooltipHtml(d) {
  const rows = (d.rows || [])
    .filter((r) => r && r[1])
    .map((r) => `<tr><td>${escapeHtml(r[0])}</td><td>${escapeHtml(r[1])}</td></tr>`)
    .join("");
  const diagram = d.pinout ? `<div class="t-pinout">${pinoutDiagram(d.pinout)}</div>` : "";
  return `<div class="t-title">${escapeHtml(d.title || "")}</div>
    ${d.subtitle ? `<div class="t-sub">${escapeHtml(d.subtitle)}</div>` : ""}
    ${diagram}
    ${rows ? `<table>${rows}</table>` : ""}
    ${d.note ? `<div class="t-note">${escapeHtml(d.note)}</div>` : ""}
    ${d.warn ? `<div class="t-warn">${escapeHtml(d.warn)}</div>` : ""}`;
}

/* The tooltip follows the mouse, sits under a tapped part on a touch screen,
 * and under the focused part for keyboard users. Esc hides it. */
let tipHost = null;

function showTip(host, x, y) {
  if (host !== tipHost) {
    let data;
    try {
      data = JSON.parse(host.getAttribute("data-tip"));
    } catch {
      return hideTip();
    }
    tipHost = host;
    tooltip.innerHTML = tooltipHtml(data);
    tooltip.hidden = false;
    const nets = new Set();
    if (host.dataset.net) nets.add(host.dataset.net);
    host.querySelectorAll?.("[data-net]").forEach((n) => nets.add(n.dataset.net));
    highlight(nets.size ? [...nets] : null);
  }
  const pad = 16;
  const r = tooltip.getBoundingClientRect();
  tooltip.style.left = `${Math.max(8, Math.min(x + pad, window.innerWidth - r.width - 8))}px`;
  tooltip.style.top = `${Math.max(8, Math.min(y + pad, window.innerHeight - r.height - 8))}px`;
}

function hideTip() {
  if (!tipHost && tooltip.hidden) return;
  tipHost = null;
  tooltip.hidden = true;
  highlight(null);
}

document.addEventListener("pointermove", (e) => {
  if (e.pointerType !== "mouse") return;
  const host = e.target.closest?.("[data-tip]");
  if (host) showTip(host, e.clientX, e.clientY);
  else if (tipHost && tipHost !== document.activeElement) hideTip();
});

document.addEventListener("pointerdown", (e) => {
  if (e.pointerType === "mouse") return;
  const host = e.target.closest?.("[data-tip]");
  if (host) showTip(host, e.clientX, e.clientY);
  else hideTip();
});

document.addEventListener("focusin", (e) => {
  const host = e.target.closest?.("[data-tip]");
  if (!host) return;
  const r = host.getBoundingClientRect();
  showTip(host, r.left, r.bottom - 8);
});
document.addEventListener("focusout", (e) => {
  if (e.target === tipHost) hideTip();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideTip();
});

/* Light up everything on the same net, dim the rest. Seeing one node at a
 * time is the fastest way to check a board against a schematic. */
function highlight(nets) {
  const svg = $("board").querySelector("svg");
  if (!svg) return;
  const groups = svg.querySelectorAll(".comp, .wire, .lead");
  if (!nets) {
    groups.forEach((g) => g.classList.remove("dimmed", "lit"));
    return;
  }
  const set = new Set(nets.filter(Boolean));
  groups.forEach((g) => {
    const touches = [...g.querySelectorAll("[data-net]"), g].some(
      (n) => n.dataset?.net && set.has(n.dataset.net)
    );
    g.classList.toggle("lit", touches);
    g.classList.toggle("dimmed", !touches);
  });
}
