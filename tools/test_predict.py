#!/usr/bin/env python3
"""A ```python predict block in the notes — the same file in PyIDE, WebIDE
and FlaskIDE.

    python3 tools/test_predict.py

The student says what the code will print and must get it RIGHT (the
teacher's call, Nov 2026): before, any guess ran it, and pressing Enter ran
a two-line prediction after its first line. So, checked here:

  * the guess takes new lines; Enter never checks it
  * a wrong guess never shows the output — each line is marked ✓ / ✗ and
    the next `# hint:` comes out — and the code can't be edited until it's
    right (or a student edits it to print("x") and predicts "x")
  * right: the output, data-predicted (what `locked: yes` waits for), and
    claim() on the FIRST try only — a reload doesn't make a later try first
  * hints are taken out of the code shown and run
  * an example that stops with an error never holds anyone
  * a teacher's page has Show the output; a student's doesn't
  * snippets.js and xp.py read a block's code alike (or no claim matches)
  * /api/predict/xp pays xp.PREDICT_XP once, only for a block in that
    assignment's notes, and nothing to a teacher

The real snippets.js runs in node on a small fake DOM, with its Python
worker stood in for (it prints what the code's first `print("...")` says).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNIPPETS_JS = open(os.path.join(ROOT, "static", "snippets.js")).read()

DB = os.path.join(tempfile.mkdtemp(), "predict.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
sys.path.insert(0, ROOT)

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else "   " + str(detail)[:400]))


if not shutil.which("node"):
    print("  FAIL node is needed: brew install node")
    sys.exit(1)

DOM = r"""
var store = {};
var localStorage = { getItem: function (k) { return k in store ? store[k] : null; },
                     setItem: function (k, v) { store[k] = String(v); } };
var location = { pathname: "/a/demo" };
function El(tag) {
  this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null;
  this.attrs = {}; this.className = ""; this.hidden = false; this.disabled = false; this.readOnly = false;
  this.title = ""; this.value = ""; this._text = ""; this.handlers = {}; this.style = {};
}
Object.defineProperty(El.prototype, "textContent", {
  get: function () { return this._text + this.children.map(function (c) { return c.textContent; }).join(""); },
  set: function (v) { this._text = String(v); this.children = []; } });
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.replaceChild = function (c, old) { var i = this.children.indexOf(old); this.children[i] = c; c.parentNode = this; return old; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.addEventListener = function (ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); };
El.prototype.dispatchEvent = function (e) {
  for (var n = this; n; n = n.parentNode) (n.handlers[e.type] || []).forEach(function (fn) { fn(e); });
  return true;
};
El.prototype.fire = function (type, e) { (this.handlers[type] || []).forEach(function (fn) { fn(e || {}); }); };
El.prototype.click = function () { this.fire("click"); };
function has(el, c) { return (" " + el.className + " ").indexOf(" " + c + " ") >= 0; }
function matches(el, sel) {
  if (sel.indexOf(",") >= 0) return sel.split(",").some(function (s) { return matches(el, s.trim()); });
  var tag = /^[a-z]+/i.exec(sel);
  if (tag && el.tagName !== tag[0].toUpperCase()) return false;
  var ok = true;
  sel.replace(/\.([\w-]+)/g, function (_, c) { if (!has(el, c)) ok = false; return ""; });
  return ok;
}
El.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (c) { if (matches(c, sel)) out.push(c); walk(c); }); })(this);
  return out;
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
var document = { createElement: function (t) { return new El(t); } };
function CustomEvent(type) { this.type = type; }
var window = {};
// The worker, stood in for: whatever the code's print("...") calls say, a
// line each; `raise` in the code ends it with an error. Counts its runs.
var runs = [];
function Worker() { var w = this; setTimeout(function () { w.onmessage({ data: { type: "ready" } }); }, 0); }
Worker.prototype.postMessage = function (m) {
  var w = this; runs.push(m.code);
  setTimeout(function () {
    var said = []; m.code.replace(/print\("([^"]*)"\)/g, function (_, s) { said.push(s); return ""; });
    if (said.length) w.onmessage({ data: { type: "out", id: m.id, text: said.join("\n") + "\n" } });
    w.onmessage({ data: { type: "done", id: m.id, error: /raise/.test(m.code) ? "line 2: ValueError: no" : "" } });
  }, 0);
};
"""

harness = DOM + SNIPPETS_JS + r"""
var S = window.IDESnippets;
var out = {};
var tick = function () { return new Promise(function (r) { setTimeout(r, 0); }); };
async function settle() { for (var i = 0; i < 5; i++) await tick(); }
function block(code) {
  var root = new El("div"), pre = root.appendChild(new El("pre")), c = pre.appendChild(new El("code"));
  c.className = "language-python-predict"; c.textContent = code + "\n";
  S.renderBlocks(root);
  var box = root.children[0];
  var btns = box.querySelectorAll(".snippet-run");
  return { root: root, box: box, area: box.querySelector(".snippet-code"), guess: box.querySelector(".snippet-guess"),
           check: btns[0], run: btns[1], show: box.querySelector(".snippet-show"),
           out: box.querySelector(".snippet-out"), marks: box.querySelector(".snippet-marks"),
           hints: box.querySelector(".snippet-hints"), status: box.querySelector(".snippet-status") };
}
function type(b, text) { b.guess.value = text; b.guess.fire("input"); }
var claims = [];
S.configure({ claim: function (code) { claims.push(code); } });
(async function () {
  var CODE = 'word = "TURKEY"\n# hint: [0] is the first letter\nprint("T")\n# hint: [-1] counts from the end\nprint("Y")';
  var b = block(CODE);
  var heard = 0; b.root.addEventListener("ide-checks", function () { heard++; });
  out.fresh = { code: b.area.value, ro: b.area.readOnly, checkOff: b.check.disabled, runHidden: b.run.hidden,
                guessTag: b.guess.tagName, show: b.show.hidden, predicted: b.box.hasAttribute("data-predict") && !b.box.hasAttribute("data-predicted") };
  type(b, "T");
  // Enter: a new line, never a check.
  var stopped = false;
  b.guess.fire("keydown", { key: "Enter", preventDefault: function () { stopped = true; } });
  await settle();
  out.enter = { runs: runs.length, stopped: stopped };
  // Wrong (one line of two): no output, marks, the first hint, still read only.
  b.check.click(); await settle();
  out.wrong1 = { outHidden: b.out.hidden, marks: b.marks.textContent, hints: b.hints.children.length,
                 hint: b.hints.textContent, ro: b.area.readOnly, predicted: b.box.hasAttribute("data-predicted"),
                 ran: runs[runs.length - 1] };
  type(b, "t\nY");
  b.check.click(); await settle();
  out.wrong2 = { outHidden: b.out.hidden, hints: b.hints.children.length, marks: b.marks.textContent };
  type(b, "  T \n\nY  ");
  b.check.click(); await settle();
  out.right = { outHidden: b.out.hidden, out: b.out.textContent, ro: b.area.readOnly, predicted: b.box.hasAttribute("data-predicted"),
                runShown: !b.run.hidden, checkHidden: b.check.hidden, hints: b.hints.hidden, heard: heard,
                claims: claims.length, status: b.status.textContent };
  // After: the code is theirs to change and run.
  b.area.value = 'print("changed")'; b.run.click(); await settle();
  out.after = b.out.textContent;
  // Drawn again: still right, nothing to redo.
  var b2 = block(CODE);
  out.redrawn = { predicted: b2.box.hasAttribute("data-predicted"), ro: b2.area.readOnly };

  // Right on the first try: claimed, once, with the code as the server reads it.
  var c1 = block('print("A")\n# hint: nothing');
  type(c1, "A"); c1.check.click(); await settle();
  out.first = { claims: claims.slice(), status: c1.status.textContent };
  // A reload (memory gone, storage kept) doesn't make a later try the first.
  var c2code = 'print("B")';
  var c2 = block(c2code); type(c2, "x"); c2.check.click(); await settle();
  var key = Object.keys(store).filter(function (k) { return k.indexOf("pyide-predict:/a/demo:") === 0; });
  out.stored = key.length;
  // An example that stops with an error: shown, and it holds nobody.
  var e = block('print("half")\nraise ValueError("no")');
  type(e, "anything"); e.check.click(); await settle();
  out.erred = { predicted: e.box.hasAttribute("data-predicted"), out: e.out.textContent, hidden: e.out.hidden };
  // A teacher's page: Show the output, without predicting or passing.
  S.configure({ teacher: true });
  var t = block('print("Q")');
  out.teacher = { show: t.show.hidden };
  t.show.click(); await settle();
  out.teacherShown = { out: t.out.textContent, predicted: t.box.hasAttribute("data-predicted") };
  S.configure({ teacher: false });
  // Hints out of the code, as the server reads it.
  out.split = ["a = 1\n# hint: one\n  #HINT:two\nprint(a)\n\n", "# hint:\nx", "print('# hint: in a string')"].map(function (s) {
    var p = S._splitHints(s); return [p.code, p.hints]; });
  console.log(JSON.stringify(out));
})().catch(function (e) { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
"""

res = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=60)
try:
    got = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = {"error": res.stderr[-800:] or res.stdout[-800:]}
check("node ran snippets.js", "error" not in got, got.get("error"))

# ```html predict with # choice: lines — the student picks what the page
# shows (Nov 2026, for WebIDE's lessons, where nothing is printed).
PICK_HARNESS = DOM + SNIPPETS_JS + r"""
var S = window.IDESnippets;
var out = {};
var tick = function () { return new Promise(function (r) { setTimeout(r, 0); }); };
function pickBlock(code) {
  var root = new El("div"), pre = root.appendChild(new El("pre")), c = pre.appendChild(new El("code"));
  c.className = "language-html-predict"; c.textContent = code + "\n";
  S.renderBlocks(root);
  var box = root.children[0], btns = box.querySelectorAll(".snippet-run");
  return { root: root, box: box, area: box.querySelector(".snippet-code"), rows: box.querySelectorAll(".snippet-choice"),
           radios: box.querySelectorAll("input"), check: btns[0], run: btns[1], show: box.querySelector(".snippet-show"),
           frame: box.querySelector(".snippet-frame"), hints: box.querySelector(".snippet-hints"), status: box.querySelector(".snippet-status") };
}
function pick(b, i) { b.radios[i].checked = true; b.radios[i].fire("change"); }
var claims = [];
S.configure({ claim: function (code) { claims.push(code); } });
(async function () {
  var CODE = '<input type="checkbox"> Gravy\n# choice: a box you can tick\n# choice: a round button\n# hint: checkbox: a to-do list\n# answer: a box you can tick\n# choice: a text box';
  var b = pickBlock(CODE);
  var heard = 0; b.root.addEventListener("ide-checks", function () { heard++; });
  out.fresh = { code: b.area.value, ro: b.area.readOnly, n: b.rows.length, texts: b.rows.map(function (r) { return r.textContent; }),
                held: b.box.hasAttribute("data-predict") && !b.box.hasAttribute("data-predicted"),
                checkOff: b.check.disabled, frame: b.frame.hidden, run: b.run.hidden, show: b.show.hidden };
  pick(b, 1); out.picked = b.check.disabled;
  b.check.click(); await tick();
  out.wrong = { marked: b.rows[1].className, sign: b.rows[1].textContent, gone: b.radios[1].disabled, frame: b.frame.hidden,
                hints: b.hints.children.length, held: !b.box.hasAttribute("data-predicted"), checkOff: b.check.disabled,
                answerShown: /✓/.test(b.rows[0].textContent), ro: b.area.readOnly };
  pick(b, 0); b.check.click(); await tick();
  out.right = { predicted: b.box.hasAttribute("data-predicted"), frame: b.frame.hidden, page: b.frame.srcdoc, heard: heard,
                marked: b.rows[0].className, claims: claims.length, ro: b.area.readOnly, run: b.run.hidden, check: b.check.hidden,
                status: b.status.textContent, hints: b.hints.hidden };
  b.area.value = "<p>mine</p>"; b.run.click(); out.after = b.frame.srcdoc;
  var again = pickBlock(CODE);
  out.redrawn = { predicted: again.box.hasAttribute("data-predicted"), frame: again.frame.hidden };
  // First try right: claimed once, with the page as xp.py reads it.
  var f = pickBlock("<b>Pie</b>\n# choice: bold Pie\n# choice: slanted Pie\n# answer: bold Pie");
  pick(f, 0); f.check.click(); await tick();
  out.first = { claims: claims.slice(), status: f.status.textContent };
  // No choices: the plain html run box it always was, holding nothing.
  var plain = pickBlock("<p>Hi</p>");
  out.plain = { kind: plain.box.className, predict: plain.box.hasAttribute("data-predict"), run: !!plain.check };
  // A teacher's page: Show the answer, without passing the box.
  S.configure({ teacher: true });
  var t = pickBlock("<i>x</i>\n# choice: slanted x\n# choice: bold x\n# answer: slanted x");
  out.teacher = { show: t.show.hidden };
  t.show.click();
  out.teacherShown = { frame: t.frame.hidden, marked: t.rows[0].className, predicted: t.box.hasAttribute("data-predicted") };
  S.configure({ teacher: false });
  out.split = ["<p>a</p>\n# choice: x\n  #ANSWER: y\n# hint: h\n#menu { color: red }\n\n", "# choice:\n<b>"].map(function (x) {
    var q = S._splitPick(x); return [q.code, q.choices, q.answer, q.hints]; });
  console.log(JSON.stringify(out));
})().catch(function (e) { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
"""
res = subprocess.run(["node", "-e", PICK_HARNESS], capture_output=True, text=True, timeout=60)
try:
    pk = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    pk = {"error": res.stderr[-800:] or res.stdout[-800:]}
print("\nAn HTML pick (```html predict with # choice: lines)")
check("node ran the pick", "error" not in pk, pk.get("error"))
if "error" not in pk:
    f = pk["fresh"]
    check("the choice/answer/hint lines are out of the code; a choice each, the answer among them, in order",
          f["code"] == '<input type="checkbox"> Gravy' and f["n"] == 3
          and f["texts"] == ["a box you can tick", "a round button", "a text box"], f)
    check("  read only, held, no page yet, Check waits for a pick; a student has no Show the answer",
          f["ro"] and f["held"] and f["checkOff"] and f["frame"] and f["run"] and f["show"], f)
    check("  picking opens Check", pk["picked"] is False)
    w = pk["wrong"]
    check("a wrong pick: marked ✗ and can't be picked again, the first hint, still held",
          "is-wrong" in w["marked"] and "✗" in w["sign"] and w["gone"] and w["hints"] == 1 and w["held"] and w["ro"], w)
    check("  and the page and the answer are NOT shown", w["frame"] and not w["answerShown"], w)
    check("  Check waits for a new pick", w["checkOff"] is True, w)
    r = pk["right"]
    check("the right pick: ✓, the page itself shown, the box predicted, and the slide told",
          r["predicted"] and not r["frame"] and r["page"] == '<input type="checkbox"> Gravy' and r["heard"] >= 1
          and "is-right" in r["marked"], r)
    check("  the code opens up with Run; Check and the hints go; not the first try, so no XP",
          not r["ro"] and not r["run"] and r["check"] and r["hints"] and r["claims"] == 0 and "first" not in r["status"], r)
    check("  their own changes then render", pk["after"] == "<p>mine</p>", pk["after"])
    check("  drawn again: still predicted, the page shown", pk["redrawn"] == {"predicted": True, "frame": False}, pk["redrawn"])
    check("right on the first try: claimed once, the page without its lines",
          pk["first"]["claims"] == ["<b>Pie</b>"] and "first try" in pk["first"]["status"], pk["first"])
    check("without choices it's the plain html run box, holding nothing",
          "snippet-html" in pk["plain"]["kind"] and not pk["plain"]["predict"] and pk["plain"]["run"], pk["plain"])
    check("a teacher's page has Show the answer: it marks the answer and shows the page, passing nothing",
          pk["teacher"]["show"] is False and not pk["teacherShown"]["frame"] and "is-answer" in pk["teacherShown"]["marked"]
          and not pk["teacherShown"]["predicted"], pk)

if "error" not in got:
    print("\nThe box")
    f = got["fresh"]
    check("hints are taken out of the code shown", f["code"] == 'word = "TURKEY"\nprint("T")\nprint("Y")', f["code"])
    check("  the code is read only, Check waits for a guess, no Run yet",
          f["ro"] and f["checkOff"] and f["runHidden"], f)
    check("  the guess is a box of lines, and the box waits to be predicted",
          f["guessTag"] == "TEXTAREA" and f["predicted"], f)
    check("  a student's page has no Show the output", f["show"] is True, f)
    e = got["enter"]
    check("Enter is a new line: it never checks", e["runs"] == 0 and e["stopped"] is False, e)
    w = got["wrong1"]
    check("a wrong guess never shows the output", w["outHidden"] is True, w)
    check("  marks each line, a missing one too",
          "✓T" in w["marks"].replace(" ", "") and "missing" in w["marks"], w["marks"])
    check("  gives the first hint, only", w["hints"] == 1 and "[0] is the first letter" in w["hint"], w)
    check("  and the code stays read only, the box unpassed", w["ro"] and not w["predicted"], w)
    check("  what ran is the code without its hints", "hint" not in w["ran"] and 'print("Y")' in w["ran"], w["ran"])
    w2 = got["wrong2"]
    check("capitals count; the next hint comes out", w2["outHidden"] and w2["hints"] == 2 and "✗t" in w2["marks"].replace(" ", ""), w2)
    r = got["right"]
    check("right (spaces and blank lines don't count): the output shows",
          r["outHidden"] is False and r["out"].startswith("T\nY"), r)
    check("  the box is predicted, and tells the slide (ide-checks)", r["predicted"] and r["heard"] >= 1, r)
    check("  the code opens up: Run instead of Check, hints put away",
          not r["ro"] and r["runShown"] and r["checkHidden"] and r["hints"], r)
    check("  not the first try: no XP claimed", r["claims"] == 0 and "first" not in r["status"], r)
    check("  then their changes run", got["after"].startswith("changed"), got["after"])
    check("  a box drawn again stays predicted", got["redrawn"] == {"predicted": True, "ro": False}, got["redrawn"])
    fi = got["first"]
    check("right on the first try: claimed once, the code without its hints",
          fi["claims"] == ['print("A")'] and "first try" in fi["status"], fi)
    check("  how many tries is kept in the browser, so a reload can't make a first try", got["stored"] >= 3, got["stored"])
    er = got["erred"]
    check("an example that stops with an error shows it and holds nobody",
          er["predicted"] and not er["hidden"] and "ValueError" in er["out"], er)
    check("a teacher's page has Show the output", got["teacher"]["show"] is False, got["teacher"])
    check("  which shows it without passing the box",
          got["teacherShown"]["out"].startswith("Q") and not got["teacherShown"]["predicted"], got["teacherShown"])

    print("\nThe same block on both sides")
    import xp
    samples = ["a = 1\n# hint: one\n  #HINT:two\nprint(a)\n\n", "# hint:\nx", "print('# hint: in a string')"]
    check("snippets.js and xp.py take the same code out of a block",
          [s[0] for s in got["split"]] == [xp.predict_code(s) for s in samples],
          ([s[0] for s in got["split"]], [xp.predict_code(s) for s in samples]))
    pick_samples = ["<p>a</p>\n# choice: x\n  #ANSWER: y\n# hint: h\n#menu { color: red }\n\n", "# choice:\n<b>"]
    check("snippets.js and xp.py take the same page out of an HTML pick (a CSS #id line stays)",
          "error" not in pk and [x[0] for x in pk["split"]] == [xp.pick_code(x) for x in pick_samples]
          and pk["split"][0][0].endswith("#menu { color: red }"), (pk.get("split"), [xp.pick_code(x) for x in pick_samples]))
    check("  an answer not among the choices is added; an empty line is nothing",
          "error" not in pk and pk["split"][0][1] == ["x", "y"] and pk["split"][0][2] == "y" and pk["split"][1][1] == [], pk.get("split"))
    check("  hints in order; an empty one is no hint",
          got["split"][0][1] == ["one", "two"] and got["split"][1][1] == [], got["split"])

print("\nXP")
import accounts  # noqa: E402
import xp  # noqa: E402
import app as P  # noqa: E402


def add_user(sub, email, name):
    db = P.SessionLocal()
    try:
        u = accounts.User(google_sub=sub, email=email, name=name)
        db.add(u)
        db.commit()
        return u.id
    finally:
        db.close()


def client(uid=None):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


TEACHER = add_user("t", "teacher@school.org", "Mr Franz")
AMY = add_user("a", "amy@school.org", "Amy Adams")
teacher, amy, nobody = client(TEACHER), client(AMY), client()
CLASS = teacher.post("/api/class", json={"name": "P4"}).get_json()["id"]
_db = P.SessionLocal()
_db.add(accounts.Enrollment(class_id=CLASS, email="amy@school.org", name="Amy"))
_db.commit()
_db.close()
SLUG = teacher.post("/api/class/%d/new" % CLASS, json={"title": "Strings"}).get_json()["slug"]
NOTES = """# Strings

```python predict
word = "TURKEY"
# hint: [0] is the first one
print(word[0])
```

~~~py predict
print(len("PIE"))
~~~

```html predict
<b>Pie</b>
# choice: bold Pie
# answer: bold Pie
```

```html predict
<p>no choices, a plain run box</p>
```
"""
teacher.post("/api/library", json={"body": NOTES, "linkTo": SLUG})
check("every predict block in the notes is found (an HTML one too), and nothing else",
      len(xp.predict_keys({"notes.md": NOTES, "main.py": "```python predict\nx\n```"})) == 4)


def claim(c, code):
    r = c.post("/api/predict/xp", json={"assignment": SLUG, "code": code})
    return r.status_code, (r.get_json() or {}).get("xp")


A = 'word = "TURKEY"\nprint(word[0])'
check("a first-try prediction pays PREDICT_XP", claim(amy, A) == (200, xp.PREDICT_XP), claim)
check("  once: the same block again pays nothing", claim(amy, A) == (200, 0))
check("  the other block pays too", claim(amy, 'print(len("PIE"))') == (200, xp.PREDICT_XP))
check("  and an HTML pick, by its page", claim(amy, "<b>Pie</b>") == (200, xp.PREDICT_XP))
check("  a block that isn't in the notes pays nothing", claim(amy, 'print("free xp")') == (200, 0))
check("  nor does a teacher's", claim(teacher, A) == (200, 0))
check("  and signed out, it's refused", claim(nobody, A)[0] == 401)
_db = P.SessionLocal()
paid = [a.source for a in _db.query(accounts.XpAward).filter_by(user_id=AMY).all()]
_db.close()
check("  paid as predict:<assignment>:<block>", len(paid) == 3 and all(s.startswith("predict:") for s in paid), paid)

failed = results.count(False)
print("\n" + ("ALL PASSED" if not failed else "SOME FAILED") + " (%d checks, %d failed)" % (len(results), failed))
sys.exit(1 if failed else 0)
