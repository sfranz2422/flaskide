"""Lessons: notes and questions with no code, for classes that are not
programming.

    python3 tools/test_lesson.py

A lesson is an assignment with kind "lesson" and its notes in lesson.md, so
the quiz, the dashboard, Classroom and the live link work on it as they do
on any assignment. What this guards is where a lesson must differ.

WHAT IS ACTUALLY BEING GUARDED

  The class never gets the answers.
      The notes go to students on the lesson page and on every live push.
      Both are searched for the key. The teacher's own page keeps it.

  A lesson is its own page, and nothing of the code editor's.
      The assignment link opens the lesson for a student and the lesson's
      editor for its teacher; Edit and the dashboard's Go live go there too;
      the code editor's Go live chooser does not offer it.

  Live follows the teacher; the assignment link does not.
      The same page, told which: from the live link it is given the lesson's
      code and polls; from the assignment link it is given none.

  Turn in is what counts.
      It makes a Submission with no snapshot, the teacher sees each
      student's answers in place of an Open link, and Sync sends the points.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(tempfile.mkdtemp(), "lesson.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@example.org, other@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402
import quiz                                                  # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


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


def item(slug):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Assignment).filter_by(slug=slug).first()
    finally:
        db.close()


TEACHER = add_user("t", "teacher@example.org", "Mr Franz")
OTHER = add_user("o", "other@example.org", "Other Teacher")
KID = add_user("k", "kid@example.org", "A Student")
KID2 = add_user("k2", "kid2@example.org", "B Student")
teacher, other, kid, kid2, stranger = (client(TEACHER), client(OTHER), client(KID),
                                       client(KID2), client())

NOTES = """# The water cycle

Water moves.

---

```quiz
What is water vapour turning into liquid called?
- [ ] Evaporation
- [x] Condensation
- [ ] Runoff
points: 2
```

---

```quiz
Which gas makes up most of the air?
answer: nitrogen
```
"""

# ------------------------------------------------------------ making one
print("\nMaking a lesson")
r = kid.post("/api/lesson", json={"title": "Nope"})
check("a student cannot make one", r.status_code == 403)
r = teacher.post("/api/lesson", json={"title": "The water cycle"})
d = r.get_json() or {}
SLUG = d.get("slug", "")
check("a teacher can, and is sent to its page",
      r.status_code == 200 and d.get("url") == "/teacher/%s/lesson" % SLUG, d)
it = item(SLUG)
check("  it is an assignment of kind lesson, with no code",
      it.kind == "lesson" and it.code == "" and "lesson.md" in it.file_map())
check("  starting from example notes with a slide and a question",
      "---" in it.file_map()["lesson.md"] and "```quiz" in it.file_map()["lesson.md"])
check("ordinary assignments are still kind code",
      item(teacher.post("/api/assignment", json={"title": "Loops", "files": {"app.py": "from flask import Flask\n"}})
           .get_json()["slug"]).kind == "code")

page = teacher.get("/teacher/%s/lesson" % SLUG).get_data(as_text=True)
check("its page has Write and Present, Save and Go live",
      'data-mode="write"' in page and 'data-mode="present"' in page
      and 'id="lesson-save"' in page and 'id="go-live"' in page)
check("  only for its teacher",
      other.get("/teacher/%s/lesson" % SLUG).status_code == 404
      and kid.get("/teacher/%s/lesson" % SLUG).status_code == 404)

r = teacher.post("/api/lesson/%s" % SLUG, json={"title": "Water", "notes": NOTES})
check("saving it keeps the title and the notes",
      r.status_code == 200 and item(SLUG).title == "Water"
      and item(SLUG).file_map() == {"lesson.md": NOTES})
check("  only for its teacher",
      other.post("/api/lesson/%s" % SLUG, json={"notes": "x"}).status_code in (403, 404)
      and item(SLUG).file_map() == {"lesson.md": NOTES})
page = teacher.get("/teacher/%s/lesson" % SLUG).get_data(as_text=True)
check("the teacher's page has the key, to write it",
      "- [x] Condensation" in page and "answer: nitrogen" in page)
keys = {q["qid"]: q for q in quiz.keys(NOTES)}
MC = next(q for q in keys.values() if q["kind"] == "choice")["qid"]
SA = next(q for q in keys.values() if q["kind"] == "text")["qid"]

# ------------------------------------------------- where it opens
print("\nWhere a lesson opens")
r = teacher.get("/a/" + SLUG)
check("its teacher, from the assignment link, gets the lesson's page",
      r.status_code == 302 and r.headers["Location"].endswith("/teacher/%s/lesson" % SLUG))
r = teacher.get("/teacher/%s/edit" % SLUG)
check("  and Edit on the dashboard goes there too",
      r.status_code == 302 and r.headers["Location"].endswith("/teacher/%s/lesson" % SLUG))
r = teacher.get("/teacher/%s/live" % SLUG)
check("  and Go live goes there, presenting",
      r.status_code == 302 and "/teacher/%s/lesson" % SLUG in r.headers["Location"]
      and "go=live" in r.headers["Location"])
dash = teacher.get("/teacher").get_data(as_text=True)
check("the dashboard has Create lesson, and marks lessons",
      'id="create-lesson"' in dash and '<span class="kind-tag">lesson</span>' in dash)
chooser = teacher.get("/api/live/assignments").get_json()["assignments"]
check("the code editor's Go live does not offer lessons",
      SLUG not in [a["slug"] for a in chooser] and chooser)

page = kid.get("/a/" + SLUG).get_data(as_text=True)
check("a student gets the lesson page, not the editor",
      'class="lesson-page' in page and 'id="lesson-body"' in page and "CodeMirror" not in page)
check("  with no answers in it", "[x]" not in page and "nitrogen" not in page)
check("  and the questions there to answer", ("id: " + MC) in page and ("id: " + SA) in page)
check("  at their own pace: given no live lesson to follow", 'live: ""' in page)
check("  with Turn in", 'id="lesson-turnin"' in page)
P.accounts.login_configured = lambda: True
page = stranger.get("/a/" + SLUG).get_data(as_text=True)
check("signed out: Sign in instead, and no answers", "Sign in" in page
      and 'id="lesson-turnin"' not in page and "[x]" not in page)

# ------------------------------------------------------- answering
print("\nAnswering, turning in, and the grade")


def answer(c, qid, response):
    return c.post("/api/quiz/answer", json={"assignment": SLUG, "question": qid,
                                            "response": response})


check("a question is marked", answer(kid, MC, "Condensation").get_json().get("correct") is True)
check("  once", answer(kid, MC, "Runoff").get_json().get("response") == "Condensation")
answer(kid, SA, "oxygen")
answer(kid2, SA, "Nitrogen")
r = kid.post("/api/lesson/%s/turnin" % SLUG)
check("Turn in records it", r.status_code == 200 and r.get_json().get("again") is False)
check("  signed out cannot", stranger.post("/api/lesson/%s/turnin" % SLUG).status_code == 401)
r = kid.post("/api/lesson/%s/turnin" % SLUG)
check("  turning in again moves the time", r.get_json().get("again") is True)
db = P.SessionLocal()
sub = db.query(accounts.Submission).filter_by(assignment_id=item(SLUG).id,
                                              student_id=KID).first()
db.close()
check("  as a Submission with no snapshot", sub is not None and sub.snippet_slug == "")

teacher.post("/api/assignment/%s/out-of" % SLUG, json={"out_of": 3})
page = teacher.get("/teacher/" + SLUG).get_data(as_text=True)
check("the results page lists each student's answers, right and wrong",
      "Condensation" in page and "oxygen" in page
      and 'class="is-right"' in page and 'class="is-wrong"' in page)
check("  with no Open link, there being no code",
      not re.search(r'<a class="linkbtn" href="">Open</a>', page) and "/s/" not in page)
check("  and the points: 2 of 3 from the questions",
      "Questions 2/3" in page, re.findall(r"Questions [^<]*", page))
# A wrong [x] fixed and saved: everyone's marks follow the key as it is now.
teacher.post("/api/lesson/%s" % SLUG, json={"notes": NOTES.replace(
    "- [ ] Evaporation\n- [x] Condensation", "- [x] Evaporation\n- [ ] Condensation")})
db = P.SessionLocal()
earned_now = P._quiz_earned(db, item(SLUG).id).get(KID)
db.close()
check("saving a lesson with the [x] moved remarks answers already given",
      earned_now == 0, "kid's points %r, should be 0 now" % earned_now)
teacher.post("/api/lesson/%s" % SLUG, json={"notes": NOTES})
names = page.split("Started but not turned in")[-1].split("</section>")[0]
check("one who answered but did not turn in is listed as not turned in",
      "B Student" in names)
my = kid.get("/my").get_data(as_text=True)
check("My work shows the lesson, turned in, with no snapshot link",
      "Water" in my and "What I turned in" not in my)

# -------------------------------------------------------------- live
print("\nLive")
page = teacher.get("/teacher/%s/lesson" % SLUG).get_data(as_text=True)
code = re.search(r'liveCode: "([a-z0-9]+)"', page).group(1)
r = teacher.post("/api/live/start", json={"reopen": code, "body": "", "filename": "lesson.md"})
check("Go live reopens the lesson's own code", r.get_json().get("code") == code)
teacher.post("/api/live/%s/push" % code, json={"body": "", "filename": "lesson.md",
                                               "notes": NOTES, "slide": "2/3", "seq": 10})
poll = stranger.get("/api/live/%s?v=-1" % code).get_json()
check("the class gets the notes and the teacher's slide",
      poll.get("slide") == "2/3" and ("id: " + MC) in poll.get("notes", ""))
check("  with no answers in them", "[x]" not in json.dumps(poll) and "nitrogen" not in json.dumps(poll))
page = kid.get("/live/" + code).get_data(as_text=True)
check("the live link gives a student the lesson page, following",
      'class="lesson-page is-live"' in page and ('live: "%s"' % code) in page)
check("  with the teacher's slide to start on", 'slide: "2/3"' in page)
check("  and no answers in it", "[x]" not in page and "nitrogen" not in page)
host = teacher.get("/live/" + code).get_data(as_text=True)
check("its teacher, opening the live link, is sent to present it",
      ("/teacher/%s/lesson?go=live" % SLUG) in host)

# ---------------------------------------------------- the pages' code
print("\nThe pages' code")
lesson_js = open(os.path.join(ROOT, "static", "lesson.js")).read()
teacher_js = open(os.path.join(ROOT, "static", "lesson_teacher.js")).read()
check("a student page snaps only when the teacher moves",
      re.search(r"if \(slide !== teacherSlide\) \{\s*teacherSlide = slide;", lesson_js) is not None)
check("  and only from the live link: the assignment link just shows the slides",
      re.search(r"if \(!L\.live\) \{\s*slides\.show\(L\.notes\);", lesson_js) is not None)
check("  answering into this lesson", "N.setQuizContext({ assignment: L.slug" in lesson_js)
check("the teacher's moves in Present go to the class",
      "present.onMove(function () { pushNow(); });" in teacher_js
      and re.search(r'body: JSON\.stringify\(\{ body: "", filename: "lesson\.md", notes: editor\.getValue\(\),\s*slide: slideStamp\(\)',
                    teacher_js) is not None)
check("  and saving is never as they type",
      "editor.on(\"change\", function () { paintSaved(); redraw(); pushSoon(); });" in teacher_js
      and "save()" not in teacher_js.split('editor.on("change"')[1].split("});")[0])

failed = results.count(False)
print("\n%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                       len(results), failed))
sys.exit(1 if failed else 0)
