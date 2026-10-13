"""Saves reach the app even when they look like an attack to the firewall.

    python3 tools/test_pack.py

THE BUG

Render puts a firewall in front of the app. A teacher pasted a lesson's
notes — HTML in f-strings, Flask routes, `127.0.0.1:5000`, `${found}` — and
pressed Update assignment. The firewall refused the request before it reached
gunicorn, so the logs showed nothing; the editor got the firewall's page
where it expected JSON and said "Couldn't reach the server." Nothing saved.
Each part of the notes saved fine on its own, so no single pattern was to
blame and "avoid writing X" was never going to be the fix.

static/pack.js now sends every same-origin JSON body as
{"_packed": base64(utf-8 JSON)}, and app.py's PackedRequest unwraps it before
any route reads it.

WHAT IS CHECKED

  The real pack.js, run in node with a stubbed browser: which requests it
  wraps, which it leaves alone, and that the round trip is exact for text
  that is not ASCII.

  Its output, posted to the real update route: the notes that failed are
  saved and come back when the assignment is opened again. This is the one
  check that joins the two halves — each could pass alone with the other
  speaking a different format.

  Every page that can send a request loads pack.js. A page left out would
  fail exactly as silently as the original bug.

The firewall itself is not here and cannot be: what it blocks is Render's
business. What can be pinned is that the body it sees is base64.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "pack.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32

sys.path.insert(0, APP)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-62s %s" % ("ok" if ok else "FAIL", label, detail))


if not shutil.which("node"):
    sys.exit("node is needed to run pack.js; install it or skip this test")


# Notes in the shape of the ones that would not save: HTML inside Python
# strings, a template, a loopback address, a `${...}`, a pipe between links,
# and a character outside ASCII so the UTF-8 step is exercised.
NOTES = '''## ✏ Hello, Flask
```python
@app.route("/")
def home():
    return nav() + "<h1>Welcome to Game Vault</h1>"

if __name__ == "__main__":
    app.run(debug=True)
```
Visit http://127.0.0.1:5000/about after `pip install flask`.
print(f"<p>Price: ${found}</p>")
'<nav><a href="/">Home</a> | <a href="/about">About</a></nav>'
<h1>{{ game.title }}</h1>
'''


# ==========================================================================
# pack.js in node
# ==========================================================================
print("pack.js")

HARNESS = r"""
const fs = require("fs");
const sent = [];
globalThis.window = {
  location: { href: "https://flaskide.example/teacher/x/edit",
              origin: "https://flaskide.example" },
  fetch: function (input, init) { sent.push({ input, init: init || null });
                                  return Promise.resolve(); },
};
const src = fs.readFileSync(process.argv[2], "utf8");
eval(src);
eval(src);                       // loaded twice must not wrap twice
const cases = JSON.parse(process.argv[3]);
for (const c of cases) {
  if (c.headersClass) c.init.headers = new Headers(c.init.headers);
  window.fetch(c.input, c.init);
}
process.stdout.write(JSON.stringify(sent.map(s => ({
  input: s.input,
  body: s.init && typeof s.init.body === "string" ? s.init.body : null,
}))));
"""

harness = os.path.join(tempfile.mkdtemp(), "harness.js")
with open(harness, "w") as f:
    f.write(HARNESS)

# ensure_ascii=False, as JSON.stringify does: Python's default writes ✏ as
# ✏, which made this payload pure ASCII and let an encoder that mangled
# UTF-8 pass every check here. Watched happen.
payload = json.dumps({"files": {"app.py": "x = 1\n", "notes.md": NOTES},
                      "title": "Day 4 ✏"}, ensure_ascii=False)
assert not payload.isascii()
big = json.dumps({"files": {"app.py": "y" * 60000}})     # fits 64 KB, its base64 does not
JSON_H = {"Content-Type": "application/json"}
CASES = [
    {"input": "/api/assignment/abc", "init": {"method": "POST", "headers": JSON_H, "body": payload}},
    {"input": "https://flaskide.example/api/draft/d", "init": {"method": "POST", "headers": JSON_H, "body": payload}},
    {"input": "https://oauth2.googleapis.com/token", "init": {"method": "POST", "headers": JSON_H, "body": payload}},
    {"input": "/api/image", "init": {"method": "POST", "headers": {"Content-Type": "text/plain"}, "body": payload}},
    {"input": "/api/live/abc", "init": None},
    {"input": "/api/draft/d", "init": {"method": "POST", "headers": JSON_H, "body": big, "keepalive": True}},
    {"input": "/api/draft/d", "init": {"method": "POST", "headers": JSON_H, "body": payload, "keepalive": True}},
    {"input": "/api/quiz/answer", "init": {"method": "POST", "headers": {"content-type": "application/json; charset=utf-8"}, "body": payload}, "headersClass": True},
]
out = subprocess.run(["node", harness, os.path.join(APP, "static", "pack.js"),
                      json.dumps(CASES)], capture_output=True, text=True)
if out.returncode != 0:
    print(out.stderr)
    sys.exit("the node harness failed")
sent = json.loads(out.stdout)


def unpacked(body):
    try:
        outer = json.loads(body)
        if set(outer) != {"_packed"}:
            return None
        return base64.b64decode(outer["_packed"]).decode("utf-8")
    except Exception:
        return None


check("eight requests went out, each once", len(sent) == 8, len(sent))
check("a relative JSON save is packed, and unpacks to exactly what was sent",
      unpacked(sent[0]["body"]) == payload)
check("the packed body carries none of the notes as text",
      "<h1>" not in sent[0]["body"] and "127.0.0.1" not in sent[0]["body"])
check("an absolute same-origin address is packed too",
      unpacked(sent[1]["body"]) == payload)
check("another site's request is left alone", sent[2]["body"] == payload)
check("a body that is not JSON is left alone", sent[3]["body"] == payload)
check("a request with no body goes through untouched",
      sent[4]["input"] == "/api/live/abc" and sent[4]["body"] is None)
check("a closing-tab save that packing would push past 64 KB goes plain",
      sent[5]["body"] == big)
check("a closing-tab save that fits is packed",
      unpacked(sent[6]["body"]) == payload)
check("a Headers object, lower-case, with a charset, is still seen as JSON",
      unpacked(sent[7]["body"]) == payload)


# ==========================================================================
# The server, fed what pack.js produced
# ==========================================================================
print("\nthe server")

db = P.SessionLocal()
teacher = accounts.User(google_sub="t", email="teacher@school.org", name="T")
db.add(teacher)
db.commit()
TID = teacher.id
db.close()

c = P.app.test_client()
with c.session_transaction() as s:
    s["uid"] = TID
CID = c.post("/api/class", json={"name": "Web 2"}).get_json()["id"]
SLUG = c.post("/api/class/%d/new" % CID, json={"title": "Day 4"}).get_json()["url"].split("/")[2]


def files_of(slug):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Assignment).filter_by(slug=slug).one().file_map()
    finally:
        db.close()


r = c.post("/api/assignment/" + SLUG, data=sent[0]["body"],
           content_type="application/json")
check("pack.js's body is accepted by Update assignment",
      r.status_code == 200, r.status_code)
check("the notes are saved exactly", files_of(SLUG).get("notes.md") == NOTES)
check("the title, outside the files, came through too",
      (r.get_json() or {}).get("title") == "Day 4 ✏")
page = c.get("/teacher/%s/edit" % SLUG).get_data(as_text=True)
check("and they are there when the assignment is opened again",
      "Welcome to Game Vault" in page and "127.0.0.1:5000" in page)

r = c.post("/api/assignment/" + SLUG,
           json={"files": {"app.py": "plain = 1\n"}, "title": "Day 4"})
check("a plain JSON body still saves (a tab opened before the deploy)",
      r.status_code == 200 and files_of(SLUG) == {"app.py": "plain = 1\n"})

r = c.post("/api/assignment/" + SLUG, json={"_packed": "not base64 at all!"})
check("a packed body that will not decode is refused, not a crash",
      r.status_code == 400, r.status_code)
check("and saves nothing", files_of(SLUG) == {"app.py": "plain = 1\n"})

sneaky = {"_packed": base64.b64encode(b'{"files": {"app.py": "z"}}').decode(),
          "files": {"app.py": "plain = 2\n"}}
r = c.post("/api/assignment/" + SLUG, json=sneaky)
check("only a body that is _packed alone is unwrapped",
      r.status_code == 200 and files_of(SLUG) == {"app.py": "plain = 2\n"})

other = P.app.test_client()
r = other.post("/api/assignment/" + SLUG, data=sent[0]["body"],
               content_type="application/json")
check("unpacking skips no check: signed out is still refused",
      r.status_code == 403 and files_of(SLUG) == {"app.py": "plain = 2\n"},
      r.status_code)


# ==========================================================================
# Every page that can send anything loads it
# ==========================================================================
print("\nthe pages")

TEMPLATES = os.path.join(APP, "templates")
missing, late = [], []
for name in sorted(os.listdir(TEMPLATES)):
    if not name.endswith(".html") or name.startswith("_"):
        continue
    text = open(os.path.join(TEMPLATES, name)).read()
    included = "".join(open(os.path.join(TEMPLATES, inc)).read()
                       for inc in re.findall(r"include ['\"]([^'\"]+)['\"]", text))
    if "fetch(" not in text + included and "<script src" not in text:
        continue
    if "filename='pack.js'" not in text:
        missing.append(name)
        continue
    # Before every other script file, so none can keep the unwrapped fetch.
    first = re.search(r"<script src=[^>]*filename='([^']+)'", text)
    if first and first.group(1) != "pack.js":
        late.append(name)
check("every page that sends requests loads pack.js", not missing,
      ", ".join(missing))
check("and loads it before any other script file", not late, ", ".join(late))


bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
