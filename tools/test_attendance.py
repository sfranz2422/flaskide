#!/usr/bin/env python3
"""Two idle hours sign a student out; coming into a class is recorded.

    python3 tools/test_attendance.py

WHAT IS BEING GUARDED

  An open tab cannot keep a student signed in forever.
      Two hours with nothing but background polls and the session is
      emptied on the next request, whatever it is. A poll (a GET to /api/)
      must not count as working, or the live page's once-a-second poll
      would keep every forgotten tab alive — which is the bug.

  Working does count, and teachers are never signed out.
      A page load, a save or the page's beat moves the clock. A teacher's
      session is left alone: signing out ends their live lesson.

  The deploy does not sign out the room.
      A session from before this existed starts its clock, it is not
      treated as infinitely old.

  Attendance: a sitting per stretch of work, for the class's students.
      Opening the class's page, one of its assignments or its live lesson
      records the student; the same sitting goes on while they work, and a
      gap starts another. The teacher is never recorded, a beat cannot put
      a student on a class they never opened, and only the class's own
      teacher sees the page.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "attendance.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


def add(row):
    db = P.SessionLocal()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def client(uid=None, **extra):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
            s.update(extra)
    return c


def sess(c):
    with c.session_transaction() as s:
        return dict(s)


def visits(**by):
    db = P.SessionLocal()
    try:
        return (db.query(accounts.Visit).filter_by(**by)
                  .order_by(accounts.Visit.id).all())
    finally:
        db.close()


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="Ms T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="Mr O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy Google"))
BEN = add(accounts.User(google_sub="b", email="ben@school.org", name="Ben"))
CLASS = add(accounts.Course(app=P.APP_NAME, teacher_id=TEACHER, name="P4 Intro"))
add(accounts.Enrollment(class_id=CLASS, email="amy@school.org", name="Amy Roster"))
LOOPS = add(accounts.Assignment(slug="loops1", app=P.APP_NAME, teacher_id=TEACHER,
                                title="Loops", code="print(1)\n"))
add(accounts.ClassItem(class_id=CLASS, assignment_id=LOOPS))
LOOSE = add(accounts.Assignment(slug="loose1", app=P.APP_NAME, teacher_id=TEACHER,
                                title="In no class", code=""))
add(accounts.LiveSession(code="live01", app=P.APP_NAME, host_id=TEACHER,
                         title="Loops", assignment_id=LOOPS, version=1))

H = P.STUDENT_IDLE_SECONDS
now = int(time.time())

print("idle sign-out")

c = client(AMY, act=now - H - 5)
c.get("/api/my/projects")
check("two idle hours: the next request, even a poll, signs out",
      "uid" not in sess(c), sess(c))

c = client(AMY, act=now - H + 120)
c.get("/my")
check("under two hours: still signed in", sess(c).get("uid") == AMY)
check("…and a page load moves the clock", sess(c).get("act", 0) >= now)

c = client(AMY, act=now - 600)
c.get("/api/my/projects")
check("a GET to /api/ (a poll) does not move the clock",
      sess(c).get("act") == now - 600, sess(c).get("act"))
c.post("/api/alive", json={})
check("the page's beat does", sess(c).get("act", 0) >= now)

c = client(AMY, act=now - 30)
c.post("/api/alive", json={})
check("the clock is rewritten at most once a minute", sess(c).get("act") == now - 30)

c = client(AMY)
c.get("/api/my/projects")
check("a session from before this starts its clock, not signed out",
      sess(c).get("uid") == AMY and sess(c).get("act", 0) >= now, sess(c))

c = client(TEACHER, act=now - H * 5)
c.get("/teacher")
check("a teacher is never signed out", sess(c).get("uid") == TEACHER)

r = client(AMY, act=now).post("/api/alive", json={}).get_json()
check("/api/alive says signed in", r == {"signed_in": True}, r)
r = client(AMY, act=now - H - 5).post("/api/alive", json={}).get_json()
check("…and signed out once the time is up", r == {"signed_in": False}, r)

html = client(AMY).get("/my").get_data(as_text=True)
check("a student's page carries the Sign in again card", 'id="idle-out"' in html)
check("…which gives up before the server does",
      "(%d - 120) * 1000" % H in html)
html = client(TEACHER).get("/live/live01").get_data(as_text=True)
check("a teacher's page has no card", "live01" in html and 'id="idle-out"' not in html)
html = client().get("/a/loose1").get_data(as_text=True)
check("nor a signed-out student's", 'id="idle-out"' not in html)

print("attendance")

amy = client(AMY)
html = amy.get("/class/%d" % CLASS).get_data(as_text=True)
v = visits(class_id=CLASS, user_id=AMY)
check("opening the class's page starts a sitting", len(v) == 1, len(v))
check("…under the roster's name", v and v[0].name == "Amy Roster", v and v[0].name)
check("…and the page's beat carries the class", "var CLASS = %d;" % CLASS in html)

r = amy.get("/a/loops1")
amy.get(r.headers["Location"])
v = visits(class_id=CLASS, user_id=AMY)
check("an assignment in the class adds to the same sitting",
      len(v) == 1 and v[0].places.split("\n") == ["Class page", "Loops"],
      v and v[0].places)

amy.get("/live/live01")
v = visits(class_id=CLASS, user_id=AMY)
check("its live lesson too, marked live",
      len(v) == 1 and v[0].places.split("\n")[-1] == "Loops (live)", v and v[0].places)

db = P.SessionLocal()
try:
    old = accounts.now() - P.timedelta(minutes=accounts.VISIT_GAP_MINUTES + 1)
    db.query(accounts.Visit).update({"last_at": old})
    db.commit()
finally:
    db.close()
amy.get("/class/%d" % CLASS)
check("a gap of more than %d minutes starts a new sitting" % accounts.VISIT_GAP_MINUTES,
      len(visits(class_id=CLASS, user_id=AMY)) == 2)

before = visits(class_id=CLASS, user_id=AMY)[-1].last_at
time.sleep(0.01)
client(AMY).post("/api/alive", json={"class": CLASS})
after = visits(class_id=CLASS, user_id=AMY)[-1].last_at
check("the beat keeps the sitting going", after > before, (before, after))

ben = client(BEN)
ben.post("/api/alive", json={"class": CLASS})
check("a beat cannot start a sitting in a class never opened",
      not visits(class_id=CLASS, user_id=BEN))
r = ben.get("/a/loops1")
ben.get(r.headers["Location"])
v = visits(class_id=CLASS, user_id=BEN)
check("a student off the roster who opens its work is recorded",
      len(v) == 1 and v[0].name == "Ben", [(x.name, x.places) for x in v])

client(TEACHER).get("/class/%d" % CLASS)
client(TEACHER).get("/live/live01")
check("the teacher is never recorded", not visits(user_id=TEACHER))

r = client(AMY).get("/a/loose1")
client(AMY).get(r.headers["Location"])
check("an assignment in no class records nothing",
      len(visits(user_id=AMY)) == 2
      and not any("In no class" in v.places for v in visits(user_id=AMY)))

page = client(TEACHER).get("/teacher/class/%d/attendance" % CLASS)
html = page.get_data(as_text=True)
check("the class's teacher sees the page", page.status_code == 200, page.status_code)
check("…with the sittings and the roster in it",
      "amy@school.org" in html and "Amy Roster" in html and "Loops (live)" in html)
check("…linked from the class's page",
      "/teacher/class/%d/attendance" % CLASS in
      client(TEACHER).get("/teacher/class/%d" % CLASS).get_data(as_text=True))
check("another teacher does not",
      client(OTHER).get("/teacher/class/%d/attendance" % CLASS).status_code == 404)
check("nor a student",
      client(AMY).get("/teacher/class/%d/attendance" % CLASS).status_code == 404)
check("?days=all works",
      client(TEACHER).get("/teacher/class/%d/attendance?days=all" % CLASS).status_code == 200)

print("the page's half (_idle.html, run in node)")

if not shutil.which("node"):
    sys.exit("node is needed to run _idle.html's script; brew install node")

# The script exactly as a student's page gets it, so the numbers in it are
# the ones the server rendered.
page = client(AMY).get("/class/%d" % CLASS).get_data(as_text=True)
script = re.search(r'<div id="idle-out".*?<script>(.*?)</script>', page, re.S).group(1)

HARNESS = r"""
const script = require("fs").readFileSync(0, "utf8");
let clock = 1e12, ticks = [], listeners = {}, sent = [], reply = {signed_in: true};
const el = (id) => ({ id, hidden: true, focused: false, focus() { this.focused = true; },
                      contains(t) { return t === button || t === this; },
                      addEventListener(type, fn) { this["on" + type] = fn; } });
const box = el("idle-out"), button = el("idle-out-go");
global.document = { hidden: false, addEventListener() {},
                    getElementById: (id) => id === "idle-out" ? box : id === "idle-out-go" ? button : null };
global.window = { addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); } };
global.location = { pathname: "/p/abc", search: "?x=1", href: "" };
global.setInterval = (fn) => ticks.push(fn);
global.fetch = (url, opts) => { sent.push([url, JSON.parse(opts.body)]);
  return Promise.resolve({ json: () => Promise.resolve(reply) }); };
Date.now = () => clock;
eval(script);

function fire(type, target) {
  const e = { target: target || {}, stopped: false, prevented: false,
              stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; } };
  (listeners[type] || []).forEach((fn) => fn(e));
  return e;
}
const out = {};
const MIN = 60 * 1000;
let e = fire("keydown");
out.typing_at_once = { beats: sent.length, blocked: e.prevented || e.stopped, shown: !box.hidden };
clock += 6 * MIN;
e = fire("keydown");
out.after_six_min = { beats: sent.length, body: sent[0] && sent[0][1], url: sent[0] && sent[0][0],
                      blocked: e.prevented || e.stopped };
clock += 3 * MIN;
fire("pointerdown");
out.three_min_later = { beats: sent.length };
const LIMIT = %d * 1000;
clock += LIMIT - 3 * MIN - 1000;      // just short of LIMIT since the beat
ticks.forEach((t) => t());
out.just_before = { shown: !box.hidden };
clock += 2000;
ticks.forEach((t) => t());
out.timer = { shown: !box.hidden, focused: button.focused };
e = fire("keydown");
out.key_after = { blocked: e.prevented && e.stopped };
e = fire("pointerdown", button);
out.own_button = { blocked: e.prevented || e.stopped };
button.onclick();
out.href = location.href;
console.log(JSON.stringify(out));
"""

def run_idle(js):
    harness = os.path.join(tempfile.mkdtemp(), "idle.js")
    with open(harness, "w") as f:
        f.write(js)
    proc = subprocess.run(["node", harness], input=script, capture_output=True, text=True)
    if proc.returncode:
        print(proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])

o = run_idle(HARNESS % (H - 120))
check("typing straight after load: no beat, nothing blocked",
      o["typing_at_once"] == {"beats": 0, "blocked": False, "shown": False}, o["typing_at_once"])
check("after five minutes a key sends one beat, with the class",
      o["after_six_min"]["beats"] == 1 and o["after_six_min"]["url"] == "/api/alive"
      and o["after_six_min"]["body"] == {"class": CLASS} and not o["after_six_min"]["blocked"],
      o["after_six_min"])
check("…and not another until five more", o["three_min_later"]["beats"] == 1)
check("a tab left open shows the card by itself, on time",
      not o["just_before"]["shown"] and o["timer"]["shown"] and o["timer"]["focused"],
      (o["just_before"], o["timer"]))
check("then a key is swallowed, never reaching the editor", o["key_after"]["blocked"])
check("…but the card's own button still works", not o["own_button"]["blocked"])
check("Sign in again signs out, then signs in back to this page",
      o["href"] == "/logout?next=" + "%2Flogin%3Fnext%3D%252Fp%252Fabc%253Fx%253D1", o["href"])

# Signed out some other way (another tab, the server's clock): the first
# beat to hear about it shows the card, long before the page's own time.
o = run_idle(HARNESS.split("const out = {};")[0] % () + """
reply = {signed_in: false};
clock += 6 * 60 * 1000;
fire("keydown");
const before = !box.hidden;
setTimeout(() => console.log(JSON.stringify({ before, after: !box.hidden })), 0);
""")
check("a beat answered signed out shows the card",
      o == {"before": False, "after": True}, o)

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
