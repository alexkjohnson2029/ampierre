/* The one way the page talks to the layout engine.
 *
 * Run locally, that's the Python server. On the GitHub Pages site there is no
 * server, so the same Python runs in the browser (engine.js) and answers the
 * same paths with the same JSON. */

export const isStatic = () => !!window.AMPIERRE_STATIC;

export async function api(path, options) {
  if (isStatic()) {
    const { call } = await import("./engine.js");
    return call(path, options);
  }
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}
