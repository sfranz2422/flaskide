#!/usr/bin/env python3
"""The tutorial library (library.py): one tutorial, many assignments.

    python3 tools/test_library.py

THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE (like library.py itself).

WHAT IS BEING GUARDED

  Notes from before the library are taken into it the first time it opens:
      identical notes (a period's copies) become ONE tutorial linked to all
      of them, and nothing is taken twice.

  Saving a tutorial writes it into every assignment linked to it — their
      notes, and their answer keys — and a student already working sees the
      new notes with the answers taken out.

  The library is the only place notes are edited: the assignment page has
      no editor (its Tutorial box links there), the old notes route is
      gone, and the editor's and the lesson page's saves leave notes alone.

  Linking, unlinking (the notes stay, its own), deleting (the same, for
      every assignment that used it), duplicating, downloading, a new
      tutorial made for an assignment, a rename.

  Uploading many files at once: added, REPLACED by title (links kept, so
      the change reaches every assignment), unchanged, skipped.

  A copy of an assignment for another period keeps the link.

  Only the teacher whose library it is: never another teacher, a student
      or anyone signed out — and the library hands a student nothing.
"""
import base64
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "library.db")
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


def client(uid=None):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


def one(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).first()
    finally:
        db.close()


def count(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).count()
    finally:
        db.close()


ENTRY = getattr(P, "ENTRY", None)   # WebIDE/FlaskIDE keep the program in files
MAIN = "print('start')\n"


def assignment(slug, notes, kind="code"):
    files = {"lesson.md" if kind == "lesson" else "notes.md": notes} if notes is not None else {}
    if ENTRY and kind != "lesson":
        files[ENTRY] = MAIN
    return add(accounts.Assignment(slug=slug, app=P.APP_NAME, teacher_id=TEACHER, title=slug.upper(),
                                   code="" if ENTRY else MAIN, files=json.dumps(files), kind=kind))


def notes(slug):
    a = one(accounts.Assignment, slug=slug)
    return a.file_map().get("lesson.md" if a.kind == "lesson" else "notes.md")


def library(c):
    return c.get("/api/library").get_json()


def item_titled(c, title):
    return next((i for i in library(c)["items"] if i["title"] == title), None)


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
teacher, other, amy, stranger = client(TEACHER), client(OTHER), client(AMY), client()

LOOPS = "# Loops\n\nRead this.\n\n```quiz\nWhat is 2+2?\n- [ ] 3\n- [x] 4\n```\n"
assignment("p2", LOOPS)
assignment("p5", LOOPS)               # another period's copy, word for word
assignment("vars", "# Variables\n\nName things.\n")
assignment("bare", None)              # no notes at all
assignment("les", "# A lesson\n\nHello.\n", kind="lesson")

print("the import")
lib = library(teacher)
titles = sorted(i["title"] for i in lib["items"])
check("notes from before the library become tutorials", titles == ["A lesson", "Loops", "Variables"], titles)
loops = item_titled(teacher, "Loops")
check("  identical notes are ONE tutorial, linked to both periods",
      sorted(u["title"] for u in loops["uses"]) == ["P2", "P5"], loops["uses"])
check("  an assignment with no notes is left alone", one(accounts.Assignment, slug="bare").tutorial_id is None)
library(teacher)
check("  and nothing is taken twice", count(accounts.LibraryItem, teacher_id=TEACHER) == 3)

print("the pages")
html = teacher.get("/teacher/tutorials").get_data(as_text=True)
check("the library page", "library.js" in html and 'id="lib-upload"' in html)
html = teacher.get("/teacher/tutorials/%s/edit" % loops["slug"]).get_data(as_text=True)
check("a tutorial's page edits it, saving to the library",
      'id="notes-src"' in html and '"/api/library/%s"' % loops["slug"] in html and "Read this." in html)
check("  and says where it's used", "P2" in html and "P5" in html)
html = teacher.get("/teacher/p2").get_data(as_text=True)
check("an assignment's page has its Tutorial box, and no notes editor",
      'id="tutorial-edit"' in html and "/teacher/tutorials/%s/edit" % loops["slug"] in html and 'id="notes-src"' not in html)
check("  saying it's in one other assignment", "also in 1 other assignment" in html)
check("  and still the button that opens the whole project", 'id="edit-project"' in html)
check("the dashboard links to the library", "/teacher/tutorials" in teacher.get("/teacher").get_data(as_text=True))

print("one place to edit")
check("the old notes route is gone",
      teacher.post("/api/assignment/p2/notes", json={"notes": "# Hacked\n"}).status_code in (404, 405)
      and notes("p2") == LOOPS)
# PyIDE sends the program as `code`; WebIDE and FlaskIDE keep it in files.
sent = ({"title": "P2", "files": {ENTRY: MAIN, "notes.md": "# Editor\n"}} if ENTRY
        else {"title": "P2", "code": MAIN, "files": {"notes.md": "# Editor\n"}})
r = teacher.post("/api/assignment/p2", json=sent)
check("the editor's save leaves the notes alone", r.status_code == 200 and notes("p2") == LOOPS, r.status_code)
teacher.post("/api/lesson/les", json={"title": "Les", "notes": "# Lesson page\n"})
check("the lesson page's save leaves them alone too", notes("les") == "# A lesson\n\nHello.\n")

print("saving writes through")
SLUG = amy.get("/a/p2").headers.get("Location", "").rsplit("/", 1)[-1]
NEW = "# Loops\n\nNEW words.\n\n```quiz\nWhat is 3+3?\n- [ ] 5\n- [x] 6\n```\n"
r = teacher.post("/api/library/" + loops["slug"], json={"body": NEW})
check("saving a tutorial says how many assignments it changed", r.status_code == 200 and r.get_json().get("updated") == 2, r.get_json())
check("  both periods' notes are the new text", notes("p2") == NEW and notes("p5") == NEW)
p2, p5 = one(accounts.Assignment, slug="p2"), one(accounts.Assignment, slug="p5")
db = P.SessionLocal()
keys = {(q.assignment_id, q.prompt.split("\n")[0]) for q in db.query(accounts.QuizQuestion).all()}
db.close()
check("  and both keep the new question's key, each its own", (p2.id, "What is 3+3?") in keys and (p5.id, "What is 3+3?") in keys, keys)
page = amy.get("/p/" + SLUG).get_data(as_text=True) if SLUG else ""
check("a student already working sees the new notes", "NEW words." in page)
check("  with the answers taken out", "[x]" not in page and "- [ ] 6" in page)

print("linking")
r = teacher.post("/api/library/%s/link" % loops["slug"], json={"link": ["vars"]})
check("linking an assignment gives it the tutorial's text", r.status_code == 200 and notes("vars") == NEW)
r = teacher.post("/api/library/%s/link" % loops["slug"], json={"unlink": ["p5"]})
check("unlinking keeps its notes, as its own", notes("p5") == NEW and one(accounts.Assignment, slug="p5").tutorial_id == 0)
teacher.post("/api/library/" + loops["slug"], json={"body": NEW + "\nMore.\n"})
check("  and the tutorial's next change doesn't reach it", notes("p5") == NEW and notes("p2") == NEW + "\nMore.\n")
library(teacher)
check("  nor does the import take it back", one(accounts.Assignment, slug="p5").tutorial_id == 0)

print("making, renaming, copying, downloading")
r = teacher.post("/api/library", json={"title": "Bare notes", "body": "# Bare notes\n\nHi.\n", "linkTo": "bare"})
check("a new tutorial made for an assignment is linked to it", r.status_code == 201 and notes("bare") == "# Bare notes\n\nHi.\n")
bare = r.get_json()["slug"]
teacher.post("/api/library/" + bare, json={"title": "Renamed"})
check("a rename alone keeps the text", item_titled(teacher, "Renamed") and notes("bare") == "# Bare notes\n\nHi.\n")
r = teacher.post("/api/library/%s/duplicate" % loops["slug"])
dup = item_titled(teacher, "Loops (copy)")
check("a duplicate is its own, linked to nothing", r.status_code == 201 and dup and dup["uses"] == [])
r = teacher.get("/api/library/%s/download" % loops["slug"])
check("a download is the file", r.status_code == 200 and r.get_data(as_text=True) == NEW + "\nMore.\n"
      and 'filename="loops.md"' in r.headers.get("Content-Disposition", ""), r.headers.get("Content-Disposition"))

print("uploading many")
files = [
    {"name": "Loops.md", "data": b64("# Loops\n\nUploaded from home.\n")},          # same title: replaces
    {"name": "fresh.md", "data": b64("# Brand New\n\nHi.\n")},                       # added
    {"name": "Variables.md", "data": b64(notes("vars") if False else "# Variables\n\nName things.\n")},  # unchanged
    {"name": "deck.html", "data": b64("<!doctype html><html><script>x()</script></html>")},
    {"name": "photo.png", "data": b64("not text")},
    {"name": "bad.md", "data": "%%%"},
]
r = teacher.post("/api/library/upload", json={"files": files})
rep = {x["name"]: x for x in r.get_json()["report"]}
check("a file with the same title replaces the tutorial", rep["Loops.md"]["result"] == "replaced", rep["Loops.md"])
check("  and every assignment using it gets it", notes("p2") == "# Loops\n\nUploaded from home.\n" and notes("vars") == notes("p2"))
check("  saying how many", rep["Loops.md"].get("updated") == 2, rep["Loops.md"])
check("a new title is added, titled from its heading", rep["fresh.md"]["result"] == "added" and item_titled(teacher, "Brand New"))
check("the same text again is left as it is", rep["Variables.md"]["result"] == "unchanged", rep["Variables.md"])
check("an .html file is a teacher deck", rep["deck.html"]["result"] == "added"
      and one(accounts.LibraryItem, slug=rep["deck.html"]["slug"]).kind == "deck")
check("anything else is skipped, saying why", rep["photo.png"]["result"] == "skipped" and rep["bad.md"]["result"] == "skipped")
r = teacher.post("/api/library/upload", json={"files": [{"name": "Loops.md", "data": b64("# Loops\n\nSecond.\n")}], "replace": False})
check("replace off adds it as another", r.get_json()["report"][0]["result"] == "added" and notes("p2") == "# Loops\n\nUploaded from home.\n")

print("a copy for another period")
cid = teacher.post("/api/class", json={"name": "Period 7"}).get_json()["id"]
r = teacher.post("/api/assignment/p2/copy", json={"class": cid})
copy = r.get_json().get("slug")
check("a copy keeps the link", copy and one(accounts.Assignment, slug=copy).tutorial_id == one(accounts.Assignment, slug="p2").tutorial_id)
mine = next(i for i in library(teacher)["items"] if any(u["url"].endswith("/p2") for u in i["uses"]))
teacher.post("/api/library/" + mine["slug"], json={"body": "# Loops\n\nFor every period.\n"})
check("  so the tutorial's next change reaches it", notes(copy) == "# Loops\n\nFor every period.\n")
L1 = teacher.post("/api/lesson", json={"title": "Monday"}).get_json()["slug"]
L2 = teacher.post("/api/lesson", json={"title": "Tuesday"}).get_json()["slug"]
check("two new lessons, the same starter, are two tutorials, not one",
      one(accounts.Assignment, slug=L1).tutorial_id != one(accounts.Assignment, slug=L2).tutorial_id
      and item_titled(teacher, "Monday") and item_titled(teacher, "Tuesday"))

print("deleting")
r = teacher.delete("/api/library/" + mine["slug"])
check("a deleted tutorial is gone", r.status_code == 200 and not any(i["slug"] == mine["slug"] for i in library(teacher)["items"]))
check("  every assignment that used it keeps its notes, its own now",
      notes("p2") == "# Loops\n\nFor every period.\n" and one(accounts.Assignment, slug="p2").tutorial_id == 0)

print("whose library")
check("another teacher can't see, save, link or delete it",
      other.get("/api/library/" + loops["slug"]).status_code == 404
      and other.post("/api/library/" + loops["slug"], json={"body": "x"}).status_code == 404
      and other.post("/api/library/%s/link" % loops["slug"], json={"link": ["vars"]}).status_code == 404
      and other.delete("/api/library/" + bare).status_code == 404
      and not library(other)["items"])
theirs = other.post("/api/library", json={"body": "# Theirs\n"}).get_json()["slug"]
other.post("/api/library/%s/link" % theirs, json={"link": ["vars"]})
check("  nor link their tutorial to my assignment", "Theirs" not in (notes("vars") or ""))
check("a student gets nothing from it",
      amy.get("/api/library").status_code == 403 and amy.get("/api/library/" + loops["slug"]).status_code == 403
      and amy.get("/teacher/tutorials").status_code == 403 and amy.post("/api/library/upload", json={"files": []}).status_code == 403
      and amy.get("/api/library/%s/download" % loops["slug"]).status_code == 403)
check("  nor anyone signed out", stranger.get("/api/library").status_code == 403
      and stranger.get("/teacher/tutorials/%s/edit" % loops["slug"]).status_code == 403)

print("the same in all three")
home = os.path.expanduser("~")
for name in ("library.py", "static/library.js", "static/library.css", "templates/library.html",
             "templates/library_edit.html", "tools/test_library.py", "accounts.py"):
    mine_bytes = open(os.path.join(ROOT, name), "rb").read()
    for repo in ("pyide", "webide", "flaskide"):
        there = os.path.join(home, repo)
        if os.path.realpath(there) == os.path.realpath(ROOT) or not os.path.isdir(there):
            continue
        path = os.path.join(there, name)
        check("%s is the same as %s's" % (name, repo), os.path.exists(path) and open(path, "rb").read() == mine_bytes)

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
