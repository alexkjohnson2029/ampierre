/* Datasheet-style pinout drawings, generated from the package's own pin data.
 *
 * Shown next to each choice in the part picker and inside the hover card, so
 * you can check the pinout against the part in your hand before anything is
 * placed. Pins the circuit actually uses are filled in; spare pins are greyed.
 */

const esc = (s) =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

/* Crude word wrap: SVG text has no line breaking of its own. */
function wrap(text, perLine = 46) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > perLine) {
      lines.push(line.trim());
      line = w;
    } else {
      line += " " + w;
    }
  }
  if (line.trim()) lines.push(line.trim());
  return lines;
}

const CSS = `
  .po-body { fill: #26282e; stroke: #111317; stroke-width: 1.2; }
  .po-notch { fill: #ffffff; stroke: #111317; stroke-width: 1.2; }
  .po-dot { fill: #9aa0a8; }
  .po-pin { fill: #ffffff; stroke: #2b2e34; stroke-width: 1.1; }
  .po-pin.used { fill: #f6e7de; stroke: #b4552d; stroke-width: 1.6; }
  .po-num { font: 600 10px ui-monospace, Menlo, monospace; fill: #2b2e34; }
  .po-name { font: 600 10.5px ui-sans-serif, system-ui, sans-serif; fill: #2b2e34; }
  .po-name.spare { fill: #9b958a; font-weight: 500; }
  .po-net { font: 500 9.5px ui-monospace, Menlo, monospace; fill: #b4552d; }
  .po-title { font: 700 11px ui-sans-serif, system-ui, sans-serif; fill: #2b2e34; }
  .po-cap { font: 500 9.5px ui-sans-serif, system-ui, sans-serif; fill: #6f6a60; }
  .po-lead { stroke: #8f949d; stroke-width: 2.4; stroke-linecap: round; }
  .po-tab { fill: #aeb4bd; stroke: #7e848c; stroke-width: 1; }
  .po-res { fill: #e3d2a8; stroke: #ab9668; stroke-width: 1.2; }
  .po-band { stroke: rgba(0,0,0,0.2); stroke-width: 0.5; }
  .po-diode { fill: #30343c; stroke: #16181c; stroke-width: 1.2; }
  .po-diode-band { fill: #e9eaec; }
  .po-disc { fill: #d9a441; stroke: #a87a22; stroke-width: 1.2; }
  .po-film { fill: #c9504b; stroke: #8f3733; stroke-width: 1.2; }
  .po-code { font: 700 13px ui-monospace, Menlo, monospace; fill: #3a2f17; }
  .po-can { fill: #23262c; stroke: #0f1115; stroke-width: 1.2; }
  .po-stripe { fill: #e9eaec; }
  .po-stripe-mark { font: 700 15px ui-sans-serif, system-ui, sans-serif; fill: #23262c; }
  .po-led { fill: #e04f4f; stroke: #a53333; stroke-width: 1.2; }
  .po-led-rim { fill: #e04f4f; stroke: #a53333; stroke-width: 1.2; }
  .po-flat { stroke: #7e2222; stroke-width: 3.5; stroke-linecap: round; }
  .po-pot { fill: #2f5fa8; stroke: #1d3c6e; stroke-width: 1.2; }
  .po-screw { fill: #d9bd63; stroke: #8a6d1d; stroke-width: 1.4; }
  .po-slot { stroke: #6b5313; stroke-width: 4; stroke-linecap: round; }
  .po-cw { fill: none; stroke: #6f6a60; stroke-width: 1.4; }
`;

function dipDiagram({ pin_count, names = {}, used = {}, title }) {
  const n = Math.max(4, pin_count || Object.keys(names).length || 8);
  const perSide = Math.floor(n / 2);
  const rowH = 24;
  const boxW = 96;
  const boxX = 112;
  const top = 36;
  const boxH = perSide * rowH + 14;
  const width = 320;
  const height = top + boxH + 26;

  let s = "";
  s += `<text class="po-title" x="${width / 2}" y="16" text-anchor="middle">${esc(title || "")}</text>`;
  s += `<text class="po-cap" x="${width / 2}" y="29" text-anchor="middle">top view · notch up · pin 1 at top left</text>`;
  s += `<rect class="po-body" x="${boxX}" y="${top}" width="${boxW}" height="${boxH}" rx="4"/>`;
  s += `<path class="po-notch" d="M ${boxX + boxW / 2 - 10} ${top} a 10 10 0 0 0 20 0 z"/>`;
  s += `<circle class="po-dot" cx="${boxX + 13}" cy="${top + 15}" r="3"/>`;

  for (let i = 0; i < perSide; i++) {
    const yy = top + 14 + i * rowH;
    const leftPin = i + 1;
    const rightPin = n - i;
    for (const [pin, side] of [
      [leftPin, "left"],
      [rightPin, "right"],
    ]) {
      const isLeft = side === "left";
      const px = isLeft ? boxX - 20 : boxX + boxW;
      const isUsed = used[pin] !== undefined;
      s += `<rect class="po-pin${isUsed ? " used" : ""}" x="${px}" y="${yy - 8}" width="20" height="16" rx="2"/>`;
      s += `<text class="po-num" x="${px + 10}" y="${yy + 4}" text-anchor="middle">${pin}</text>`;
      const label = names[pin] || `Pin ${pin}`;
      const tx = isLeft ? px - 7 : px + 27;
      s += `<text class="po-name${isUsed ? "" : " spare"}" x="${tx}" y="${
        isUsed ? yy + 1 : yy + 4
      }" text-anchor="${isLeft ? "end" : "start"}">${esc(label)}</text>`;
      if (isUsed) {
        s += `<text class="po-net" x="${tx}" y="${yy + 11}" text-anchor="${
          isLeft ? "end" : "start"
        }">${esc(used[pin])}</text>`;
      }
    }
  }
  return { svg: s, width, height };
}

function threeLeadDiagram({ form, names = {}, used = {}, title }) {
  const width = 320;
  const height = 168; // room for the lead-name legend under the pins
  const cx = width / 2;
  const isTab = form === "to220";
  const isPot = form === "pot";
  let s = `<text class="po-title" x="${cx}" y="16" text-anchor="middle">${esc(title || "")}</text>`;
  s += `<text class="po-cap" x="${cx}" y="29" text-anchor="middle">${
    isPot
      ? "top view · adjust screw up · pins toward you"
      : isTab
        ? "metal tab away from you · leads down"
        : "flat face toward you · leads down"
  }</text>`;

  if (isPot) {
    /* square body, brass screw, and which way is clockwise */
    s += `<rect class="po-pot" x="${cx - 34}" y="36" width="68" height="48" rx="3"/>`;
    s += `<circle class="po-screw" cx="${cx}" cy="60" r="15"/>`;
    s += `<line class="po-slot" x1="${cx - 10}" y1="70" x2="${cx + 10}" y2="50"/>`;
    s += `<path class="po-cw" d="M ${cx + 22} 44 A 24 24 0 0 1 ${cx + 22} 76"/>`;
    s += `<path d="M ${cx + 18} 73 L ${cx + 22} 78 L ${cx + 26} 72" class="po-cw"/>`;
    s += `<text class="po-cap" x="${cx + 52}" y="64" text-anchor="middle">CW → pin 3</text>`;
  } else if (isTab) {
    s += `<rect class="po-tab" x="${cx - 34}" y="38" width="68" height="12" rx="2"/>`;
    s += `<circle class="po-notch" cx="${cx}" cy="44" r="3.4"/>`;
    s += `<rect class="po-body" x="${cx - 34}" y="50" width="68" height="34" rx="3"/>`;
  } else {
    s += `<path class="po-body" d="M ${cx - 34} 78 A 34 34 0 0 1 ${cx + 34} 78 Z"/>`;
    s += `<line x1="${cx - 34}" y1="78" x2="${cx + 34}" y2="78" stroke="#6b7280" stroke-width="2.5"/>`;
  }

  const baseY = isTab || isPot ? 84 : 78;
  for (let i = 0; i < 3; i++) {
    const px = cx - 24 + i * 24;
    const pin = i + 1;
    const isUsed = used[pin] !== undefined;
    s += `<line class="po-lead" x1="${px}" y1="${baseY}" x2="${px}" y2="${baseY + 22}"/>`;
    s += `<rect class="po-pin${isUsed ? " used" : ""}" x="${px - 9}" y="${baseY + 22}" width="18" height="15" rx="2"/>`;
    s += `<text class="po-num" x="${px}" y="${baseY + 33}" text-anchor="middle">${pin}</text>`;
    if (isUsed) {
      s += `<text class="po-net" x="${px}" y="${baseY + 49}" text-anchor="middle">${esc(used[pin])}</text>`;
    }
  }
  /* Full lead names go in one line underneath — side by side they collide. */
  const legend = [1, 2, 3]
    .map((p) => `${p} ${names[p] || "?"}`)
    .join("   ·   ");
  s += `<text class="po-name" x="${cx}" y="${baseY + 66}" text-anchor="middle">${esc(legend)}</text>`;
  return { svg: s, width, height };
}

function twoLeadDiagram(spec) {
  /* A portrait of the actual part, drawn large and labelled, in place of a
   * photo: body style by kind, colour bands worked out from the value, and
   * the marked end called out by name. */
  const { names = {}, used = {}, title, polarized, kind, bands, code } = spec;
  const width = 320;
  const height = polarized ? 182 : 150;
  const cx = width / 2;
  const yy = 86;
  const leadX = 118;

  let s = `<text class="po-title" x="${cx}" y="16" text-anchor="middle">${esc(title || "")}</text>`;
  s += `<text class="po-cap" x="${cx}" y="30" text-anchor="middle">${
    polarized ? "polarised — this way round only" : "not polarised — either way round"
  }</text>`;
  s += `<line class="po-lead" x1="${cx - leadX}" y1="${yy}" x2="${cx + leadX}" y2="${yy}"/>`;

  /* Which end carries the mark. names keys are 1 and 2, left to right. */
  const leftName = names[1] || "1";
  const rightName = names[2] || "2";

  if (kind === "resistor" || kind === "inductor") {
    const bw = 130;
    const bh = 38;
    s += `<rect class="po-res" x="${cx - bw / 2}" y="${yy - bh / 2}" width="${bw}" height="${bh}" rx="15"/>`;
    (bands?.colors || []).forEach((color, i) => {
      const spots = [0.17, 0.31, 0.45, 0.83];
      s += `<rect class="po-band" x="${cx - bw / 2 + bw * spots[i] - 4}" y="${yy - bh / 2}" width="9" height="${bh}" fill="${esc(color)}"/>`;
    });
    if (bands?.text) {
      s += `<text class="po-cap" x="${cx}" y="${yy + 40}" text-anchor="middle">${esc(bands.text)}</text>`;
    }
  } else if (kind === "led") {
    const r = 30;
    s += `<path class="po-led" d="M ${cx - r} ${yy + 14} L ${cx - r} ${yy - 4} A ${r} ${r} 0 0 1 ${cx + r} ${yy - 4} L ${cx + r} ${yy + 14} Z"/>`;
    s += `<rect class="po-led-rim" x="${cx - r - 4}" y="${yy + 10}" width="${r * 2 + 8}" height="7" rx="2"/>`;
    s += `<line class="po-flat" x1="${cx + r}" y1="${yy + 2}" x2="${cx + r}" y2="${yy + 14}"/>`;
    s += `<text class="po-cap" x="${cx + r + 22}" y="${yy + 34}" text-anchor="middle">flat side</text>`;
  } else if (kind === "polarized_capacitor") {
    const bw = 58;
    const bh = 64;
    s += `<rect class="po-can" x="${cx - bw / 2}" y="${yy - bh / 2}" width="${bw}" height="${bh}" rx="7"/>`;
    s += `<rect class="po-stripe" x="${cx + bw / 2 - 15}" y="${yy - bh / 2}" width="13" height="${bh}"/>`;
    s += `<text class="po-stripe-mark" x="${cx + bw / 2 - 8}" y="${yy + 5}" text-anchor="middle">−</text>`;
  } else if (kind === "capacitor") {
    if (code) {
      s += `<circle class="po-disc" cx="${cx}" cy="${yy - 6}" r="34"/>`;
      s += `<text class="po-code" x="${cx}" y="${yy - 1}" text-anchor="middle">${esc(code)}</text>`;
    } else {
      s += `<rect class="po-film" x="${cx - 44}" y="${yy - 24}" width="88" height="44" rx="5"/>`;
    }
  } else {
    /* diode: glass/plastic cylinder with the cathode band */
    const bw = 110;
    const bh = 34;
    s += `<rect class="po-diode" x="${cx - bw / 2}" y="${yy - bh / 2}" width="${bw}" height="${bh}" rx="4"/>`;
    s += `<rect class="po-diode-band" x="${cx + bw / 2 - 20}" y="${yy - bh / 2}" width="11" height="${bh}"/>`;
    s += `<text class="po-cap" x="${cx + bw / 2 - 14}" y="${yy + 38}" text-anchor="middle">band</text>`;
  }

  /* End labels, with the net each lead goes to. */
  for (const [side, name, pin] of [
    [-1, leftName, 1],
    [1, rightName, 2],
  ]) {
    const tx = cx + side * (leadX - 4);
    s += `<text class="po-name" x="${tx}" y="${yy - 26}" text-anchor="middle">${esc(name)}</text>`;
    if (used[pin]) {
      s += `<text class="po-net" x="${tx}" y="${yy - 14}" text-anchor="middle">${esc(used[pin])}</text>`;
    }
  }

  if (polarized) {
    const which =
      kind === "polarized_capacitor"
        ? "Striped side is the negative lead, and the shorter one."
        : kind === "led"
          ? "The flat edge and the shorter lead are both the cathode (K)."
          : "The banded end is the cathode (K). Current flows A → K.";
    const lines = wrap(which);
    lines.forEach((line, i) => {
      s += `<text class="po-cap" x="${cx}" y="${height - 10 - (lines.length - 1 - i) * 13}" text-anchor="middle">${esc(
        line
      )}</text>`;
    });
  }
  return { svg: s, width, height: height + (polarized ? 8 : 0) };
}

/* spec: {form, pin_count, names: {pinNumber: name}, used: {pinNumber: net}, title,
 *        plus kind / bands / code / polarized for two-lead part portraits} */
export function pinoutDiagram(spec) {
  if (!spec) return "";
  const form = spec.form || "dip";
  const { svg, width, height } =
    form === "dip"
      ? dipDiagram(spec)
      : form === "to92" || form === "to220" || form === "pot"
        ? threeLeadDiagram(spec)
        : twoLeadDiagram(spec);
  return `<svg class="pinout" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg"><style>${CSS}</style>${svg}</svg>`;
}
