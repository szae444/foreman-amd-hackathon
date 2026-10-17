"""Click through the built replay page like a visitor and save screenshots (replay_test/)."""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent / "site"
OUT = SITE.parent / "replay_test"
OUT.mkdir(exist_ok=True)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8899), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
errors = []

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1536, "height": 864})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pg.goto("http://127.0.0.1:8899/")
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(OUT / "1_loaded.png"))
    # a wrong click first: should only show the hint
    pg.evaluate("() => [...document.querySelectorAll('#faults button')].find(b => b.textContent.includes('ubric')).click()")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "2_wrong_click.png"))
    pg.click("#btnRun")
    pg.wait_for_timeout(15000)
    pg.screenshot(path=str(OUT / "3_running.png"))
    pg.wait_for_timeout(15000)
    pg.evaluate("() => [...document.querySelectorAll('#faults button')].find(b => b.textContent.includes('ubric')).click()")
    pg.wait_for_timeout(20000)
    pg.screenshot(path=str(OUT / "4_warning.png"))
    pg.wait_for_timeout(15000)
    pg.screenshot(path=str(OUT / "5_fastforward.png"))
    pg.wait_for_selector("#btnApprove", timeout=120000)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=str(OUT / "6_ticket.png"))
    pg.click("#btnApprove")
    pg.wait_for_timeout(2000)
    pg.screenshot(path=str(OUT / "7_approved.png"))
    pg.click("#btnRun")
    pg.wait_for_timeout(30000)
    pg.screenshot(path=str(OUT / "8_recovered.png"))
    b.close()
srv.shutdown()
print("errors:", errors or "none")
sys.exit(1 if errors else 0)
