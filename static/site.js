/* Which way the app is being run. The local Python server answers /api/...
 * itself; the GitHub Pages build (tools/build_site.py) overwrites this file
 * with STATIC = true, and the same Python then runs in the browser instead. */
window.AMPIERRE_STATIC = false;
