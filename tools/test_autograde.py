#!/usr/bin/env python3
"""Tests in an assignment's notes: Check my work and Check all (autograde.py,
static/autograde.js, "Tests" in app.py).

    python3 tools/test_autograde.py

WHY THIS FILE EXISTS

A test that passes a wrong app, or fails a right one, is a wrong grade —
and once the teacher presses Check all, it is the grade that goes to
Classroom. So this pins:

  * the format: requests (status, contains, a form), code checks, SQL
    rows and results, points, and a line that isn't a test being said
    rather than quietly skipped;
  * autograde.js reads every block exactly as autograde.py does (node);
  * the tests, run against the real bridge (flask.js's Python, on real
    Flask, as test_bridge.py does), pass the right app and fail each wrong
    one for the right reason — wrong status, wrong text, a route that
    crashes, a missing route, a route that never returns, an app that won't
    import, code that won't read — and a SQL project's query;
  * the server: a student's own check is kept and counts for nothing; only
    the teacher's verified result is added to the grade, and can complete
    a quest; a verified result older than the work is marked stale; a page
    can't claim more points than the lines it sent; only the teacher can
    fetch the work or post a verified result.

Needs node, and Flask installed for this Python (as test_bridge.py).
"""
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AUTOGRADE = os.path.join(ROOT, "static", "autograde.js")
FLASKJS = os.path.join(ROOT, "static", "flask.js")

DB = os.path.join(tempfile.mkdtemp(), "ag.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
sys.path.insert(0, ROOT)
import autograde                                             # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-64s %s" % ("ok" if ok else "FAIL", label, detail))


NOTES = """# A greeting site

```tests
# a comment
GET / -> 200
GET / contains Welcome
GET /nope -> 404
POST /hello name=Sam&x=1 -> contains Hello, Sam
GET /about contains about &   US       (2 points)
uses render_template
defines home
avoids eval
```
"""

# ------------------------------------------------------------- the format
print("\nThe format")
tests, errors = autograde.parse(NOTES)
check("eight tests, comment skipped", [t["kind"] for t in tests] ==
      ["request"] * 5 + ["uses", "defines", "avoids"], [t["kind"] for t in tests])
check("a status test", tests[0]["method"] == "GET" and tests[0]["path"] == "/"
      and tests[0]["status"] == 200 and tests[0]["expect"] == "")
check("a contains test", tests[1]["status"] is None and tests[1]["expect"] == "Welcome")
check("a form goes with a POST", tests[3]["method"] == "POST" and tests[3]["form"] == "name=Sam&x=1"
      and tests[3]["expect"] == "Hello, Sam")
check("(2 points) is two points, the rest one each",
      [t["points"] for t in tests] == [1, 1, 1, 1, 2, 1, 1, 1])
check("labels read as sentences",
      [t["label"] for t in tests[:5]] == ["GET / answers 200", "GET / shows Welcome",
                                          "GET /nope answers 404",
                                          "POST /hello with name=Sam&x=1 shows Hello, Sam",
                                          "GET /about shows about &   US"]
      and tests[5]["label"] == "Uses render_template", [t["label"] for t in tests])
sql, _ = autograde.parse("```tests\nreturns 3 rows\nresult contains Alice\nreturns 1 row\n```")
check("SQL tests: rows and a result", [t["kind"] for t in sql] == ["rows", "result", "rows"]
      and sql[0]["count"] == 3 and sql[2]["label"] == "The query returns 1 row")
_, errs = autograde.parse("```tests\nGET / -> maybe\nopen the page\n```")
check("a line that isn't a test is an error, not skipped", len(errs) == 2, errs)
check("possible points add up", autograde.possible({"notes.md": NOTES}) == 9)

# ------------------------------------------------- the same in JavaScript
node = shutil.which("node")
if not node:
    check("node is available", False, "brew install node")
    sys.exit(1)
samples = [NOTES, "```tests\nGET /a?b=1 -> contains x\nPOST / a=1 -> 302\nGET / -> contains  Hi there\n```",
           "```tests\nreturns 3 rows (2 points)\nresult contains Alice (1 point)\nuses import sqlite3\n```",
           "```tests\nGET / -> maybe\nPOST /x -> 200\nnonsense\n```", "no block here"]
script = ("global.window={};eval(require('fs').readFileSync(%s,'utf8'));"
          "process.stdout.write(JSON.stringify(%s.map(s=>window.PyIDETests.parse(s))))"
          % (json.dumps(AUTOGRADE), json.dumps(samples)))
out = subprocess.run([node, "-e", script], capture_output=True, text=True)
try:
    js = json.loads(out.stdout)
except ValueError:
    js = []
check("node read autograde.js", len(js) == len(samples), out.stderr[-300:])
for i, (s, j) in enumerate(zip(samples, js)):
    py = autograde.parse(s)
    same = j["tests"] == py[0] and j["errors"] == py[1]
    check("  sample %d reads the same in both" % (i + 1), same,
          "" if same else "js=%r py=%r" % (j, py))

# ----------------------------------------- running them on the real bridge
print("\nRunning the tests (flask.js's Python, on real Flask)")
# The bridge as JavaScript hands it to Python: node evaluates flask.js's
# template literal, so every escape is undone exactly as in the browser.
src = open(FLASKJS).read()
literal = re.search(r"const BRIDGE = (`.*?`);", src, re.S).group(1)
project = tempfile.mkdtemp()
bridge = subprocess.run([node, "-e", "const PROJECT=%s;process.stdout.write(%s)"
                         % (json.dumps(project), literal)], capture_output=True, text=True).stdout
harness = subprocess.run([node, "-e", "global.window={};eval(require('fs').readFileSync(%s,'utf8'));"
                          "process.stdout.write(window.PyIDETests.HARNESS)" % json.dumps(AUTOGRADE)],
                         capture_output=True, text=True).stdout
check("the bridge and the harness were found", "_flaskide_load" in bridge
      and "_flaskide_autograde" in harness)

RIGHT = '''from flask import Flask, render_template, request
app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return "<h1>About &amp; us</h1>"

@app.route("/hello", methods=["POST"])
def hello():
    return "Hello, " + request.form["name"] + "!"
'''
INDEX = "<html><body><h1>Welcome   to my site</h1></body></html>"
APPS = {
    "right": {"app.py": RIGHT, "templates/index.html": INDEX},
    "wrong_text": {"app.py": RIGHT, "templates/index.html": "<h1>Hi</h1>"},
    "crashes": {"app.py": RIGHT.replace('"!"', '1'),
                "templates/index.html": INDEX},
    "no_about": {"app.py": RIGHT.replace('@app.route("/about")\ndef about():\n'
                                         '    return "<h1>About &amp; us</h1>"\n', ""),
                 "templates/index.html": INDEX},
    "endless": {"app.py": RIGHT.replace('    return "<h1>About &amp; us</h1>"',
                                        '    while True:\n        pass'),
                "templates/index.html": INDEX},
    "wont_import": {"app.py": RIGHT + "\nimport no_such_module\n",
                    "templates/index.html": INDEX},
    "unreadable": {"app.py": RIGHT.replace("def home():", "def home()"),
                   "templates/index.html": INDEX},
    "evil": {"app.py": RIGHT + "\neval('1')\n", "templates/index.html": INDEX},
}
SQL_NOTES = "```tests\nreturns 2 rows\nresult contains Alice\nresult contains Zed\nreturns 5 rows\n```"
SQL_FILES = {"schema.sql": "CREATE TABLE p (name TEXT);\nINSERT INTO p VALUES ('Alice'), ('Bob');",
             "query.sql": "-- everyone\nSELECT name FROM p ORDER BY name;"}
runner = '''
import json, sys
scope = {}
exec(compile(open(sys.argv[1]).read(), "flask.js:BRIDGE", "exec"), scope)
exec(compile(open(sys.argv[2]).read(), "autograde.js:HARNESS", "exec"), scope)
jobs = json.load(open(sys.argv[3]))
out = {}
for name, (files, tests) in jobs.items():
    out[name] = json.loads(scope["_flaskide_autograde"](json.dumps(files), json.dumps(tests), 2))
print(json.dumps(out))
'''
tmp = tempfile.mkdtemp()
for name, text in (("bridge.py", bridge), ("harness.py", harness), ("runner.py", runner)):
    with open(os.path.join(tmp, name), "w") as f:
        f.write(text)
jobs = {name: [files, tests] for name, files in APPS.items()}
jobs["sql"] = [SQL_FILES, autograde.parse(SQL_NOTES)[0]]
jobs["sql_broken"] = [dict(SQL_FILES, **{"query.sql": "SELEC name FROM p;"}), autograde.parse(SQL_NOTES)[0]]
with open(os.path.join(tmp, "jobs.json"), "w") as f:
    json.dump(jobs, f)
out = subprocess.run([sys.executable, os.path.join(tmp, "runner.py"), os.path.join(tmp, "bridge.py"),
                      os.path.join(tmp, "harness.py"), os.path.join(tmp, "jobs.json")],
                     capture_output=True, text=True, cwd=tmp, timeout=300)
try:
    ran = json.loads(out.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    ran = {}
check("every app was checked", len(ran) == len(jobs), out.stderr[-500:])


def lines(name):
    return {r["label"]: r for r in ran.get(name, {}).get("results", [])}


r = ran.get("right", {})
check("the right app passes everything: 9 of 9", r.get("earned") == 9 and r.get("possible") == 9,
      [(x["label"], x["detail"]) for x in r.get("results", []) if not x["ok"]])
check("  contains ignores case and spacing, and reads the page as text",
      lines("right")["GET / shows Welcome"]["ok"] and lines("right")["GET /about shows about &   US"]["ok"])
L = lines("wrong_text")
check("wrong text fails, saying what the page showed",
      not L["GET / shows Welcome"]["ok"] and "It showed: Hi" in L["GET / shows Welcome"]["detail"]
      and L["GET / answers 200"]["ok"], L["GET / shows Welcome"])
L = lines("crashes")
check("a route that crashes fails, naming the error",
      not L["POST /hello with name=Sam&x=1 shows Hello, Sam"]["ok"]
      and "crashed" in L["POST /hello with name=Sam&x=1 shows Hello, Sam"]["detail"],
      L["POST /hello with name=Sam&x=1 shows Hello, Sam"]["detail"])
L = lines("no_about")
check("a missing route fails with the status it got",
      not L["GET /about shows about &   US"]["ok"] and "404" in L["GET /about shows about &   US"]["detail"],
      L["GET /about shows about &   US"]["detail"])
L = lines("endless")
check("a route that never returns fails instead of hanging",
      "never ends" in L["GET /about shows about &   US"]["detail"] and L["GET / answers 200"]["ok"],
      L["GET /about shows about &   US"]["detail"])
L = lines("wont_import")
check("an app that won't import fails every request, saying why",
      all(not L[t["label"]]["ok"] for t in tests if t["kind"] == "request")
      and "ModuleNotFoundError" in L["GET / answers 200"]["detail"]
      and L["Uses render_template"]["ok"], L["GET / answers 200"]["detail"])
L = lines("unreadable")
check("code that won't read fails everything, saying where",
      ran["unreadable"]["earned"] == 0 and "can't be read" in L["Defines home()"]["detail"])
check("avoids catches a name that is used", not lines("evil")["Doesn't use eval"]["ok"]
      and lines("right")["Doesn't use eval"]["ok"])
check("a status test passes on the right status only", lines("right")["GET /nope answers 404"]["ok"]
      and not lines("no_about")["GET /about shows about &   US"]["ok"])
L = lines("sql")
check("SQL: the last query's rows are counted", L["The query returns 2 rows"]["ok"]
      and not L["The query returns 5 rows"]["ok"]
      and L["The query returns 5 rows"]["detail"] == "It returned 2 rows.", L.get("The query returns 5 rows"))
check("  a value in them is found, and one not there isn't",
      L["The query's result contains Alice"]["ok"] and not L["The query's result contains Zed"]["ok"]
      and "Alice" in L["The query's result contains Zed"]["detail"])
L = lines("sql_broken")
check("  a query that won't run fails, saying why",
      not L["The query returns 2 rows"]["ok"] and "SQL didn't run" in L["The query returns 2 rows"]["detail"])

# ---------------------------------------------------------------- server
print("\nThe server")
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402


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
OTHER = add_user("o", "other@school.org", "Ms Other")
AMY = add_user("a", "amy@school.org", "Amy Adams")
BEN = add_user("b", "ben@school.org", "Ben Brown")
teacher, other, amy, ben = client(TEACHER), client(OTHER), client(AMY), client(BEN)

CLASS = teacher.post("/api/class", json={"name": "P4"}).get_json()["id"]
_db = P.SessionLocal()
for email in ("amy@school.org", "ben@school.org"):
    _db.add(accounts.Enrollment(class_id=CLASS, email=email, name=email))
_db.commit()
_db.close()
SLUG = teacher.post("/api/class/%d/new" % CLASS, json={"title": "Greeting"}).get_json()["slug"]
STARTER = {"app.py": "from flask import Flask\n", "notes.md": NOTES}
teacher.post("/api/assignment/%s" % SLUG, json={"title": "Greeting", "files": STARTER})
teacher.post("/api/assignment/%s/out-of" % SLUG, json={"out_of": 9})


def turn_in(c, files):
    draft = c.get("/a/" + SLUG).headers["Location"].rsplit("/", 1)[1]
    r = c.post("/api/submit", json={"draft": draft, "files": dict(files, **{"notes.md": NOTES})})
    return draft, r


DRAFTS = {}
DRAFTS[AMY], r1 = turn_in(amy, APPS["right"])
DRAFTS[BEN], r2 = turn_in(ben, APPS["wrong_text"])


def sub_of(uid):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Submission).filter_by(student_id=uid).first()
    finally:
        db.close()


check("both turned in", sub_of(AMY) is not None and sub_of(BEN) is not None,
      (r1.status_code, r2.status_code))

ALL_RIGHT = [{"label": x["label"], "ok": True, "detail": "", "points": x["points"]}
             for x in ran["right"]["results"]]
r = amy.post("/api/tests/self", json={"assignment": SLUG, "results": ALL_RIGHT})
check("a student's own check is kept", r.status_code == 200 and r.get_json()["earned"] == 9)
page = teacher.get("/teacher/" + SLUG).get_data(as_text=True)
check("  and counts for nothing: no grade from it", "Tests not checked" in page
      and "(their check 9 / 9)" in page)
check("  not on the class page either",
      "badge-grade" not in amy.get("/class/%d" % CLASS).get_data(as_text=True))

r = teacher.get("/api/assignment/%s/tests/work" % SLUG)
work = {w["student"]: w for w in r.get_json().get("work", [])}
check("the teacher fetches every file each student turned in, but the notes",
      set(work) == {AMY, BEN} and work[AMY]["files"].get("app.py") == RIGHT
      and work[AMY]["files"].get("templates/index.html") == INDEX
      and "notes.md" not in work[AMY]["files"], sorted(work.get(AMY, {}).get("files", {})))
check("  nobody else can", other.get("/api/assignment/%s/tests/work" % SLUG).status_code == 404
      and amy.get("/api/assignment/%s/tests/work" % SLUG).status_code == 403)

r = teacher.post("/api/assignment/%s/tests/verify" % SLUG, json={"student": AMY, "results": ALL_RIGHT})
check("the teacher's check counts: 9 / 9 is the total", r.status_code == 200
      and r.get_json()["total"] == "9", r.get_json())
BEN_LINES = ran["wrong_text"]["results"]
r = teacher.post("/api/assignment/%s/tests/verify" % SLUG,
                 json={"student": BEN, "results": BEN_LINES, "earned": 999})
check("the points come from the lines, not a sum the page sent",
      r.get_json()["earned"] == ran["wrong_text"]["earned"] < 9, r.get_json())
check("a student can't post a verified result",
      amy.post("/api/assignment/%s/tests/verify" % SLUG,
               json={"student": AMY, "results": ALL_RIGHT}).status_code == 403)
check("  nor another teacher",
      other.post("/api/assignment/%s/tests/verify" % SLUG,
                 json={"student": AMY, "results": ALL_RIGHT}).status_code == 404)

page = teacher.get("/teacher/" + SLUG).get_data(as_text=True)
check("the results page has Check all, and each student's tests",
      "tests-check-all" in page and "Tests 9 / 9" in page and "✗ GET / shows Welcome" in page)
check("  says how many tests the notes have, and loads Flask's runtime for them",
      "8 tests" in page and "9 points" in page and "flask.js" in page)
mine = amy.get("/my").get_data(as_text=True)
check("My work shows the grade with the tests in it",
      "Score: <strong>9 / 9</strong>" in mine and "9 from the questions and tests" in mine)
check("so does the class page",
      '<span class="badge badge-grade">9 / 9</span>' in amy.get("/class/%d" % CLASS).get_data(as_text=True))

time.sleep(1.1)
turn_in(amy, dict(APPS["right"], **{"app.py": RIGHT + "# more\n"}))
page = teacher.get("/teacher/" + SLUG).get_data(as_text=True)
check("work turned in again after the check is marked stale", "is-stale" in page and "⟳" in page)

teacher.post("/api/assignment/%s/xp-bonus" % SLUG, json={"xp": 25})
db = P.SessionLocal()
paid = {a.user_id for a in db.query(accounts.XpAward).filter(accounts.XpAward.source.like("bonus:%"))}
db.close()
check("full marks from the tests completes the quest", AMY in paid and BEN not in paid, paid)

helppage = client().get("/help/questions").get_data(as_text=True)
example = _html.unescape(re.search(r'id="tests-example">(.*?)</pre>', helppage, re.S).group(1))
bare = "\n".join(re.split(r"\s{3,}", ln)[0] for ln in example.split("\n"))
got, bad = autograde.parse(bare)
check("the help page's example is all tests", len(got) == 9 and not bad, (len(got), bad))

edit = teacher.get("/teacher/%s/edit" % SLUG).get_data(as_text=True)
check("the teacher's notes pane links to how to write tests",
      'help/questions#tests"' in edit and ">Tests</a>" in edit)

editor = amy.get("/p/" + DRAFTS[AMY]).get_data(as_text=True)
check("the editor has Check my work and loads autograde.js",
      'id="check"' in editor and "autograde.js" in editor)

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
