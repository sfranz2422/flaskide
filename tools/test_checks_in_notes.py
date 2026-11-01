#!/usr/bin/env python3
"""Check my work in the notes, and `locked: yes` — the same file in PyIDE,
WebIDE and FlaskIDE.

    python3 tools/test_checks_in_notes.py

A ```tests block in the notes is a card (checks_in_notes.js): each test a
line, ✓ or ✗ with why once checked, and its own ✔ Check my work where the
page can check code — the only one: the button at the top of the editor and
the live page is gone. With `locked: yes` at the top of the notes, a slide
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
SNIPPETS_JS = open(os.path.join(STATIC, "snippets.js")).read()
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
  // Cleared children are cut loose, as in a browser: notes.js checks a
  // box's parentNode to put Play back after the slide is drawn again.
  set: function (v) { this._text = String(v); this.children.forEach(function (c) { c.parentNode = null; }); this.children = []; } });
Object.defineProperty(El.prototype, "innerHTML", {
  get: function () { return this._text; }, set: function (v) { this._text = String(v); this.children = []; } });
Object.defineProperty(El.prototype, "offsetParent", { get: function () { return this.parentNode ? {} : null; } });
Object.defineProperty(El.prototype, "nextSibling", { get: function () {
  var s = this.parentNode ? this.parentNode.children : []; return s[s.indexOf(this) + 1] || null; } });
// Appending what's already in the page MOVES it, as in a browser (notes.js
// moves Play down under each new part).
El.prototype.appendChild = function (c) { if (c.parentNode) c.remove(); this.children.push(c); c.parentNode = this; return c; };
El.prototype.insertBefore = function (c) { return this.appendChild(c); };
El.prototype.replaceChild = function (c, old) { var i = this.children.indexOf(old); this.children[i] = c; c.parentNode = this; old.parentNode = null; return old; };
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
// Selectors: tag, .class, [attr], :not([attr]), one compound part, or a
// comma list of those — all the card, the viewer and snippets.js use.
function matches(el, sel) {
  if (sel.indexOf(",") >= 0) return sel.split(",").some(function (s) { return matches(el, s.trim()); });
  // "a > b": b, whose parent is a (enhanceCards' pre > code.language-cards).
  var gt = sel.lastIndexOf(" > ");
  if (gt >= 0) return matches(el, sel.slice(gt + 3)) && !!el.parentNode && matches(el.parentNode, sel.slice(0, gt));
  var tag = /^[a-z]+/i.exec(sel);
  if (tag && el.tagName !== tag[0].toUpperCase()) return false;
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
var window = { marked: { parse: function (s) { return s; }, parseInline: function (s) { return s; } },
               DOMPurify: { sanitize: function (s) { return s; } },
               matchMedia: function () { return { matches: false }; } };
// snippets.js's Python worker, stood in for: ready at once, and every run
// prints "1" and finishes.
function Worker() { var w = this; setTimeout(function () { w.onmessage({ data: { type: "ready" } }); }, 0); }
Worker.prototype.postMessage = function (m) {
  var w = this;
  setTimeout(function () { w.onmessage({ data: { type: "out", id: m.id, text: "1\n" } });
                           w.onmessage({ data: { type: "done", id: m.id } }); }, 0);
};
"""

harness = DOM + CHECKS_JS + "\nvar C = window.IDENotesChecks;\n" + NOTES_JS + "\n" + SNIPPETS_JS + r"""
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

  // ---------------------------------------------------- a prediction holds too
  // A ```python predict block, drawn by the real snippets.js: the slide
  // waits until it has been run, which needs a guess typed first.
  var pdeck = "locked: yes\n# One\n```python predict\nprint(1)\n```\n---\n# Two";
  // Each viewer its own code: a box once run is remembered by its code.
  function predictBox(w, src) {
    var pre = w.body.appendChild(new El("pre")), code = pre.appendChild(new El("code"));
    code.className = "language-python-predict"; code.textContent = (src || "print(1)") + "\n";
    window.IDESnippets.renderBlocks(w.body);
    return w.body.querySelector(".snippet");
  }
  var p1 = await viewer(pdeck, { locked: true, key: "p" });
  var box = predictBox(p1); await refresh(p1, pdeck);
  var run = box.querySelector(".snippet-run"), guess = box.querySelector(".snippet-guess");
  out.pHeld = { next: p1.next.disabled, title: p1.next.title, run: run.disabled };
  // A wrong prediction (the stand-in worker always prints 1) keeps it held.
  guess.value = "2"; guess.handlers.input.forEach(function (f) { f({}); });
  out.pTyped = { next: p1.next.disabled, run: run.disabled };
  run.click(); await tick(); await tick(); await tick();
  out.pWrong = p1.next.disabled;
  guess.value = "1"; guess.handlers.input.forEach(function (f) { f({}); });
  run.click(); await tick(); await tick(); await tick();
  out.pRan = { next: p1.next.disabled, kept: store["pyide-unlocked:p"], said: box.querySelector(".snippet-status").textContent };
  p1.pane.remove();
  // Passing the slide's checks isn't enough while its prediction waits.
  C.forget();
  answer = { results: [{ label: "Step test", ok: true }] };
  var p2 = await viewer(pdeck, { locked: true, key: "p2" });
  predictBox(p2, "print(3)"); p2.put(); await refresh(p2, pdeck); await C.check();
  out.pChecksOnly = p2.next.disabled;
  p2.pane.remove();
  // Drawn again after it ran (the slide shown again): not asked twice.
  var p3 = await viewer(pdeck, { locked: true, key: "p3" });
  predictBox(p3); await refresh(p3, pdeck);
  out.pRedrawn = p3.next.disabled;
  p3.pane.remove();
  // And never held where the page doesn't lock.
  // (Shown again with the same text: a changed slide is redrawn, box and all.)
  var p4 = await viewer(pdeck, { locked: false, key: "p4" });
  var b4 = predictBox(p4, "print(2)"); await refresh(p4, pdeck);
  out.pFreeBox = !!b4;
  out.pFree = p4.next.disabled;
  p4.pane.remove();

  // ---------------------------------------------------- held mid-slide
  // `animate:` with `locked: yes`: a part with a card holds ▶ Play until it
  // passes — students pressed Play past every "Type this" without typing.
  var still = window.matchMedia;
  window.matchMedia = function () { return { matches: true }; };   // no animation to wait for
  C.forget();
  answer = { results: [{ label: "Step test", ok: false, detail: "not yet" }] };
  var adeck = "animate: words\nlocked: yes\n# One\n...\nType this\n...\nNow your own line\n---\n# Two";
  var a = await viewer(adeck, { locked: true, animate: true, key: "anim" });
  var play = a.pane.querySelector(".reveal-play");
  play.click(); await tick(); await tick();
  a.put();                                    // the part just played had a tests block
  await C.check();
  out.midHeld = { play: play.disabled, hint: a.pane.querySelector(".reveal-hint").textContent,
                  next: a.next.disabled, pulse: play.classList.contains("is-ready") };
  play.click(); await tick(); await tick();
  a.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  out.midStillAt = a.pane.querySelectorAll(".reveal-part").length;
  answer = { results: [{ label: "Step test", ok: true }] };
  await C.check();
  // Play is the last thing in the slide, under the parts, and pulses.
  var kids = a.body.children, box = play.parentNode;
  out.midOpen = { play: play.disabled, next: a.next.disabled, nextTitle: a.next.title, kept: store["pyide-unlocked:anim"] || null,
                  pulse: play.classList.contains("is-ready"), arrowPulse: a.next.classList.contains("is-ready"),
                  last: box.parentNode === a.body && kids[kids.length - 1] === box };
  // The ARROW plays the next part, as Play would — and stays on this slide.
  a.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  out.midPlayed = a.pane.querySelectorAll(".reveal-part").length;
  out.midAt = a.v.at();
  kids = a.body.children;
  out.midLastAgain = kids[kids.length - 1] === box && kids[kids.length - 2] === a.pane.querySelectorAll(".reveal-part")[1];
  // All played (the third and last part, by the arrow again): Play goes,
  // and now the arrow pulses, and turns the slide.
  a.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  out.midThree = [a.pane.querySelectorAll(".reveal-part").length, a.v.at()];
  out.midDone = { play: play.hidden, pulse: play.classList.contains("is-ready"), arrowPulse: a.next.classList.contains("is-ready") };
  a.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  out.midTurned = a.v.at();
  a.pane.remove();

  // Held at the END of a slide (nothing left to play): the line says why,
  // never "Done — on to the next slide" beside a greyed arrow.
  window.matchMedia = function () { return { matches: true }; };
  C.forget();
  answer = { results: [{ label: "Step test", ok: false, detail: "not yet" }] };
  var e = await viewer("animate: words\nlocked: yes\n# One\n...\nLast part\n---\n# Two", { locked: true, animate: true, key: "endheld" });
  e.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  e.next.handlers.click.forEach(function (f) { f(); }); await tick(); await tick();
  e.put(); await C.check();
  out.endHeld = { next: e.next.disabled, hint: e.pane.querySelector(".reveal-hint").textContent, parts: e.pane.querySelectorAll(".reveal-part").length };
  e.pane.remove();
  window.matchMedia = still;

  // ---------------------------------------------------- cards to turn over
  // Words to Know under `locked: yes`: the slide holds until every card has
  // been turned over once — the real enhanceCards, clicked as a student would.
  var cdeck = "locked: yes\n# Words\n---\n# Two";
  async function cardsViewer(opts, key) {
    var w = await viewer(cdeck, Object.assign({ key: key }, opts));
    var pre = w.body.appendChild(new El("pre")), code = pre.appendChild(new El("code"));
    code.className = "language-cards"; code.textContent = "key -> a label\nvalue -> what's stored\n";
    N._enhanceCards(w.body);
    await refresh(w, cdeck);
    return w;
  }
  var k1 = await cardsViewer({ locked: true }, "cards");
  var cs = k1.body.querySelectorAll(".flip-card");
  out.cHeld = { n: cs.length, next: k1.next.disabled, title: k1.next.title };
  cs[0].click(); await tick();
  cs[0].click(); await tick();               // turned back: still seen
  out.cOne = k1.next.disabled;
  cs[1].click(); await tick();
  out.cAll = { next: k1.next.disabled, kept: store["pyide-unlocked:cards"] || null };
  k1.pane.remove();
  var k2 = await cardsViewer({ locked: false }, "cards2");
  out.cFree = k2.next.disabled;
  k2.pane.remove();
  window.matchMedia = still;

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
    mh = got["midHeld"]
    check("animate: a part with a check holds ▶ Play until it passes, saying why — and the arrow too",
          mh["play"] is True and "check above" in mh["hint"] and mh["next"] is True, mh)
    check("  held, Play doesn't pulse", mh["pulse"] is False, mh)
    check("  pressing Play or the arrow anyway plays nothing", got["midStillAt"] == 1, got["midStillAt"])
    mo = got["midOpen"]
    check("  passed: Play opens and pulses — but the slide isn't passed, with parts still to play",
          mo["play"] is False and mo["pulse"] is True and mo["kept"] is None, mo)
    check("  Play sits last in the slide, under what's been played", mo["last"] is True, mo)
    check("  the arrow is open too, saying it plays the next part (no pulse: Play's the one)",
          mo["next"] is False and mo["nextTitle"] == "Play the next part of this slide" and mo["arrowPulse"] is False, mo)
    check("  pressing the arrow plays the next part, on the same slide",
          got["midPlayed"] == 2 and got["midAt"] == 0, [got["midPlayed"], got["midAt"]])
    check("  and Play moves down under the new part", got["midLastAgain"] is True)
    check("  and again for the last part, still on the slide", got["midThree"] == [3, 0], got["midThree"])
    md_ = got["midDone"]
    check("  all played: Play goes, and the arrow pulses", md_["play"] is True and md_["pulse"] is False and md_["arrowPulse"] is True, md_)
    check("  and now the arrow turns the slide", got["midTurned"] == 1, got["midTurned"])
    eh = got["endHeld"]
    check("held at the end of a slide, the line says why — not \"Done, on to the next slide\"",
          eh["parts"] == 2 and eh["next"] is True and eh["hint"] == "Pass the check above to go on", eh)
    ch = got["cHeld"]
    check("locked: Words to Know holds the next slide until every card is turned over, saying why",
          ch["n"] == 2 and ch["next"] is True and ch["title"] == "Turn over every card first", ch)
    check("  one card turned (and turned back) isn't enough", got["cOne"] is True)
    check("  all turned: open, and kept", got["cAll"]["next"] is False and got["cAll"]["kept"] == "1", got["cAll"])
    check("  and cards hold nothing where the page doesn't lock", got["cFree"] is False)
    ph = got["pHeld"]
    check("a slide with a python predict block holds the next one, saying why",
          ph["next"] is True and ph["title"] == "Get this slide's prediction right first" and ph["run"] is True, ph)
    check("  typing a guess isn't enough: it opens Check, not the slide",
          got["pTyped"] == {"next": True, "run": False}, got["pTyped"])
    check("  a wrong prediction keeps it held", got["pWrong"] is True)
    pr = got["pRan"]
    check("  a right one opens the slide, and how far they got is kept",
          pr["next"] is False and pr["kept"] == "1" and "✓" in pr["said"], pr)
    check("  passing the slide's checks doesn't open it while the prediction waits", got["pChecksOnly"] is True)
    check("  a box drawn again after it ran isn't asked for twice", got["pRedrawn"] is False)
    check("  and a prediction holds nothing where the page doesn't lock", got["pFree"] is False and got["pFreeBox"])

print("\nWhere it's on")
pages = {}
for name in ("app.js", "live.js", "autograde.js"):
    pages[name] = open(os.path.join(STATIC, name)).read()
check("the tests block is drawn as the card when the file is on the page",
      "window.IDENotesChecks.card(got.tests" in pages["autograde.js"])
# Registered whatever else is on the page: WebIDE's once waited for the
# button at the top, and with that gone the cards would have had no runner.
RUNNER = r"\n  if \(window\.IDENotesChecks\) window\.IDENotesChecks\.setRunner\((runChecks|runLiveChecks|function \(\) \{ return run(?:Live)?Checks\(null\); \})\)"
for name in ("app.js", "live.js"):
    check("  %s gives the cards its runner" % name, re.search(RUNNER, pages[name]) is not None)
    check("  the student's result is still kept for the teacher", pages[name].count('fetch("/api/tests/self"') == 1)
    # The button at the top came out: the teacher wanted students checking
    # on the card, beside the step. Its code went with it, and a page still
    # calling it would throw on the first click of anything wired near it.
    check("  and has no Check my work of its own, only the cards'",
          not re.search(r"checkWork|checkInNotes|onScreen\(|\$\(\"check\"\)", pages[name]))
check("the editor locks for a student only — never the teacher writing them, nor live",
      re.search(r"locked: function \(\) \{ return !(?:window\.\w+|cfg)\.authoring && !(?:window\.\w+|cfg)\.readonly && !liveCode; \}",
                pages["app.js"]) is not None)
check("  the live page never locks", "locked:" not in re.findall(r"slideView\([^)]*\)", pages["live.js"])[0]
      if re.findall(r"slideView\([^)]*\)", pages["live.js"]) else True)
for t in ("index.html", "live.html"):
    html = open(os.path.join(ROOT, "templates", t)).read()
    check("%s loads checks_in_notes.js, before autograde.js draws a card" % t,
          0 <= html.find("filename='checks_in_notes.js'") < html.find("filename='autograde.js'"))
    check("  and has no ✔ Check my work at the top", 'id="check"' not in html)
help_page = open(os.path.join(ROOT, "templates", "help_questions.html")).read()
check("the help page says how to lock, and that the checks are in the notes",
      'id="locked"' in help_page and "locked: yes" in help_page and "card in the" in help_page)

failed = results.count(False)
print("\n" + ("ALL PASSED" if not failed else "SOME FAILED") + " (%d checks, %d failed)" % (len(results), failed))
sys.exit(1 if failed else 0)
