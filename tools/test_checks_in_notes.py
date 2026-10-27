#!/usr/bin/env python3
"""Check my work in the notes, and `locked: yes` — the same file in PyIDE,
WebIDE and FlaskIDE.

    python3 tools/test_checks_in_notes.py

A ```tests block in the notes is a card (checks_in_notes.js): each test a
line, ✓ or ✗ with why once checked, and its own ✔ Check my work where the
page can check code. With `locked: yes` at the top of the notes, a slide
with a card holds the next slide until every check on it passes (notes.js,
slideView) — in the student's own editor only.

node runs the real checks_in_notes.js and notes.js here, on a small fake
DOM: enough elements, classes, attributes, selectors and bubbling events
for the card and the slide viewer, and nothing more. The rest — that each
page registers its runner and loads the file — is read from the pages.
The whole thing was also watched in a browser, in all three editors and on
the live page.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "static")
CHECKS_JS = open(os.path.join(STATIC, "checks_in_notes.js")).read()
NOTES_JS = open(os.path.join(STATIC, "notes.js")).read()
GLOBAL = re.search(r"window\.(\w+) = \(function", NOTES_JS).group(1)

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else "   " + str(detail)[:400]))


if not shutil.which("node"):
    print("  FAIL node is needed: brew install node")
    sys.exit(1)

DOM = r"""
var store = {};
var localStorage = { getItem: function (k) { return k in store ? store[k] : null; },
                     setItem: function (k, v) { store[k] = String(v); } };
function ClassList(el) { this.el = el; }
ClassList.prototype.list = function () { return this.el.className.split(/\s+/).filter(Boolean); };
ClassList.prototype.contains = function (c) { return this.list().indexOf(c) >= 0; };
ClassList.prototype.add = function (c) { if (!this.contains(c)) this.el.className = (this.el.className + " " + c).trim(); };
ClassList.prototype.remove = function (c) { this.el.className = this.list().filter(function (x) { return x !== c; }).join(" "); };
ClassList.prototype.toggle = function (c, on) { if (on === undefined) on = !this.contains(c); if (on) this.add(c); else this.remove(c); return on; };
function El(tag) {
  this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null;
  this.attrs = {}; this.className = ""; this.hidden = false; this.disabled = false; this.title = "";
  this._text = ""; this.handlers = {}; this.scrollTop = 0; this.style = {};
  this.classList = new ClassList(this);
}
Object.defineProperty(El.prototype, "textContent", {
  get: function () { return this._text + this.children.map(function (c) { return c.textContent; }).join(""); },
  set: function (v) { this._text = String(v); this.children = []; } });
Object.defineProperty(El.prototype, "innerHTML", {
  get: function () { return this._text; }, set: function (v) { this._text = String(v); this.children = []; } });
Object.defineProperty(El.prototype, "offsetParent", { get: function () { return this.parentNode ? {} : null; } });
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.insertBefore = function (c) { return this.appendChild(c); };
El.prototype.remove = function () { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.addEventListener = function (ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); };
El.prototype.dispatchEvent = function (e) {
  for (var n = this; n; n = n.parentNode) (n.handlers[e.type] || []).forEach(function (fn) { fn(e); });
  return true;
};
El.prototype.click = function () { this.dispatchEvent({ type: "click" }); };
// Selectors: .class, [attr], :not([attr]), one compound part — all the card and viewer use.
function matches(el, sel) {
  var not = /:not\(\[([\w-]+)\]\)/.exec(sel), base = sel.replace(/:not\(\[[\w-]+\]\)/, "");
  if (not && el.hasAttribute(not[1])) return false;
  var ok = true;
  base.replace(/\.([\w-]+)/g, function (_, c) { if (!el.classList.contains(c)) ok = false; return ""; });
  base.replace(/\[([\w-]+)\]/g, function (_, a) { if (!el.hasAttribute(a)) ok = false; return ""; });
  return ok;
}
El.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (c) { if (matches(c, sel)) out.push(c); walk(c); }); })(this);
  return out;
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
var root = new El("html");
var document = { createElement: function (t) { return new El(t); },
                 querySelectorAll: function (s) { return root.querySelectorAll(s); },
                 createTreeWalker: function () { return { nextNode: function () { return null; } }; } };
function CustomEvent(type) { this.type = type; }
var window = { marked: { parse: function (s) { return s; } },
               DOMPurify: { sanitize: function (s) { return s; } },
               matchMedia: function () { return { matches: false }; } };
"""

harness = DOM + CHECKS_JS + "\nvar C = window.IDENotesChecks;\n" + NOTES_JS + r"""
var N = window.%s;
var out = {};
var tick = function () { return new Promise(function (r) { setTimeout(r, 0); }); };
(async function () {
  // ---------------------------------------------------- the header line
  out.header = ["locked: yes\n# A", "theme: ocean\nanimate: words\nlocked: yes\n# A", "locked: no\n# A",
                "locked: maybe\n# A", "# A\nlocked: yes"].map(function (md) { var h = N.takeHeader(md); return [h.locked, h.body]; });
  out.slides = [N.slides("locked: yes\n# A\n---\n# B").length, N.slides("# A\n---\n# B").length];

  // ---------------------------------------------------- the card
  var tests = [{ label: "Uses a for loop", points: 1 }, { label: "Defines area()", points: 2 }];
  var card = C.card(tests, "✔ Tests your code will be checked against");
  root.appendChild(card);
  var marks = function () { return card.querySelectorAll(".tests-mark").map(function (m) { return m.textContent; }); };
  out.fresh = { marks: marks(), button: card.querySelector(".tests-run").hidden, sum: card.querySelector(".tests-sum").textContent,
                points: card.textContent.indexOf("(2 points)") >= 0 };
  var answer = null, runs = 0;
  C.setRunner(function () { runs++; return Promise.resolve(answer); });
  out.withRunner = { button: card.querySelector(".tests-run").hidden, sum: card.querySelector(".tests-sum").textContent };
  answer = { results: [{ label: "Uses a for loop", ok: true, detail: "" }, { label: "Defines area()", ok: false, detail: "There's no def area(...) in the code." }] };
  var heard = 0;
  root.addEventListener("ide-checks", function () { heard++; });
  card.querySelector(".tests-run").click();
  await tick(); await tick();
  out.checked = { marks: marks(), why: card.querySelectorAll(".tests-why").map(function (w) { return w.textContent; }),
                  passed: card.hasAttribute("data-passed"), sum: card.querySelector(".tests-sum").textContent, heard: heard, runs: runs };
  answer = { results: [{ label: "Uses a for loop", ok: true }, { label: "Defines area()", ok: true }] };
  await C.check();
  out.allPass = { marks: marks(), passed: card.hasAttribute("data-passed"), why: card.querySelectorAll(".tests-why").map(function (w) { return w.textContent; }) };
  // A card drawn later (the slide shown again) shows the last check at once.
  var again = C.card(tests);
  root.appendChild(again);
  out.redrawn = again.hasAttribute("data-passed");
  again.remove(); card.remove();

  // ---------------------------------------------------- the lock
  var deck = "locked: yes\n# One\n---\n# Two\n---\n# Three";
  async function viewer(md, opts) {
    var pane = new El("div"), body = pane.appendChild(new El("div"));
    root.appendChild(pane);
    var v = N.slideView(body, opts);
    var bar = v.bar, next = bar.children[2];
    await v.show(md);
    var put = function () { var c = C.card([{ label: "Step test", points: 1 }]); body.appendChild(c); return c; };
    return { v: v, body: body, next: next, put: put, pane: pane };
  }
  async function refresh(w, md) { await w.v.show(md); }
  C.forget();
  answer = { results: [{ label: "Step test", ok: false, detail: "not yet" }] };
  var w = await viewer(deck, { locked: true, key: "hw" });
  w.put(); await refresh(w, deck);
  out.held = { next: w.next.disabled, title: w.next.title, said: w.body.classList.contains("tests-locking") };
  w.next.handlers.click.forEach(function (f) { f(); }); await tick();
  out.heldStep = w.v.at();
  await C.check();
  out.stillHeld = w.next.disabled;
  answer = { results: [{ label: "Step test", ok: true }] };
  await C.check();
  out.opened = { next: w.next.disabled, said: w.body.classList.contains("tests-locking"), kept: store["pyide-unlocked:hw"] };
  w.next.handlers.click.forEach(function (f) { f(); }); await tick();
  out.moved = w.v.at();
  w.pane.remove();
  // Opened again (a reload): the slide passed once is still open, before any check.
  C.forget();
  var w2 = await viewer(deck, { locked: true, key: "hw" });
  w2.put(); await refresh(w2, deck);
  out.reload = w2.next.disabled;
  w2.pane.remove();
  // Not held: without the line, where the page doesn't ask for it, or on a slide with no tests.
  var w3 = await viewer(deck.replace("locked: yes\n", ""), { locked: true, key: "a" });
  w3.put(); await refresh(w3, deck.replace("locked: yes\n", ""));
  var w4 = await viewer(deck, { locked: false, key: "b" });
  w4.put(); await refresh(w4, deck);
  var w5 = await viewer(deck, { locked: function () { return false; }, key: "c" });
  w5.put(); await refresh(w5, deck);
  var w6 = await viewer(deck, { locked: true, key: "d" });
  out.free = [w3.next.disabled, w4.next.disabled, w5.next.disabled, w6.next.disabled];
  [w3, w4, w5, w6].forEach(function (x) { x.pane.remove(); });

  // ------------------------------------- the toolbar's button, no card on screen
  var steps = "# Intro\nRead.\n---\n# Step 1\n```tests\nStep one\n```\n---\n# Step 2\n```tests\nStep two\n```";
  var labels = function (text) {
    var m = /```tests\n([\s\S]*?)```/.exec(text);
    return m ? m[1].trim().split("\n").map(function (l) { return { label: l }; }) : [];
  };
  async function fromIntro(md, results, key) {
    C.forget();
    answer = { results: results };
    var x = await viewer(md, { locked: true, key: key });
    var opened = 0;
    var got = await C.checkInNotes({ markdown: function () { return md; }, open: function () { opened++; },
                                     slides: N.slides, tests: labels, viewer: x.v });
    var at = x.v.at();
    x.pane.remove();
    return { at: at, opened: opened, got: !!got };
  }
  var one = [{ label: "Step one", ok: true }, { label: "Step two", ok: false, detail: "no" }];
  out.toFailing = await fromIntro(steps, one, "j1");
  out.lockedStops = await fromIntro("locked: yes\n" + steps, one, "j2");
  out.earlierFails = await fromIntro(steps, [{ label: "Step one", ok: false, detail: "no" }, { label: "Step two", ok: true }], "j4");
  out.allPassJump = await fromIntro(steps, [{ label: "Step one", ok: true }, { label: "Step two", ok: true }], "j3");
  out.noTests = await C.checkInNotes({ markdown: function () { return "# No tests here"; }, open: function () {},
                                       slides: N.slides, tests: labels, viewer: null });
  console.log(JSON.stringify(out));
})().catch(function (e) { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
""" % GLOBAL

res = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=60)
try:
    got = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = {"error": res.stderr[-600:] or res.stdout[-600:]}
check("node ran checks_in_notes.js and notes.js", "error" not in got, got.get("error"))

if "error" not in got:
    print("\nThe header line")
    h = got["header"]
    check("locked: yes is taken out, alone or beside theme: and animate:",
          h[0] == [True, "# A"] and h[1] == [True, "# A"], h[:2])
    check("  locked: no is a header line too, and says no", h[2] == [False, "# A"], h[2])
    check("  a word it doesn't know stays in, as text; and only the top counts",
          h[3][0] is False and h[3][1].startswith("locked: maybe") and h[4][0] is False, h[3:])
    check("  and it never changes how many slides there are", got["slides"] == [2, 2], got["slides"])

    print("\nThe card")
    f = got["fresh"]
    check("each test a line, ○ until it's checked, with its points", f["marks"] == ["○", "○"] and f["points"], f)
    check("  no Check my work where nothing can check code (no runner)", f["button"] is True and f["sum"] == "", f)
    w = got["withRunner"]
    check("  where the page can, its own ✔ Check my work", w["button"] is False and w["sum"] == "2 to pass", w)
    c = got["checked"]
    check("Check my work marks each line ✓ or ✗, with why under a failure",
          c["marks"] == ["✓", "✗"] and c["why"] == ["", "There's no def area(...) in the code."], c)
    check("  says how many pass, and isn't passed until all do",
          c["sum"] == "1 of 2 passing" and c["passed"] is False and c["runs"] == 1, c)
    check("  and tells the page it checked (ide-checks), so the slide viewer hears", c["heard"] >= 1, c)
    a = got["allPass"]
    check("all passing: every ✓, no why, and the card is passed", a["marks"] == ["✓", "✓"] and a["passed"] and a["why"] == ["", ""], a)
    check("a card drawn again shows the last check at once", got["redrawn"] is True)

    print("\nlocked: yes")
    he = got["held"]
    check("a slide with checks holds the next one, saying why", he["next"] is True and he["title"] == "Pass this slide's checks first"
          and he["said"] is True, he)
    check("  the arrow can't be got round", got["heldStep"] == 0, got["heldStep"])
    check("  still held while a check fails", got["stillHeld"] is True)
    o = got["opened"]
    check("  open once every check passes, and how far they got is kept", o.get("next") is False and o.get("said") is False
          and o.get("kept") == "1", o)
    check("  and the way on works", got["moved"] == 1, got["moved"])
    check("a slide passed once stays open after a reload, before any check", got["reload"] is False)
    check("never held without the line, where the page doesn't ask, or on a slide with no tests",
          got["free"] == [False, False, False, False], got["free"])

    print("\nThe toolbar's Check my work, with no card on screen")
    check("the notes open, and turn to the first slide with a check failing",
          got["toFailing"] == {"at": 2, "opened": 1, "got": True} and got["earlierFails"]["at"] == 1,
          (got["toFailing"], got["earlierFails"]))
    check("  never past a slide with checks the lock still holds (a slide with none holds nothing)",
          got["lockedStops"]["at"] == 1, got["lockedStops"])
    check("  every check passing: the last slide with checks", got["allPassJump"]["at"] == 2, got["allPassJump"])
    check("  notes with no tests in them leave it to the page (the console)", got["noTests"] is False, got["noTests"])

print("\nWhere it's on")
pages = {}
for name in ("app.js", "live.js", "autograde.js"):
    pages[name] = open(os.path.join(STATIC, name)).read()
check("the tests block is drawn as the card when the file is on the page",
      "window.IDENotesChecks.card(got.tests" in pages["autograde.js"])
RUNNER = r"window\.IDENotesChecks\.setRunner\((runChecks|runLiveChecks|function \(\) \{ return run(?:Live)?Checks\(null\); \})\)"
for name in ("app.js", "live.js"):
    check("  %s gives the cards its runner" % name, re.search(RUNNER, pages[name]) is not None)
    check("  and its own Check my work puts the results in a card on screen",
          "if (window.IDENotesChecks && window.IDENotesChecks.onScreen()) {" in pages[name]
          and "await window.IDENotesChecks.check();" in pages[name])
    check("  the student's result is still kept for the teacher", pages[name].count('fetch("/api/tests/self"') == 1)
    check("  and with no card on screen, it opens the notes there rather than the console",
          "await window.IDENotesChecks.checkInNotes({" in pages[name]
          and pages[name].find("checkInNotes({") < pages[name].find("Checking your ", pages[name].find("checkInNotes({")))
check("the editor locks for a student only — never the teacher writing them, nor live",
      re.search(r"locked: function \(\) \{ return !(?:window\.\w+|cfg)\.authoring && !(?:window\.\w+|cfg)\.readonly && !liveCode; \}",
                pages["app.js"]) is not None)
check("  the live page never locks", "locked:" not in re.findall(r"slideView\([^)]*\)", pages["live.js"])[0]
      if re.findall(r"slideView\([^)]*\)", pages["live.js"]) else True)
for t in ("index.html", "live.html"):
    html = open(os.path.join(ROOT, "templates", t)).read()
    check("%s loads checks_in_notes.js, before autograde.js draws a card" % t,
          0 <= html.find("filename='checks_in_notes.js'") < html.find("filename='autograde.js'"))
help_page = open(os.path.join(ROOT, "templates", "help_questions.html")).read()
check("the help page says how to lock, and that the checks are in the notes",
      'id="locked"' in help_page and "locked: yes" in help_page and "card in the" in help_page)

failed = results.count(False)
print("\n" + ("ALL PASSED" if not failed else "SOME FAILED") + " (%d checks, %d failed)" % (len(results), failed))
sys.exit(1 if failed else 0)
