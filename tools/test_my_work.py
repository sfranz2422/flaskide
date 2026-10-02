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

editor = student.get("/").get_data(as_text=True)
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

page = student.get("/").get_data(as_text=True)
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

page = stranger.get("/").get_data(as_text=True)
check("signed out: Sign in", "/login" in page and ">Sign in<" in page)
check("  and Share, since sign-in is optional", has_id(page, "share"))
check("  and Download is off the bar, in the share dialog",
      not has_id(page, "download") and has_id(page, "download-share"))
page = stranger.get("/a/%s" % hw).get_data(as_text=True)
check("signed out on an assignment link, Share is still the way in",
      has_id(page, "share") and not has_id(page, "turn-in"))

page = teacher.get("/").get_data(as_text=True)
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
      re.search(r"function autosave\(\) \{\s*if \(!draftSlug\) \{ keepQuietly\(\);",
                live_js) is not None)
check("  and Turn in does not wait for a Save that no longer exists",
      "if (!draftSlug || !canTurnIn) return;" not in live_js)

bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
