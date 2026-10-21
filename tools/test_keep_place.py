#!/usr/bin/env python3
"""The teacher keeps their place when a class page reloads (static/keep_place.js).

    python3 tools/test_keep_place.py

WHY THIS FILE EXISTS

Hide, Show, Archive, approving a photo — every button on the class page and
the XP page ends in location.reload(), and the page came back at the top.
The first fix saved and restored window.scrollY. On a laptop the window
never scrolls on these pages (html and body are overflow: hidden; .sheet
scrolls), so it saved 0 every time and the bug stayed exactly as it was,
reported again by the teacher the next day. Nothing had checked it on a
page laid out the way the real one is.

So this runs the real keep_place.js in node, against a page whose .sheet
does the scrolling and whose window stays at 0, and checks that:

  * leaving the page saves where .sheet was;
  * a reload, and Back/Forward, put .sheet back there — and again on load,
    after pictures have pushed the rows down;
  * opening the page anew starts at the top;
  * at phone width, where the window scrolls instead, the window is kept.

And that both reloading pages load it. Needs node.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-64s %s" % ("ok" if condition else "FAIL", label, detail))


HARNESS = r"""
// One page load: a fake window and .sheet, the real keep_place.js, then
// pagehide. `stored` is what sessionStorage held before; `nav` how we came.
const [file, nav, stored, sheetY, winY] = process.argv.slice(2);
const store = stored === "-" ? {} : { k: stored };
const listeners = {};
const sheet = { scrollTop: 0 };
global.window = global;
global.scrollY = 0;
global.scrollTo = (x, y) => { global.scrollY = y; };
global.addEventListener = (name, fn) => { (listeners[name] = listeners[name] || []).push(fn); };
global.history = { scrollRestoration: "auto" };
global.sessionStorage = { getItem: k => (k in store ? store[k] : null),
                          setItem: (k, v) => { store[k] = String(v); } };
global.performance = { getEntriesByType: () => [{ type: nav }] };
global.document = { querySelector: s => (s === ".sheet" ? sheet : null) };
require(file);
window.KeepPlace("k");
const restored = { sheet: sheet.scrollTop, win: global.scrollY };
sheet.scrollTop = 0; global.scrollY = 0;
(listeners.load || []).forEach(f => f());
const onLoad = { sheet: sheet.scrollTop, win: global.scrollY };
// The teacher scrolls, then the page goes.
sheet.scrollTop = Number(sheetY); global.scrollY = Number(winY);
(listeners.pagehide || []).forEach(f => f());
process.stdout.write(JSON.stringify({ restored, onLoad, saved: store.k,
                                      manual: history.scrollRestoration === "manual" }));
"""

node = shutil.which("node")
if not node:
    check("node is available to run keep_place.js", False, "brew install node")
    sys.exit(1)

harness = os.path.join(os.environ.get("TMPDIR", "/tmp"), "keep_place_harness.js")
with open(harness, "w") as f:
    f.write(HARNESS)
js = os.path.join(ROOT, "static", "keep_place.js")


def load(nav, stored="-", sheet_y=0, win_y=0):
    out = subprocess.run([node, harness, js, nav, str(stored), str(sheet_y), str(win_y)],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"error": out.stderr[-300:]}


print("\nA laptop: .sheet scrolls, the window doesn't")
r = load("navigate", sheet_y=1500)
check("leaving the page saves where the list was", r.get("saved") == "1500", r)
check("  and the browser's own restoring is off", r.get("manual"))
r = load("reload", stored=1500)
check("a reload puts the list back", r.get("restored", {}).get("sheet") == 1500, r)
check("  and again once the pictures have loaded", r.get("onLoad", {}).get("sheet") == 1500, r)
r = load("back_forward", stored=1500)
check("Back (from Go live, or an assignment) puts it back too",
      r.get("restored", {}).get("sheet") == 1500, r)
r = load("navigate", stored=1500)
check("opening the page anew starts at the top",
      r.get("restored", {}).get("sheet") == 0 and r.get("onLoad", {}).get("sheet") == 0, r)

print("\nA phone: the window scrolls")
r = load("navigate", win_y=900)
check("leaving saves the window's place", r.get("saved") == "900", r)
r = load("reload", stored=900)
check("a reload puts the window back", r.get("restored", {}).get("win") == 900, r)

print("\nThe pages that reload themselves")
for page in ("class_teacher.html", "class_xp.html"):
    text = open(os.path.join(ROOT, "templates", page)).read()
    check("%s loads keep_place.js and uses it" % page,
          "keep_place.js" in text and "KeepPlace(" in text)

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
