#!/usr/bin/env python3
"""A class's view-only link, for administrators (class_view in app.py).

    python3 tools/test_view_link.py

WHY THIS FILE EXISTS

An administrator needs to see a class as its students do, and open its
assignments, without being one of the class. The danger is not what they
see but what happens when they look: they are usually signed in here with
their school account, and the ordinary assignment link would make them a
draft, the automatic turn-in would hand it in, and they would turn up in the
teacher's results and the class's attendance. So this pins:

  * the teacher's class page shows a link, the same one each time, and New
    link replaces it, the old one then going nowhere;
  * the link shows what students see — no hidden or archived assignment,
    no live links, no grades — and links only to its own previews;
  * a preview of an assignment is read-only, and of a lesson has no Turn in;
    neither reaches a hidden, archived or other class's assignment;
  * the answer keys are out of both, as from every exit (CLAUDE.md);
  * opening all of it signed in as a student makes no draft, no submission,
    no answer and no attendance — and an idle signed-in visitor is not sent
    to sign in;
  * questions in a preview say they are view only, and cannot be answered.
"""
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "view.db")
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
    print("  %-4s %-64s %s" % ("ok" if condition else "FAIL", label, detail))


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


def set_notes(c, slug, text):
    """An assignment's notes, written where they are written now: its
    tutorial in the library (library.py), saved — and linked first, if it
    has none."""
    items = c.get("/api/library").get_json()["items"]
    mine = next((i for i in items if any(u["url"].rstrip("/").endswith("/" + slug) for u in i["uses"])), None)
    if mine is None:
        return c.post("/api/library", json={"body": text, "linkTo": slug})
    return c.post("/api/library/" + mine["slug"], json={"body": text})


def count(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).count()
    finally:
        db.close()


teacher = client(add_user("t", "teacher@school.org", "Teach"))
other = client(add_user("o", "other@school.org", "Other Teacher"))
admin_id = add_user("a", "principal@school.org", "The Principal")
admin = client(admin_id)                 # signed in, and not a teacher here
anyone = client()

C = teacher.post("/api/class", json={"name": "Intro — P4"}).get_json()["id"]
C2 = teacher.post("/api/class", json={"name": "Intro — P7"}).get_json()["id"]
NEW = "/api/class/%d/new" % C
NOTES = ("# Loops\n\nRead this.\n\n```quiz\nWhat is 2 + 2?\n- [ ] 3\n- [x] 4\n```\n\n"
         "```quiz\nName the loop.\nanswer: for\n```\n")
HELLO = teacher.post(NEW, json={"title": "Hello World"}).get_json()["slug"]
teacher.post("/api/assignment/%s" % HELLO, json={
    "title": "Hello World",
    # This app keeps its whole project in files, the starter included.
    "files": {"app.py": "print('starter')\n", "notes.md": NOTES}})
set_notes(teacher, HELLO, NOTES)   # the notes are the library's (library.py)
SECRET = teacher.post(NEW, json={"title": "Secret one"}).get_json()["slug"]
OLD = teacher.post(NEW, json={"title": "Old one"}).get_json()["slug"]
LESSON = teacher.post(NEW, json={"title": "Loops lesson", "kind": "lesson"}).get_json()["slug"]
set_notes(teacher, LESSON, NOTES)
ELSEWHERE = teacher.post("/api/class/%d/new" % C2, json={"title": "Period 7 only"}).get_json()["slug"]

db = P.SessionLocal()
try:
    a_secret = db.query(accounts.Assignment).filter_by(slug=SECRET).first()
    row = db.query(accounts.ClassItem).filter_by(assignment_id=a_secret.id).first()
    SECRET_ROW = row.id
finally:
    db.close()
teacher.post("/api/class/%d/item/%d" % (C, SECRET_ROW), json={"hidden": True})
teacher.post("/api/assignment/%s/archive" % OLD)

# --------------------------------------------------------------- the link
print("The link, on the teacher's class page")
page = teacher.get("/teacher/class/%d" % C).get_data(as_text=True)
m = re.search(r'id="view-url"[^>]*value="([^"]+)"', page)
URL = m.group(1) if m else ""
TOKEN = URL.rsplit("/view/", 1)[-1] if "/view/" in URL else ""
check("the class page shows a view-only link", bool(TOKEN), URL)
again = teacher.get("/teacher/class/%d" % C).get_data(as_text=True)
check("  the same one every time it is opened", ('value="%s"' % URL) in again)
p7 = teacher.get("/teacher/class/%d" % C2).get_data(as_text=True)
check("  and each class has its own", ('value="%s"' % URL) not in p7 and 'id="view-url"' in p7)
check("  long enough not to be guessed", len(TOKEN) >= 16, len(TOKEN))

VIEW = "/view/" + TOKEN
# --------------------------------------------------------------- the page
print("What it shows")
for who, c in (("someone signed out", anyone), ("an administrator signed in", admin)):
    r = c.get(VIEW)
    body = r.get_data(as_text=True)
    check("%s sees the class page" % who, r.status_code == 200 and "Intro — P4" in body,
          r.status_code)
    check("  marked as view only", "View only" in body)
    check("  with what students see", "Hello World" in body and "Loops lesson" in body)
    check("  and not what is hidden or archived",
          "Secret one" not in body and "Old one" not in body)
    check("  nor another class's", "Period 7 only" not in body)
    check("  every assignment opening as a preview, never the real link",
          ("/view/%s/a/%s" % (TOKEN, HELLO)) in body and ('href="/a/%s"' % HELLO) not in body
          and ("/view/%s/a/%s" % (TOKEN, LESSON)) in body, "")
    check("  and no live link", "/live/" not in body)
    check("  nor Sign out or My work", "Sign out" not in body and "My work" not in body)

# --------------------------------------------------------------- previews
print("An assignment through it")
r = admin.get("/view/%s/a/%s" % (TOKEN, HELLO))
body = r.get_data(as_text=True)
check("opens", r.status_code == 200, r.status_code)
check("  read-only, with the starter", "readonly: true" in body and "starter" in body)
check("  told it is view only, with a way back to the class",
      "View only" in body and ("href=\"%s\"" % VIEW) in body)
check("  its questions marked view only", "viewOnly: true" in body)
check("  no Turn in, no Save", 'id="turn-in"' not in body and 'id="save-project"' not in body)
check("THE ANSWER KEY IS NOT IN IT", "[x] 4" not in body and "answer: for" not in body
      and "What is 2 + 2?" in body, "")
r = admin.get("/view/%s/a/%s" % (TOKEN, LESSON))
body = r.get_data(as_text=True)
check("a lesson opens", r.status_code == 200 and "Loops lesson" in body, r.status_code)
check("  with no Turn in and no Sign in", 'id="lesson-turnin"' not in body
      and ">Sign in<" not in body)
check("  its questions marked view only", "viewOnly: true" in body)
check("THE LESSON'S ANSWER KEY IS NOT IN IT EITHER", "[x] 4" not in body
      and "answer: for" not in body and "What is 2 + 2?" in body)
for label, slug in (("a hidden", SECRET), ("an archived", OLD), ("another class's", ELSEWHERE)):
    r = anyone.get("/view/%s/a/%s" % (TOKEN, slug))
    check("%s assignment is not there" % label, r.status_code == 404, r.status_code)
check("nor one that does not exist",
      anyone.get("/view/%s/a/nothing" % TOKEN).status_code == 404)

# --------------------------------------------------------------- nothing kept
print("Looking leaves no trace")
check("no draft was made for the administrator", count(accounts.Draft, owner_id=admin_id) == 0,
      count(accounts.Draft, owner_id=admin_id))
check("  no submission", count(accounts.Submission, student_id=admin_id) == 0)
check("  no answer", count(accounts.QuizAnswer, student_id=admin_id) == 0)
check("  no attendance", count(accounts.Visit, user_id=admin_id) == 0)

with admin.session_transaction() as s:
    s["act"] = int(time.time()) - P.STUDENT_IDLE_SECONDS - 60
r = admin.get(VIEW, headers={"Accept": "text/html", "Sec-Fetch-Dest": "document"})
check("an administrator idle two hours is shown it, not sent to sign in",
      r.status_code == 200 and "Intro — P4" in r.get_data(as_text=True), r.status_code)

# The cards in the browser: notes.js says so instead of taking an answer.
with open(os.path.join(PYIDE, "static", "notes.js"), encoding="utf-8") as f:
    njs = f.read()
check("notes.js has a view-only answer for both kinds of question card",
      njs.count("if (quizCtx.viewOnly)") == 2, njs.count("if (quizCtx.viewOnly)"))
for name in ("app.js", "lesson.js"):
    with open(os.path.join(PYIDE, "static", name), encoding="utf-8") as f:
        check("  and %s tells it" % name, "viewOnly:" in f.read())

# --------------------------------------------------------------- new link
print("A new link")
check("only the class's teacher can make one",
      other.post("/api/class/%d/view-link" % C).status_code == 404
      and admin.post("/api/class/%d/view-link" % C).status_code in (403, 404)
      and anyone.post("/api/class/%d/view-link" % C).status_code in (302, 403))
r = teacher.post("/api/class/%d/view-link" % C)
NEWURL = (r.get_json() or {}).get("url", "")
NEWTOKEN = NEWURL.rsplit("/view/", 1)[-1]
check("the teacher gets one", r.status_code == 200 and NEWTOKEN and NEWTOKEN != TOKEN, NEWURL)
check("  which works", anyone.get("/view/" + NEWTOKEN).status_code == 200)
check("  and the old one goes nowhere — page and previews alike",
      anyone.get(VIEW).status_code == 404
      and anyone.get("/view/%s/a/%s" % (TOKEN, HELLO)).status_code == 404)
check("  and the class page shows the new one",
      ('value="%s"' % NEWURL) in teacher.get("/teacher/class/%d" % C).get_data(as_text=True))
check("a token that is no token is refused", anyone.get("/view/x").status_code == 404
      and anyone.get("/view/").status_code == 404)

failed = results.count(False)
print("%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                     len(results), failed))
sys.exit(1 if failed else 0)
