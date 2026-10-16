/* The layout engine in the browser, for the GitHub Pages site.
 *
 * Loads Pyodide (Python compiled to WebAssembly), copies the app's own
 * Python files into it, and answers the same /api/... paths the local server
 * does by calling app/service.py. Nothing leaves the browser.
 *
 * The first call downloads Python (a few MB, cached by the browser after
 * that); boot() starts it early so it's usually ready by the time you click.
 */

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

let ready = null;

function say(text) {
  const el = document.getElementById("busy-text");
  if (el) el.textContent = text;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`Couldn't load ${src}`));
    document.head.append(s);
  });
}

/* The site's root, wherever GitHub Pages put it (/ampierre/ for a project page). */
const ROOT = new URL("..", import.meta.url);
const at = (path) => new URL(path, ROOT).href;

async function getText(path) {
  const res = await fetch(at(path));
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.text();
}

export function boot() {
  ready ||= (async () => {
    await loadScript(`${PYODIDE}pyodide.js`);
    const py = await window.loadPyodide({ indexURL: PYODIDE });
    await py.loadPackage("pydantic");
    const files = JSON.parse(await getText("app/files.json"));
    py.FS.mkdirTree("/home/pyodide/app");
    await Promise.all(
      files.map(async (name) => py.FS.writeFile(`/home/pyodide/app/${name}`, await getText(`app/${name}`)))
    );
    py.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
    return py.pyimport("app.service");
  })();
  ready.catch(() => (ready = null)); // let a later click try again
  return ready;
}

async function run(route, body) {
  const warm = ready !== null;
  if (!warm) say("starting the layout engine (first time only)…");
  const service = await boot();
  const out = JSON.parse(service.call(route, body));
  if (out && out.error) throw new Error(out.detail);
  return out;
}

export async function call(path, options = {}) {
  const p = path.replace(/^\//, "");
  if (p === "api/examples") return JSON.parse(await getText("examples/index.json"));
  const ex = p.match(/^api\/examples\/([\w-]+)$/);
  if (ex) return run("netlist", await getText(`examples/${ex[1]}.json`));
  const route = p.match(/^api\/(parse|netlist|place)$/);
  if (route) return run(route[1], options.body || "{}");
  throw new Error(`Not available on the website: ${path}`);
}
