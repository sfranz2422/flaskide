"""Work typed while signed out is not lost. All three editors.

    python3 tools/test_rescue.py

THE BUG

A student opens an assignment link, works for ten minutes, realises they are
not signed in, and clicks Sign in. Google takes the tab away and brings it
back, the page reloads with a fresh copy of the starter, and everything they
wrote is gone. Nothing anywhere tried to prevent it — localStorage held the
theme and the font size and nothing else.

Signing in was only the commonest way to lose it. A refresh, a crashed tab
and a flat battery did the same, because the work had nowhere to be.

WHAT IS CHECKED, AND WHY IT IS RUN RATHER THAN READ

The decision that matters — put it back silently, ask first, or leave it
alone — is four branches in rescue.js, and grepping for the branch names
would pass on code where none of them could be reached. So the real file is
loaded into node with a stubbed browser and each case is actually driven.

The dangerous branch is the third: a student who had already done real work
on this assignment must never have it replaced without being asked.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
APPS = [d for d in ("pyide", "webide", "flaskide")
        if os.path.isfile(os.path.join(ROOT, d, "static", "rescue.js"))]

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-58s %s" % ("ok" if ok else "FAIL", label, detail))


def done():
    bad = results.count(False)
    print("\n%s (%d checks, %d failed)"
          % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
    sys.exit(1 if bad else 0)


if not shutil.which("node"):
    sys.exit("node is needed to run rescue.js; install it or skip this test")


# ==========================================================================
# The module itself, driven in node
# ==========================================================================

HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const scenario = JSON.parse(process.argv[3]);

// A browser, as far as rescue.js is concerned.
const store = Object.assign({}, scenario.store || {});
const blocked = !!scenario.blocked;
global.window = {
  localStorage: {
    getItem(k) { if (blocked) throw new Error("blocked"); return k in store ? store[k] : null; },
    setItem(k, v) { if (blocked) throw new Error("blocked"); store[k] = v; },
    removeItem(k) { if (blocked) throw new Error("blocked"); delete store[k]; }
  },
  confirm() { return !!scenario.answerYes; }
};

eval(src);

let project = Object.assign({}, scenario.project);
let asked = 0, restoredCalled = 0;

const r = window.IDERescue.attach({
  app: scenario.app,
  cfg: scenario.cfg,
  readAll: () => Object.assign({}, project),
  writeAll: (incoming) => { project = Object.assign({}, incoming); },
  onRestored: () => { restoredCalled++; },
  ask: () => { asked++; return !!scenario.answerYes; }
});

if (scenario.thenEdit) {
  project = Object.assign({}, project, scenario.thenEdit);
  r.noteEdit();
}

const out = () => console.log(JSON.stringify({
  project, asked, restoredCalled, store,
  key: window.IDERescue.keyFor(scenario.app, scenario.cfg)
}));

// noteEdit debounces; wait past it.
if (scenario.thenEdit) setTimeout(out, 900); else out();
"""


def drive(app, scenario):
    """Run rescue.js for real and report what it did."""
    path = os.path.join(ROOT, app, "static", "rescue.js")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(HARNESS)
        harness = fh.name
    try:
        proc = subprocess.run(
            ["node", harness, path, json.dumps(scenario)],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return {"error": (proc.stderr or "").strip().splitlines()[-1:]}
        return json.loads(proc.stdout)
    finally:
        os.unlink(harness)


STARTER = {"main.py": "# starter"}
THEIRS = {"main.py": "# ten minutes of work"}
LATER = {"main.py": "# work from another day"}


def stash(files, age_ms=0):
    import time
    return json.dumps({"at": int(time.time() * 1000) - age_ms, "files": files})


for app in APPS:
    print("\n%s" % app)
    key = "%s:rescue:hw1" % app
    signed_out = {"signedIn": False, "assignmentSlug": "hw1"}
    signed_in = {"signedIn": True, "assignmentSlug": "hw1",
                 "draftSlug": "d1", "draftFresh": True}
    worked_on = dict(signed_in, draftFresh=False)

    # ---- the bug itself -------------------------------------------------
    r = drive(app, {"app": app, "cfg": signed_in, "project": STARTER,
                    "store": {key: stash(THEIRS)}})
    check("work typed before signing in comes back after it",
          r.get("project") == THEIRS, r.get("project"))
    check("  silently, with nothing to click",
          r.get("asked") == 0, "asked %s times" % r.get("asked"))
    check("  and the local copy is cleared once it has landed",
          key not in r.get("store", {}),
          "a stale copy would reappear over tomorrow's work")
    check("  and the project is marked edited so it saves to the server",
          r.get("restoredCalled") == 1, r.get("restoredCalled"))

    # ---- THE DANGEROUS ONE ----------------------------------------------
    r = drive(app, {"app": app, "cfg": worked_on, "project": LATER,
                    "store": {key: stash(THEIRS)}, "answerYes": False})
    check("work already saved on that assignment is never replaced silently",
          r.get("asked") == 1, "asked %s times" % r.get("asked"))
    check("  and saying no keeps what was saved",
          r.get("project") == LATER, r.get("project"))
    check("  and stops it being offered again",
          key not in r.get("store", {}))

    r = drive(app, {"app": app, "cfg": worked_on, "project": LATER,
                    "store": {key: stash(THEIRS)}, "answerYes": True})
    check("  saying yes puts the typed work back",
          r.get("project") == THEIRS, r.get("project"))

    # ---- a refresh while still signed out -------------------------------
    r = drive(app, {"app": app, "cfg": signed_out, "project": STARTER,
                    "store": {key: stash(THEIRS)}})
    check("a refresh before signing in also gets the work back",
          r.get("project") == THEIRS and r.get("asked") == 0,
          r.get("project"))

    # ---- nothing to do --------------------------------------------------
    r = drive(app, {"app": app, "cfg": signed_in, "project": STARTER,
                    "store": {}})
    check("with nothing stashed, nothing happens",
          r.get("project") == STARTER and r.get("asked") == 0)

    r = drive(app, {"app": app, "cfg": signed_in, "project": THEIRS,
                    "store": {key: stash(THEIRS)}})
    check("a stash identical to what is open is dropped, not offered",
          r.get("asked") == 0 and key not in r.get("store", {}))

    # ---- age ------------------------------------------------------------
    r = drive(app, {"app": app, "cfg": signed_in, "project": STARTER,
                    "store": {key: stash(THEIRS, age_ms=25 * 3600 * 1000)}})
    check("something abandoned yesterday is not dropped on today's work",
          r.get("project") == STARTER,
          "a rescue that is old enough is an ambush")

    # ---- who it covers --------------------------------------------------
    r = drive(app, {"app": app, "cfg": signed_in, "project": STARTER,
                    "store": {}, "thenEdit": {"main.py": "typing"}})
    check("a signed-in student's typing is not copied locally",
          r.get("store") == {},
          "their work goes to the server; two copies is two answers")

    r = drive(app, {"app": app, "cfg": signed_out, "project": STARTER,
                    "store": {}, "thenEdit": {"main.py": "typing"}})
    check("a signed-out student's typing is",
          r.get("store", {}).get(key) is not None
          and json.loads(r["store"][key])["files"] == {"main.py": "typing"},
          sorted(r.get("store", {})))

    # ---- the school laptop ----------------------------------------------
    r = drive(app, {"app": app, "cfg": signed_out, "project": STARTER,
                    "store": {}, "blocked": True,
                    "thenEdit": {"main.py": "typing"}})
    check("blocked site data does not stop the editor opening",
          "error" not in r,
          r.get("error", ""))
    check("  and the work still shows on screen",
          r.get("project", {}).get("main.py") == "typing")

    # ---- the key bridges the two addresses ------------------------------
    at_a = drive(app, {"app": app, "cfg": signed_out, "project": STARTER,
                       "store": {}, "thenEdit": THEIRS})
    check("what /a/<assignment> saves is what /p/<draft> looks for",
          at_a.get("key") == key and key in at_a.get("store", {}),
          "keyed by the page, the work could never be found again")

# ==========================================================================
# The flag the silent branch depends on
# ==========================================================================
#
# draftFresh is what decides whether the rescue can happen without asking.
# Wrong in one direction it interrupts the whole class for nothing; wrong in
# the other it destroys work without a word, which is the failure this
# feature exists to prevent.
print("\ndraftFresh, from the server")

import tempfile as _tf
os.environ.setdefault("SECRET_KEY", "k" * 32)
os.environ["TEACHER_EMAILS"] = "t@example.org"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_tf.mkdtemp(), "f.db")
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
sys.path.insert(0, APP)
import app as A            # noqa: E402
import accounts            # noqa: E402

db = A.SessionLocal()
for sub, em, nm in (("t1", "t@example.org", "T"), ("s1", "kid@example.org", "S")):
    db.add(accounts.User(google_sub=sub, email=em, name=nm))
db.commit()
tid = db.query(accounts.User).filter_by(email="t@example.org").first().id
sid = db.query(accounts.User).filter_by(email="kid@example.org").first().id
db.close()

tc, st = A.app.test_client(), A.app.test_client()
with tc.session_transaction() as s:
    s["uid"] = tid
with st.session_transaction() as s:
    s["uid"] = sid

starter = ({"code": "# starter", "files": {}} if A.APP_NAME == "pyide"
           else {"files": {"index.html": "<h1>starter</h1>"}}
           if A.APP_NAME == "webide" else {"files": {"app.py": "# starter"}})
hw = tc.post("/api/assignment",
             json=dict(starter, title="HW")).get_json()["slug"]
slug = st.get("/a/" + hw).headers["Location"].rsplit("/", 1)[-1]

page = st.get("/p/" + slug).get_data(as_text=True)
check("a draft made by signing in is fresh, so the rescue is silent",
      "draftFresh: true" in page)

st.post("/api/draft/" + slug,
        json=dict(starter, code="# their own work",
                  files={"index.html": "<h1>mine</h1>"}
                  if A.APP_NAME == "webide" else {"app.py": "# mine"}))
page = st.get("/p/" + slug).get_data(as_text=True)
check("  and stops being fresh the moment they work on it",
      "draftFresh: false" in page,
      "a stale true here would overwrite real work without asking")

check("every editor page carries the rescue",
      "rescue.js" in page and "draftFresh" in page)

done()
