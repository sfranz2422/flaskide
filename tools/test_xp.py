#!/usr/bin/env python3
"""XP, levels, badges, tokens, leaderboards and avatars (xp.py; "XP" in app.py).

    python3 tools/test_xp.py

WHY THIS FILE EXISTS

XP is points students compete over, so every way of earning it is a way of
earning it twice, and every place it is shown is a place a student's name
is shown to the class. This pins:

  * a question pays XP_PER_POINT per point, part for part right, once — a
    second answer, a wrong one and the teacher's practice pay nothing;
  * answering every question pays once, and only when it is every one;
  * the full-marks bonus pays once, from a score, and to those already at
    full marks when it is set;
  * a run pays only after RUN_EVERY_SECONDS of WORKING time, only when the
    code changed, never twice in RUN_EVERY_SECONDS, and never a teacher —
    and the working time counts at most one step per gap;
  * a teacher gives and takes XP only to their own class's students, and
    Use takes one token and never goes below none;
  * a leaderboard has only its class, first name and last initial, never an
    email, in order, equal XP an equal place, and nobody who hid;
  * the home page shows it all; an avatar is a picture on xp.AVATARS,
    unlocked, with its file — and avatar.js turns nothing else into markup
    (needs node).
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

DB = os.path.join(tempfile.mkdtemp(), "xp.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402
import quiz                                                  # noqa: E402
import xp                                                    # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-64s %s" % ("ok" if condition else "FAIL", label, detail))


def add(row):
    db = P.SessionLocal()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def add_user(sub, email, name, first="", last=""):
    return add(accounts.User(google_sub=sub, email=email, name=name,
                             first_name=first, last_name=last))


def client(uid=None, **session):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
            s.update(session)
    return c


def total(uid):
    db = P.SessionLocal()
    try:
        return xp.total(db, uid)
    finally:
        db.close()


def awards(uid, prefix=""):
    db = P.SessionLocal()
    try:
        return [a.source for a in db.query(accounts.XpAward).filter_by(user_id=uid)
                if a.source.startswith(prefix)]
    finally:
        db.close()


def age_awards(uid, seconds):
    """Move a student's awards into the past, as if time had gone by. A
    run's source is the minute it was paid in, so that moves too — or the
    next run, in the same real minute, would collide with it."""
    db = P.SessionLocal()
    try:
        for a in db.query(accounts.XpAward).filter_by(user_id=uid):
            a.created_at = a.created_at - P.timedelta(seconds=seconds)
            if a.source.startswith("run:"):
                a.source = "run:%d" % (int(a.source[4:]) - seconds // 60 - 1)
        db.commit()
    finally:
        db.close()


NOTES = """# Loops

```quiz
What does len("hello") return?
- [ ] 4
- [x] 5
points: 2
```

```quiz
Fill in: for i in [[range]](3): print([[i]])
type: blank
points: 2
```

```quiz
Why do loops matter?
type: long
points: 3
```
"""

KEYS = quiz.keys(NOTES)
MC, BLANK, LONG = (KEYS + [{}, {}, {}])[:3]
check("the notes have three questions", len(KEYS) == 3, len(KEYS))

# ----------------------------------------------------------------- the rules
print("\nThe rules")

check("level 1 at 0 XP, 2 at 100, still 2 at 249, 3 at 250",
      [xp.level_of(n) for n in (0, 99, 100, 249, 250)] == [1, 1, 2, 2, 3])
check("  and on past the end of the list",
      xp.level_of(xp.LEVEL_STARTS[-1] + xp.LEVEL_STEP_AFTER) == len(xp.LEVEL_STARTS) + 1)
s = xp.summary(2 * xp.TOKEN_EVERY + 40, tokens_used=1)
check("a summary: tokens earned less used, badges by XP",
      s["tokens_earned"] == 2 and s["tokens"] == 1
      and [b["have"] for b in s["badges"]] == [x <= 2 * xp.TOKEN_EVERY + 40 for x, _, _, _ in xp.BADGES]
      and any(b["have"] for b in s["badges"]) and not all(b["have"] for b in s["badges"]),
      s["tokens"])
check("a token costs 1000 XP, as the teacher set it", xp.TOKEN_EVERY == 1000)
check("  one XP short of a token is no token",
      xp.summary(xp.TOKEN_EVERY - 1)["tokens"] == 0 and xp.summary(xp.TOKEN_EVERY)["tokens"] == 1)
check("  progress through the level, 0 to 100",
      xp.summary(175)["progress"] == 50, xp.summary(175)["progress"])
check("a name on the board is the first name and last initial",
      xp.board_name(accounts.User(name="Mary Ann Smith", first_name="Mary Ann",
                                  last_name="Smith", email="m@x")) == "Mary Ann S."
      and xp.board_name(accounts.User(name="Ana Cruz", email="a@x")) == "Ana C."
      and xp.board_name(accounts.User(name="", email="z@x")) == "Student")

# ------------------------------------------------------------------- people
TEACHER = add_user("t1", "teacher@school.org", "Mr Franz")
OTHER = add_user("t2", "other@school.org", "Ms Other")
AMY = add_user("s1", "amy@school.org", "Amy Adams", "Amy", "Adams")
BEN = add_user("s2", "Ben@School.org", "Ben Brown", "Ben", "Brown")
CAL = add_user("s3", "cal@school.org", "Cal Cole", "Cal", "Cole")
OUT = add_user("s4", "out@school.org", "Out Sider", "Out", "Sider")
teacher, other = client(TEACHER), client(OTHER)
amy, ben, cal, out = client(AMY), client(BEN), client(CAL), client(OUT)

CLASS = teacher.post("/api/class", json={"name": "P4 Intro"}).get_json()["id"]
for email, name in (("amy@school.org", "Amy Adams"), ("ben@school.org", "Ben Brown"),
                    ("cal@school.org", "Cal Cole"), ("dee@school.org", "Dee Never")):
    add(accounts.Enrollment(class_id=CLASS, email=email, name=name))

# The same file runs in all three editors (like xp.py), and each keeps an
# assignment's program its own way: PyIDE in `code`, the others in a file.
ENTRY = {"pyide": None, "webide": "index.html", "flaskide": "app.py"}[P.APP_NAME]


def starter(notes):
    if ENTRY is None:
        return {"code": "print('hi')\n", "files": {"notes.md": notes}}
    return {"files": {ENTRY: "<h1>Hi</h1>\n" if ENTRY.endswith(".html")
                      else "from flask import Flask\n", "notes.md": notes}}


SLUG = teacher.post("/api/class/%d/new" % CLASS, json={"title": "Loops"}).get_json()["slug"]
teacher.post("/api/assignment/%s" % SLUG, json=dict(starter(NOTES), title="Loops"))


def answer(c, qid, response):
    r = c.post("/api/quiz/answer", json={"assignment": SLUG, "question": qid,
                                         "response": response})
    return r.status_code, r.get_json() or {}


# ------------------------------------------------------------------ questions
print("\nQuestions")

st, d = answer(amy, MC["qid"], "5")
check("a right answer worth 2 points pays 20 XP", st == 200 and d.get("xp") == 20
      and total(AMY) == 20, (st, d.get("xp"), total(AMY)))
st, d = answer(amy, MC["qid"], "4")
check("  answering it again pays nothing", d.get("xp", 0) == 0 and total(AMY) == 20,
      total(AMY))
st, d = answer(ben, MC["qid"], "4")
check("a wrong answer pays nothing", d.get("xp", 0) == 0 and total(BEN) == 0
      and not awards(BEN), awards(BEN))
st, d = answer(amy, BLANK["qid"], json.dumps(["range", "x"]))
check("half of a blank question pays half its XP", d.get("xp") == 10
      and total(AMY) == 30, (d.get("xp"), total(AMY)))
check("  and nothing for answering them all yet", not awards(AMY, "all:"))
st, d = answer(amy, LONG["qid"], "<p>Because they repeat.</p>")
check("a long response pays nothing itself, but finishing the set pays %d"
      % xp.ALL_ANSWERED_XP, d.get("xp") == xp.ALL_ANSWERED_XP
      and awards(AMY, "all:") and total(AMY) == 30 + xp.ALL_ANSWERED_XP,
      (d.get("xp"), total(AMY)))
r = teacher.post("/api/quiz/answer", json={"assignment": SLUG, "question": MC["qid"],
                                           "response": "5"}).get_json()
check("the teacher's practice answer pays nothing", not awards(TEACHER)
      and r.get("practice"), awards(TEACHER))

# ------------------------------------------------------------ full marks
print("\nThe full-marks bonus")

r = teacher.post("/api/assignment/%s/out-of" % SLUG, json={"out_of": 10})
check("the assignment is out of 10", r.status_code == 200, r.status_code)


def sub_of(uid):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Submission).filter_by(student_id=uid).first().id
    finally:
        db.close()


def score(uid, value):
    return teacher.post("/api/assignment/%s/feedback" % SLUG, json={
        "submission": sub_of(uid), "feedback": "", "score": value})


score(AMY, 7)          # 7 + 3 from the questions = 10, full marks — but no bonus yet
check("full marks with no bonus set pays nothing", not awards(AMY, "bonus:"))
r = teacher.post("/api/assignment/%s/xp-bonus" % SLUG, json={"xp": 50}).get_json()
check("setting a bonus pays those already at full marks",
      r.get("paid") == 1 and awards(AMY, "bonus:"), r)
check("  and not those below it", not awards(BEN, "bonus:"))
score(BEN, 9)          # 9 + 0 = 9
check("a score short of full marks pays nothing", not awards(BEN, "bonus:"))
score(BEN, 10)
check("a score reaching full marks pays the bonus", awards(BEN, "bonus:")
      and total(BEN) == 50, total(BEN))
score(BEN, 9)
score(BEN, 10)
check("  once, however often it is reached", total(BEN) == 50, total(BEN))
check("someone else's assignment's bonus can't be set",
      other.post("/api/assignment/%s/xp-bonus" % SLUG, json={"xp": 5}).status_code == 404)
check("a bonus has to be a sensible number",
      teacher.post("/api/assignment/%s/xp-bonus" % SLUG, json={"xp": -5}).status_code == 400
      and teacher.post("/api/assignment/%s/xp-bonus" % SLUG, json={"xp": "x"}).status_code == 400)

# ------------------------------------------------------------------ running
print("\nRunning a program")

def run(uid, code, busy):
    c = client(uid, busy=busy, act=int(time.time()))
    return c.post("/api/xp/run", json={"code": code}).get_json(), c


d, _ = run(CAL, "aaaa", xp.RUN_EVERY_SECONDS - 60)
check("not yet: less than 30 minutes of work", d.get("awarded") == 0
      and d.get("minutes") == 1 and total(CAL) == 0, d)
d, c = run(CAL, "aaaa", xp.RUN_EVERY_SECONDS)
check("30 minutes of work and a run pays %d" % xp.RUN_XP,
      d.get("awarded") == xp.RUN_XP and total(CAL) == xp.RUN_XP, d)
with c.session_transaction() as s:
    check("  and the working time starts again", s.get("busy") == 0, s.get("busy"))
# A minute on, so the minute in a run's source can't be what refuses this:
# the clock check alone has to.
db = P.SessionLocal()
for a in db.query(accounts.XpAward).filter_by(user_id=CAL):
    a.source = "run:%d" % (int(a.source[4:]) - 1)
db.commit()
db.close()
d, _ = run(CAL, "bbbb", xp.RUN_EVERY_SECONDS)
check("not twice in 30 minutes, even from another browser",
      d.get("awarded") == 0 and total(CAL) == xp.RUN_XP, d)
age_awards(CAL, xp.RUN_EVERY_SECONDS + 5)
d, _ = run(CAL, "aaaa", xp.RUN_EVERY_SECONDS)
check("30 minutes on, the same code again pays nothing",
      d.get("awarded") == 0 and d.get("same"), d)
d, _ = run(CAL, "cccc", xp.RUN_EVERY_SECONDS)
check("  changed code pays", d.get("awarded") == xp.RUN_XP
      and total(CAL) == 2 * xp.RUN_XP, d)
d, _ = run(TEACHER, "dddd", 10 ** 6)
check("a teacher earns nothing by running", d.get("awarded") == 0 and not awards(TEACHER))
check("signed out earns nothing",
      client().post("/api/xp/run", json={"code": "eeee"}).get_json().get("awarded") == 0)

# The working time itself: a request that counts as activity adds the time
# since the last one, but never more than one step.
c = client(CAL, act=int(time.time()) - 120, busy=0)
c.post("/api/alive", json={})
with c.session_transaction() as s:
    check("two minutes of work since the last sign adds two minutes",
          115 <= s.get("busy", 0) <= 130, s.get("busy"))
c = client(CAL, act=int(time.time()) - 3600, busy=0)
c.post("/api/alive", json={})
with c.session_transaction() as s:
    check("an hour away adds only one step", s.get("busy") == P.BUSY_STEP_SECONDS,
          s.get("busy"))
c = client(CAL, act=int(time.time()) - 120, busy=0)
c.get("/api/alive")
with c.session_transaction() as s:
    check("a poll (a GET to /api/) adds nothing", s.get("busy", 0) == 0, s.get("busy"))

# ------------------------------------------------------------- teacher's XP
print("\nGiving XP and using tokens")

# Cal to exactly two tokens' worth, whatever the runs above paid: most of it
# directly (a grant is capped at GRANT_LIMIT), the last 10 from the teacher.
TARGET = 2 * xp.TOKEN_EVERY
xp.award(P.SessionLocal(), CAL, "test:bulk", TARGET - 10 - total(CAL), "", "pyide")
r = teacher.post("/api/class/%d/xp" % CLASS, json={"student": CAL, "xp": 10,
                                                   "reason": "Helped a classmate"})
check("the teacher gives XP to a student in the class", r.status_code == 200
      and r.get_json()["xp"] == TARGET and r.get_json()["tokens"] == 2, r.get_json())
check("  and the student sees why",
      "Helped a classmate" in cal.get("/classes").get_data(as_text=True))
check("not to someone outside the class",
      teacher.post("/api/class/%d/xp" % CLASS, json={"student": OUT, "xp": 5})
      .status_code == 404 and total(OUT) == 0)
check("not from a teacher whose class it isn't",
      other.post("/api/class/%d/xp" % CLASS, json={"student": CAL, "xp": 5})
      .status_code in (403, 404))
_before = total(AMY)
check("not by a student",
      amy.post("/api/class/%d/xp" % CLASS, json={"student": AMY, "xp": 500})
      .status_code == 403 and total(AMY) == _before, total(AMY))
check("0 and too much are refused",
      teacher.post("/api/class/%d/xp" % CLASS, json={"student": CAL, "xp": 0}).status_code == 400
      and teacher.post("/api/class/%d/xp" % CLASS,
                       json={"student": CAL, "xp": xp.GRANT_LIMIT + 1}).status_code == 400)
r = teacher.post("/api/class/%d/xp" % CLASS, json={"student": CAL, "xp": -10,
                                                   "reason": "Oops"})
check("a negative grant takes XP back", r.status_code == 200 and total(CAL) == TARGET - 10,
      total(CAL))
teacher.post("/api/class/%d/xp" % CLASS, json={"student": CAL, "xp": 10})

page = teacher.get("/teacher/class/%d/xp" % CLASS).get_data(as_text=True)
check("the teacher's XP page lists the class, and who hasn't signed in",
      "Cal Cole" in page and "Dee Never" in page and "Hasn't signed in" in page
      and "Out Sider" not in page)


def use(c, uid):
    return c.post("/api/class/%d/tokens" % CLASS, json={"student": uid})


r = use(teacher, CAL)
check("Use takes one token", r.status_code == 200 and r.get_json()["tokens"] == 1,
      r.get_json())
check("  not for another teacher", use(other, CAL).status_code in (403, 404))
check("  not for a student", use(cal, CAL).status_code == 403)
use(teacher, CAL)
r = use(teacher, CAL)
check("  and never below none", r.status_code == 409, r.status_code)
db = P.SessionLocal()
check("  two used in all", db.get(accounts.User, CAL).tokens_used == 2)
db.close()

# ------------------------------------------------------------- leaderboard
print("\nThe leaderboard")

add(accounts.XpAward(user_id=BEN, source="test:tie", xp=total(AMY) - total(BEN),
                     reason="", app="pyide"))          # Ben level with Amy
page = amy.get("/class/%d" % CLASS).get_data(as_text=True)
board = page[page.find('id="leaderboard"'):]
order = [n for n in ("Cal C.", "Amy A.", "Ben B.") if n in board]
check("the board has the class's students, first name and last initial",
      order == ["Cal C.", "Amy A.", "Ben B."], order)
check("  ranked by XP, top first",
      board.find("Cal C.") < board.find("Amy A.") and board.find("Cal C.") < board.find("Ben B."))
check("  equal XP is an equal place",
      board.count('<span class="xp-place">2</span>') == 2, total(AMY) == total(BEN))
check("  no emails, no full names", "@school.org" not in board and "Adams" not in board
      and "Brown" not in board)
check("  nobody from outside the class", "Out S." not in board)
check("  and the reader is marked", '<li class="me' in board and "(you)" in board)

r = cal.post("/api/me/board", json={"hidden": True})
board = amy.get("/class/%d" % CLASS).get_data(as_text=True)
board = board[board.find('id="leaderboard"'):]
check("a student who hides leaves the board", "Cal C." not in board
      and '<span class="xp-place">1</span>' in board)
check("  and still earns", total(CAL) == TARGET)
page = cal.get("/class/%d" % CLASS).get_data(as_text=True)
check("  and their class page says they're hidden", "You&#39;re hidden" in page
      or "You're hidden" in page)
cal.post("/api/me/board", json={"hidden": False})

_token = re.search(r'/view/([A-Za-z0-9_-]+)"', teacher.get(
    "/teacher/class/%d" % CLASS).get_data(as_text=True)).group(1)
view = amy.get("/view/" + _token).get_data(as_text=True)
check("the view-only link shows no leaderboard", 'id="leaderboard"' not in view
      and "Amy A." not in view, len(view))

# ------------------------------------------------------------------ home
print("\nThe student's home page")

page = cal.get("/classes").get_data(as_text=True)
check("their level, XP and tokens", "Level %d" % xp.level_of(TARGET) in page
      and "%d XP" % TARGET in page and "<strong>0</strong> tokens" in page, "")
_have = [n for x, _, n, _ in xp.BADGES if x <= TARGET][-1]
_locked = [n for x, _, n, _ in xp.BADGES if x > TARGET][0]
check("  their badges, earned and not", ('class="have" title="%s' % _have) in page
      and ('class="locked" title="%s' % _locked) in page, (_have, _locked))
check("  and what a token costs", "One for every %d XP" % xp.TOKEN_EVERY in page)
board = page[page.find("xp-home-board"):]
check("  each class's leaderboard, top first, and their place in it",
      "You're #1 of 3" in page and "P4 Intro" in board
      and 0 < board.find("Cal C.") < board.find("Amy A.") < board.find("Ben B."))
check("  and their avatar, to change", "data-avatar=" in page and "/me/avatar" in page)
check("a teacher has no XP panel", "xp-card" not in teacher.get(
    "/classes", follow_redirects=True).get_data(as_text=True))

# ------------------------------------------------------------------ quests
print("\nQuests")

# Loops carries a 50 XP reward (set above), which Amy and Ben have had.
page = amy.get("/class/%d" % CLASS).get_data(as_text=True)
check("a quest someone completed says so on their class page", "✓ Quest complete" in page)
page = cal.get("/class/%d" % CLASS).get_data(as_text=True)
check("  and one they haven't shows its reward", "⚔️ Quest · +50 XP" in page)
check("an open quest is listed on their home page",
      "+50 XP" in cal.get("/classes").get_data(as_text=True).split("xp-quests")[-1])
check("  and a completed one isn't", "xp-quests" not in amy.get("/classes").get_data(as_text=True))
check("the teacher's class page marks the quest",
      "⚔️ quest +50" in teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True))
db = P.SessionLocal()
db.query(accounts.ClassItem).filter_by(class_id=CLASS).update({"hidden": 1})
db.commit()
check("a hidden quest isn't listed", "xp-quests" not in cal.get("/classes").get_data(as_text=True))
db.query(accounts.ClassItem).filter_by(class_id=CLASS).update({"hidden": 0})
db.commit()
db.close()

# ---------------------------------------------------------------- avatars
print("\nAvatars")

def saved_avatar(uid):
    db = P.SessionLocal()
    try:
        return db.get(accounts.User, uid).avatar
    finally:
        db.close()


# Amy is level 2: the mech (level 2) is hers, the wizard (level 3) is not.
r = amy.post("/api/me/avatar", json={"avatar": "mech"})
check("an unlocked picture is saved", r.status_code == 200
      and saved_avatar(AMY) == "mech", r.get_json())
r = amy.post("/api/me/avatar", json={"avatar": "wizard"})
check("a picture above their level is refused", r.status_code == 400
      and "level 3" in r.get_json()["error"] and saved_avatar(AMY) == "mech",
      r.get_json())
for bad in ("../../app.py", '"><script>', "", None, {"pic": "fox"}):
    r = amy.post("/api/me/avatar", json={"avatar": bad})
    check("  and one that isn't on the list: %r" % (bad,), r.status_code == 400
          and saved_avatar(AMY) == "mech")
db = P.SessionLocal()
u = db.get(accounts.User, AMY)
u.avatar = '{"hat": "crown", "skin": "s4"}'
check("an avatar from the old parts builder shows as the silhouette",
      xp.avatar_of(u) == xp.DEFAULT_AVATAR == "")
db.rollback()
db.close()
page = amy.get("/me/avatar").get_data(as_text=True)
check("the avatar page shows every picture, locked ones marked",
      all(('data-id="%s"' % i) in page for i in xp.AVATAR_IDS)
      and "Unlocks at level 3" in page)
check("the leaderboard shows the picture",
      'data-avatar="mech"' in amy.get("/class/%d" % CLASS).get_data(as_text=True))

# Every picture on the list has its file, and every file is on the list: a
# missing file is a broken image on every board that student is on.
folder = os.path.join(PYIDE, "static", "avatars")
files = sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".webp"))
check("every picture has its file", not set(xp.AVATAR_IDS) - set(files),
      sorted(set(xp.AVATAR_IDS) - set(files)))
check("  and every file is a picture on the list", not set(files) - set(xp.AVATAR_IDS),
      sorted(set(files) - set(xp.AVATAR_IDS)))
check("  each one small enough for a leaderboard of thirty",
      all(os.path.getsize(os.path.join(folder, f + ".webp")) < 80 * 1024 for f in files))

node = shutil.which("node")
if node:
    script = ("global.window = {}; require(%s);"
              "const A = window.PyIDEAvatar;"
              "process.stdout.write(JSON.stringify([A.html('fox'), A.html('\\\"><img onerror=x>'),"
              " A.html(''), A.html('../app')]));") % json.dumps(
        os.path.join(PYIDE, "static", "avatar.js"))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True)
    try:
        fox, evil, empty, up = json.loads(res.stdout)
    except ValueError:
        fox = evil = empty = up = ""
    check("node ran avatar.js", bool(fox), res.stderr[-300:])
    check("  a picture's id becomes its file", 'src="/static/avatars/fox.webp"' in fox)
    check("  an id that isn't one becomes the silhouette, never markup",
          evil.startswith("<svg") and "onerror" not in evil
          and up.startswith("<svg") and empty.startswith("<svg"), evil[:60])
else:
    check("node is available to run avatar.js", False, "brew install node")

# ------------------------------------------------- rewards and random events
print("\nRewards, penalties and random events")

ZED = add_user("s5", "zed@school.org", "Zed Zero", "Zed", "Zero")
add(accounts.Enrollment(class_id=CLASS, email="zed@school.org", name="Zed Zero"))
zed = client(ZED)
before = {u: total(u) for u in (AMY, BEN, CAL, ZED)}
r = teacher.post("/api/class/%d/xp" % CLASS, json={"students": [AMY, BEN], "xp": 10,
                                                   "reason": "Helped debug a teammate's code"})
check("a reward goes to every ticked student", r.status_code == 200
      and total(AMY) == before[AMY] + 10 and total(BEN) == before[BEN] + 10
      and total(CAL) == before[CAL], r.get_json())
r = teacher.post("/api/class/%d/xp" % CLASS, json={"students": [ZED, AMY], "xp": -5,
                                                   "reason": "Late to class"})
check("a penalty never takes anyone below 0: Zed has none, and is named",
      r.status_code == 200 and total(ZED) == 0 and total(AMY) == before[AMY] + 5
      and r.get_json()["skipped"] == ["Zed Z."], r.get_json())
xp.award(P.SessionLocal(), ZED, "test:three", 3, "", "pyide")
teacher.post("/api/class/%d/xp" % CLASS, json={"students": [ZED], "xp": -5, "reason": "Late"})
check("  a student on 3 XP loses 3, not 5", total(ZED) == 0, total(ZED))
check("someone from outside the class can't be ticked",
      teacher.post("/api/class/%d/xp" % CLASS, json={"students": [AMY, OUT], "xp": 5})
      .status_code == 404 and total(OUT) == 0)

import random                                                 # noqa: E402
EVENT = {e["id"]: e for e in xp.EVENTS}


def draw(event_id, seed=1):
    """Press Random event with the draw fixed to one event."""
    real_pick, real_rng = xp.pick_event, P._rng
    xp.pick_event = lambda rng: EVENT[event_id]
    P._rng = random.Random(seed)
    try:
        return teacher.post("/api/class/%d/event" % CLASS)
    finally:
        xp.pick_event, P._rng = real_pick, real_rng


def totals_now():
    return {u: total(u) for u in (AMY, BEN, CAL, ZED)}


was = totals_now()
r = draw("first-try")
now_ = totals_now()
check("an everyone event moves every signed-in student in the class",
      r.status_code == 200 and all(now_[u] == was[u] + 5 for u in was)
      and total(OUT) == 0, (was, now_))
ev = r.get_json()["event"]
check("  and says who, by first name and last initial",
      len(ev["hits"]) == 4 and {"Amy A.", "Ben B.", "Cal C.", "Zed Z."} ==
      {h["name"] for h in ev["hits"]}, ev["hits"])

was = totals_now()
draw("mentor")
now_ = totals_now()
low = min(was, key=lambda u: was[u])
check("the least-XP event finds the student with the least",
      now_[low] == was[low] + 15 and sum(now_.values()) == sum(was.values()) + 15,
      (low, was, now_))
was = totals_now()
draw("off-by-one")
now_ = totals_now()
top = max(was, key=lambda u: was[u])
check("the most-XP event finds the student with the most",
      now_[top] == was[top] - 10 and sum(now_.values()) == sum(was.values()) - 10)
was = totals_now()
draw("merge-conflict")
now_ = totals_now()
check("a some-students event moves exactly that many",
      sum(1 for u in was if now_[u] != was[u]) == 2, (was, now_))
was = totals_now()
draw("rubber-duck")
check("a one-student event moves one", sum(1 for u, v in totals_now().items()
                                          if v != was[u]) == 1)

# Zed back to 0, then everyone loses 5: Zed loses nothing and isn't a hit.
db = P.SessionLocal()
for a in db.query(accounts.XpAward).filter_by(user_id=ZED):
    db.delete(a)
db.commit()
db.close()
was = totals_now()
r = draw("prod-bug")
check("an everyone penalty takes nothing from a student with none",
      total(ZED) == 0 and all(totals_now()[u] == was[u] - 5 for u in (AMY, BEN, CAL))
      and "Zed Z." not in {h["name"] for h in r.get_json()["event"]["hits"]})
BUG = r.get_json()["event"]["id"]

page = teacher.get("/teacher/class/%d/xp" % CLASS).get_data(as_text=True)
check("the XP page lists the events, newest first, with Undo",
      page.find("Unexpected bug in production") < page.find("Rubber duck debugging")
      and "js-undo" in page)
check("  and the reasons to pick from", "Helped debug a teammate&#39;s code" in page
      or "Helped debug a teammate's code" in page)

cal.post("/api/me/board", json={"hidden": True})
page = amy.get("/class/%d" % CLASS).get_data(as_text=True)
check("the class page shows the latest event", "Unexpected bug in production" in page
      and "xp-latest-event" in page)
check("  naming a hidden student only as a classmate",
      "A classmate -5" in page and "Cal C." not in page.split('id="leaderboard"')[0])
cal.post("/api/me/board", json={"hidden": False})

was = totals_now()
r = teacher.post("/api/class/%d/event/%d/undo" % (CLASS, BUG))
check("Undo gives the event's XP back", r.status_code == 200
      and all(totals_now()[u] == was[u] + 5 for u in (AMY, BEN, CAL)), totals_now())
check("  and the class page stops showing it",
      "Unexpected bug in production" not in amy.get("/class/%d" % CLASS).get_data(as_text=True))
check("  and only that event's XP went", totals_now()[AMY] > 0 and awards(AMY, "event:"))

check("another teacher can't set off an event in this class",
      other.post("/api/class/%d/event" % CLASS).status_code in (403, 404))
check("  nor can a student", amy.post("/api/class/%d/event" % CLASS).status_code == 403)
check("  nor undo one", amy.post("/api/class/%d/event/%d/undo" % (CLASS, BUG)).status_code == 403
      and other.post("/api/class/%d/event/%d/undo" % (CLASS, BUG)).status_code in (403, 404))

rng = random.Random(4)
seen = {xp.pick_event(rng)["id"] for _ in range(2000)}
check("every event can be drawn", seen == set(xp.EVENT_IDS), sorted(set(xp.EVENT_IDS) - seen))

page = amy.get("/me/xp").get_data(as_text=True)
check("My XP lists every reason, rewards and penalties",
      "Helped debug a teammate" in page and "Late to class" in page
      and "Random event: It compiled on the first try!" in page
      and "Question in Loops" in page)
check("  and only their own", "Helped a classmate" not in page)
check("the home page links to it", "/me/xp" in amy.get("/classes").get_data(as_text=True))

# Six on the board, Zed last: his home page shows the top five, a gap, and
# his own row — the place he is, not only the places he isn't.
for i in (1, 2):
    uid = add_user("x%d" % i, "extra%d@school.org" % i, "Extra Student%d" % i, "Extra", "S%d" % i)
    add(accounts.Enrollment(class_id=CLASS, email="extra%d@school.org" % i, name="Extra %d" % i))
    xp.award(P.SessionLocal(), uid, "test:extra", 500, "", "pyide")
page = zed.get("/classes").get_data(as_text=True)
board = page[page.find("xp-home-board"):]
check("a student below the top five sees their own row under it",
      "xp-board-gap" in board and board.find("xp-board-gap") < board.find("Zed Z.")
      and "You're #6 of 6" in page, total(ZED))

# -------------------------------------------------------- all classes board
print("\nAll classes")

page = amy.get("/class/%d" % CLASS).get_data(as_text=True)
check("a teacher with one class has no all-classes board", 'id="all-classes"' not in page)
CLASS2 = teacher.post("/api/class", json={"name": "Programming 1"}).get_json()["id"]
add(accounts.Enrollment(class_id=CLASS2, email="out@school.org", name="Out Sider"))
add(accounts.Enrollment(class_id=CLASS2, email="amy@school.org", name="Amy Adams"))
OTHERS = other.post("/api/class", json={"name": "Someone else's"}).get_json()["id"]
STRANGER = add_user("s9", "far@school.org", "Far Away", "Far", "Away")
add(accounts.Enrollment(class_id=OTHERS, email="far@school.org", name="Far Away"))
add(accounts.Enrollment(class_id=OTHERS, email="amy@school.org", name="Amy Adams"))
page = amy.get("/class/%d" % CLASS).get_data(as_text=True)
board = page[page.find('id="leaderboard"'):page.find('id="all-classes"')]
every = page[page.find('id="all-classes"'):]
check("the class's own board has only its class", "Out S." not in board and "Amy A." in board)
check("  the all-classes board has every class of that teacher's",
      'id="all-classes"' in page and "Out S." in every and "Amy A." in every)
check("  and nobody from another teacher's class", "Far A." not in every)
check("  a student in two of the classes is on it once", every.count("Amy A.") == 1)
home = amy.get("/classes").get_data(as_text=True)
check("the home page has an all-classes board too, linked to the full one",
      "All classes" in home and "#all-classes" in home)
check("  named for the teacher when a student has two teachers",
      "All classes — Mr Franz" in home, "")

# ------------------------------------------------------------- own photos
print("\nStudents' own photos")

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 200


def upload(c, data=PNG):
    return c.post("/api/me/photo", data={"photo": (__import__("io").BytesIO(data), "p.png")},
                  content_type="multipart/form-data")


before_avatar = saved_avatar(BEN)
r = upload(ben)
check("a student uploads a photo", r.status_code == 200, r.get_json())
slug = r.get_json()["pending"].split(":")[1]
check("  it isn't their avatar yet", saved_avatar(BEN) == before_avatar)
check("  they can see it", ben.get("/photo/" + slug).status_code == 200)
check("  their teacher can", teacher.get("/photo/" + slug).status_code == 200)
check("  a classmate can't", amy.get("/photo/" + slug).status_code == 404)
check("  nor anyone signed out", client().get("/photo/" + slug).status_code == 404)
check("  nor a teacher who doesn't teach them", other.get("/photo/" + slug).status_code == 404)
check("  and it's not on any board", ("photo:" + slug) not in amy.get(
    "/class/%d" % CLASS).get_data(as_text=True))
page = teacher.get("/teacher/class/%d/xp" % CLASS).get_data(as_text=True)
check("the teacher's XP page has it to approve", "Pictures to approve" in page
      and "/photo/" + slug in page)
check("  and the class page says one is waiting",
      "1 to approve" in teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True))
check("not a picture is refused", upload(ben, b"<svg onload=alert(1)>").status_code == 400)
check("too big is refused", upload(ben, PNG + b"\0" * (P.PHOTO_MAX_BYTES + 1)).status_code == 413)
check("a teacher can't upload one", upload(teacher).status_code == 403)
check("a student can't choose a photo nobody approved",
      ben.post("/api/me/avatar", json={"avatar": "photo"}).status_code == 400)

db = P.SessionLocal()
PID = db.query(accounts.StudentPhoto).filter_by(slug=slug).first().id
db.close()
check("another teacher can't approve it",
      other.post("/api/class/%d/photo/%d/approve" % (CLASS, PID)).status_code in (403, 404))
check("  nor can a student", ben.post("/api/class/%d/photo/%d/approve" % (CLASS, PID)).status_code == 403)
check("  nor through a class of the teacher's the student isn't in",
      teacher.post("/api/class/%d/photo/%d/approve" % (CLASS2, PID)).status_code == 404
      and saved_avatar(BEN) == before_avatar)
r = teacher.post("/api/class/%d/photo/%d/approve" % (CLASS, PID))
check("approving makes it their avatar", r.status_code == 200
      and saved_avatar(BEN) == "photo:" + slug)
check("  on the board", ('data-avatar="photo:%s"' % slug) in amy.get(
    "/class/%d" % CLASS).get_data(as_text=True))
check("  and anyone can see it now", client().get("/photo/" + slug).status_code == 200)

r = upload(ben)
new_slug = r.get_json()["pending"].split(":")[1]
check("a second upload waits too, the approved one staying",
      saved_avatar(BEN) == "photo:" + slug and amy.get("/photo/" + new_slug).status_code == 404)
db = P.SessionLocal()
PID2 = db.query(accounts.StudentPhoto).filter_by(slug=new_slug).first().id
db.close()
teacher.post("/api/class/%d/photo/%d/reject" % (CLASS, PID2))
check("rejecting deletes it", ben.get("/photo/" + new_slug).status_code == 404
      and saved_avatar(BEN) == "photo:" + slug)
ben.post("/api/me/avatar", json={"avatar": "fox"})
r = ben.post("/api/me/avatar", json={"avatar": "photo"})
check("a student can go back to their approved photo", r.status_code == 200
      and saved_avatar(BEN) == "photo:" + slug)
db = P.SessionLocal()
u = db.get(accounts.User, BEN)
u.avatar = "photo:../../etc"
check("a malformed photo avatar is the silhouette", xp.avatar_of(u) == "")
db.rollback()
db.close()
if node:
    res = subprocess.run([node, "-e", "global.window={};require(%s);process.stdout.write("
                          "JSON.stringify([window.PyIDEAvatar.html('photo:abc1234'),"
                          "window.PyIDEAvatar.html('photo:../x')]))" % json.dumps(
                              os.path.join(PYIDE, "static", "avatar.js"))],
                         capture_output=True, text=True)
    good, bad = (json.loads(res.stdout) if res.stdout else ["", ""])
    check("avatar.js shows an approved photo from /photo/",
          'src="/photo/abc1234"' in good and bad.startswith("<svg"), res.stderr[-200:])

# --------------------------------------------------------------- database
print("\nAn older database")

for table, column in (("users", "avatar"), ("users", "board_hidden"),
                      ("users", "tokens_used"), ("assignments", "xp_bonus")):
    check("  %s.%s is added to an existing table" % (table, column),
          any(t == table and c == column for t, c, _ in accounts.LATER_COLUMNS))

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
