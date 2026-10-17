"""Assemble the static replay page (GitHub Pages) from the real UI and a recorded run.

    python -m scripts.build_replay_site --rec replay --out site
The page is the unmodified web/ UI plus web/replay.js, which serves the recording in place of the API.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--rec", default="replay")
ap.add_argument("--out", default="site")
args = ap.parse_args()
rec, out = ROOT / args.rec, ROOT / args.out
if out.exists():
    shutil.rmtree(out)
(out / "static").mkdir(parents=True)
for f in ("app.js", "app.css", "replay.js"):
    shutil.copy(ROOT / "web" / f, out / "static" / f)
html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
html = html.replace('href="/static/', 'href="./static/').replace('src="/static/', 'src="./static/')
tag = '<script src="./static/app.js" type="module"></script>'
assert tag in html, "index.html no longer loads app.js the expected way"
html = html.replace(tag, '<script src="./static/replay.js"></script>\n  ' + tag)
(out / "index.html").write_text(html, encoding="utf-8")
shutil.copytree(rec, out / "replay")
(out / ".nojekyll").write_text("")
size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
print(f"{out}  {size / 1e6:.1f} MB")
