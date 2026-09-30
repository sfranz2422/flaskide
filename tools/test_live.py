"""FlaskIDE, teaching live: the mirror, and what could quietly ruin a lesson.

    python3 tools/test_live.py

A live lesson is thirty people watching one row in a table. Almost everything
that can go wrong with it goes wrong SILENTLY — the page still renders, the
button still says Live, and the only symptom is a class looking at a line
their teacher fixed two minutes ago. So each of those is a check here.

WHAT IS ACTUALLY BEING GUARDED

  A student's own work is never touched.
      The page has two editors. If anything arriving from the network could
      reach the lower one, a class would lose a paragraph of their own typing
      the moment the teacher pressed a key, and nobody would use this twice.
      Checked by reading live.js: the mirror is the only editor given a value.

  A push that arrives late cannot win.
      The teacher's browser sends every 400ms. On school wifi two of those
      can overtake each other, and without a guard the OLDER text lands with
      the NEWER version number — after which nothing corrects it until the
      next keystroke. The write is conditional on a stamp that only goes up.

  A student who joins late is not left behind.
      No catch-up path, no replay: the first poll carries the whole file.

  Nothing lives in memory.
      Every one of these apps runs `gunicorn --workers 2`. A dict in a module
      is visible to one worker and invisible to the other, and which one a
      student reaches changes from poll to poll. It would pass every test on
      a laptop running a single worker and fail in front of a class.

  Only the host can type into the lesson.
      Checked against the row, not against the teacher list — a second
      teacher must not be able to write into somebody else's lesson.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FLASKIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "live.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@example.org, other@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, FLASKIDE)
import app as F                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


def add_user(sub, email, name):
    db = F.SessionLocal()
    try:
        user = accounts.User(google_sub=sub, email=email, name=name)
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def client(uid=None):
    c = F.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


def row(code):
    db = F.SessionLocal()
    try:
        return db.query(accounts.LiveSession).filter_by(code=code).first()
    finally:
        db.close()


TEACHER = add_user("t1", "teacher@example.org", "Mr Franz")
OTHER = add_user("t2", "other@example.org", "Another Teacher")
STUDENT = add_user("s1", "kid@example.org", "A Student")
STUDENT2 = add_user("s2", "kid2@example.org", "Another Student")

teacher = client(TEACHER)
other = client(OTHER)
student = client(STUDENT)
stranger = client()                      # signed out, like most of a class


# ---------------------------------------------------------------- starting
print("\nStarting a lesson")

r = student.post("/api/live/start", json={"body": "print(1)"})
check("a student cannot start one", r.status_code == 403, r.status_code)

r = stranger.post("/api/live/start", json={"body": "print(1)"})
check("nor can somebody signed out", r.status_code == 403, r.status_code)

r = teacher.post("/api/live/start",
                 json={"body": "from flask import Flask", "filename": "app.py",
                       "title": "Loops"})
check("a teacher can", r.status_code == 200, r.status_code)
CODE = r.get_json()["code"]
check("  and gets a code to read out", bool(CODE), CODE)
check("  with no look-alike characters in it",
      not set(CODE) & set("01lioIO"), CODE)

again = teacher.post("/api/live/start", json={"body": "print(2)"}).get_json()
check("pressing Go live again reuses the same lesson",
      again["code"] == CODE,
      "a second code would leave half the class on the wrong one")


# ------------------------------------------------------------------ pushing
print("\nPushing what the teacher types")

r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "line one", "seq": 1000, "filename": "app.py"})
check("the host can push", r.status_code == 200 and not r.get_json().get("stale"),
      r.status_code)
check("  and the row holds it", row(CODE).body == "line one")
check("  at the version they sent", row(CODE).version == 1000)

r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "line one, fixed", "seq": 1001})
check("a newer push replaces it", row(CODE).body == "line one, fixed")

# THE ONE THAT MATTERS. A push that was sent earlier but arrived later.
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "line one", "seq": 1000})
check("a push that arrives late is refused",
      r.get_json().get("stale") is True, r.get_json())
check("  and the newer text is still what the class sees",
      row(CODE).body == "line one, fixed",
      "stale text on the board is invisible to the teacher")
check("  and the version did not go backwards", row(CODE).version == 1001)

r = other.post("/api/live/%s/push" % CODE, json={"body": "hijacked", "seq": 9999})
check("another teacher cannot push into this lesson", r.status_code == 403,
      r.status_code)
check("  and did not change it", row(CODE).body == "line one, fixed")

r = student.post("/api/live/%s/push" % CODE, json={"body": "hijacked", "seq": 9999})
check("nor can a student", r.status_code == 403, r.status_code)

big = "x" * (F.MAX_FILE_BYTES + 1)
r = teacher.post("/api/live/%s/push" % CODE, json={"body": big, "seq": 2000})
check("an oversized file is refused", r.status_code == 413, r.status_code)
check("  and did not land", row(CODE).body == "line one, fixed")


# ------------------------------------------------------------------ polling
print("\nWhat the class sees")

r = stranger.get("/api/live/%s" % CODE)
check("a student who is not signed in can watch", r.status_code == 200,
      r.status_code)
body = r.get_json()
check("  and gets the whole file, not a diff", body["body"] == "line one, fixed")
check("  with the version to poll against", body["version"] == 1001)
check("  and who is teaching", body["host"] == "Mr Franz", body.get("host"))

r = stranger.get("/api/live/%s?v=%d" % (CODE, body["version"]))
check("polling with the version they have gets 304, not the file again",
      r.status_code == 304,
      "thirty students pulling the file every second is the whole cost")

teacher.post("/api/live/%s/push" % CODE, json={"body": "line two", "seq": 3000})
r = stranger.get("/api/live/%s?v=%d" % (CODE, body["version"]))
check("  and the next change comes straight through",
      r.status_code == 200 and r.get_json()["body"] == "line two",
      r.status_code)

# A student opening the page halfway through the lesson.
late = client()
r = late.get("/api/live/%s?v=-1" % CODE)
check("someone joining late gets the current file at once",
      r.status_code == 200 and r.get_json()["body"] == "line two",
      "no catch-up path, because the first poll IS the catch-up")

r = stranger.get("/api/live/nosuchcode")
check("an unknown code is a clean 404", r.status_code == 404, r.status_code)


# -------------------------------------------------------------- the pages
print("\nThe pages")

r = stranger.get("/live/%s" % CODE)
check("the live page opens for anyone with the code", r.status_code == 200,
      r.status_code)
page = r.get_data(as_text=True)
check("  and carries two editors, mirror and their own",
      'id="mirror"' in page and 'id="mine"' in page)

# LAYOUT, because the first version got this wrong in a way only a kaypy
# lesson showed: three panes stacked down the page put an 800x600 canvas in
# the middle, squeezed the student's own editor to a few lines at the
# bottom, and left Run in the header far from the code it runs.
#
# Checked as structure rather than by eye: the two editors are inside one
# left-hand column, and the output and the canvas are a sibling of that
# column, not a third row under it.
# NESTING, not order. The first version of this sliced from the left
# column's class to the string "live-right" — which is the same slice
# whether the student's editor is inside that column or has been moved out
# of it into a sibling, because both sit between those two points in the
# text. It passed a deliberately broken page.
start = page.index('class="pane live-left"')
end = page.index("</section>", start)
left = page[start:end]
check("  with both editors stacked inside the left column",
      'id="mirror"' in left and 'id="mine"' in left,
      "mirror: %s, mine: %s" % ('id="mirror"' in left, 'id="mine"' in left))
check("  and the output beside them, not under them",
      'id="output"' not in left and 'id="canvas"' not in left,
      "a game in the middle row is what squeezed the editor last time")
check("  in the same right-hand pane class the editor uses",
      'class="pane pane-right live-right"' in page,
      "so the two pages do not disagree about where output lives")
check("  with the lesson already in it, so it is not blank while it polls",
      "line two" in page)
check("  and no button that copies the teacher's code down",
      not re.search(r"copy[^<]{0,20}(mine|into|down)", page, re.I),
      "typing it is the exercise")

r = stranger.get("/live/nosuchcode")
check("a bad code goes back to the join page", r.status_code == 302
      and "/live" in r.headers.get("Location", ""),
      r.headers.get("Location", r.status_code))

check("the join page opens", stranger.get("/live").status_code == 200)

r = teacher.get("/live/%s" % CODE)
host_page = r.get_data(as_text=True)
check("the host gets their own view, not a mirror of themselves",
      'id="mirror"' not in host_page)
# A projector showing two paragraphs and a code does not need several
# megabytes of WebAssembly to do it.
check("  and is not made to download Python to show a code",
      "pyodide.js" not in host_page)
check("  while a student following along does get it",
      "pyodide.js" in page and "flask.js" in page)

r = teacher.get("/")
check("the editor offers Go live to a teacher", 'id="go-live"' in
      r.get_data(as_text=True))
r = student.get("/")
check("  and does not offer it to a student", 'id="go-live"' not in
      r.get_data(as_text=True))


# ------------------------------------------------ keeping their own copy
print("\nSaving their own work")

r = student.get("/live/%s" % CODE)
student_page = r.get_data(as_text=True)
check("a signed-in student is offered Save", 'id="live-save"' in student_page)
check("  and is not told their work is browser-only",
      "sign in to save it properly" not in student_page)

r = stranger.get("/live/%s" % CODE)
out_page = r.get_data(as_text=True)
check("a signed-out student is not offered Save",
      'id="live-save"' not in out_page,
      "there is nowhere for it to go, so the button would be a lie")
check("  and is told where their work is kept instead",
      "sign in to save it properly" in out_page)

# Sign in, on the lesson page itself. Save and Turn in only exist once signed
# in, so without this a student had no way to get them short of leaving the
# lesson — and nothing on the page said so. Login is off in this suite (no
# Google keys), so it is switched on just for these two requests.
_login = accounts.login_configured
accounts.login_configured = lambda: True
try:
    signin_out = stranger.get("/live/%s" % CODE).get_data(as_text=True)
    signin_in = student.get("/live/%s" % CODE).get_data(as_text=True)
finally:
    accounts.login_configured = _login
check("a signed-out student is offered Sign in on the lesson",
      "/login?next=/live/%s" % CODE in signin_out
      or "/login?next=%%2Flive%%2F%s" % CODE in signin_out)
check("  and a signed-in one is not",
      ">Sign in</a>" not in signin_in)
check("  and the page loads tab stops for their editor",
      "tabstops.js" in out_page)

# The live page saves through the editor's own endpoints, so a project made
# here is an ordinary project: it opens at /p/<slug>, lists in My projects,
# and can be turned in. Nothing about it is special-cased.
r = student.post("/api/draft", json={"files": {"app.py": "# mine"}, "title": "Loops"})
check("their copy saves through the ordinary draft endpoint",
      r.status_code == 200, r.status_code)
SLUG = r.get_json()["slug"]

r = student.post("/api/draft/" + SLUG,
                 json={"files": {"app.py": "# mine 2"}, "title": "Loops"})
check("  and autosaves from then on", r.status_code == 200, r.status_code)

listed = student.get("/api/my/projects").get_json()
titles = [row["title"] for row in listed.get("projects", listed if
          isinstance(listed, list) else [])]
check("  and turns up in My projects", "Loops" in titles, titles)

r = student.get("/p/" + SLUG)
check("  and opens in the full editor",
      r.status_code == 200 and "mine 2"
      in r.get_data(as_text=True), r.status_code)

r = stranger.post("/api/draft", json={"files": {"app.py": "x"}})
check("a signed-out student saving is told to sign in, not ignored",
      r.status_code == 401, r.status_code)

# A deleted project must not leave the page autosaving into nothing while
# telling the student it saved.
student.delete("/api/draft/" + SLUG)
r = student.post("/api/draft/" + SLUG, json={"files": {"app.py": "after"}})
check("autosaving into a deleted project is a clean 404, not a silent success",
      r.status_code == 404, r.status_code)
_live_js = open(os.path.join(FLASKIDE, "static", "live.js")).read()
check("  and live.js turns that back into a Save button",
      "res.status === 404" in _live_js and "removeItem(SLUG_KEY)" in _live_js,
      "otherwise it says Saved for the rest of the lesson and saves nothing")


# ------------------------------------------------- handing work in
#
# THE THING THAT WAS IMPOSSIBLE.
#
# Turning work in needs a draft with an assignment on it. A live lesson had
# no assignment and the live page saved through /api/draft, which makes a
# free-standing project — so the Turn in button could not appear, on the
# live page or on reopening the saved copy. Nothing errored; the lesson
# worked, the saving worked, and handing in simply could not happen.
print("\nHanding work in")

hw = teacher.post("/api/assignment",
                  json={"files": {"app.py": "# starter app"},
                        "title": "Flask homework"}).get_json()["slug"]

r = teacher.get("/api/live/assignment/" + hw)
check("a teacher can fetch one assignment's starter for the editor",
      r.status_code == 200 and r.get_json()["files"]["app.py"].startswith("# starter app"),
      r.status_code)
check("  another teacher cannot",
      other.get("/api/live/assignment/" + hw).status_code == 404)
check("  nor can a student",
      student.get("/api/live/assignment/" + hw).status_code == 403)

r = teacher.get("/api/live/assignments")
check("a teacher can list their open assignments", r.status_code == 200,
      r.status_code)
check("  and the list stays light, with no starter code in it",
      all("code" not in a for a in r.get_json()["assignments"]),
      "every starter in the chooser would be megabytes nobody reads")
check("  and the new one is in it",
      hw in [a["slug"] for a in r.get_json()["assignments"]])
check("a student cannot", student.get("/api/live/assignments").status_code == 403)

r = other.post("/api/live/start", json={"body": "x", "assignment": hw})
check("a teacher cannot attach someone else's assignment",
      r.status_code == 400, r.get_json())

# CODE is still the teacher open lesson at this point; close it so
# the next start makes a fresh one attached to the assignment.
teacher.post("/api/live/%s/stop" % CODE)
started = teacher.post("/api/live/start",
                       json={"body": "for i in range(3):", "title": "Loops",
                             "assignment": hw}).get_json()
LESSON = started["code"]
check("a lesson can be started for an assignment",
      started.get("assignment") == hw, started)

# Resuming after a page reload sends no assignment key at all.
again2 = teacher.post("/api/live/start", json={"body": "more"}).get_json()
check("  and reloading the editor does not drop it",
      again2.get("assignment") == hw,
      "the class would silently lose the ability to hand in")

# The assignment ships more than one file, which is the normal WebIDE case.
db = F.SessionLocal()
try:
    row = db.query(accounts.Assignment).filter_by(slug=hw).first()
    row.files = json.dumps({"app.py": "# starter app",
                            "templates/home.html": "<h1>hi</h1>"})
    db.commit()
finally:
    db.close()

r = student.post("/api/live/%s/keep" % LESSON, json={"code": "# my work"})
check("a student's save lands in the assignment's own draft",
      r.status_code == 200 and r.get_json()["can_turn_in"] is True,
      r.get_json())
KEPT = r.get_json()["slug"]

def drafts_for(uid):
    db = F.SessionLocal()
    try:
        item = db.query(accounts.Assignment).filter_by(slug=hw).first()
        return db.query(accounts.Draft).filter_by(
            owner_id=uid, assignment_id=item.id).count()
    finally:
        db.close()


# THE DUPLICATE, EXERCISED PROPERLY.
#
# The first version of this saved once and then counted, which is one draft
# however the code behaves — it passed a deliberately broken server that made
# a fresh row every time. Two copies of one piece of work is the failure
# worth catching: the student edits one and hands in the other.
# THE STATUS, NOT JUST THE COUNT. Counting alone still passed a server that
# inserted a fresh row every time — because the table's unique constraint on
# (owner, assignment) rejected the second insert, so the count stayed at 1
# while every save after the first was a 500 the student would have seen as
# "could not save". The count was right for the wrong reason.
again_a = student.post("/api/live/%s/keep" % LESSON,
                       json={"code": "my work, further on"})
again_b = student.post("/api/live/%s/keep" % LESSON,
                       json={"code": "further still"})
check("  and saving again succeeds rather than colliding",
      again_a.status_code == 200 and again_b.status_code == 200,
      "%s then %s" % (again_a.status_code, again_b.status_code))
check("  writing to that same row, not a new one",
      drafts_for(STUDENT) == 1,
      "%d drafts for one student on one assignment" % drafts_for(STUDENT))
check("  and the latest text is what was kept",
      again_b.get_json().get("slug") == KEPT, again_b.get_json())

# The other order, which is the one that happens in a real week: they open
# the handout link in class on Monday, then join the live lesson on Tuesday.
handout_first = client(STUDENT2)
r = handout_first.get("/a/" + hw)
check("  a student who opened the handout link first has one copy",
      drafts_for(STUDENT2) == 1, drafts_for(STUDENT2))
joined = handout_first.post("/api/live/%s/keep" % LESSON,
                            json={"code": "typed along"})
check("  and saving from the live lesson succeeds",
      joined.status_code == 200, joined.status_code)
check("  finding it rather than making another",
      drafts_for(STUDENT2) == 1,
      "%d drafts — they would edit one and hand in the other"
      % drafts_for(STUDENT2))

r = student.get("/a/" + hw)
check("  so opening the handout link afterwards finds it",
      r.status_code == 302 and KEPT in r.headers.get("Location", ""),
      r.headers.get("Location", r.status_code))

kept_files = student.post("/api/live/%s/keep" % LESSON,
                          json={"code": "# my work"}).get_json()["files"]
r = student.post("/api/submit", json={"draft": KEPT, "files": kept_files})
check("the student can turn it in", r.status_code == 200, r.get_json())

# THE FILE THAT NEARLY GOT DROPPED. Turning in replaces a draft's files
# with what is posted, and the live pane edits only the entry page — so a
# first version of this posted one file and would have deleted any other the
# assignment shipped, at the moment the work was handed in.
db = F.SessionLocal()
try:
    kept = db.query(accounts.Draft).filter_by(slug=KEPT).first().file_map()
finally:
    db.close()
check("  and the project's other files survived being handed in",
      "templates/home.html" in kept, sorted(kept))

seen_by_teacher = teacher.get("/teacher/" + hw).get_data(as_text=True)
check("  and it reaches the teacher's dashboard",
      "A Student" in seen_by_teacher)

page = student.get("/live/%s" % LESSON).get_data(as_text=True)
check("the live page offers Turn in once there is an assignment",
      'id="live-turn-in"' in page)
check("  and says they have already handed it in",
      "Turn in again" in page)

# A lesson with no assignment still saves — it just cannot hand in, and
# says nothing misleading about it.
plain = teacher.post("/api/live/start", json={"body": "x"}).get_json()
check("  (an open lesson is reused, so this is still the same one)",
      plain["code"] == LESSON, plain["code"])

teacher.post("/api/live/%s/stop" % LESSON)
bare = teacher.post("/api/live/start",
                    json={"body": "x", "assignment": ""}).get_json()
r = student.post("/api/live/%s/keep" % bare["code"], json={"code": "notes"})
check("a lesson with no assignment still saves",
      r.status_code == 200 and r.get_json()["can_turn_in"] is False,
      r.get_json())
page = student.get("/live/%s" % bare["code"]).get_data(as_text=True)
check("  and offers no Turn in button at all",
      'id="live-turn-in"' not in page,
      "a button that cannot work reads as lost work")

r = stranger.post("/api/live/%s/keep" % bare["code"], json={"code": "x"})
check("signed out, saving says to sign in", r.status_code == 401, r.status_code)


# ------------------------------------------------- the other kind of project
#
# FlaskIDE teaches two things, and they have different entry files. A live
# save has to land in the one the assignment actually uses: dropping an
# app.py beside a query.sql makes a project that is neither, and the student
# sees their work vanish from the editor they typed it in.
print("\nA SQL lesson")

sql_hw = teacher.post("/api/assignment",
                      json={"files": {"query.sql": "SELECT 1;",
                                      "schema.sql": "CREATE TABLE t (a);"},
                            "title": "SQL homework"}).get_json()["slug"]
teacher.post("/api/live/%s/stop" % LESSON)
sql_lesson = teacher.post("/api/live/start",
                          json={"body": "SELECT * FROM t;",
                                "filename": "query.sql",
                                "assignment": sql_hw}).get_json()["code"]

r = student.post("/api/live/%s/keep" % sql_lesson,
                 json={"code": "SELECT a FROM t;"})
check("a save in a SQL lesson succeeds", r.status_code == 200, r.status_code)
kept_sql = r.get_json()["files"]
check("  and lands in query.sql, not a stray app.py",
      kept_sql.get("query.sql") == "SELECT a FROM t;" and "app.py" not in kept_sql,
      sorted(kept_sql))
check("  while the schema that came with the assignment survives",
      "schema.sql" in kept_sql, sorted(kept_sql))

# And again on the update path, which is a different branch entirely.
r = student.post("/api/live/%s/keep" % sql_lesson,
                 json={"code": "SELECT a, b FROM t;"})
kept_sql = r.get_json()["files"]
check("  saving again still writes query.sql",
      kept_sql.get("query.sql") == "SELECT a, b FROM t;"
      and "app.py" not in kept_sql,
      sorted(kept_sql))


# ------------------------------------------------------------------ ending
print("\nEnding it")

r = student.post("/api/live/%s/stop" % CODE)
check("a student cannot end the lesson", r.status_code == 403, r.status_code)

r = teacher.post("/api/live/%s/stop" % CODE)
check("the host can", r.status_code == 200, r.status_code)

r = stranger.get("/api/live/%s?v=3000" % CODE)
check("a student still on the page is TOLD it ended",
      r.status_code == 200 and r.get_json()["ended"] is True,
      "a mirror that just stops moving looks like a broken page")

r = teacher.post("/api/live/%s/push" % CODE, json={"body": "after", "seq": 5000})
check("and nothing more can be pushed into it", r.status_code == 409,
      r.status_code)

after = teacher.post("/api/live/start", json={"body": "new"}).get_json()
check("starting again makes a NEW lesson, not the ended one",
      after["code"] != CODE, after["code"])


# ------------------------------------------- resuming, and signing out
print("\nResuming after a reload, and signing out")

def open_lessons(uid):
    db = F.SessionLocal()
    try:
        return db.query(accounts.LiveSession).filter_by(
            host_id=uid, app=F.APP_NAME, ended=0).count()
    finally:
        db.close()

r = teacher.post("/api/live/start", json={"body": "x", "resume": after["code"]})
check("a reload resumes the lesson it was broadcasting",
      r.get_json().get("code") == after["code"], r.get_json())

# THE BUG: the editor resumed by calling start like a fresh Go live, so an
# ended lesson in the browser's memory put the teacher back on the air in a
# brand-new lesson just for opening the editor — "sign in and I'm live".
teacher.post("/api/live/%s/stop" % after["code"])
r = teacher.post("/api/live/start", json={"body": "x", "resume": after["code"]})
check("resuming a lesson that has ended starts nothing",
      r.get_json().get("resumed") is False and "code" not in r.get_json(),
      r.get_json())
check("  and no lesson was opened behind the teacher's back",
      open_lessons(TEACHER) == 0, "%d open" % open_lessons(TEACHER))

fresh = teacher.post("/api/live/start", json={"body": "x"}).get_json()
r = teacher.post("/api/live/start", json={"body": "x", "resume": CODE})
check("  nor does resuming an old code while a different lesson is open",
      r.get_json().get("resumed") is False, r.get_json())
check("  and the open one is left alone",
      open_lessons(TEACHER) == 1)

teacher.get("/logout")
check("signing out ends the lesson being broadcast",
      open_lessons(TEACHER) == 0, "%d open" % open_lessons(TEACHER))
r = stranger.get("/api/live/%s" % fresh["code"])
check("  and the class is told it ended",
      r.get_json().get("ended") is True, r.get_json())
teacher = client(TEACHER)                  # signed back in for what follows


# --------------------------------------------------- how it is built at all
print("\nHow it is built")

app_src = open(os.path.join(FLASKIDE, "app.py")).read()
live_js = open(os.path.join(FLASKIDE, "static", "live.js")).read()
app_js = open(os.path.join(FLASKIDE, "static", "app.js")).read()


def code_only(js):
    """The JavaScript with its comments taken out.

    NOT a nicety. The check below for `readOnly: "nocursor"` was written
    against the raw file and passed happily while the actual option said
    `readOnly: true` — because the phrase was also sitting in the comment
    above it explaining why. A check that its own documentation satisfies is
    a check that can never fail.
    """
    out = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", r"\1", out, flags=re.M)


live_code = code_only(live_js)

# TWO WORKERS. `gunicorn --workers 2` is in render.yaml, so any per-session
# state kept in a module-level dict is visible to one process and invisible
# to the other — and a student's poll reaches whichever one it lands on.
live_block = app_src[app_src.index("# Teaching live"):]
check("no live state is kept in module memory",
      not re.search(r"^_?live_?\w* *= *(\{\}|\[\]|dict\(|list\()",
                    live_block, re.M),
      "with two gunicorn workers, half the class would see nothing")

check("the row is what two workers agree on",
      "class LiveSession" in open(os.path.join(FLASKIDE, "accounts.py")).read())

# The stamp has to be a 64-bit column: it is a millisecond clock reading,
# about 1.8e12, and Postgres INTEGER stops at 2.1e9. As a plain Integer this
# passes on SQLite and raises on the first push in production.
accounts_src = open(os.path.join(FLASKIDE, "accounts.py")).read()
check("  and its version column is big enough for a clock reading",
      re.search(r"version = Column\(BigInteger", accounts_src) is not None,
      "Integer overflows on Postgres at 2.1e9; Date.now() is 1.8e12")

# THE RULE THE WHOLE PAGE EXISTS TO KEEP, asked about the argument and not
# about where the line sits. An earlier version of this check only counted
# the calls and looked for the word localStorage somewhere above — which
# passed unchanged when the call was rewritten to `mine.setValue(L.body)`,
# i.e. to fill the student's editor from the lesson. It tested position, not
# source, which is not the thing that matters.
sets = re.findall(r"(\w+)\.setValue\(", live_code)
check("live.js writes into only two editors, and knows which",
      set(sets) <= {"mirror", "mine"},
      "editors written to: %s" % sorted(set(sets)))

mine_calls = re.findall(r"mine\.setValue\(([^)]*)\)", live_code)
check("  the student's editor is written to exactly once",
      len(mine_calls) == 1, "%d times" % len(mine_calls))
arg = (mine_calls[0].strip() if mine_calls else "")
from_storage = bool(arg) and re.search(
    r"\b(var\s+)?%s\s*=\s*window\.localStorage\.getItem" % re.escape(arg),
    live_code) is not None
check("  and what goes in came out of their own browser, not the wire",
      from_storage,
      "mine.setValue(%s) — %s" % (arg or "nothing",
                                  "read from localStorage" if from_storage
                                  else "NOT traced to localStorage"))

after_mirror = live_code[live_code.index("function showMirror"):]
# What gets saved has to be the student's editor. Saving the mirror would
# put the teacher's code in the student's projects under their name, and it
# would look completely correct on screen while doing it.
#
# ONE LEVEL OF INDIRECTION IS RESOLVED, because the first version of this
# check only matched `code: <editor>.getValue()` and the initial Save passes
# a variable — so changing that variable to read the mirror passed the suite
# untouched. A check that covers the autosave and not the Save is worse than
# none, because it reads as though both are guarded.
def editors_behind(field):
    """Which CodeMirror every `field: ...` ends up reading."""
    found = set()
    for value in re.findall(r"\b%s: *([\w.()]+)" % field, live_code):
        value = value.rstrip(",")
        direct = re.match(r"(\w+)\.getValue\(\)$", value)
        if direct:
            found.add(direct.group(1))
            continue
        if re.match(r"^\w+$", value):          # a variable: find what it holds
            for src in re.findall(
                    r"\b%s *= *(\w+)\.getValue\(\)" % re.escape(value),
                    live_code):
                found.add(src)
            else:
                if not re.search(r"\b%s *= *\w+\.getValue\(\)"
                                 % re.escape(value), live_code):
                    found.add("?" + value)     # unresolved: say so, don't pass
    return found


saved_from = editors_behind("code")
check("  and what is saved to their projects is their editor, not the mirror",
      bool(saved_from) and saved_from == {"mine"},
      "saved from: %s" % sorted(saved_from))

check("  and nothing in the polling path touches it at all",
      "mine.setValue(" not in after_mirror,
      "a class losing their own work is the one unforgivable bug here")

mirror_opts = live_code[live_code.index('fromTextArea($("mirror")'):]
mirror_opts = mirror_opts[:mirror_opts.index("});")]
# THE TEACHER'S CODE IS NOT LIFTABLE. Without this a student drags across
# the mirror, presses Ctrl+C, and has the whole lesson in their own editor
# in two seconds — which is why there is no copy button either.
css = open(os.path.join(FLASKIDE, "static", "style.css")).read()
mirror_css = css[css.index(".live-mirror,"):]
mirror_css = mirror_css[:mirror_css.index("}")]
# ANCHORED TO THE START OF THE LINE. `"user-select: none" in block` looks
# right and is not: `-webkit-user-select: none` contains it as a substring,
# so flipping the real property to `text` left the check passing and the
# teacher's code selectable. Both of these were written the lazy way first
# and both passed a deliberately broken stylesheet.
def declares(block, prop, value):
    return re.search(r"(?m)^\s*%s:\s*%s\s*;" % (prop, value), block) is not None


check("the teacher's code cannot be selected",
      declares(mirror_css, "user-select", "none"),
      "a drag and Ctrl+C would lift the whole lesson")
check("  including on the browsers that need the prefix",
      declares(mirror_css, "-webkit-user-select", "none"))
mine_css = css[css.index(".live-mine,"):]
mine_css = mine_css[:mine_css.index("}")]
check("  while the student's own editor still can be",
      declares(mine_css, "user-select", "text"),
      "their own work has to be copyable — it is theirs")
check("  and a copy made some other way is refused",
      re.search(r'\["copy", "cut"\]', live_code) is not None
      and "preventDefault" in live_code,
      "user-select is a hint; find-on-page and extensions get round it")

# A .md FILE IS A LINK THE CLASS CAN CLICK.
#
# The teacher opens a notes tab, puts an address in it, and it renders on
# thirty screens as a real link. Without this it arrives as
# `[click here](http://…)` in grey in a code pane, which is worse than
# useless in front of a room.
check("the live page can render notes, not just code",
      'id="mirror-notes"' in page and "notes.js" in page)
check("  and switches to them on a .md filename",
      "FlaskIDENotes.isMarkdown(data.filename)" in live_code,
      "the filename is already on the wire; this is what reads it")
check("  rendering through the same sanitiser the editor uses",
      "FlaskIDENotes.render(mirrorNotes" in live_code,
      "notes.js drops scripts and forces links to a new tab")
# THE GUARD, not the variable's name. Checking that `lastNotes` appears
# somewhere passed happily when the condition it guards was replaced by
# `true` — the name was still in the file, doing nothing.
check("  and re-renders only when the text changed",
      re.search(r"data\.body\s*!==\s*lastNotes", live_code) is not None,
      "re-parsing every second replaces the link under the cursor, so a "
      "click that lands mid-poll hits a dead element")
# CodeMirror measures itself on build. Measured while display:none it
# measures zero and comes back blank — switching tabs in front of a class is
# exactly when that happens.
check("  and the code pane is refreshed on the way back",
      "mirror.refresh()" in live_code,
      "CodeMirror returns from a hidden container as an empty box")
# Verified in a real browser against these exact rules: the teacher's code
# and notes text compute to user-select none, and a link inside the notes
# computes to text. The :not(.is-authoring) rule applies because the live
# page's body is is-live.
check("  with links inside the notes still usable",
      re.search(r"(?m)^body:not\(\.is-authoring\) \.notes-body a \{", css)
      is not None and "is-live" in page,
      "unselectable notes with an unclickable link would be pointless")

# THE CLIENT HALF. The server can do all of this correctly and the feature
# still be broken, because it is live.js that chooses which endpoint to call
# — and /api/draft makes a project with no assignment, which is the thing
# that could never be turned in. Swapping the URL back passed the entire
# server-side suite untouched.
# The chooser must not read as "open this lesson" — it decides where the
# CLASS's work goes, and the first wording sent a teacher looking for code
# that never loaded.
app_code = code_only(app_js)
check("the chooser says what it actually does",
      "Where should the class turn this work in?" in app_code
      and "does not change what is in your editor" in app_code,
      "the old wording read like it was about to open the assignment")
check("  and loading the starter is a separate, confirmed step",
      "function offerStarter" in app_code
      and re.search(r"offerStarter[\s\S]{0,800}window\.confirm", app_code)
      is not None,
      "it replaces the editor, so it cannot be silent")
check("  which the reload-resume path never takes",
      re.search(r'if \(resumeCode\) startLive\(undefined, resumeCode\);',
                app_code) is not None,
      "resuming a broadcast must not wipe what is being demonstrated")

check("the live page saves through the lesson, not as a loose project",
      "/keep" in live_code and 'fetch("/api/draft"' not in live_code,
      "/api/draft makes a draft with no assignment, which cannot be handed in")
check("  and offers Turn in only once the save says it can",
      "can_turn_in" in live_code and "canTurnIn" in live_code)
# WHAT TURN IN POSTS, which the server-side checks above cannot see: they
# build the payload themselves. Posting an empty file map is accepted by the
# server and deletes every other file in the project, at the moment the work
# is handed in.
submit_call = live_code[live_code.index('"/api/submit"'):]
submit_call = submit_call[:submit_call.index("}).then")]
check("  turning in posts the whole project, not an empty map",
      "saved.files" in submit_call and "files: {}" not in submit_call,
      "an empty map wipes the assignment's own files on hand-in")
check("  having saved it first, so the two agree",
      "keep().then" in live_code,
      "otherwise what is handed in is not what was saved")

check("  handing in through the editor's own endpoint",
      '"/api/submit"' in live_code,
      "so the dashboard sees the same thing either way")

check("the mirror cannot be typed into",
      '"nocursor"' in mirror_opts,
      "a plain readOnly still takes a cursor, so it looks typeable")

check("the teacher's push carries a stamp that only goes up",
      "function nextSeq" in app_js and "Math.max(Date.now()" in app_js)
check("  and the server refuses a lower one",
      "LiveSession.version < seq" in app_src,
      "without this, late pushes overwrite newer text")

check("the poll answers 304 when nothing changed",
      'return ("", 304)' in app_src)

# The editor's own rule for game mode: the output becomes a log strip under
# the picture. Without the class the stylesheet has nothing to hook, and the
# output pane fights the canvas for the right-hand column.
# WebIDE has no Python: running is a sandboxed frame, and Stop works by
# removing the element — a page stuck in `while (true)` wedges that frame's
# process, and a wedged frame cannot navigate itself away.
check("running goes through FlaskIDE's own runtime",
      "FlaskIDERuntime" in live_code and "runtime.run(" in live_code,
      "so the live app and the editor's app cannot drift apart")
check("  and the preview is the editor's, address bar and all",
      "new window.FlaskIDEPreview(" in live_code,
      "the page on screen is one route's answer; which route matters")
# A FlaskIDE project is Flask OR SQL, and the lesson's own filename is what
# says which. Without this a SQL lesson would try to boot a Flask app.
# THE BRANCH, not the two names. Checking that runSql and isSql both appear
# somewhere passed happily with the `if (isSql())` replaced by `if (false)`,
# because neither name moved — the call was simply unreachable.
sql_branch = re.search(r"if \(isSql\(\)\)\s*\{[\s\S]{0,400}?runtime\.runSql\(",
                       live_code)
check("  and a SQL lesson runs as SQL, decided by the file being taught",
      sql_branch is not None,
      "otherwise a query.sql lesson tries to boot Flask and fails")
check("  with no Stop button, because there is nothing to interrupt",
      "stopBtn.hidden = true" in live_code,
      "a request runs to completion on this thread; the editor has none either")

# STOP HAS TO PUT THE TOOLBAR BACK ITSELF.
#
# Reproduced on the deployed editor: press Stop on a kaypy game and the
# canvas freezes and "— stopped —" is printed, but the await on
# `_pyide_drive_game()` never settles, so Run stays disabled on "Running…"
# with Stop showing until the page is reloaded. Leaving the reset to the
# promise's finally is leaving it to something that may never run.
# PyIDE needed a run token because its Stop waited on a Pyodide promise that
# never settled. Nothing here waits on anything: Stop removes the frame,
# which kills the page outright even mid-loop. So only the toolbar half
# applies.
check("the Run button comes back when the request is answered",
      "setBusy(false)" in live_code,
      "otherwise it stays disabled and the lesson looks frozen")

check("a finished lesson stops the polling",
      'throw new Error("ended")' in live_code,
      "thirty browsers polling an ended lesson until home time")

# Resuming (see "Resuming after a reload" above): the editor's half.
_app_code = code_only(open(os.path.join(HERE, "..", "static", "app.js")).read())
check("the editor sends the remembered code when it resumes",
      re.search(r"startLive\(undefined, resumeCode\)", _app_code) is not None
      and "resume: resume" in _app_code)
check("  and forgets it when the server says that lesson is over",
      re.search(r"data\.resumed === false\)\s*\{[^}]*removeItem\(\"flaskide-live-host\"\)",
                _app_code) is not None)
check("  and forgets it on any page with no Go live button",
      re.search(r"\}\s*else\s*\{\s*try\s*\{\s*localStorage\.removeItem\(\"flaskide-live-host\"\)",
                _app_code) is not None)

bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
