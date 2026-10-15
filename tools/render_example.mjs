/* Render a layout JSON to a standalone .svg, without a browser.
 *
 *   python3 -m app.cli examples/three_band_equalizer.json -o /tmp/layout.json
 *   node tools/render_example.mjs /tmp/layout.json board.svg
 *
 * Handy for dropping a board into a lab report, and it is how the renderer
 * gets tested without spinning up a browser.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { renderBoard } from "../static/breadboard.js";

const [, , inPath, outPath = "board.svg"] = process.argv;
if (!inPath) {
  console.error("usage: node tools/render_example.mjs <layout.json> [out.svg]");
  process.exit(1);
}

const layout = JSON.parse(readFileSync(inPath, "utf8"));
const svg = renderBoard(layout);
writeFileSync(outPath, `<?xml version="1.0" encoding="UTF-8"?>\n${svg}\n`);
console.log(`wrote ${outPath} — ${layout.components.length} parts, ${layout.wires.length} jumpers`);
