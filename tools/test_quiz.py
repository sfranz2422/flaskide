"""Questions in the notes: the format, the key kept off the wire, and the marks.

    python3 tools/test_quiz.py

A teacher writes a ```quiz block in an assignment's notes; students answer it
once, on the page, and are told at once whether they were right; the points
go on top of the teacher's score and Sync sends the two together.

WHAT IS ACTUALLY BEING GUARDED

  The answer key never reaches a student.
      The notes are copied into every student's draft and ride on every live
      push, so a key left in them is a key anyone can read in the page
      source. It is taken out at each exit, and a missed exit leaks it with
      no sign at all — the page looks exactly the same. So every exit is
      opened here as a student and searched for the key. A new route that
      hands an assignment's files out needs a check in that section.

  One try.
      The second answer to a question is refused, and the reply is the first
      one's result. Two quick clicks across two workers cannot both count.

  The browser reads a block exactly as the server does.
      quiz.parse and notes.js's parseQuiz are two copies of one reader. If
      they disagree, the question shown is not the question marked. node runs
      the browser's copy on the same blocks.

  The grade is the score plus the questions.
      On the dashboard, in what Sync sends, and on the student's My work page.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)    # this app's folder

DB = os.path.join(tempfile.mkdtemp(), "quiz.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402
import quiz                                                  # noqa: E402

ENTRY = 'app.py'

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


def leaks(text):
    """What would give the key away: an [x], an answer: line, or the words
    that only appear in the key."""
    text = text if isinstance(text, str) else json.dumps(text)
    found = [w for w in ("[x]", "[X]", "answer:", "ZEBRA") if w in text]
    return found


# The notes every check below uses. The short answer's key is a word found
# nowhere else, so finding it anywhere is finding the key.
NOTES = """# Loops

Read this first.

```quiz
What does len("hello") return?
- [ ] "hello"
- [x] 5
- [ ] 4
points: 2
```

Then this.

```quiz
Which animal is the secret?
answer: zebra
answer: ZEBRA crossing
```
"""

# ------------------------------------------------------------ the format
print("\nThe format")

keys = quiz.keys(NOTES)
check("two questions are found", len(keys) == 2, len(keys))
mc = keys[0] if keys else {}
sa = keys[1] if len(keys) > 1 else {}
check("  the first is multiple choice, 5 marked right, 2 points",
      mc.get("kind") == "choice" and mc.get("correct") == ["5"]
      and mc.get("choices") == ['"hello"', "5", "4"] and mc.get("points") == 2,
      repr(mc))
check("  the second is short answer, two answers, 1 point",
      sa.get("kind") == "text" and sa.get("answers") == ["zebra", "ZEBRA crossing"]
      and sa.get("points") == 1, repr(sa))

red = quiz.redact(NOTES)
check("redacting takes every key out", not leaks(red), leaks(red))
check("  and puts each question's id in",
      ("id: " + mc.get("qid", "?")) in red and ("id: " + sa.get("qid", "?")) in red)
check("  and keeps the question, its choices and its points",
      'What does len("hello") return?' in red and '- [ ] 5' in red
      and "points: 2" in red)
check("  and leaves the rest of the notes alone",
      red.startswith("# Loops\n\nRead this first.\n") and "Then this." in red)
check("redacting twice is redacting once",
      quiz.redact(red) == red, "a second pass would drop the ids")
# A data file is the program's input, byte for byte, even when it happens to
# hold something shaped like a question.
DATA = "```quiz\nQ?\n- [x] a\n- [ ] b\n```\n"
check("files: only notes are redacted",
      quiz.redact_files({"notes.md": NOTES, "data.txt": DATA})
      == {"notes.md": red, "data.txt": DATA})

inner = quiz.parse("What prints?\n~~~python\n- [x] not a choice\nanswer: nor this\n"
                   "~~~\n- [x] 1\n- [ ] 2")
check("inside a ~~~ fence nothing is a choice or an answer",
      inner["choices"] == ["1", "2"] and inner["answers"] == []
      and "- [x] not a choice" in inner["prompt"], repr(inner))

example = "```markdown\n```quiz\nQ?\n- [x] a\n- [ ] b\n```\n```\n"
check("a ```quiz shown inside another code fence is an example, not a question",
      quiz.keys(example) == [] and quiz.redact(example) == example)

broken = quiz.parse("Pick one\n- [x] only")
check("one choice is not a question, so it gets no id", broken["qid"] == "")
check("  and redacting it still takes the [x] out",
      "[x]" not in quiz.redact("```quiz\nPick one\n- [x] only\n```"))

a = quiz.parse("Q?\n- [x] a\n- [ ] b")
b = quiz.parse("Q?\n- [ ] a\n- [x] b\npoints: 3")
c = quiz.parse("Q, reworded?\n- [x] a\n- [ ] b")
check("moving the [x] or the points keeps the question's id",
      a["qid"] and a["qid"] == b["qid"])
check("  rewording it gives a new one", c["qid"] and c["qid"] != a["qid"])

check("short answers ignore case, spacing and a full stop",
      quiz.is_correct("text", [], ["while"], "  While. "))
check("  and nothing else", not quiz.is_correct("text", [], ["print()"], "print"))
check("a choice is right only if it is a marked one",
      quiz.is_correct("choice", ["5"], [], "5")
      and not quiz.is_correct("choice", ["5"], [], "4"))

# --------------------------------------------- the browser reads it the same
print("\nThe browser's reader")

notes_js = open(os.path.join(PYIDE, "static", "notes.js")).read()
samples = [
    "What?\n- [ ] a\n- [x] b\npoints: 2",
    "Which keyword?\nanswer: while\nanswer: While loop",
    "What prints?\n~~~python\n- [x] not a choice\n~~~\n* [X] 1\n+ [ ] 2",
    "\r\nCRLF?\r\n- [x] yes\r\n- [ ] no\r\npoint: 1.5\r\n",
    "id: 0123456789ab\npoints: 2\nRedacted?\n- [ ] a\n- [ ] b",
    "Answer: is not an answer line when it is the question?\nanswer:   \n",
    "Explain why.\nType: Long\npoints: 4\n- [x] ignored\nanswer: ignored too",
    "id: 0123456789ab\npoints: 4\ntype: essay\nRedacted long?",
]
if shutil.which("node"):
    harness = "var window = {};\n" + notes_js + """
var N = window.FlaskIDENotes;
console.log(JSON.stringify(%s.map(function (s) { return N.parseQuiz(s); })));
""" % json.dumps(samples)
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    try:
        got = json.loads(res.stdout)
    except ValueError:
        got = []
    check("node ran parseQuiz", len(got) == len(samples), res.stderr[-200:])
    for i, (s, js) in enumerate(zip(samples, got)):
        py = quiz.parse(s)
        same = (js["prompt"] == py["prompt"] and js["choices"] == py["choices"]
                and js["correct"] == py["correct"] and js["answers"] == py["answers"]
                and js["points"] == py["points"] and js["kind"] == py["kind"]
                and js["id"] == py["given_id"] and js["hasKey"] == py["has_key"])
        check("  block %d reads the same in both" % (i + 1), same,
              "" if same else "js=%r py=%r" % (js, py))
else:
    check("node is available to run parseQuiz", False, "brew install node")

# ---------------------------------------------------------- the key stays home
print("\nThe key never reaches a student")

TEACHER = add_user("t1", "teacher@example.org", "Mr Franz")
KID = add_user("s1", "kid@example.org", "A Student")
KID2 = add_user("s2", "kid2@example.org", "B Student")
KID3 = add_user("s3", "kid3@example.org", "C Student")
teacher, kid, kid2, kid3 = client(TEACHER), client(KID), client(KID2), client(KID3)
stranger = client()

r = teacher.post("/api/assignment", json={
    "title": "Loops", "files": {ENTRY: 'from flask import Flask\n', "notes.md": NOTES}})
SLUG = r.get_json()["slug"]

page = teacher.get("/teacher/%s/edit" % SLUG).get_data(as_text=True)
check("the teacher's own edit page has the key (so these checks can fail)",
      "ZEBRA" in page and "[x]" in page)

page = stranger.get("/a/" + SLUG).get_data(as_text=True)
check("the assignment link, signed out", not leaks(page), leaks(page))

r = kid.get("/a/" + SLUG)
page = kid.get(r.headers["Location"]).get_data(as_text=True)
check("the assignment link, signed in", not leaks(page), leaks(page))
check("  and the question is there, with its id",
      ("id: " + mc["qid"]) in page)
check("  and the copy still counts as untouched, for the rescue",
      "draftFresh: true" in page,
      "every sign-in would ask about restoring work")


def draft_of(uid):
    db = P.SessionLocal()
    try:
        d = db.query(accounts.Draft).filter_by(owner_id=uid).first()
        return d.files if d else ""
    finally:
        db.close()


check("  the saved copy itself", not leaks(draft_of(KID)) and draft_of(KID),
      leaks(draft_of(KID)))

r = teacher.post("/api/live/start", json={
    "body": NOTES, "filename": "notes.md", "title": "Loops", "assignment": SLUG})
CODE = r.get_json()["code"]
poll = stranger.get("/api/live/" + CODE).get_json()
check("a live lesson that starts on the notes tab", not leaks(poll), leaks(poll))

teacher.post("/api/live/%s/push" % CODE, json={
    "body": NOTES, "filename": "notes.md", "notes": NOTES, "seq": 10})
poll = stranger.get("/api/live/" + CODE).get_json()
check("a live push, notes and open file", not leaks(poll), leaks(poll))
check("  and the class still gets the questions",
      ("id: " + sa["qid"]) in poll.get("notes", "")
      and ("id: " + sa["qid"]) in poll.get("body", ""))

page = kid2.get("/live/" + CODE).get_data(as_text=True)
check("the live page's starter, for a student with no copy yet",
      not leaks(page), leaks(page))
page = stranger.get("/live/" + CODE).get_data(as_text=True)
check("  and signed out", not leaks(page), leaks(page))

kid3.post("/api/live/%s/keep" % CODE, json={"code": 'from flask import Flask\n'})
check("saving from the live page with no copy yet",
      not leaks(draft_of(KID3)), leaks(draft_of(KID3)))
check("  and that copy really has the notes, questions and all",
      ("id: " + mc["qid"]) in draft_of(KID3),
      "without them the check above passes on an empty copy")

# ---------------------------------------------------------------- answering
print("\nAnswering")

def answer(c, qid, response, slug=None):
    r = c.post("/api/quiz/answer", json={"assignment": slug or SLUG,
                                         "question": qid, "response": response})
    return r.status_code, r.get_json()

st, d = answer(stranger, mc["qid"], "5")
check("signed out cannot answer", st == 401, st)

st, d = answer(kid, mc["qid"], "4")
check("a wrong answer is marked wrong, at once",
      st == 200 and d["correct"] is False and d["earned"] == 0 and d["points"] == 2,
      repr(d))
check("  and the reply does not say what was right",
      "5" not in json.dumps({k: v for k, v in d.items() if k != "points"}),
      repr(d))
st, d = answer(kid, mc["qid"], "5")
check("a second try is not taken", st == 200 and d["correct"] is False
      and d["response"] == "4" and d.get("already"), repr(d))

st, d = answer(kid, sa["qid"], "  Zebra. ")
check("a short answer is marked kindly", d.get("correct") is True
      and d.get("earned") == 1, repr(d))

st, d = answer(kid, "ffffffffffff", "5")
check("a question that isn't there is refused", st == 404, st)

st, d = answer(teacher, mc["qid"], "5")
check("the teacher trying their own question is marked",
      st == 200 and d.get("correct") is True and d.get("practice"), repr(d))

mine = kid.get("/api/quiz/%s/mine" % SLUG).get_json()["answers"]
check("the page is told what was already answered",
      set(mine) == {mc["qid"], sa["qid"]} and mine[mc["qid"]]["response"] == "4"
      and mine[sa["qid"]]["correct"] is True, repr(mine))
mine_t = teacher.get("/api/quiz/%s/mine" % SLUG).get_json()["answers"]
check("  and the teacher's try was not recorded", mine_t == {}, repr(mine_t))

# A question the teacher adds mid-lesson, never saved to the assignment.
LIVE_ONLY = "```quiz\nAdded during class?\n- [x] yes\n- [ ] no\n```"
teacher.post("/api/live/%s/push" % CODE, json={
    "body": "print(1)", "filename": "main.py", "notes": LIVE_ONLY, "seq": 20})
live_q = quiz.parse("Added during class?\n- [x] yes\n- [ ] no")["qid"]
st, d = answer(kid2, live_q, "yes")
check("a question pushed live and never saved can be answered",
      st == 200 and d.get("correct") is True, repr(d))

# ------------------------------------------------------------------ grades
print("\nThe grade")

teacher.post("/api/assignment/%s/out-of" % SLUG, json={"out_of": 10})
r = kid.post("/api/submit", json={"draft": json.loads(json.dumps(
    P.SessionLocal().query(accounts.Draft).filter_by(owner_id=KID).first().slug)),
    "files": json.loads(draft_of(KID))})
check("the student turns in", r.status_code == 200, r.status_code)


def sub_id(uid):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Submission).filter_by(student_id=uid).first().id
    finally:
        db.close()


r = teacher.post("/api/assignment/%s/feedback" % SLUG,
                 json={"submission": sub_id(KID), "feedback": "", "score": "5"})
d = r.get_json()
check("score 5, plus 1 from the questions, is 6", d.get("score") == "5"
      and d.get("total") == "6", repr(d))

page = teacher.get("/teacher/" + SLUG).get_data(as_text=True)
check("the dashboard shows the questions' points beside the score",
      "Questions 1/3" in page and '<span class="fb-total">6</span>' in page,
      re.findall(r"Questions [^<]*", page))
check("  and how many questions the notes have",
      "<strong>2 questions</strong>" in page and "<strong>3 points</strong>" in page)
names = page.split("Started but not turned in")[-1].split("</section>")[0]
check("  a student who only answered live is listed, with their points",
      "B Student" in names and "questions 1/3" in names, names.strip()[:200])

my = kid.get("/my").get_data(as_text=True)
check("My work shows the total and where it came from",
      "6 / 10" in my and "1 from the questions" in my)

# Sync, with Classroom stood in for.
sent = []
db = P.SessionLocal()
db.add(accounts.ClassroomPost(assignment_id=db.query(accounts.Assignment)
                              .filter_by(slug=SLUG).first().id,
                              course_id="c1", course_name="P4", work_id="w1"))
db.commit()
db.close()
P._classroom_token = lambda db, user: ("token", "")


def fake_lists(db, item, access):
    post = P._posts(db, item)[0]
    return [(post, {"kid@example.org": "cs1"})], [], set(), ""


P._class_lists = fake_lists


def fake_api(method, url, access, body=None, params=None):
    sent.append(body)
    return 200, {}


P._google_api = fake_api
d = teacher.post("/api/assignment/%s/classroom/sync" % SLUG).get_json()
check("Sync sends the score plus the questions", sent == [{"draftGrade": 6.0}],
      repr(sent))
check("  and calls it synced", d.get("synced") == [sub_id(KID)], repr(d))

# Fixing a wrong key fixes everyone's marks.
FIXED = NOTES.replace("- [x] 5\n- [ ] 4", "- [ ] 5\n- [x] 4")
teacher.post("/api/assignment/" + SLUG, json={
    "title": "Loops", "files": {ENTRY: 'from flask import Flask\n', "notes.md": FIXED}})
r = teacher.post("/api/assignment/%s/feedback" % SLUG,
                 json={"submission": sub_id(KID), "feedback": ""})
d = r.get_json()
check("moving the [x] remarks answers already given (4 is now right: 5+1+2)",
      d.get("total") == "8", repr(d))
check("  and the grade in Classroom is now out of date", d.get("synced") is False)

# One try holds when the assignment is closed, too — and no new answers.
db = P.SessionLocal()
db.query(accounts.Assignment).filter_by(slug=SLUG).update({"closed": 1})
db.commit()
db.close()
st, d = answer(kid3, mc["qid"], "4")
check("a closed assignment takes no new answers", st == 403, st)

# Deleting.
r = teacher.post("/api/assignment", json={
    "title": "Spare", "files": {ENTRY: 'from flask import Flask\n', "notes.md": LIVE_ONLY}})
SPARE = r.get_json()["slug"]
answer(kid, live_q, "no", slug=SPARE)
r = teacher.delete("/api/assignment/" + SPARE)
check("an assignment whose questions were answered cannot be deleted",
      r.status_code == 409, r.status_code)
r = teacher.post("/api/assignment", json={
    "title": "Unused", "files": {ENTRY: 'from flask import Flask\n', "notes.md": LIVE_ONLY}})
db = P.SessionLocal()
unused_id = db.query(accounts.Assignment).filter_by(
    slug=r.get_json()["slug"]).first().id
had_keys = db.query(accounts.QuizQuestion).filter_by(
    assignment_id=unused_id).count()
db.close()
r = teacher.delete("/api/assignment/" + r.get_json()["slug"])
db = P.SessionLocal()
left = db.query(accounts.QuizQuestion).filter_by(assignment_id=unused_id).count()
db.close()
# SQLite does not enforce foreign keys, so the delete succeeds here either
# way; on Postgres a key left behind makes it fail. Hence counting the rows.
check("  one nobody answered can, keys and all",
      r.status_code == 200 and had_keys == 1 and left == 0,
      "status %s, keys %s before and %s after" % (r.status_code, had_keys, left))

# ------------------------------------------------------- long responses
print("\nLong responses")

LONG_Q = "Explain why a loop stops.\ntype: long\npoints: 4\n- [x] not a key\nanswer: nor this"
lq = quiz.parse(LONG_Q)
check("type: long is a long response, answerable with no key",
      lq["kind"] == "long" and lq["qid"] and lq["points"] == 4
      and lq["correct"] == [] and lq["answers"] == [] and lq["choices"] == [], repr(lq))
LONG_NOTES = ("# Essay\n\n```quiz\n" + LONG_Q + "\n```\n\n```quiz\nPick b\n"
              "- [ ] a\n- [x] b\n```\n")
red = quiz.redact(LONG_NOTES)
check("  redacted, it keeps type: long and gets its id",
      "type: long" in red and ("id: " + lq["qid"]) in red, red[:80])
check("  and nothing it was written with leaks as a key",
      "not a key" not in red and "nor this" not in red)
check("  a second pass changes nothing", quiz.redact(red) == red)
again = quiz.parse(red.split("```quiz\n")[1].split("```")[0])
check("  the student's copy reads as the same long question",
      again["kind"] == "long" and again["given_id"] == lq["qid"]
      and again["qid"] == lq["qid"], repr(again))

dirty = ('<p onclick="x()">Hi <b style="color:red">there</b></p><script>alert(1)</script>'
         '<a href="javascript:alert(2)">link</a><img src=x onerror=alert(3)>'
         '<ul><li>one</li></ul><iframe src="//evil"></iframe>&lt;b&gt;')
cleaned = quiz.clean_html(dirty)
check("clean_html keeps the toolbar's tags and nothing else",
      cleaned == "<p>Hi <b>there</b></p>link<ul><li>one</li></ul>&lt;b&gt;", cleaned)
check("  plain_text sees through it", quiz.plain_text("<p>a &amp; b</p><p><br></p>") == "a & b")

r = teacher.post("/api/assignment", json={
    "title": "Essay", "files": {ENTRY: 'from flask import Flask\n', "notes.md": LONG_NOTES}})
ESSAY = r.get_json()["slug"]
CLASS = teacher.post("/api/class", json={"name": "P4 Intro"}).get_json()["id"]
teacher.post("/api/assignment/%s/class" % ESSAY, json={"class": CLASS})

st, d = answer(kid, lq["qid"], "<p><br></p>", slug=ESSAY)
check("an empty long response is refused", st == 400, st)
st, d = answer(kid, lq["qid"], dirty, slug=ESSAY)
check("a long response is taken, and not marked right or wrong",
      st == 200 and d.get("kind") == "long" and d.get("graded") is False
      and d.get("correct") is None and d.get("points") == 4, repr(d))
db = P.SessionLocal()
kept = db.query(accounts.QuizAnswer).filter_by(student_id=KID, qid=lq["qid"]).first()
kept = kept.response if kept else ""
db.close()
check("  it is cleaned before it is kept", kept == cleaned, kept)
st, d = answer(kid, lq["qid"], "<p>A better answer</p>", slug=ESSAY)
check("  and one try holds for it too",
      d.get("response") == cleaned and d.get("already"), repr(d))
st, d = answer(teacher, lq["qid"], "<p>Mine</p>", slug=ESSAY)
check("the teacher's own try is not recorded",
      st == 200 and d.get("practice") and d.get("graded") is False, repr(d))
mine = kid.get("/api/quiz/%s/mine" % ESSAY).get_json()["answers"]
check("the page is told it is waiting for the teacher",
      mine.get(lq["qid"], {}).get("graded") is False, repr(mine))

page = teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True)
check("not turned in yet: no 'needs grading' (it's not the teacher's yet)",
      "Needs grading" not in page)

kid.get("/a/" + ESSAY)
db = P.SessionLocal()
essay_id = db.query(accounts.Assignment).filter_by(slug=ESSAY).first().id
essay_draft = db.query(accounts.Draft).filter_by(owner_id=KID, assignment_id=essay_id).first()
db.close()
r = kid.post("/api/submit", json={"draft": essay_draft.slug,
                                   "files": json.loads(essay_draft.files)})
check("the student turns it in", r.status_code == 200, r.status_code)

# As if it had been stored by a route that forgot to clean it: the page
# must clean it again on the way out, or this check could never fail.
db = P.SessionLocal()
db.query(accounts.QuizAnswer).filter_by(assignment_id=essay_id, student_id=KID).update(
    {"response": dirty})
db.commit()
db.close()

page = teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True)
check("the class page says it needs grading", "Needs grading · 1" in page)
dash = teacher.get("/teacher").get_data(as_text=True)
check("  so does the class's card on the dashboard", "1 to grade" in dash)
page = teacher.get("/teacher/" + ESSAY).get_data(as_text=True)
check("the assignment's page lists the answer to mark",
      'class="long-answer is-waiting"' in page and "<b>there</b>" in page
      and 'data-qid="%s"' % lq["qid"] in page)
check("  cleaned on the way out as well", not re.search(
    r"<script|onerror|onclick|javascript:|<iframe|<img", page.split("lesson-answers")[1]
    .split("</ol>")[0]))
check("  and its header says how many wait", re.search(
    r'id="needs-grading"[^>]*>1 to grade<', page) is not None)

GRADE = {"assignment": ESSAY, "student": KID, "question": lq["qid"], "score": "3"}
r = kid.post("/api/quiz/grade", json=GRADE)
check("a student cannot mark", r.status_code == 403, r.status_code)
r = client(add_user("t2", "other@example.org", "Not Teacher")).post("/api/quiz/grade", json=GRADE)
check("  nor anyone who isn't a teacher", r.status_code == 403, r.status_code)
# Answered, so the only thing refusing it is that it has a key.
pick_b = quiz.keys(LONG_NOTES)[1]["qid"]
answer(kid, pick_b, "b", slug=ESSAY)
r = teacher.post("/api/quiz/grade", json=dict(GRADE, question=pick_b))
check("a question marked by its key cannot be marked by hand", r.status_code == 404, r.status_code)
r = teacher.post("/api/quiz/grade", json=dict(GRADE, score="lots"))
check("a score that isn't a number is refused", r.status_code == 400, r.status_code)

d = teacher.post("/api/quiz/grade", json=GRADE).get_json()
check("the teacher marks it 3 (plus 1 for picking b)", d.get("score") == "3" and d.get("quiz") == "4"
      and d.get("waiting") == 0, repr(d))
check("  and it is in the grade", P._quiz_earned(P.SessionLocal(), essay_id).get(KID) == 4)
mine = kid.get("/api/quiz/%s/mine" % ESSAY).get_json()["answers"][lq["qid"]]
check("  the student is told their mark", mine.get("graded") is True
      and mine.get("earned") == 3, repr(mine))
check("  and what they wrote comes back cleaned", mine.get("response") == cleaned,
      mine.get("response"))
page = teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True)
check("  and 'needs grading' is gone", "Needs grading" not in page)
d = teacher.post("/api/quiz/grade", json=dict(GRADE, score="")).get_json()
check("emptying the mark puts it back to waiting",
      d.get("score") == "" and d.get("waiting") == 1, repr(d))

# ------------------------------------------------------------ the wiring
print("\nThe wiring")

app_js = open(os.path.join(PYIDE, "static", "app.js")).read()
live_js = open(os.path.join(PYIDE, "static", "live.js")).read()
css = open(os.path.join(PYIDE, "static", "style.css")).read()
check("the editor says which assignment answers go to",
      "setQuizContext({ assignment: cfg.assignmentSlug," in app_js)
check("so does the live page",
      "setQuizContext({ assignment: L.assignment," in live_js)
check("one question that fails to build does not take the notes with it",
      re.search(r"try \{\s*code\.parentNode\.replaceWith\(buildQuiz\(parseQuiz\(",
                notes_js) is not None,
      "the whole pane said 'could not be displayed' instead")
check("rendered notes turn quiz blocks into questions",
      re.search(r"hardenLinks\(target\);\s*enhanceQuizzes\(target\);", notes_js)
      is not None)
check("the answer box can be typed in under the no-select rule",
      re.search(r"body:not\(\.is-authoring\) \.notes-body \.quiz-text,[^{]*\{\s*"
                r"user-select: text;\s*-webkit-user-select: text;", css) is not None,
      "Safari will not type into it otherwise")
check("  nor can the long response's box",
      re.search(r"body:not\(\.is-authoring\) \.notes-body \.quiz-long-box,[^{]*\{\s*"
                r"user-select: text;", css) is not None)
lesson_js = open(os.path.join(PYIDE, "static", "lesson.js")).read()
check("the slide keys leave a long response's box alone",
      "isContentEditable" in lesson_js and lesson_js.count("if (typing(e)) return;") == 2,
      "← and → turned the slide mid-sentence")
check("what a student writes is cleaned in the browser before it is sent",
      re.search(r"var value = area\.textContent\.trim\(\) \? cleanLong\(", notes_js)
      is not None)

# ------------------------------------------- the notes pane in the editor
print("\nThe notes pane in FlaskIDE's editor")

# FlaskIDE's editor had a notes pane in its page that nothing ever filled, so
# a .md opened as raw text and its questions could not be answered. The notes
# now take the preview's place on the right (app.js, showNotes); there is no
# room for both. These read the code, because running the editor needs a
# browser: each line is the one whose loss would quietly bring that back.
page_html = open(os.path.join(PYIDE, "templates", "index.html")).read()
check("the Notes | Preview switch is in both of the right pane's heads",
      page_html.count('class="view-switch"') == 2)
check("  and hides properly (it sets display, so [hidden] alone would not)",
      re.search(r"\.view-switch\[hidden\]\s*\{\s*display:\s*none", css) is not None)
_open = re.search(r"function openFile\(name\) \{(.*?)\n  \}\n", app_js, re.S)
_open = _open.group(1) if _open else ""
check("a .md tab shows the notes and leaves the editor on the code",
      re.search(r"if \(isNotes\(name\)\) \{[^}]*showNotes\(name\);\s*return;", _open)
      is not None, "it would open the markdown as text again")
check("  and a code tab brings the preview back",
      _open.rstrip().endswith("loadIntoEditor(name);\n    showPreview();"))
check("Run with the notes up shows the preview first",
      re.search(r"async function run\(\) \{\s*if \(running\) return;[^}]*?"
                r"if \(notesShown\) showPreview\(\);", app_js) is not None,
      "Run would draw into a pane nobody can see")
check("an assignment opens on its notes, except for its author",
      "if (!cfg.authoring && notesFiles().length) showNotes(notesFiles()[0]);" in app_js)
check("the author's Edit source re-renders the notes as they type",
      re.search(r"if \(mdSource && notesShown === current\) \{\s*"
                r"slidesView\(\)\.show\(files\[current\]\);", app_js) is not None)
check("a live lesson shows the class the notes while they are on show",
      app_js.count("var name = notesShown || current;") == 2,
      "the mirror would show code while the teacher talks to the notes")
check("replacing the files (rescue, a starter) re-checks the notes on show",
      app_js.count("refreshNotes();") == 2)

failed = results.count(False)
print("\n%s (%d checks, %d failed)" % (
    "ALL PASSED" if not failed else "SOME FAILED", len(results), failed))
sys.exit(1 if failed else 0)
