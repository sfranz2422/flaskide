#!/usr/bin/env python3
"""A student's My work page, and the one button each student gets. FlaskIDE.

    python3 tools/test_my_work.py

WHY THIS FILE EXISTS

Assignments and saved projects are both drafts underneath, and the window
that listed them showed every draft the same way. A student who pressed Save
and then Turn in on a live lesson saw what looked like two things — a saved
project and a turned-in one — when it was one row all along. And the toolbar
offered Save, Share and Turn in side by side, so which one hands work in was
a question every student had to answer.

So this pins:

  * /my lists an assignment ONCE, under Assignments, with where it stands,
    however the student came to it (handout link, live lesson, or both), and
    lists under Projects only what is not for an assignment;
  * work turned in stays listed after the working copy is deleted, because
    it is still the teacher's;
  * each kind of student gets one thing to press: Turn in on an assignment,
    Save otherwise, Sign in and Share when signed out;
  * a live lesson for an assignment has Turn in and no Save.
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FLASKIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "my.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, FLASKIDE)
import app as P                                              # noqa: E402  (FlaskIDE)
import accounts                                              # noqa: E402

# Sign-in has to look ON for the signed-out toolbar to be the real one. Set
# here rather than through GOOGLE_CLIENT_ID, which would make app.py import
# authlib — not needed for anything this file checks.
accounts.login_configured = lambda: True

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


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


def section(page, name):
    """The part of /my under one heading, up to the next."""
    start = page.find(">%s <" % name)
    if start == -1:
        return ""
    end = page.find("<h2>", start)
    return page[start:end if end != -1 else len(page)]


def has_id(page, ident):
    return ('id="%s"' % ident) in page


TEACHER = add_user("t1", "teacher@example.org", "Mr Franz")
STUDENT = add_user("s1", "kid@example.org", "A Student")
teacher = client(TEACHER)
student = client(STUDENT)
stranger = client()

hw = teacher.post("/api/assignment", json={
    "files": {"app.py": "# starter app"}, "title": "Loops homework"}).get_json()["slug"]
# A SQL assignment too: FlaskIDE has two kinds of project, and both are
# drafts of this one app, so both belong on the same page.
sql_hw = teacher.post("/api/assignment", json={
    "files": {"query.sql": "SELECT 1;", "schema.sql": "CREATE TABLE t (a);"},
    "title": "SQL homework"}).get_json()["slug"]


# ------------------------------------------------------------------ the page
print("\nThe My work page")

r = stranger.get("/my")
check("signed out, /my sends you to sign in",
      r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      r.status_code)

page = student.get("/my").get_data(as_text=True)
check("a new student's page says there is nothing yet",
      "None yet" in section(page, "Assignments")
      and "Nothing saved yet" in section(page, "Projects"))

student.get("/a/%s" % hw)                         # opening the handout link
page = student.get("/my").get_data(as_text=True)
check("an opened assignment is listed under Assignments",
      "Loops homework" in section(page, "Assignments"))
check("  as not turned in", "Not turned in" in section(page, "Assignments"))
check("  and NOT under Projects as well",
      "Loops homework" not in section(page, "Projects"),
      "the same draft listed twice is what made it look like two things")

# The live lesson writes into the same draft, so it is still one row.
code = teacher.post("/api/live/start",
                    json={"body": "x", "assignment": hw}).get_json()["code"]
kept = student.post("/api/live/%s/keep" % code, json={"code": "# mine"}).get_json()
page = student.get("/my").get_data(as_text=True)
check("saving from a live lesson for it still makes one row",
      section(page, "Assignments").count("Loops homework") == 1
      and "Loops homework" not in section(page, "Projects"))

db = P.SessionLocal()
draft = db.query(accounts.Draft).filter_by(owner_id=STUDENT).first()
db.close()
student.post("/api/submit", json={"draft": draft.slug, "files": kept["files"]})
page = student.get("/my").get_data(as_text=True)
mine = section(page, "Assignments")
check("turned in, the row says when", "Not turned in" not in mine
      and "turned-in" in mine)
snap = re.search(r'href="(/s/[^"]+)"[^>]*>\s*What I turned in', mine, re.S)
check("  and links to exactly what was handed in", snap is not None)
if snap:
    check("  which opens", student.get(snap.group(1)).status_code == 200)

student.post("/api/draft", json={"files": {"app.py": "# just for fun"},
                                 "title": "Doodle"})
page = student.get("/my").get_data(as_text=True)
check("a project of their own is under Projects",
      "Doodle" in section(page, "Projects"))
check("  and not under Assignments", "Doodle" not in section(page, "Assignments"))

student.get("/a/%s" % sql_hw)
student.post("/api/draft", json={"files": {"query.sql": "SELECT 2;"},
                                 "title": "Scratch query"})
page = student.get("/my").get_data(as_text=True)
row = re.search(r"SQL homework.*?</tr>", section(page, "Assignments"), re.S)
check("a SQL assignment is listed with the rest, marked SQL",
      row is not None and "SQL" in row.group(0).replace("SQL homework", ""))
row = re.search(r"Scratch query.*?</tr>", section(page, "Projects"), re.S)
check("  and so is a SQL project of their own",
      row is not None and "SQL" in row.group(0).replace("Scratch query", ""))
row = re.search(r"Doodle.*?</tr>", section(page, "Projects"), re.S)
check("  while a Flask one is not marked SQL",
      row is not None and "SQL" not in row.group(0))
db = P.SessionLocal()
sql_draft = (db.query(accounts.Draft)
               .filter_by(owner_id=STUDENT, title="Scratch query").first())
db.close()
check("  and Open takes a SQL project to its own editor page",
      'href="/p/%s"' % sql_draft.slug in page
      and student.get("/p/%s" % sql_draft.slug).status_code == 200)

student.delete("/api/draft/%s" % draft.slug)
page = student.get("/my").get_data(as_text=True)
check("work turned in stays listed after the copy is deleted",
      "Loops homework" in section(page, "Assignments")
      and "What I turned in" in section(page, "Assignments"))

editor = student.get("/new").get_data(as_text=True)
check("the account menu goes to /my", 'href="/my"' in editor)
check("  and the old projects window is gone",
      not has_id(editor, "projects-modal") and not has_id(editor, "my-projects"))


# --------------------------------------------------------- one button each
print("\nOne button each")

page = student.get("/a/%s" % hw, follow_redirects=True).get_data(as_text=True)
check("signed in on an assignment: Turn in",
      has_id(page, "turn-in"))
check("  and no Save or Share beside it",
      not has_id(page, "save-project") and not has_id(page, "share")
      and not has_id(page, "share-menu"))

page = student.get("/new").get_data(as_text=True)
check("signed in, a new project: Save", has_id(page, "save-project"))
check("  and no Share or Turn in on the bar",
      not has_id(page, "share") and not has_id(page, "turn-in"))
check("  Share is still there, in the account menu", has_id(page, "share-menu"))

db = P.SessionLocal()
doodle = db.query(accounts.Draft).filter_by(owner_id=STUDENT, title="Doodle").first()
db.close()
page = student.get("/p/%s" % doodle.slug).get_data(as_text=True)
check("signed in, a saved project: just the Saved state",
      has_id(page, "save-state") and not has_id(page, "share")
      and not has_id(page, "save-project") and not has_id(page, "turn-in"))

page = stranger.get("/new").get_data(as_text=True)
check("signed out: Sign in", "/login" in page and ">Sign in<" in page)
check("  and Share, since sign-in is optional", has_id(page, "share"))
check("  and Download is off the bar, in the share dialog",
      not has_id(page, "download") and has_id(page, "download-share"))
page = stranger.get("/a/%s" % hw).get_data(as_text=True)
check("signed out on an assignment link, Share is still the way in",
      has_id(page, "share") and not has_id(page, "turn-in"))

page = teacher.get("/new").get_data(as_text=True)
check("a teacher's bar is untouched: Share and Publish",
      has_id(page, "share") and has_id(page, "publish"))


# ------------------------------------------------------------- live lessons
print("\nLive lessons")

page = student.get("/live/%s" % code).get_data(as_text=True)
btn = re.search(r'<button id="live-turn-in"[^>]*>', page)
check("a lesson for an assignment shows Turn in from the start",
      btn is not None and " hidden" not in btn.group(0),
      btn.group(0) if btn else "missing")
check("  and no Save", not has_id(page, "live-save"))

teacher.post("/api/live/%s/stop" % code)        # a second Go live reuses an open one
plain = teacher.post("/api/live/start", json={"body": "y"}).get_json()["code"]
page = student.get("/live/%s" % plain).get_data(as_text=True)
check("a lesson with no assignment has Save",
      has_id(page, "live-save") and not has_id(page, "live-turn-in"))

live_js = open(os.path.join(FLASKIDE, "static", "live.js")).read()
check("an assignment lesson saves itself on the first keystroke",
      re.search(r"function autosave\(\) \{\s*(if \(stale\) return;\s*)?"
                r"if \(!draftSlug\) \{ keepQuietly\(\);",
                live_js) is not None)
check("  and Turn in does not wait for a Save that no longer exists",
      "if (!draftSlug || !canTurnIn) return;" not in live_js)


# ----------------------------------------------------------------- feedback
print("\nFeedback")

M = P


def the_submission():
    db = M.SessionLocal()
    try:
        item = db.query(accounts.Assignment).filter_by(slug=hw).first()
        return db.query(accounts.Submission).filter_by(
            assignment_id=item.id, student_id=STUDENT).first()
    finally:
        db.close()


sub = the_submission()
FB = "/api/assignment/%s/feedback" % hw
note = "Good loop.\n\n    for i in range(3):\nwould be shorter."

r = student.post(FB, json={"submission": sub.id, "feedback": "A+ from me"})
check("a student cannot write feedback", r.status_code == 403, r.status_code)
OTHER_T = add_user("t2", "teacher2@example.org", "Another Teacher")
os.environ["TEACHER_EMAILS"] = "teacher@example.org, teacher2@example.org"
r = client(OTHER_T).post(FB, json={"submission": sub.id, "feedback": "hi"})
check("  nor a teacher who did not set the assignment",
      r.status_code == 404, r.status_code)
os.environ["TEACHER_EMAILS"] = "teacher@example.org"
other_hw = teacher.post("/api/assignment", json={
    "files": {"app.py": "# x"}, "title": "Something else"}).get_json()["slug"]
r = teacher.post("/api/assignment/%s/feedback" % other_hw,
                 json={"submission": sub.id, "feedback": "hi"})
check("  nor on a submission to a different assignment",
      r.status_code == 404, r.status_code)

page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("the teacher's page has a feedback box under the student",
      'class="fb-row" data-sub="%d"' % sub.id in page and "fb-text" in page)

r = teacher.post(FB, json={"submission": sub.id, "feedback": note})
check("the teacher can save feedback", r.status_code == 200, r.status_code)
check("  and its line breaks are kept", the_submission().feedback == note,
      repr(the_submission().feedback))
r = teacher.post(FB, json={"submission": sub.id, "feedback": "x" * 5001})
check("  a whole program pasted in is refused", r.status_code == 413,
      r.status_code)
check("    and leaves the saved feedback alone", the_submission().feedback == note)

page = student.get("/my").get_data(as_text=True)
mine = section(page, "Assignments")
check("the student sees it on My work", "Good loop." in mine
      and "would be shorter." in mine)
check("  marked New the first time", "badge-new" in mine)
page = student.get("/my").get_data(as_text=True)
check("  and not the second", "badge-new" not in section(page, "Assignments")
      and "Good loop." in section(page, "Assignments"))
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("the teacher can see it has been seen", "· seen" in page)
check("  and the box shows what they wrote", "would be shorter." in page)

# Turning in again: the feedback stays, and both sides are told it is older.
student.get("/a/%s" % hw)
db = M.SessionLocal()
d = db.query(accounts.Draft).filter_by(owner_id=STUDENT,
                                       assignment_id=sub.assignment_id).first()
payload = {"draft": d.slug, "code": d.code or "x", "files": d.file_map()}
db.close()
r = student.post("/api/submit", json=payload)
check("the student turns in again", r.status_code == 200, r.get_data(as_text=True)[:80])
check("  and the feedback survives it", the_submission().feedback == note)
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("  the teacher's page says it was turned in again since",
      "Turned in again since your feedback" in page)
page = student.get("/my").get_data(as_text=True)
check("  and so does the student's",
      "turned it in again after this was written" in section(page, "Assignments"))

r = teacher.post(FB, json={"submission": sub.id, "feedback": "Better now."})
page = student.get("/my").get_data(as_text=True)
check("new feedback shows as New again", "badge-new" in section(page, "Assignments")
      and "Better now." in page)
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("  and no longer says turned in again since",
      "Turned in again since your feedback" not in page)

teacher.post(FB, json={"submission": sub.id, "feedback": "   "})
check("saving an empty box takes it back",
      the_submission().feedback == "" and the_submission().feedback_at is None)
page = student.get("/my").get_data(as_text=True)
check("  and the student's page shows none", "Feedback from your teacher" not in page)


# ------------------------------------------------------------------ scores
print("\nScores")

OUT = "/api/assignment/%s/out-of" % hw
check("a student cannot set the points",
      student.post(OUT, json={"out_of": 10}).status_code == 403)
os.environ["TEACHER_EMAILS"] = "teacher@example.org, teacher2@example.org"
check("  nor a teacher who did not set the assignment",
      client(OTHER_T).post(OUT, json={"out_of": 10}).status_code == 404)
os.environ["TEACHER_EMAILS"] = "teacher@example.org"
check("points that are not a whole number are refused",
      teacher.post(OUT, json={"out_of": "ten"}).status_code == 400)
check("  and so is zero", teacher.post(OUT, json={"out_of": 0}).status_code == 400)

page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("ungraded, there is no score box", 'class="field fb-score"' not in page)
r = teacher.post(OUT, json={"out_of": "10"})
check("the teacher sets it out of 10", r.status_code == 200
      and r.get_json()["out_of"] == 10, r.get_data(as_text=True)[:60])
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("  and a score box appears for each student, out of 10",
      'class="field fb-score"' in page and "/ 10" in page)

sub = the_submission()
r = teacher.post(FB, json={"submission": sub.id, "feedback": "", "score": "8"})
check("a score can be saved on its own, with no comment",
      r.status_code == 200 and the_submission().score == 8.0,
      r.get_data(as_text=True)[:80])
check("  and counts as feedback for 'turned in again since'",
      the_submission().feedback_at is not None)
page = student.get("/my").get_data(as_text=True)
mine = section(page, "Assignments")
check("the student sees it: Score 8 / 10", "8 / 10" in mine, mine[mine.find("Score"):][:60])
check("  marked New", "badge-new" in mine)

r = teacher.post(FB, json={"submission": sub.id, "feedback": "Nice", "score": "7.5"})
check("half marks are kept", the_submission().score == 7.5)
r = teacher.post(FB, json={"submission": sub.id, "feedback": "Nice", "score": "12"})
check("extra credit above the points is allowed", the_submission().score == 12.0)
for bad, why in (("abc", "not a number"), ("-1", "negative"), ("nan", "NaN")):
    r = teacher.post(FB, json={"submission": sub.id, "feedback": "Nice", "score": bad})
    check("a score that is %s is refused" % why,
          r.status_code == 400 and the_submission().score == 12.0, r.status_code)
r = teacher.post(FB, json={"submission": sub.id, "feedback": "Still nice"})
check("saving with no score key leaves the score alone",
      the_submission().score == 12.0 and the_submission().feedback == "Still nice")
r = teacher.post(FB, json={"submission": sub.id, "feedback": "Nice", "score": ""})
check("an empty score box takes the score back, and is not 0",
      the_submission().score is None)

db = P.SessionLocal()
it = db.query(accounts.Assignment).filter_by(slug=hw).first()
db.add(accounts.ClassroomPost(assignment_id=it.id, course_id="1", work_id="999"))
db.commit()
db.close()
r = teacher.post(OUT, json={"out_of": ""})
check("once posted to Classroom, the points cannot be cleared",
      r.status_code == 400, r.status_code)
db = P.SessionLocal()
db.query(accounts.ClassroomPost).delete()
db.commit()
db.close()
r = teacher.post(OUT, json={"out_of": ""})
check("  but can be before, and the score boxes go",
      r.status_code == 200
      and 'class="field fb-score"' not in teacher.get("/teacher/%s" % hw).get_data(as_text=True))


# ---------------------------------------------------- an earlier database
print("\nA database from before feedback")

# create_all() makes missing tables but never missing columns. A submissions
# table from the last deploy has none of the three, and without the
# LATER_COLUMNS entries every query that selects a Submission — the
# dashboard, My work, turning in — fails on the first request after deploy.
import sqlalchemy                                            # noqa: E402
old_db = os.path.join(tempfile.mkdtemp(), "old.db")
eng = sqlalchemy.create_engine("sqlite:///" + old_db)
with eng.begin() as c:
    c.execute(sqlalchemy.text(
        "CREATE TABLE submissions (id INTEGER PRIMARY KEY, assignment_id INTEGER "
        "NOT NULL, student_id INTEGER NOT NULL, snippet_slug VARCHAR(16) NOT NULL, "
        "submitted_at DATETIME NOT NULL, times_submitted INTEGER NOT NULL)"))
    c.execute(sqlalchemy.text(
        "INSERT INTO submissions VALUES (1, 1, 1, 'abc', '2026-09-01 10:00:00', 2)"))
    c.execute(sqlalchemy.text(
        "CREATE TABLE assignments (id INTEGER PRIMARY KEY, slug VARCHAR(16) NOT NULL, "
        "app VARCHAR(16) NOT NULL, teacher_id INTEGER NOT NULL, title VARCHAR(200) "
        "NOT NULL, code TEXT NOT NULL, files TEXT NOT NULL, created_at DATETIME "
        "NOT NULL, closed INTEGER NOT NULL, archived INTEGER NOT NULL)"))
    c.execute(sqlalchemy.text(
        "INSERT INTO assignments VALUES (1, 'old', 'pyide', 1, 'Old one', '', '{}', "
        "'2026-09-01 10:00:00', 0, 0)"))
accounts.create_all(eng)
cols = {c["name"] for c in sqlalchemy.inspect(eng).get_columns("submissions")}
acols = {c["name"] for c in sqlalchemy.inspect(eng).get_columns("assignments")}
check("an old assignments table gets the points and Classroom columns",
      {"out_of", "classroom_course_id", "classroom_course_name",
       "classroom_work_id", "classroom_url"} <= acols, sorted(acols))
with eng.connect() as c:
    _upd = c.execute(sqlalchemy.text(
        "SELECT updated_at FROM assignments WHERE slug = 'old'")).fetchall()
check("  and updated_at, empty on an old one so it sorts by when it was made",
      "updated_at" in acols and _upd == [(None,)], _upd)
with eng.begin() as c:
    arow = c.execute(sqlalchemy.text(
        "SELECT out_of, classroom_work_id, classroom_url FROM assignments")).fetchone()
check("  and an old one reads as ungraded and not posted",
      tuple(arow) == (None, "", ""), tuple(arow))
check("an old submissions table gets the feedback and score columns",
      {"feedback", "feedback_at", "feedback_seen", "score", "score_synced"} <= cols,
      sorted(cols))
with eng.begin() as c:
    row = c.execute(sqlalchemy.text(
        "SELECT feedback, feedback_at, feedback_seen, score, score_synced "
        "FROM submissions")).fetchone()
check("  and an old row reads as no feedback and no score, not as an error",
      tuple(row) == ("", None, 0, None, None), tuple(row))


# ------------------------------------------------------- choosing the account
print("\nSigning in")

# Read from the source: signing in needs authlib, which the tests do without.
# Without the prompt Google picks the browser's default account, which on a
# teacher's laptop is a personal Gmail; incognito was the only way round it.
check("sign-in always shows Google's account chooser",
      'authorize_redirect(target, prompt="select_account")'
      in open(os.path.join(HERE, "..", "app.py")).read())

bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
