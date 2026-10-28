#!/usr/bin/env python3
"""An assignment's notes, edited on its page.

    python3 tools/test_notes_page.py

THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE (like test_notes_follow.py).

WHAT IS BEING GUARDED

  The assignment's page has the notes, to edit there: the whole file, keys
      and all — the page is the teacher's — and the script that edits them.

  Saving there changes the notes and nothing else. The starter's code and
      data files are never sent from that page, and must come through a
      notes save exactly as they were.

  It is an edit like any other: the answer keys are kept for marking, and
      students who already started see the new notes, keys taken out.

  An assignment with no notes gets notes.md; emptied, the file goes again.
      A lesson's notes are lesson.md, and stay even emptied.

  Edit project, at the top, opens the whole project in the editor, for
      the code; a lesson, having none, has no such button.

  Only the teacher who set it can save its notes.

  assignment_notes.js is the same in all three editors (checked when the
      other repos are beside this one, skipped when not).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "notes_page.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org,other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-66s %s" % ("ok" if condition else "FAIL", label, detail))


def add(row):
    db = P.SessionLocal()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def client(uid):
    c = P.app.test_client()
    with c.session_transaction() as s:
        s["uid"] = uid
    return c


def one(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).first()
    finally:
        db.close()


def page_files(html, key):
    at = html.find("%s: " % key)
    if at < 0:
        return None
    return json.JSONDecoder().raw_decode(html, at + len(key) + 2)[0]


# PyIDE keeps the program in `code`; WebIDE and FlaskIDE keep it in `files`
# under ENTRY. The same test runs in all three.
ENTRY = getattr(P, "ENTRY", None)
MAIN = "print('start')\n"


def assignment(slug, files, kind="code"):
    if ENTRY and kind != "lesson":   # a lesson is only its notes, in every editor
        files = dict(files, **{ENTRY: MAIN})
        code = ""
    else:
        code = MAIN
    return add(accounts.Assignment(slug=slug, app=P.APP_NAME, teacher_id=TEACHER, title=slug.upper(),
                                   code=code, files=json.dumps(files), kind=kind))


def files_of(slug):
    return json.loads(one(accounts.Assignment, slug=slug).files)


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
teacher, other, amy = client(TEACHER), client(OTHER), client(AMY)

OLD = "# Week 1\nRead <this> & that.\n"
NEW = "# Week 1\nNew words.\n\n```quiz\nWhat is 2+2?\n- [ ] 3\n- [x] 4\n```\n"
HW = assignment("hw1", {"notes.md": OLD, "words.txt": "cat\n"})

print("the page")
html = teacher.get("/teacher/hw1").get_data(as_text=True)
check("the assignment's page has the notes editor", 'id="notes-src"' in html and 'id="notes-save"' in html)
check("  and a button at the top that opens the whole project in the editor",
      'id="edit-project" href="/teacher/hw1/edit"' in html and html.index('id="edit-project"') < html.index('id="notes-src"'))
check("  which opens it, code and all", teacher.get("/teacher/hw1/edit").status_code == 200)
check("  holding the notes as they are, escaped", "Read &lt;this&gt; &amp; that." in html)
check("  and the script that edits them, saving to this assignment",
      "assignment_notes.js" in html and "/api/assignment/hw1/notes" in html)
check("  which is there to be loaded", os.path.exists(os.path.join(ROOT, "static", "assignment_notes.js")))
ns = page_files(html, "ns")
check("  told which editor's notes script to use", ns in ("PyIDE", "WebIDE", "FlaskIDE"), ns)

print("saving")
SLUG = amy.get("/a/hw1").headers["Location"].rsplit("/", 1)[-1]   # Amy starts before the edit
r = teacher.post("/api/assignment/hw1/notes", json={"notes": NEW})
check("the teacher saves new notes", r.status_code == 200, r.get_data(as_text=True)[:80])
f = files_of("hw1")
check("  which are the assignment's notes now", f.get("notes.md") == NEW)
check("  and nothing else changed: data files", f.get("words.txt") == "cat\n")
row = one(accounts.Assignment, slug="hw1")
check("  …nor the code", (f.get(ENTRY) if ENTRY else row.code) == MAIN)
db = P.SessionLocal()
keys = db.query(accounts.QuizQuestion).filter_by(assignment_id=HW).count()
db.close()
check("the question's answer key is kept for marking", keys == 1, keys)
seen = (page_files(amy.get("/p/" + SLUG).get_data(as_text=True), "files") or {}).get("notes.md", "")
check("a student who had started sees the new notes", "New words." in seen, seen[:30])
check("  with the answer key taken out", "[x]" not in seen and "- [ ] 4" in seen)

print("files")
assignment("hw2", {"words.txt": "x\n"})
teacher.post("/api/assignment/hw2/notes", json={"notes": "# Hello\n"})
check("an assignment with no notes gets notes.md", files_of("hw2").get("notes.md") == "# Hello\n")
assignment("hw3", {"guide.md": "old\n", "notes.md": "second\n"})
teacher.post("/api/assignment/hw3/notes", json={"notes": "new\n"})
check("  one with notes keeps their file's name (the first .md)",
      files_of("hw3").get("guide.md") == "new\n" and files_of("hw3").get("notes.md") == "second\n")
teacher.post("/api/assignment/hw2/notes", json={"notes": "  \n"})
check("emptied, the notes file goes", "notes.md" not in files_of("hw2") and "words.txt" in files_of("hw2"))
# A lesson with no notes yet: its notes are still lesson.md, not notes.md.
assignment("les", {}, kind="lesson")
check("a lesson's page points to its lesson page instead",
      'id="notes-src"' not in teacher.get("/teacher/les").get_data(as_text=True))
check("  and no Edit project, a lesson having no code",
      'id="edit-project"' not in teacher.get("/teacher/les").get_data(as_text=True))
teacher.post("/api/assignment/les/notes", json={"notes": "# A lesson\n"})
check("  its notes are lesson.md", files_of("les").get(P.LESSON_FILE) == "# A lesson\n" and "notes.md" not in files_of("les"))
teacher.post("/api/assignment/les/notes", json={"notes": ""})
check("  and stay lesson.md, even emptied", files_of("les").get(P.LESSON_FILE) == "")
r = teacher.post("/api/assignment/les/notes", json={"notes": "x" * (P.MAX_FILE_BYTES + 10)})
check("  too long, refused for a lesson too", r.status_code == 413 and files_of("les").get(P.LESSON_FILE) == "", r.status_code)

print("who may")
r = other.post("/api/assignment/hw1/notes", json={"notes": "mine now"})
check("another teacher can't save its notes", r.status_code in (403, 404) and files_of("hw1")["notes.md"] == NEW, r.status_code)
r = amy.post("/api/assignment/hw1/notes", json={"notes": "mine now"})
check("a student can't", r.status_code == 403 and files_of("hw1")["notes.md"] == NEW, r.status_code)
r = teacher.post("/api/assignment/hw1/notes", json={"notes": "x" * (P.MAX_FILE_BYTES + 10)})
check("notes too long are refused, in words", r.status_code == 413 and files_of("hw1")["notes.md"] == NEW, r.status_code)
r = teacher.post("/api/assignment/hw1/notes", json={})
check("nothing sent saves nothing", r.status_code == 400 and files_of("hw1")["notes.md"] == NEW)

print("the same in all three")
mine = open(os.path.join(ROOT, "static", "assignment_notes.js"), "rb").read()
home = os.path.expanduser("~")
for repo in ("pyide", "webide", "flaskide"):
    other_copy = os.path.join(home, repo, "static", "assignment_notes.js")
    if os.path.realpath(os.path.join(home, repo)) == os.path.realpath(ROOT) or not os.path.isdir(os.path.join(home, repo)):
        continue
    check("assignment_notes.js is the same as %s's" % repo,
          os.path.exists(other_copy) and open(other_copy, "rb").read() == mine)

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
