#!/usr/bin/env python3
"""The teacher's laser pointer in a live lesson (static/laser.js).

    python3 tools/test_laser.py

WHY THIS FILE EXISTS

The highlight went out with every push, but a yellow block is hard to see
from the back of a room, and there was no way at all to point at a word on a
slide. So the teacher holds Alt and points, and every student sees a red dot
on the same letter — on their own screen, whatever its size.

Two halves. The SERVER half pins the route and the poll:

  * only the lesson's own teacher can point, and not at an ended lesson;
  * a pointer is checked against LASER before it is stored, so nothing
    longer than its column (Postgres would refuse it) or shaped otherwise
    gets in;
  * pointers are kept in order by their own stamp, and pointing never moves
    `version` — or every student would download the whole file and notes
    several times a second;
  * a student whose file is current but whose pointer is not is answered
    with the pointer ALONE, a page from before the laser still gets its 304,
    and an ended lesson points at nothing.

The BROWSER half (tools/laser_browser.mjs) runs the real pages in a real
Chrome, teacher and students on screens of different sizes, and checks the
dot lands on the very letter pointed at — from the code, a slide, the
pop-out and a lesson — goes out on letting go, on reading ahead, and by
itself when the teacher's tab vanishes mid-point. It needs Chrome and node,
and says "skip" without Chrome rather than failing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(TMP, "laser.db")
os.environ["TEACHER_EMAILS"] = "teacher@example.org, other@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


def add_user(sub, email, name):
    db = P.SessionLocal()
    try:
        user = accounts.User(google_sub=sub, email=email, name=name)
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def client(uid=None):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


def row(code):
    db = P.SessionLocal()
    try:
        return db.query(accounts.LiveSession).filter_by(code=code).first()
    finally:
        db.close()


tid = add_user("t", "teacher@example.org", "Teach")
teacher = client(tid)
other = client(add_user("o", "other@example.org", "Other Teacher"))
student = client(add_user("s", "kid@example.org", "Kid"))
anyone = client()

CODE = ("for i in range(5):\n    print('hello', i)\n\n\n\n"
        "# I'll make a circle around THIS\n")
code = teacher.post("/api/live/start", json={"body": CODE, "filename": "app.py",
                                             "title": "Laser"}).get_json()["code"]
POINT = "/api/live/%s/point" % code
POLL = "/api/live/%s" % code

# --------------------------------------------------------------- who
print("Who may point")
check("the lesson's teacher can",
      teacher.post(POINT, json={"pointer": "c:1:6", "seq": 10}).status_code == 200)
for name, c in (("another teacher", other), ("a student", student), ("someone signed out", anyone)):
    r = c.post(POINT, json={"pointer": "c:0:0", "seq": 20})
    check("  %s cannot" % name, r.status_code == 403, r.status_code)
check("  and nothing they sent was kept", row(code).pointer == "c:1:6", row(code).pointer)

# --------------------------------------------------------------- what
print("What a pointer may be")
GOOD = ["c:0:0", "c:12:4", "c:5:2835:-120", "c:999999:99999999:-99999",
        "s:0::e500,500", "s:2:0.3.1:t17", "s:2:0.3.1:t17:85,-140", "s:1:4:e450,300",
        "s:9999:" + ".".join(["999"] * 12) + ":t999999:-99999,-99999", ""]
seq = 100
for p in GOOD:
    seq += 1
    r = teacher.post(POINT, json={"pointer": p, "seq": seq})
    check("  %-40s is kept" % (p or '"" (let go)'),
          r.status_code == 200 and row(code).pointer == p, r.status_code)
check("the longest there can be fits its column",
      len(GOOD[-2]) <= accounts.LiveSession.pointer.type.length, len(GOOD[-2]))
BAD = ["c:1", "x:1:2", "c:1:2:3:4", "c:1:2:--3", "s:1:0.1:t", "s:1:0.1:q4", "s:1:1000:t1",
       "s:1:0.1:t4:5", "s:1:0.1:e4,5:6,7",
       "s:1:" + ".".join(["1"] * 13) + ":t1", "c:1:2 ", "<b>", 7, None]
for p in BAD:
    seq += 1
    r = teacher.post(POINT, json={"pointer": p, "seq": seq})
    check("  %-40s is refused" % repr(p), r.status_code == 400, r.status_code)

# --------------------------------------------------------------- the path
print("The path to it")
PATH = "100@c:5:2835:-120;140@c:5:2900:-100;180@s:0:1:t4:20,30"
seq += 1
r = teacher.post(POINT, json={"pointer": "c:5:2900:-100", "path": PATH, "seq": seq})
check("a path of places, each with the teacher's clock, is kept",
      r.status_code == 200 and row(code).pointer_path == PATH, row(code).pointer_path)
for bad in ("100@c:1", "c:5:1:1", "100@", "x@c:1:2", "1234567890@c:1:2", 7,
            ";".join(["1@c:1:2"] * 21)):
    seq += 1
    r = teacher.post(POINT, json={"pointer": "c:1:2", "path": bad, "seq": seq})
    check("  %-40s is refused" % repr(bad)[:40], r.status_code == 400, r.status_code)
check("  and nothing refused was kept", row(code).pointer_path == PATH)
seq += 1
teacher.post(POINT, json={"pointer": "c:1:2", "seq": seq})
check("an editor from before paths sends none, and none is kept",
      row(code).pointer_path == "", row(code).pointer_path)
seq += 1
teacher.post(POINT, json={"pointer": "c:1:2", "path": PATH, "seq": seq})
seq += 1
teacher.post(POINT, json={"pointer": "", "path": PATH, "seq": seq})
check("letting go clears the path with the place",
      row(code).pointer == "" and row(code).pointer_path == "", row(code).pointer_path)

# --------------------------------------------------------------- order
print("In order, and apart from the file")
before = row(code).version
teacher.post(POINT, json={"pointer": "c:3:3", "seq": 5000})
r = teacher.post(POINT, json={"pointer": "", "seq": 4000}).get_json()
check("a late one is dropped, not stored over a newer one",
      row(code).pointer == "c:3:3" and r.get("stale") is True, (row(code).pointer, r))
check("pointing never moves the file's version", row(code).version == before,
      (before, row(code).version))

# --------------------------------------------------------------- the poll
print("What the class is answered")
full = anyone.get(POLL).get_json()
check("the full answer carries the pointer and its stamp",
      full.get("pointer") == "c:3:3" and full.get("pointer_seq") == 5000, full.get("pointer"))
v = full["version"]
r = anyone.get(POLL + "?v=%d&p=5000" % v)
check("file and pointer both current: 304", r.status_code == 304, r.status_code)
r = anyone.get(POLL + "?v=%d" % v)
check("a page from before the laser sends no p, and still gets its 304",
      r.status_code == 304, r.status_code)
teacher.post(POINT, json={"pointer": "s:0:1:t4", "path": "9@s:0:1:t4", "seq": 6000})
r = anyone.get(POLL + "?v=%d&p=5000" % v)
d = r.get_json() or {}
check("only the pointer moved: the pointer and its path, and nothing else",
      r.status_code == 200 and d.get("pointer_only") is True and d.get("pointer") == "s:0:1:t4"
      and d.get("pointer_path") == "9@s:0:1:t4"
      and d.get("pointer_seq") == 6000 and "body" not in d and "notes" not in d, d)
check("  and the full answer carries the path too",
      anyone.get(POLL).get_json().get("pointer_path") == "9@s:0:1:t4")
r = anyone.get(POLL + "?v=%d&p=6000" % v)
check("  and then 304 again", r.status_code == 304, r.status_code)
r = anyone.get(POLL + "?v=%d&p=zzz" % v)
check("  a p that is not a number is just behind",
      r.status_code == 200 and (r.get_json() or {}).get("pointer_only"), r.status_code)

teacher.post("/api/live/%s/stop" % code)
check("stopping puts the pointer out", row(code).pointer == "" and row(code).pointer_path == "",
      row(code).pointer)
r = teacher.post(POINT, json={"pointer": "c:0:0", "seq": 9000})
check("and an ended lesson cannot be pointed at", r.status_code == 409, r.status_code)
db = P.SessionLocal()
try:
    db.query(accounts.LiveSession).filter_by(code=code).update(
        {"pointer": "c:1:1", "pointer_path": "1@c:1:1"})
    db.commit()
finally:
    db.close()
ended = anyone.get(POLL).get_json()
check("an ended lesson points at nothing, whatever is left in its row",
      ended.get("ended") is True and ended.get("pointer") == ""
      and ended.get("pointer_path") == "", ended.get("pointer"))

# --------------------------------------------------------------- the pages
print("Every page that points or shows the dot loads laser.js")
for page in ("index.html", "live.html", "lesson.html", "lesson_teacher.html",
             "notes_present.html"):
    with open(os.path.join(ROOT, "templates", page), encoding="utf-8") as f:
        check("  " + page, "filename='laser.js'" in f.read())

# --------------------------------------------------------------- a browser
print("In a real browser")


def find_chrome():
    for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if os.path.exists(path):
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


chrome = find_chrome()
if chrome is None or shutil.which("node") is None:
    print("  skip  no Chrome (or no node) here — the dot's placement is not checked")
else:
    import logging
    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # a line per poll otherwise

    server = make_server("127.0.0.1", 0, P.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_port

    notes = ("# Loops\n\nA **for loop** repeats code once for each item in a list. "
             "Look at THIS word in the middle of a longer sentence that wraps.\n\n"
             "---\n\n## Second slide\n\nThe word *range* gives numbers counting up.\n")
    # FlaskIDE keeps everything in files: the code is app.py.
    draft = teacher.post("/api/draft", json={"files": {"app.py": CODE, "notes.md": notes},
                                             "title": "Laser"}).get_json()["slug"]
    live = teacher.post("/api/live/start", json={"body": CODE, "filename": "app.py",
                                                 "title": "Laser"}).get_json()["code"]
    lesson = teacher.post("/api/lesson", json={"title": "Laser lesson"}).get_json()
    # Its notes, written where they are now: its tutorial in the library (library.py).
    tut = teacher.get("/api/library").get_json()["items"][0]["slug"]
    teacher.post("/api/library/" + tut, json={
        "body": "# Photosynthesis\n\nPlants turn **sunlight** into food.\n\n---\n\n## Two\n\nMore.\n"})
    setup = os.path.join(TMP, "setup.json")
    with open(setup, "w") as f:
        json.dump({"cookie": P.app.session_interface.get_signing_serializer(P.app).dumps({"uid": tid}),
                   "draft": draft, "code": live, "lesson": lesson["url"]}, f)
    out = subprocess.run(["node", os.path.join(HERE, "laser_browser.mjs"), base, setup, chrome,
                          os.path.join(TMP, "chrome")],
                         cwd=ROOT, capture_output=True, text=True, timeout=240)
    lines = [ln for ln in out.stdout.splitlines() if ln[:5] in ("ok   ", "FAIL ")]
    for ln in lines:
        label, _, detail = ln[5:].partition("\t")
        check(label, ln.startswith("ok"), "" if ln.startswith("ok") else detail[:150])
    check("the browser run reported every check", len(lines) == 15,
          (len(lines), out.stderr.strip()[-200:]))
    server.shutdown()

failed = results.count(False)
print("%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                     len(results), failed))
sys.exit(1 if failed else 0)
