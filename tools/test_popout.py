#!/usr/bin/env python3
"""Notes popped out into their own tab, still driving the class's slide.

    python3 tools/test_popout.py

WHAT IS BEING GUARDED

  The editor stays in charge, and the class follows the pop-out.
      Moving in the pop-out, live, moves the editor's slideAt and pushes at
      once — the same move the ◀ ▶ under "Class sees" make. Not live, it
      moves the editor's own notes and pushes nothing.

  The pop-out follows the editor.
      Its arrows, a change to the notes, going live: each reaches the
      pop-out without anything pressed there.

  It never shows a slide it has moved away from.
      A state already on its way when the clicker is pressed carries the
      slide before; shown, the projector would flick back for a moment.

  It says when the editor has gone, rather than sit on a slide that looks
  live: at once when the editor says goodbye, and after six seconds of
  silence when it cannot.

  Only a teacher can open the page.

The editor's own pop-out code (cut out of app.js) and present.js run in node
against each other over node's real BroadcastChannel, with the page around
them stubbed and the timers driven by hand.
"""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "popout.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


def read(*parts):
    return open(os.path.join(PYIDE, *parts)).read()


# ------------------------------------------------------------ the page
print("the page")
db = P.SessionLocal()
teacher = accounts.User(google_sub="t", email="teacher@school.org", name="T")
student = accounts.User(google_sub="s", email="s@school.org", name="S")
db.add_all([teacher, student])
db.commit()
TID, SID = teacher.id, student.id
db.close()


def client(uid):
    c = P.app.test_client()
    if uid:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


r = client(TID).get("/notes/present?ch=abc")
check("a teacher gets the pop-out page", r.status_code == 200
      and b"present.js" in r.data, r.status_code)
check("a student does not", client(SID).get("/notes/present").status_code == 404)
check("nor anyone signed out",
      client(None).get("/notes/present").status_code in (302, 404))
editor_page = read("templates", "index.html")
check("the editor has Pop out beside the notes and the class's slides",
      editor_page.count("js-popout") == 2)

# ------------------------------------------------------------ in node
print("the two tabs, in node")
if not shutil.which("node"):
    sys.exit("node is needed to run app.js and present.js; brew install node")

# The same test runs in all three editors: their notes.js global and their
# channel's name are the only differences it needs to know.
NS = re.search(r"window\.(\w+)Notes = \(function", read("static", "notes.js")).group(1)
CHANNEL = NS.lower() + "-notes-"

app_js = read("static", "app.js")
start = app_js.index("    // ------------------------------------------------- notes, popped out")
end = app_js.index("\n  } else {", start)
editor_block = app_js[start:end]

HARNESS = r"""
const notesJs = %(notes)s, editorBlock = %(editor)s, presentJs = %(present)s;
const NS = %(ns)s, CHANNEL = %(channel)s;

// Timers by hand, and a clock to move.
let clock = 1e12, intervals = [], timeouts = [];
Date.now = () => clock;
global.setInterval = (fn) => { intervals.push(fn); return intervals.length; };
global.setTimeout = (fn, ms) => { timeouts.push(fn); return 0; };
function tick() { intervals.slice().forEach((f) => f()); }
let editorTimers = 0;     // how many of `intervals` are the editor's
function tickEditor() { intervals.slice(0, editorTimers).forEach((f) => f()); }
const settle = () => new Promise((r) => setImmediate(() => setImmediate(r)));
async function flush() { for (let i = 0; i < 6; i++) await settle(); }

function node(tag) {
  return { tag, className: "", innerHTML: "", hidden: false, children: [], textContent: "",
           scrollTop: 0, parentNode: null, disabled: false, type: "", title: "", listeners: {},
           classList: { on: {}, toggle(c, v) { this.on[c] = !!v; } },
           setAttribute() {}, querySelectorAll() { return []; },
           addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
           appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
           insertBefore(c) { this.children.push(c); c.parentNode = this; return c; } };
}
const els = {};
const docListeners = {};
global.document = {
  title: "", documentElement: node("html"),
  createElement: node, head: { appendChild() {} },
  getElementById: (id) => els[id] || (els[id] = node(id), node("div").appendChild(els[id])),
  querySelectorAll: () => buttons,
  addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
};
const winListeners = {};
const opened = [];
global.window = { marked: { parse: (s) => s }, DOMPurify: { sanitize: (s) => s },
                  BroadcastChannel,
                  open: (u, n) => opened.push([u, n]),
                  addEventListener: (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); } };
global.location = { search: "" };
eval(notesJs);
const N = window[NS + "Notes"];

// ---- the editor's side, as app.js has it, in a stubbed scope
const buttons = [node("button")];
let notesText = "# One\n---\n# Two\n---\n# Three\n---\n# Four";
let slideAt = 0, liveCode = null, pushes = [];
const notesSlides = { i: 0, at() { return this.i; }, go(i) { this.i = Math.max(0, Math.min(3, i)); } };
function currentSlides() { const c = N.slides(notesText); return c.length >= 2 ? c : null; }
function liveNotes() { return notesText; }
function pushNow() { pushes.push(slideAt); }
function $(id) { return null; }
function slidesView() { return notesSlides; }      // FlaskIDE's, made on first use
eval(editorBlock);

const out = {};
const click = () => (docListeners.click || []).forEach((f) => f({ target: { closest: () => buttons[0] } }));
click();
click();
out.opened = opened;
if (!opened.length) { console.log(JSON.stringify(out)); process.exit(0); }
editorTimers = intervals.length;
const ch = new URLSearchParams(opened[0][0].split("?")[1]).get("ch");

// ---- the pop-out, as present.js is, in the same stubbed browser
location.search = "?ch=" + ch;
window.PRESENT = { ns: NS, channel: CHANNEL };
eval(presentJs);
const body = els["present-body"], chip = els["present-state"], lost = els["present-lost"];
lost.hidden = true;
function key(k) {
  const e = { key: k, preventDefault() {} };
  (docListeners.keydown || []).forEach((f) => f(e));
}
const shown = () => body.innerHTML;
const drawn = [];
Object.defineProperty(body, "innerHTML", {
  get() { return this._html || ""; },
  set(v) { this._html = v; drawn.push(v); }
});

(async function () {
  await flush();
  out.first = { shown: shown(), chip: chip.textContent, lost: lost.hidden };

  key("ArrowRight"); await flush();
  out.notLive = { editorNotes: notesSlides.i, pushes: pushes.slice(), shown: shown() };

  liveCode = "abc"; slideAt = 0; tick(); await flush();
  out.goneLive = { shown: shown(), chip: chip.textContent, live: chip.classList.on["live-chip"] };

  key("PageDown"); await flush();
  out.liveMove = { slideAt, pushes: pushes.slice(), shown: shown() };

  // The editor's arrows, with the pop-out not asking: its own timer.
  slideAt = 3; tickEditor(); await flush();
  out.editorArrows = shown();

  notesText = "# One\n---\n# Two\n---\n# Three\n---\n# Four, edited"; tick(); await flush();
  out.edited = shown();

  // The clicker pressed with an older state already on its way.
  slideAt = 1; tick(); await flush();
  key("ArrowRight");
  const from = drawn.length;
  const stale = new BroadcastChannel(CHANNEL + ch);
  stale.postMessage({ type: "state", notes: notesText, live: true, slide: 1, title: "T" });
  await flush();
  out.noFlick = { shown: shown(), slideAt, between: drawn.slice(from) };
  stale.close();

  // The editor goes quiet: after six seconds, the notice.
  clock += 3000; tick(); await flush();
  out.quiet3 = lost.hidden;
  // Silent as a crashed tab: neither its timer nor its answers.
  const wasIntervals = intervals.slice(), answer = popChan.onmessage;
  intervals = intervals.filter((f) => !String(f).includes("tellPopout"));
  popChan.onmessage = null;
  clock += 7000; tick(); await flush();
  out.quiet10 = lost.hidden;
  intervals = wasIntervals;
  popChan.onmessage = answer;

  // Back, then the editor unloads and says so.
  tick(); await flush();
  out.back = lost.hidden;
  (winListeners.pagehide || []).forEach((f) => f());
  await flush();
  out.bye = lost.hidden;

  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""

script = HARNESS % {"notes": json.dumps(read("static", "notes.js")),
                    "editor": json.dumps(editor_block),
                    "present": json.dumps(read("static", "present.js")),
                    "ns": json.dumps(NS), "channel": json.dumps(CHANNEL)}
res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    print(res.stdout[-1500:], res.stderr[-2500:])
    sys.exit(1)

_url, _name = (o["opened"] or [["", ""]])[0]
_ch = _url.split("ch=")[-1]
check("Pop out opens one named tab, and again brings the same one forward",
      len(o["opened"]) == 2 and o["opened"][0] == o["opened"][1]
      and _url.startswith("/notes/present?ch=") and _name == CHANNEL + _ch
      and re.fullmatch(r"[a-z0-9]{6,}", _ch), o["opened"])
if "first" not in o:
    print()
    print("%d/%d ok" % (sum(results), len(results)))
    sys.exit(1)
check("the pop-out shows the editor's notes as slides",
      o["first"]["shown"] == "# One" and o["first"]["lost"], o["first"])
check("  and says it is not live", o["first"]["chip"].startswith("Not live"), o["first"]["chip"])
check("not live, a move there moves the editor's notes and pushes nothing",
      o["notLive"]["editorNotes"] == 1 and o["notLive"]["pushes"] == []
      and o["notLive"]["shown"] == "# Two", o["notLive"])
check("going live reaches the pop-out, on the class's slide",
      o["goneLive"]["shown"] == "# One" and o["goneLive"]["live"]
      and o["goneLive"]["chip"].startswith("Live"), o["goneLive"])
check("live, a clicker press moves the class: slideAt, pushed at once",
      o["liveMove"]["slideAt"] == 1 and o["liveMove"]["pushes"] == [1]
      and o["liveMove"]["shown"] == "# Two", o["liveMove"])
check("the editor's own arrows move the pop-out", o["editorArrows"] == "# Four",
      o["editorArrows"])
check("editing the notes reaches it", o["edited"] == "# Four, edited", o["edited"])
check("a state from before the press does not flick it back",
      o["noFlick"]["shown"] == "# Three" and o["noFlick"]["slideAt"] == 2
      and "# Two" not in o["noFlick"]["between"], o["noFlick"])
check("a few quiet seconds are not the editor gone", o["quiet3"])
check("six silent seconds and it says it lost the editor", not o["quiet10"])
check("  and recovers when the editor answers again", o["back"])
check("the editor unloading says so at once", not o["bye"])

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
