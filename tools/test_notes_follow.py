#!/usr/bin/env python3
"""A student who already started an assignment sees its notes as they are now.

    python3 tools/test_notes_follow.py

WHAT IS BEING GUARDED

  The teacher's edit reaches everyone, not only students who start later.
      A draft is a copy of the assignment, notes included. Every page that
      shows a student their draft — the editor, the live page, the live
      page's save — shows the assignment's notes as they are now, with the
      answer keys taken out like every copy a student is given.

  Only the notes. The student's code and data files stay theirs.

  Saving never writes the notes into the draft.
      The automatic turn-in compares the draft with what was last handed
      in, so new notes in the draft would hand everyone's work in again
      over a typo. Save, Turn in and the live page's save all keep the
      draft's stored notes whatever the browser sends.

  An untouched draft still counts as untouched (the rescue's draftFresh)
  after the teacher edits the notes, or every sign-in would ask.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "notes_follow.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


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
    """The files a page hands its script, as JSON (index.html: files,
    live.html: starterFiles)."""
    at = html.find("%s: " % key)
    if at < 0:
        return None
    return json.JSONDecoder().raw_decode(html, at + len(key) + 2)[0]


# PyIDE keeps the program in `code` and the rest in `files`; WebIDE and
# FlaskIDE keep the whole project in `files`, the program under ENTRY. The
# same test runs in all three, so the shapes are made here.
ENTRY = getattr(P, "ENTRY", None)


def work(main, notes, words):
    """A save's body: the program, the notes and a data file."""
    files = {"notes.md": notes, "words.txt": words}
    if ENTRY:
        return {"code": "", "files": dict(files, **{ENTRY: main})}
    return {"code": main, "files": files}


def program(draft_row):
    return json.loads(draft_row.files).get(ENTRY) if ENTRY else draft_row.code


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
BEN = add(accounts.User(google_sub="b", email="ben@school.org", name="Ben"))

OLD_NOTES = "# Week 1\nRead the old notes.\n"
NEW_NOTES = ("# Week 1\nRead the NEW notes.\n\n```quiz\nWhat is 2+2?\n"
             "- [ ] 3\n- [x] 4\n```\n")
START = work("print('start')\n", OLD_NOTES, "cat\n")
add(accounts.Assignment(slug="hw1", app=P.APP_NAME, teacher_id=TEACHER, title="HW",
                        code=START["code"], files=json.dumps(START["files"])))
teacher, amy, ben = client(TEACHER), client(AMY), client(BEN)

# Amy starts and does some work; Ben opens it and does nothing.
SLUG = amy.get("/a/hw1").headers["Location"].rsplit("/", 1)[-1]
r = amy.post("/api/draft/" + SLUG, json=dict(
    work("print('mine')\n", OLD_NOTES, "dog\n"), turn_in=True))
check("Amy's work is saved and turned in", r.status_code == 200, r.status_code)
handed = one(accounts.Submission, student_id=AMY)
BEN_SLUG = ben.get("/a/hw1").headers["Location"].rsplit("/", 1)[-1]

# The teacher edits the notes, and nothing else.
r = teacher.post("/api/assignment/hw1", json=dict(
    work("print('start')\n", NEW_NOTES, "cat\n"), title="HW"))
check("the teacher saves new notes", r.status_code == 200, r.get_data(as_text=True)[:80])

print("the editor")
html = amy.get("/p/" + SLUG).get_data(as_text=True)
files = page_files(html, "files") or {}
check("a student who had started sees the new notes",
      "NEW notes" in files.get("notes.md", ""), files.get("notes.md", "")[:40])
check("  with the answer key taken out",
      "[x]" not in files.get("notes.md", "x") and "- [ ] 4" in files.get("notes.md", ""),
      files.get("notes.md"))
check("  and her own code and data file untouched",
      (files.get(ENTRY) if ENTRY else page_files(html, "startingCode")) == "print('mine')\n"
      and files.get("words.txt") == "dog\n", files.get("words.txt"))
check("an untouched draft still counts as untouched",
      "draftFresh: true" in ben.get("/p/" + BEN_SLUG).get_data(as_text=True))

print("saving")
r = amy.post("/api/draft/" + SLUG, json=dict(
    work("print('mine')\n", NEW_NOTES, "dog\n"), turn_in=True))
stored = json.loads(one(accounts.Draft, slug=SLUG).files)
check("a save keeps the draft's stored notes, whatever was sent",
      stored.get("notes.md") == OLD_NOTES, stored.get("notes.md"))
again = one(accounts.Submission, student_id=AMY)
check("  so new notes alone never turn the work in again",
      again.submitted_at == handed.submitted_at and again.snippet_slug == handed.snippet_slug,
      (handed.submitted_at, again.submitted_at))
r = amy.post("/api/draft/" + SLUG, json=work("print('mine, more')\n", NEW_NOTES, "dog\n"))
stored = json.loads(one(accounts.Draft, slug=SLUG).files)
check("  and her own changes are still saved",
      program(one(accounts.Draft, slug=SLUG)) == "print('mine, more')\n"
      and stored.get("words.txt") == "dog\n" and stored.get("notes.md") == OLD_NOTES)

r = amy.post("/api/submit", json=dict(work("print('handed')\n", NEW_NOTES, "dog\n"),
                                       draft=SLUG))
stored = json.loads(one(accounts.Draft, slug=SLUG).files)
check("Turn in keeps the stored notes too",
      r.status_code == 200 and stored.get("notes.md") == OLD_NOTES, stored.get("notes.md"))

print("the live page")
code = teacher.post("/api/live/start", json={"body": "x", "assignment": "hw1"}).get_json()["code"]
html = amy.get("/live/%s" % code).get_data(as_text=True)
starter = page_files(html, "starterFiles") or {}
check("her live page starts with the new notes and her own files",
      "NEW notes" in starter.get("notes.md", "") and starter.get("words.txt") == "dog\n",
      starter)
r = amy.post("/api/live/%s/keep" % code, json={
    "code": "print('live')\n", "files": {"notes.md": NEW_NOTES, "words.txt": "dog\n"}})
sent = (r.get_json() or {}).get("files", {})
stored = json.loads(one(accounts.Draft, slug=SLUG).files)
check("a live save answers with the new notes, so the page keeps them",
      "NEW notes" in sent.get("notes.md", ""), sent.get("notes.md", "")[:40])
check("  and keeps the stored ones in the draft",
      stored.get("notes.md") == OLD_NOTES and stored.get("words.txt") == "dog\n")

print("not an assignment")
def own(text):
    body = work("x = 1\n", "", "")
    body["files"] = {k: v for k, v in body["files"].items() if k not in ("notes.md", "words.txt")}
    body["files"]["mine.md"] = text
    return body


r = amy.post("/api/draft", json=own("# my notes\n"))
OWN = r.get_json()["slug"]
amy.post("/api/draft/" + OWN, json=own("# rewritten\n"))
own = one(accounts.Draft, slug=OWN)
check("a project of her own saves its notes as sent",
      json.loads(own.files).get("mine.md") == "# rewritten\n", own.files)

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
