"""Build the GitHub Pages site: the app as plain files, no server.

    python tools/build_site.py _site

The page, its scripts and styles are copied as they are. The Python that lays
out the board is copied too, and runs in the browser with Pyodide
(static/engine.js) — the site gives the same boards as the local app.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.service import examples_index  # noqa: E402

#: Server-only modules the browser doesn't need (and can't import: FastAPI).
SERVER_ONLY = {"main.py", "cli.py"}


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copytree(ROOT / "static", out / "static")
    for page in ("index.html", "about.html"):
        shutil.move(out / "static" / page, out / page)
    (out / "static" / "site.js").write_text(
        "/* Built for GitHub Pages: no server, the engine runs in the browser. */\n"
        "window.AMPIERRE_STATIC = true;\n",
        encoding="utf-8",
    )

    (out / "app").mkdir()
    files = sorted(p.name for p in (ROOT / "app").glob("*.py") if p.name not in SERVER_ONLY)
    for name in files:
        shutil.copy2(ROOT / "app" / name, out / "app" / name)
    (out / "app" / "files.json").write_text(json.dumps(files), encoding="utf-8")

    (out / "examples").mkdir()
    texts = {}
    for f in sorted((ROOT / "examples").glob("*.json")):
        shutil.copy2(f, out / "examples" / f.name)
        texts[f.stem] = f.read_text(encoding="utf-8")
    (out / "examples" / "index.json").write_text(
        json.dumps(examples_index(texts), ensure_ascii=False), encoding="utf-8"
    )

    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    print(f"built {out} — {len(files)} Python files, {len(texts)} examples")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve())
