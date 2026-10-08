#!/usr/bin/env python3
"""The Skyward score file.

    python3 tools/test_skyward.py

WHY THIS FILE EXISTS

Skyward's Assignment Import ("Import Scores and Create Assignments") takes
seven columns and no header — last, first, assignment, due MMDDYYYY,
category, max score, score — and matches a student on the two names alone.
Everything that can go wrong with that goes wrong quietly, in a file the
teacher uploads to the school's gradebook:

  * a column out of order is a gradebook full of wrong numbers, or a
    preview of nothing but "Unable to find a matching student";
  * names are only kept apart from sign-in on, so a student who hasn't
    signed in since must come from the Classroom roster or be guessed —
    and a guess must be SAID, not slipped into the file;
  * another section's students in the file are rows Skyward refuses;
  * a total without the questions' points is a lower grade than Classroom
    was sent for the same work.

Google is never called: the sign-in token and the roster are both faked.
"""
import csv
import io
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "skyward.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


def add_user(sub, email, name, first="", last=""):
    db = P.SessionLocal()
    try:
        user = accounts.User(google_sub=sub, email=email, name=name,
                             first_name=first, last_name=last)
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


def user_row(uid):
    db = P.SessionLocal()
    try:
        return db.get(accounts.User, uid)
    finally:
        db.close()


def rows_of(text):
    return list(csv.reader(io.StringIO(text)))


# ------------------------------------------------------------- signing in
print("Signing in keeps first and last name apart")

token = {}
P.oauth = SimpleNamespace(google=SimpleNamespace(
    authorize_access_token=lambda: {"userinfo": dict(token)}))

token.update(sub="g-ana", email="ana@school.org", email_verified=True,
             name="Ana De La Cruz", given_name="Ana", family_name="De La Cruz")
client().get("/auth/callback")
db = P.SessionLocal()
ANA = db.query(accounts.User).filter_by(google_sub="g-ana").first().id
db.close()
check("a new student's first and last name are kept",
      (user_row(ANA).first_name, user_row(ANA).last_name) == ("Ana", "De La Cruz"),
      repr((user_row(ANA).first_name, user_row(ANA).last_name)))

# Someone from before names were kept, signing in again.
OLD = add_user("g-old", "old@school.org", "Sam Old")
token.clear()
token.update(sub="g-old", email="old@school.org", email_verified=True,
             name="Sam Old", given_name="Sam", family_name="Old")
client().get("/auth/callback")
check("  and an existing student gets them at their next sign-in",
      (user_row(OLD).first_name, user_row(OLD).last_name) == ("Sam", "Old"))

token.clear()
token.update(sub="g-old", email="old@school.org", email_verified=True, name="Sam Old")
client().get("/auth/callback")
check("  a sign-in that doesn't send them keeps what was there",
      (user_row(OLD).first_name, user_row(OLD).last_name) == ("Sam", "Old"))


# ------------------------------------------------------------- the class
TEACHER = add_user("g-t", "teacher@school.org", "Mr Teacher", "Mr", "Teacher")
OTHER_T = add_user("g-t2", "teacher2@school.org", "Ms Other")
os.environ["TEACHER_EMAILS"] = "teacher@school.org,teacher2@school.org"

# Signed in since names were kept, in Period 4.
KID = add_user("g-k1", "kid1@school.org", "Gabriel Baker", "Gabriel", "Baker")
# From before: no first/last. Period 4's roster knows them.
ROSTERED = add_user("g-k2", "kid2@school.org", "Aaron Miller")
# From before, and in Period 7, which isn't picked.
SEVEN = add_user("g-k3", "kid3@school.org", "Zoe Seven")
# From before, not on any roster: only a guess is possible.
GUESS = add_user("g-k4", "kid4@school.org", "Mary Ann Smith")
# Turned in, never scored.
UNSCORED = add_user("g-k5", "kid5@school.org", "Una Scored", "Una", "Scored")
# One name only: nothing to match on.
MONONYM = add_user("g-k6", "kid6@school.org", "Cher")

db = P.SessionLocal()
item = accounts.Assignment(slug="hw1", app=P.APP_NAME, teacher_id=TEACHER,
                           title="Lists, practice", code="", out_of=10)
db.add(item)
db.commit()
ITEM = item.id
for uid, score in ((KID, 9), (ROSTERED, 7), (SEVEN, 8), (GUESS, 6),
                   (UNSCORED, None), (MONONYM, 5)):
    db.add(accounts.Submission(assignment_id=ITEM, student_id=uid,
                               snippet_slug="s%d" % uid, score=score))
# Questions in the notes: Gabriel got one worth 0.5 right, so his grade is
# 9.5 — the same total Sync sends Classroom.
db.add(accounts.QuizQuestion(assignment_id=ITEM, qid="q1", kind="choice",
                             correct='["b"]', answers='[]', points=0.5))
db.add(accounts.QuizAnswer(assignment_id=ITEM, student_id=KID, qid="q1",
                           response='b'))
db.add(accounts.ClassroomPost(assignment_id=ITEM, course_id="c4",
                              course_name="Programming 1 — Period 4", work_id="w4"))
db.add(accounts.ClassroomPost(assignment_id=ITEM, course_id="c7",
                              course_name="Programming 1 — Period 7", work_id="w7"))
db.commit()
POST4 = db.query(accounts.ClassroomPost).filter_by(course_id="c4").first().id
db.close()

ROSTERS = {
    "c4": [{"profile": {"emailAddress": "KID1@school.org",
                        "name": {"givenName": "Gabriel", "familyName": "Baker"}}},
           {"profile": {"emailAddress": "kid2@school.org",
                        "name": {"givenName": "Aaron", "familyName": "Miller"}}},
           {"profile": {"emailAddress": "kid5@school.org",
                        "name": {"givenName": "Una", "familyName": "Scored"}}}],
    "c7": [{"profile": {"emailAddress": "kid3@school.org",
                        "name": {"givenName": "Zoe", "familyName": "Seven"}}}],
}
google = {"roster": 200}


def fake_get(url, access_token, params=None):
    for course, people in ROSTERS.items():
        if url == "%s/courses/%s/students" % (P.CLASSROOM_API, course):
            if google["roster"] != 200:
                return google["roster"], {}
            return 200, {"students": people}
    return 404, {}


P._google_get = fake_get
P._classroom_token = lambda db, user: ("AT", "")

teacher = client(TEACHER)
URL = "/api/assignment/hw1/skyward"


def get(body, who=teacher):
    r = who.post(URL, json=body)
    return r.status_code, r.get_json() or {}


# ------------------------------------------------------------- the file
print("\nThe file Skyward imports")

status, out = get({"category": "Prj", "due": "2026-10-08"})
lines = rows_of(out.get("csv", ""))
check("everyone scored, in Skyward's seven columns, no header row",
      status == 200 and lines and all(len(r) == 7 for r in lines)
      and lines[0][0] != "Student Last Name", repr(lines[:1]))
by_last = {r[0]: r for r in lines}
check("  last name first, then first name",
      by_last.get("Baker", [None, None])[1] == "Gabriel", repr(by_last.get("Baker")))
check("  then the title, the due date as MMDDYYYY, category and max score",
      by_last.get("Baker", [None] * 7)[2:6] == ["Lists, practice", "10082026", "Prj", "10"],
      repr(by_last.get("Baker")))
check("  and the score including the questions' points, as Sync sends it",
      by_last.get("Baker", [None] * 7)[6] == "9.5", repr(by_last.get("Baker")))
check("  a whole score has no .0 on it",
      by_last.get("Seven", [None] * 7)[6] == "8", repr(by_last.get("Seven")))
check("  sorted by last name, as Skyward's preview lists them",
      [r[0] for r in lines] == sorted((r[0] for r in lines), key=str.lower),
      repr([r[0] for r in lines]))
check("  rows end in CRLF, which Excel and Skyward both expect",
      out.get("csv", "").endswith("\r\n") and "\r\n" in out.get("csv", ""))
check("  a title with a comma stays one column",
      by_last.get("Baker", [None] * 7)[2] == "Lists, practice"
      and len(by_last.get("Baker", [])) == 7)

check("a student turned in but not scored is left out, and named",
      "Scored" not in by_last and out.get("ungraded") == ["Una Scored"],
      repr(out.get("ungraded")))
check("a student from before names were kept: last word is the last name",
      by_last.get("Smith", [None, None])[1] == "Mary Ann", repr(by_last.get("Smith")))
check("  and the guess is said, not slipped in",
      "Mary Ann Smith" in out.get("guessed", []) and "Gabriel Baker" not in out.get("guessed", []),
      repr(out.get("guessed")))
check("one name only can't be matched: left out, and named",
      "Cher" not in str(lines) and out.get("nameless") == ["Cher"], repr(out.get("nameless")))
check("the count is the rows in the file", out.get("count") == len(lines))
check("the file name is the title",
      out.get("filename") == "Lists, practice - Skyward.csv", repr(out.get("filename")))
check("  with anything a file name can't hold replaced",
      P._safe_filename('Lists: a/b?') == "Lists- a-b", repr(P._safe_filename('Lists: a/b?')))


# ------------------------------------------------------------- one section
print("\nOne class section")

status, out = get({"category": "N", "due": "2026-10-08", "post": POST4})
lines = rows_of(out.get("csv", ""))
lasts = sorted(r[0] for r in lines)
check("only that class's students — Skyward imports one section",
      lasts == ["Baker", "Miller"], repr(lasts))
check("  the roster's names stand in for a student from before",
      ["Miller", "Aaron"] == lines[[r[0] for r in lines].index("Miller")][:2]
      if "Miller" in lasts else False)
check("  and nobody is said to be guessed",
      out.get("guessed") == [], repr(out.get("guessed")))
check("  and they are kept, so the next file needs no roster",
      (user_row(ROSTERED).first_name, user_row(ROSTERED).last_name) == ("Aaron", "Miller"))
check("  a name the student already has is not replaced by the roster's",
      user_row(KID).first_name == "Gabriel")

google["roster"] = 403
status, out = get({"category": "N", "due": "2026-10-08", "post": POST4})
check("Google not answering is an error, not a file of everyone",
      status == 502 and "csv" not in out, "%d %r" % (status, out.get("error")))
google["roster"] = 200

status, out = get({"category": "N", "due": "2026-10-08", "post": 99999})
check("a class it wasn't posted to is refused", status == 400, str(status))


# ------------------------------------------------------------- refusals
print("\nWhat is refused")

status, out = get({"category": "", "due": "2026-10-08"})
check("no category", status == 400 and "category" in out.get("error", ""), str(status))
status, out = get({"category": "Project work", "due": "2026-10-08"})
check("  a description instead of a code", status == 400, str(status))
status, out = get({"category": "N", "due": "10/08/2026"})
check("a due date that isn't one", status == 400, str(status))
status, out = get({"category": "N", "due": "2026-10-08"}, who=client(KID))
check("a student", status == 403, str(status))
status, out = get({"category": "N", "due": "2026-10-08"}, who=client(OTHER_T))
check("another teacher", status == 404, str(status))

db = P.SessionLocal()
db.get(accounts.Assignment, ITEM).out_of = None
db.commit()
db.close()
status, out = get({"category": "N", "due": "2026-10-08"})
check("an assignment with no Out of: Skyward needs a max score",
      status == 400 and "out of" in out.get("error", "").lower(), str(status))
page = teacher.get("/teacher/hw1").get_data(as_text=True)
check("  and its page offers no download", 'id="sky-get"' not in page)
db = P.SessionLocal()
db.get(accounts.Assignment, ITEM).out_of = 10
db.commit()
db.close()

page = teacher.get("/teacher/hw1").get_data(as_text=True)
check("a graded assignment's page has the download",
      'id="sky-get"' in page and 'id="sky-cat"' in page and 'id="sky-due"' in page)
check("  with a class picker listing where it was posted",
      'id="sky-post"' in page and "Programming 1 — Period 7" in page)
check("  and says which Skyward template to use",
      "Import Scores and Create Assignments" in page)


bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
