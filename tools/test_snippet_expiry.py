#!/usr/bin/env python3
"""Code the teacher sends goes away by itself after five minutes.

    python3 tools/test_snippet_expiry.py

WHAT IS BEING GUARDED

  The card above a student's editor (Send to students) stayed until each
  student closed it, an hour later still offering a line that no longer
  fit. Now:

    - it goes five minutes after it first appeared on that student's page;
    - a reload does not start the five minutes again (they are remembered,
      by page and snippet), and coming back after them shows nothing;
    - sending again, even the same text, is a new five minutes;
    - the teacher taking it back, or the student closing it, still hides it
      at once, and a timer left over from it changes nothing later;
    - with storage blocked the card still shows, and still goes.

live.js's own snippet code runs in node, with a clock moved by hand.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


if not shutil.which("node"):
    sys.exit("node is needed to run live.js; brew install node")

live_js = open(os.path.join(PYIDE, "static", "live.js")).read()
start = live_js.index("  // ------------------------------------------------ what the teacher sent")
end = live_js.index("  /* At the caret, as its own line(s).", start)
block = live_js[start:end]

HARNESS = r"""
const block = %(block)s;
const MIN = 60 * 1000;
let clock = 1e12, timers = [], store = {}, blocked = false;
Date.now = () => clock;
global.setTimeout = (fn, ms) => { const t = { fn, due: clock + (ms || 0), on: true }; timers.push(t); return t; };
global.clearTimeout = (t) => { if (t) t.on = false; };
function advance(ms) {
  clock += ms;
  timers.filter((t) => t.on && t.due <= clock).forEach((t) => { t.on = false; t.fn(); });
}
global.localStorage = {
  getItem: (k) => { if (blocked) throw new Error("blocked"); return k in store ? store[k] : null; },
  setItem: (k, v) => { if (blocked) throw new Error("blocked"); store[k] = String(v); },
};
global.location = { pathname: "/live/abc" };

// A fresh page: the elements, the editor, and the block as live.js has it.
function page() {
  const els = {};
  const $ = (id) => els[id] || (els[id] = { hidden: true, textContent: "", listeners: {},
    addEventListener(t, f) { this.listeners[t] = f; } });
  els.snippet = $("snippet"); els.snippet.hidden = true;
  const mine = { refresh() {} };
  function insertSnippet() {}
  eval(block);
  return { show: showSnippet, card: els.snippet, close: () => els["snippet-close"].listeners.click() };
}

const out = {};
let p = page();
p.show({ snippet: "x = 1", snippet_seq: 100 });
out.shown = !p.card.hidden;
advance(4 * MIN + 59 * 1000);
out.at459 = !p.card.hidden;
advance(2 * 1000);
out.at501 = !p.card.hidden;

// Sent at a new stamp: a new five minutes, on the same page.
p.show({ snippet: "x = 1", snippet_seq: 200 });
out.again = !p.card.hidden;
advance(2 * MIN);
// Reloaded two minutes in: still there, and gone three minutes later.
p = page();
p.show({ snippet: "x = 1", snippet_seq: 200 });
out.reload2 = !p.card.hidden;
advance(2 * MIN + 59 * 1000);
out.reload459 = !p.card.hidden;
advance(2 * 1000);
out.reload501 = !p.card.hidden;
// Reloaded after the five minutes: nothing.
p = page();
p.show({ snippet: "x = 1", snippet_seq: 200 });
out.reloadAfter = !p.card.hidden;

// Taken back by the teacher: gone at once, and the old timer does nothing.
p = page();
p.show({ snippet: "y = 2", snippet_seq: 300 });
p.show({ snippet: "", snippet_seq: 301 });
out.takenBack = !p.card.hidden;
// Sent, then sent again three minutes later without taking it back: the
// first one's timer must not take the second one down two minutes in.
p = page();
p.show({ snippet: "z = 3", snippet_seq: 302 });
advance(3 * MIN);
p.show({ snippet: "z = 4", snippet_seq: 303 });
advance(3 * MIN);              // past where the first one's timer was due
out.newAfterTakeBack = !p.card.hidden;

// Closed by the student.
p = page();
p.show({ snippet: "w = 4", snippet_seq: 400 });
p.close();
out.closed = !p.card.hidden;

// Storage blocked: shown, and still goes.
blocked = true;
try {
  p = page();
  p.show({ snippet: "v = 5", snippet_seq: 500 });
  out.blockedShown = !p.card.hidden;
  advance(5 * MIN + 1000);
  out.blockedGone = !p.card.hidden;
} catch (e) { out.blockedShown = false; out.blockedGone = true; }
console.log(JSON.stringify(out));
"""
res = subprocess.run(["node", "-e", HARNESS % {"block": json.dumps(block)}],
                     capture_output=True, text=True, timeout=60)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    print(res.stdout[-1000:], res.stderr[-2000:])
    sys.exit(1)

check("a sent snippet shows", o["shown"])
check("  and is still there at 4:59", o["at459"])
check("  and gone at 5:01", not o["at501"])
check("sent again, it is back for a new five minutes", o["again"])
check("a reload two minutes in still shows it", o["reload2"])
check("  for the rest of its five minutes, not five more",
      o["reload459"] and not o["reload501"], (o["reload459"], o["reload501"]))
check("coming back after its five minutes shows nothing", not o["reloadAfter"])
check("the teacher taking it back hides it at once", not o["takenBack"])
check("a second send's five minutes are not cut short by the first's", o["newAfterTakeBack"])
check("the student's Close still hides it", not o["closed"])
check("with storage blocked it still shows", o["blockedShown"])
check("  and still goes", not o["blockedGone"])

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
