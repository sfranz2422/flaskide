#!/usr/bin/env python3
"""The teacher's own HTML slides, kept with an assignment.

    python3 tools/test_teacher_deck.py

WHAT IS BEING GUARDED

  The assignment's page has Upload teacher lesson at the top, and once one
      is uploaded, a link that opens it in a new tab.

  The link serves the file exactly as it was uploaded, scripts and all,
      never from the browser's cache — the same address serves a replaced
      deck. Uploading again replaces it; there is only ever one.

  Only the teacher who set the assignment can open or upload it. The file
      runs with the sign-in of whoever opens it, so a student or another
      teacher opening it would be the deck's scripts running as them.

  Download gives the file back as it is now, named as it was uploaded,
      to the same teacher only.

  Something that isn't HTML (a PDF picked by mistake), an empty file, a
      file too big, or a body that didn't arrive whole is refused.
"""
import base64
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "teacher_deck.db")
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
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


def decks():
    db = P.SessionLocal()
    try:
        # In the tutorial library now (library.py); teacher_decks is only
        # read, for decks from before it.
        return db.query(accounts.LibraryItem).filter_by(kind="deck").count()
    finally:
        db.close()


def send(c, slug, text, name="slides.html"):
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return c.post("/api/assignment/%s/slides" % slug,
                  json={"name": name, "data": base64.b64encode(data).decode()})


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
teacher, other, amy, nobody = client(TEACHER), client(OTHER), client(AMY), client(None)
add(accounts.Assignment(slug="hw1", app=P.APP_NAME, teacher_id=TEACHER, title="HW1",
                        code="print(1)\n", files=json.dumps({"notes.md": "# Hi\n"})))
add(accounts.Assignment(slug="les1", app=P.APP_NAME, teacher_id=TEACHER, title="L1",
                        code="", files=json.dumps({"lesson.md": "# Hi\n"}), kind="lesson"))

DECK = ("<!doctype html>\n<html><head><title>Dicts</title></head><body>"
        "<h1>Intro — dictionaries 🐍</h1><script>localStorage.getItem('x')</script>"
        "</body></html>\n")
NEWER = DECK.replace("Dicts", "Dicts v2")

print("before any upload")
html = teacher.get("/teacher/hw1").get_data(as_text=True)
check("the assignment's page has Upload teacher lesson at the top",
      'id="deck-upload"' in html and ">Upload teacher lesson<" in html
      and html.index('id="deck-upload"') < html.index('<main'))
check("  and its script, posting to this assignment",
      '+ "/slides"' in html and 'id="deck-file"' in html)
check("  Download is hidden too, with nothing to download",
      'id="deck-download"' in html
      and "hidden" in html[html.index('id="deck-download"'):html.index('>Download</a>')])
check("  and the page shows it after an upload", 'download.hidden = false' in html
      and 'download.href = out.d.url + "?download=1"' in html)
check("  the link to open it is there but hidden",
      'id="deck-open"' in html
      and "hidden" in html[html.index('id="deck-open"'):html.index('>Teacher lesson')])
check("  a lesson's page has the button too",
      'id="deck-upload"' in teacher.get("/teacher/les1").get_data(as_text=True))
check("opening it before one is uploaded is a 404",
      teacher.get("/teacher/hw1/slides").status_code == 404)

print("uploading")
r = send(teacher, "hw1", DECK, "Intro_to_Dictionaries_Teacher_Slides.html")
check("the teacher uploads a deck", r.status_code == 200, r.get_data(as_text=True)[:80])
check("  and is told where it is", r.get_json().get("url") == "/teacher/hw1/slides")
r = teacher.get("/teacher/hw1/slides")
check("it opens, byte for byte as sent, scripts and all",
      r.status_code == 200 and r.get_data(as_text=True) == DECK)
check("  as a page", r.mimetype == "text/html")
check("  never from the browser's cache", r.headers.get("Cache-Control") == "no-store")
html = teacher.get("/teacher/hw1").get_data(as_text=True)
at = html.index('id="deck-open"')
tag = html[html.rindex("<a", 0, at):html.index(">", at)]
check("the page now shows the link, in a new tab", "hidden" not in tag
      and 'target="_blank"' in tag and 'href="/teacher/hw1/slides"' in tag, tag)
check("  and says Replace", ">Replace teacher lesson<" in html)
at = html.index('id="deck-download"')
tag = html[html.rindex("<a", 0, at):html.index(">", at)]
check("  and a Download link, shown now", "hidden" not in tag
      and 'href="/teacher/hw1/slides?download=1"' in tag, tag)

print("replacing")
r = send(teacher, "hw1", NEWER)
check("uploading again works", r.status_code == 200)
check("  and replaces it", teacher.get("/teacher/hw1/slides").get_data(as_text=True) == NEWER)
check("  leaving one deck, not two", decks() == 1, decks())
r = teacher.get("/teacher/hw1/slides?download=1")
check("Download gives the file as it is now", r.status_code == 200
      and r.get_data(as_text=True) == NEWER)
check("  as a download, under the name it was uploaded with",
      r.headers.get("Content-Disposition", "").startswith("attachment")
      and "slides.html" in r.headers.get("Content-Disposition", ""), r.headers.get("Content-Disposition"))
send(teacher, "les1", DECK, "Week 3 — dictionaries")
d = teacher.get("/teacher/les1/slides?download=1").headers.get("Content-Disposition", "")
check("  a name without .html gets it, and a name with a dash in it survives",
      "Week%203%20%E2%80%94%20dictionaries.html" in d, d)
check("a byte-order mark is not part of the page",
      send(teacher, "les1", b"\xef\xbb\xbf" + DECK.encode()).status_code == 200
      and teacher.get("/teacher/les1/slides").get_data(as_text=True) == DECK)

print("who can")
for label, c in (("another teacher", other), ("a student", amy)):
    check("%s can't open it" % label, c.get("/teacher/hw1/slides").status_code in (302, 403, 404))
    check("  nor download it", c.get("/teacher/hw1/slides?download=1").status_code in (302, 403, 404))
    check("  nor upload one", send(c, "hw1", DECK).status_code in (403, 404))
r = nobody.get("/teacher/hw1/slides")
check("someone signed out is sent to sign in, not shown it",
      r.status_code in (302, 403) and "Dicts" not in r.get_data(as_text=True))
check("  and nothing they sent changed it",
      teacher.get("/teacher/hw1/slides").get_data(as_text=True) == NEWER)

print("what isn't a deck")
check("a PDF is refused", send(teacher, "hw1", b"%PDF-1.7\n...").status_code == 400)
check("text that isn't HTML is refused", send(teacher, "hw1", "just some notes").status_code == 400)
check("a file that isn't text is refused",
      send(teacher, "hw1", b"<html>\xff\xfe\x00").status_code == 400)
r = send(teacher, "hw1", b"")
check("an empty file is refused, as empty", r.status_code == 400
      and "empty" in r.get_json()["error"])
check("a file too big is refused",
      send(teacher, "hw1", "<html>" + "x" * P.DECK_MAX_BYTES).status_code == 413)
r = teacher.post("/api/assignment/hw1/slides", json={"name": "a.html", "data": "PGh0bWw+<>"})
check("a body that isn't all base64 is refused, not read past",
      r.status_code == 400 and "whole" in r.get_json()["error"], r.get_json())
check("HTML starting with a comment is taken",
      send(teacher, "hw1", "<!-- made by me -->\n" + DECK).status_code == 200)

print("decks from before the library")
# Uploaded to teacher_decks before the tutorial library (library.py) kept
# them: each is taken into the library the first time the assignment's page
# or the library opens, linked to its assignment; the same file on two
# assignments (a period's copy) is one deck.
OLD_DECK = "<!doctype html><html><body><h1>Function review</h1></body></html>"
for slug in ("old1", "old2", "old3"):
    aid = add(accounts.Assignment(slug=slug, app=P.APP_NAME, teacher_id=TEACHER, title=slug.upper(),
                                  code="print(1)\n", files="{}"))
    add(P.TeacherDeck(assignment_id=aid, name="Function Review.html",
                      html=OLD_DECK if slug != "old3" else OLD_DECK.replace("review", "practice"),
                      size=len(OLD_DECK)))
page = teacher.get("/teacher/old1").get_data(as_text=True)
check("an old deck shows on its assignment's page",
      ">Teacher lesson" in page and "hidden>Teacher lesson" not in page)
check("  and opens as it was", teacher.get("/teacher/old1/slides").get_data(as_text=True) == OLD_DECK)
lib = teacher.get("/api/library").get_json()["items"]
mine = [i for i in lib if i["kind"] == "deck" and i["title"] == "Function Review"]
check("it's in the library, named as it was uploaded", len(mine) == 2, [(i["title"], len(i["uses"])) for i in lib if i["kind"] == "deck"])
same = next((i for i in mine if len(i["uses"]) == 2), None)
check("  the same file on two assignments is one deck, linked to both",
      same is not None and sorted(u["title"] for u in same["uses"]) == ["OLD1", "OLD2"])
r = teacher.get("/teacher/old2/slides?download=1")
check("  and downloads under its old name", 'filename="Function Review.html"' in r.headers.get("Content-Disposition", "")
      or "filename=Function Review.html" in r.headers.get("Content-Disposition", ""), r.headers.get("Content-Disposition"))
before = decks()
teacher.get("/api/library")
check("  taken once", decks() == before)

print()
print("ok" if all(results) else "FAIL", "%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
