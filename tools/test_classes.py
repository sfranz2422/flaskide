#!/usr/bin/env python3
"""Classes: a page per period, its students from Classroom, its assignments.

    python3 tools/test_classes.py

WHAT IS BEING GUARDED

  A student sees their own classes and nothing else.
      The class list is in every page's menu and comes from the roster, by
      email. A student not on the roster must not reach the page at all,
      and hidden or archived assignments must not reach the ones who are.

  The page is the teacher's arrangement.
      New things go on top; the arrows' order is kept exactly, or refused
      whole when the page is out of date; a group is only a heading.

  Nothing a student did is ever lost by tidying the class.
      Archiving, moving, deleting a class — none of it touches submissions
      or what a student's My work page shows.

  A period gets a copy, not a share.
      Copy to makes a new assignment with its own links and live lesson;
      the original keeps its own.

Google is never called: the token and the two doors to it are replaced.
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "classes.db")
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
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


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


def q(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).all()
    finally:
        db.close()


# ------------------------------------------------------------ a fake Google
P4, P7 = "444", "777"
roster = {
    P4: [{"profile": {"emailAddress": "Kid1@school.org", "name": {"fullName": "Kid One"}}},
         {"profile": {"emailAddress": "kid3@school.org", "name": {"fullName": "Kid Three"}}}],
    P7: [{"profile": {"emailAddress": "kid2@school.org", "name": {"fullName": "Kid Two"}}}],
}
names = {P4: ("Intro to Programming", "Period 4"), P7: ("Intro to Programming", "Period 7")}


def fake_get(url, token, params=None):
    for cid in roster:
        base = P.CLASSROOM_API + "/courses/" + cid
        if url == base:
            return 200, {"id": cid, "name": names[cid][0], "section": names[cid][1]}
        if url == base + "/students":
            return 200, {"students": roster[cid]}
    return 404, {"error": {"message": "Requested entity was not found."}}


P._google_get = fake_get
P._classroom_token = lambda db, user: ("AT", "")
# The name menu is only drawn where Google sign-in is set up.
accounts.login_configured = lambda: True

TEACHER = add_user("t1", "teacher@school.org", "Mr Franz")
OTHER = add_user("t2", "other@school.org", "Another Teacher")
KID1 = add_user("k1", "kid1@school.org", "Kid One")
KID2 = add_user("k2", "kid2@school.org", "Kid Two")
teacher, other = client(TEACHER), client(OTHER)
kid1, kid2, stranger = client(KID1), client(KID2), client()


# ----------------------------------------------------------- making a class
print("Making a class")
check("the dashboard offers New class",
      re.search(r'<form id="new-class"[\s\S]*?type="submit">New class</button>',
                teacher.get("/teacher").get_data(as_text=True)) is not None)
check("a student cannot make one",
      kid1.post("/api/class", json={"name": "Mine"}).status_code == 403)
check("  nor with no name",
      teacher.post("/api/class", json={"name": " "}).status_code == 400)
check("  nor linked to a Classroom class id that is not one",
      teacher.post("/api/class", json={"name": "X", "course": "../1"}).status_code == 400)
check("  nor to a class Google can't find",
      teacher.post("/api/class", json={"name": "X", "course": "999"}).status_code == 400
      and not q(accounts.Course, name="X"))

r = teacher.post("/api/class", json={"name": "Intro — P4", "course": P4})
d = r.get_json() or {}
C4 = d.get("id")
check("the teacher makes Intro — P4, linked to Period 4",
      r.status_code == 200 and d.get("url") == "/teacher/class/%s" % C4, d)
c4 = q(accounts.Course, id=C4)[0] if C4 else None
check("  named by Google, so the page says which Classroom class",
      c4 is not None and c4.course_name == "Intro to Programming — Period 4", c4 and c4.course_name)
check("  and its roster is fetched at once, emails lowercased",
      d.get("students") == 2 and sorted(e.email for e in q(accounts.Enrollment, class_id=C4))
      == ["kid1@school.org", "kid3@school.org"])
C7 = teacher.post("/api/class", json={"name": "Intro — P7", "course": P7}).get_json()["id"]
CX = teacher.post("/api/class", json={"name": "Scratch"}).get_json()["id"]
check("a class with no Classroom class has no students",
      q(accounts.Enrollment, class_id=CX) == [])
page = teacher.get("/teacher").get_data(as_text=True)
check("the dashboard lists the classes",
      all('href="/teacher/class/%d"' % c in page for c in (C4, C7, CX)))
check("another teacher cannot open one",
      other.get("/teacher/class/%d" % C4).status_code == 404
      and other.post("/api/class/%d/new" % C4, json={"title": "x"}).status_code == 404)

# ------------------------------------------------------------- its contents
print("\nIts assignments")
NEW = "/api/class/%d/new" % C4
r = teacher.post(NEW, json={"title": "Hello World"})
d = r.get_json() or {}
HELLO = d.get("slug")
check("New assignment makes one and opens it to write the starter",
      r.status_code == 200 and d.get("url") == "/teacher/%s/edit" % HELLO, d)
a = q(accounts.Assignment, slug=HELLO)[0]
check("  starting as the editor's own starter project",
      a.file_map() == P.STARTER and a.kind == "code", list(a.file_map()))
check("  with its live link made already",
      len(q(accounts.LiveSession, assignment_id=a.id)) == 1)
LISTS = teacher.post(NEW, json={"title": "Lists"}).get_json()["slug"]
QUIZ = teacher.post(NEW, json={"title": "Lists quiz", "kind": "lesson"}).get_json()
check("New lesson makes a lesson, opened in the lesson editor",
      q(accounts.Assignment, slug=QUIZ["slug"])[0].kind == "lesson"
      and QUIZ["url"] == "/teacher/%s/lesson" % QUIZ["slug"], QUIZ)
QUIZ = QUIZ["slug"]
teacher.post("/api/class/%d/group" % C4, json={"title": "Topic 1: Getting started"})
check("a group needs a name", teacher.post("/api/class/%d/group" % C4,
                                           json={"title": ""}).status_code == 400)


def order(c=teacher, cid=C4):
    page = c.get("/teacher/class/%d" % cid).get_data(as_text=True)
    return re.findall(r'<tr class="[^"]*" data-item="(\d+)"(?: data-slug="([^"]*)")?'
                      r'\s+data-title="([^"]*)"', page)


titles = [t for _, _, t in order()]
check("the page is newest on top", titles == ["Topic 1: Getting started", "Lists quiz",
                                              "Lists", "Hello World"], titles)
check("the dashboard's own list leaves out what is in a class",
      'data-slug="%s"' % HELLO not in teacher.get("/teacher").get_data(as_text=True))

ids = [int(i) for i, _, _ in order()]
want = [ids[0], ids[3], ids[1], ids[2]]        # heading, Hello World, then the rest
r = teacher.post("/api/class/%d/order" % C4, json={"items": want})
check("the arrows' order is kept exactly",
      r.status_code == 200 and [int(i) for i, _, _ in order()] == want)
check("an order missing an item is refused whole, not half applied",
      teacher.post("/api/class/%d/order" % C4, json={"items": want[:-1]}).status_code == 409
      and [int(i) for i, _, _ in order()] == want)
check("  and one with another class's item",
      teacher.post("/api/class/%d/order" % C4,
                   json={"items": want[:-1] + [want[-1] + 999]}).status_code == 409)
check("a student cannot reorder it",
      kid1.post("/api/class/%d/order" % C4, json={"items": want}).status_code == 403)

hello_row = [int(i) for i, s, _ in order() if s == HELLO][0]
lists_row = [int(i) for i, s, _ in order() if s == LISTS][0]
group_row = want[0]
teacher.post("/api/class/%d/item/%d" % (C4, lists_row), json={"hidden": True})
page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
check("Hide marks it on the teacher's page and keeps it there",
      'data-slug="%s"' % LISTS in page and 'data-hidden="1"' in page)
check("a heading can be renamed",
      teacher.post("/api/class/%d/item/%d" % (C4, group_row),
                   json={"title": "Topic 1"}).get_json().get("title") == "Topic 1")
check("  but an assignment's row is not a heading to delete",
      teacher.delete("/api/class/%d/item/%d" % (C4, hello_row)).status_code == 404)

# Descriptions: markdown under an assignment or a heading.
DESC = "Make a **list** of five things.\n\nSee [the docs](https://docs.python.org/3/tutorial/datastructures.html)."
r = teacher.post("/api/class/%d/item/%d" % (C4, hello_row), json={"description": "  " + DESC + "\n"})
check("a description is saved for an assignment, trimmed",
      r.status_code == 200 and r.get_json().get("description") == DESC
      and q(accounts.ClassItem, id=hello_row)[0].description == DESC, r.get_json())
teacher.post("/api/class/%d/item/%d" % (C4, group_row), json={"description": "Week of Oct 6."})
check("  and for a group heading",
      q(accounts.ClassItem, id=group_row)[0].description == "Week of Oct 6.")
check("  not one that isn't text",
      teacher.post("/api/class/%d/item/%d" % (C4, hello_row),
                   json={"description": ["x"]}).status_code == 400)
check("  nor one too long to be a description",
      teacher.post("/api/class/%d/item/%d" % (C4, hello_row),
                   json={"description": "x" * 20001}).status_code == 413
      and q(accounts.ClassItem, id=hello_row)[0].description == DESC)
check("  and only by the class's teacher",
      kid1.post("/api/class/%d/item/%d" % (C4, hello_row), json={"description": "hi"}).status_code == 403
      and other.post("/api/class/%d/item/%d" % (C4, hello_row), json={"description": "hi"}).status_code == 404)
page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
def _row_html(item_id):
    m = re.search(r'data-item="%d"[\s\S]*?</tr>' % item_id, page)
    return m.group(0) if m else ""


check("the teacher's page previews it, and has the box to write it",
      'data-md="Make a **list** of five things.' in _row_html(hello_row)
      and 'class="field desc-box"' in _row_html(hello_row) and "notes.js" in page)
check("  with Describe on an assignment's row and a heading's",
      'js-describe">Describe' in _row_html(hello_row)
      and 'js-describe">Describe' in _row_html(group_row))

# What each is, and whether it is in Google Classroom.
check("the Add form's kinds are Code, Lesson and Material",
      re.search(r'<option value="code">Code</option>\s*<option value="lesson">Lesson</option>'
                r'\s*<option value="material">Material</option>', page) is not None)
_quiz_row = [int(i) for i, s_, _ in order() if s_ == QUIZ][0]
check("a code assignment is tagged code, a lesson lesson",
      '<span class="kind-tag">code</span>' in _row_html(hello_row)
      and '<span class="kind-tag">lesson</span>' in _row_html(_quiz_row)
      and '<span class="kind-tag">code</span>' not in _row_html(_quiz_row))
check("  and one not posted to Classroom says so",
      "tag-not-posted" in _row_html(hello_row) and "✓ Classroom" not in _row_html(hello_row))
db = P.SessionLocal()
db.add(accounts.ClassroomPost(assignment_id=a.id, course_id=P4,
                              course_name="Intro to Programming — Period 4", work_id="w1"))
db.commit()
db.close()
page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
check("posted to Classroom: tagged, naming the class on hover",
      'title="Posted to Intro to Programming — Period 4">✓ Classroom' in _row_html(hello_row)
      and "tag-not-posted" not in _row_html(hello_row)
      and "tag-not-posted" in _row_html(_quiz_row))
check("  and students never see it", "Classroom" not in kid1.get("/class/%d" % C4).get_data(as_text=True))
# A post the first version made lives on the assignment itself until its
# page is opened; it counts too.
db = P.SessionLocal()
db.query(accounts.Assignment).filter_by(id=a.id).update(
    {"classroom_work_id": "w-old", "classroom_course_name": "Old period"})
db.commit()
db.query(accounts.ClassroomPost).filter_by(assignment_id=a.id).delete()
db.commit()
db.close()
page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
check("  a post from the first version counts too",
      'title="Posted to Old period">✓ Classroom' in _row_html(hello_row))
db = P.SessionLocal()
db.query(accounts.Assignment).filter_by(id=a.id).update(
    {"classroom_work_id": "", "classroom_course_name": ""})
db.commit()
db.close()
db = P.SessionLocal()
db.query(accounts.ClassroomPost).filter_by(assignment_id=a.id).delete()
db.commit()
db.close()

_css = open(os.path.join(PYIDE, "static", "style.css")).read()
_w = re.search(r"\.class-teacher \.sheet \{ max-width: (\d+)px; \}", _css)
check("the teacher's class page is wider than the site's 860px, for the descriptions",
      '<body class="class-page class-teacher">' in page and _w is not None and int(_w.group(1)) >= 1100)
check("  and a tag never breaks in half",
      re.search(r"\.kind-tag \{[^}]*white-space: nowrap", _css) is not None)

# ------------------------------------------------------- the student's side
print("\nThe class as its students see it")
page = kid1.get("/class/%d" % C4).get_data(as_text=True)
check("a student on the roster sees the class", "Hello World" in page and "Lists quiz" in page)
check("  but not what is hidden", ">Lists<" not in page)
check("  the assignment's name opens their copy until they turn it in",
      'href="/a/%s"' % HELLO in page)
check("  with its live link", re.search(r'href="/live/\w+"', page) is not None)
check("  each assignment a card, with its description to render",
      page.count('<article class="card') == 2
      and 'class="md card-desc" data-md="Make a **list** of five things.' in page)
check("  and a heading with its words under it",
      'class="md stream-intro" data-md="Week of Oct 6."' in page)
check("  rendered by notes.js, which sanitises it and opens links in a new tab",
      "notes.js" in page and "FlaskIDENotes.render(el, el.dataset.md)" in page)
check("  escaped as written until it is",
      "<strong>list</strong>" not in page and "<script>alert" not in page)
check("a student not on the roster is turned away",
      kid2.get("/class/%d" % C4).status_code == 404)
check("  as is anyone signed out, to sign in",
      stranger.get("/class/%d" % C4).status_code == 302)
check("  and another teacher", other.get("/class/%d" % C4).status_code == 404)
check("the teacher can look, as the class would",
      teacher.get("/class/%d" % C4).status_code == 200)

menu = kid1.get("/new").get_data(as_text=True)
check("the class is in the student's name menu",
      'href="/class/%d">Intro — P4</a>' % C4 in menu)
check("  and not in a student's who isn't on its roster",
      "Intro — P4" not in kid2.get("/new").get_data(as_text=True)
      and "Intro — P7" in kid2.get("/new").get_data(as_text=True))
check("the teacher's menu has their classes, to their own pages",
      'href="/teacher/class/%d">Intro — P4</a>' % C4 in teacher.get("/new").get_data(as_text=True))

# The front door: "/" sends each person to their page.
print("\nThe front door")
r = stranger.get("/")
page = r.get_data(as_text=True)
check("signed out, / offers the editor and signing in",
      r.status_code == 200 and 'href="/new"' in page and 'href="/login?next=/"' in page, r.status_code)
r = stranger.get("/?teach=abc&a=xyz")
check("  an old /?… link still goes to the editor, as it was made for",
      r.status_code == 302 and r.headers["Location"].endswith("/new?teach=abc&a=xyz"),
      r.headers.get("Location"))
r = teacher.get("/")
check("a teacher goes on to their dashboard",
      r.status_code == 302 and r.headers["Location"].endswith("/teacher"))
page = teacher.get("/teacher").get_data(as_text=True)
check("  where their classes are at the top",
      0 <= page.find(">Classes <") < page.find('href="/teacher/class/%d"' % C4)
      < page.find("Not in a class"))
r = kid1.get("/")
check("a student goes on to their classes",
      r.status_code == 302 and r.headers["Location"].endswith("/classes"))
check("  which lists the ones they're on the roster of",
      'href="/class/%d"' % C4 in kid1.get("/classes").get_data(as_text=True)
      and 'href="/class/%d"' % C4 not in kid2.get("/classes").get_data(as_text=True))
_ghost = client(add_user("k9", "nobody@school.org", "Nobody"))
check("  or says they're not in any yet, and how that changes",
      "not in any classes yet" in _ghost.get("/classes").get_data(as_text=True))
check("a teacher asking for /classes gets the dashboard",
      teacher.get("/classes").headers.get("Location", "").endswith("/teacher"))
check("signed out, /classes asks them to sign in",
      "/login" in stranger.get("/classes").headers.get("Location", ""))
from types import SimpleNamespace                            # noqa: E402
P.oauth = SimpleNamespace(google=SimpleNamespace(authorize_access_token=lambda: {"userinfo": {
    "sub": "k1", "email": "kid1@school.org", "email_verified": True, "name": "Kid One"}}))
check("signing in with nowhere asked for lands on the front door, to go on",
      client().get("/auth/callback").headers.get("Location") == "/")
_back = client()
with _back.session_transaction() as _s:
    _s["after_login"] = "/a/xyz"
check("  and from an assignment link, back to the assignment",
      _back.get("/auth/callback").headers.get("Location") == "/a/xyz")
check("signing out with nowhere to go lands on the front door",
      client(KID2).get("/logout").headers.get("Location") == "/")

# Turned in, and marked.
teacher.post("/api/assignment/%s/out-of" % HELLO, json={"out_of": 10})
kid1.get("/a/%s" % HELLO)
draft = [d for d in q(accounts.Draft, owner_id=KID1) if d.assignment_id == a.id][0]
kid1.post("/api/submit", json={"draft": draft.slug, "files": {"app.py": "print(1)\n"}})
sub = q(accounts.Submission, student_id=KID1)[0]
teacher.post("/api/assignment/%s/feedback" % HELLO,
             json={"submission": sub.id, "feedback": "", "score": "8"})
page = kid1.get("/class/%d" % C4).get_data(as_text=True)
check("turned in: the name opens what they turned in",
      'href="/s/%s"' % sub.snippet_slug in page and "✓ Turned in</span>" in page)
check("  and their grade is on the page", 'badge-grade">8 / 10</span>' in page)
check("  only their own", 'badge-grade">8' not in teacher.get("/class/%d" % C4).get_data(as_text=True))

db = P.SessionLocal()
db.query(accounts.LiveSession).filter_by(assignment_id=a.id).update({"ended": 0})
db.commit()
db.close()
check("a lesson on the air says so on the class's page",
      "● Live now" in kid1.get("/class/%d" % C4).get_data(as_text=True)
      and "● Live now" in teacher.get("/teacher/class/%d" % C4).get_data(as_text=True))

# A heading with nothing of theirs under it says nothing to them.
teacher.post("/api/class/%d/group" % C4, json={"title": "Coming soon"})
check("an empty heading is left off the students' page",
      "Coming soon" not in kid1.get("/class/%d" % C4).get_data(as_text=True)
      and "Coming soon" in teacher.get("/teacher/class/%d" % C4).get_data(as_text=True))

# ---------------------------------------------------------------- materials
print("\nMaterials: a card that is only its description")
MAT = "/api/class/%d/material" % C4
check("a student cannot add one", kid1.post(MAT, json={"title": "x"}).status_code == 403)
check("  nor a material with no name", teacher.post(MAT, json={"title": " "}).status_code == 400)
r = teacher.post(MAT, json={"title": "Reading: lists",
                            "description": "Read [this](https://example.com/lists) first.\n\n![a diagram](/img/abc)"})
mat_row = (r.get_json() or {}).get("id")
m = q(accounts.ClassItem, id=mat_row)[0] if mat_row else None
check("the teacher adds a material, on top",
      r.status_code == 200 and m is not None and m.kind == "material"
      and m.assignment_id is None and [int(i) for i, _, _ in order()][0] == mat_row, r.get_json())
page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
_mrow = re.search(r'data-item="%d"[\s\S]*?</tr>' % mat_row, page)
_mrow = _mrow.group(0) if _mrow else ""
check("  its row on the teacher's page: Describe, Rename, Hide and Delete",
      all(x in _mrow for x in ('js-describe">Describe', 'js-rename">Rename',
                                'js-hide">Hide', 'js-remove danger">Delete', ">material<")))
page = kid1.get("/class/%d" % C4).get_data(as_text=True)
_card = re.search(r'<article class="card card-material">[\s\S]*?</article>', page)
_card = _card.group(0) if _card else ""
check("students see it as a card with its description",
      "Reading: lists" in _card and 'class="md card-desc" data-md="Read [this](https://example.com/lists)' in _card)
check("  and nothing to open: the description is all of it",
      _card and "btn" not in _card and "/a/" not in _card)
teacher.post("/api/class/%d/item/%d" % (C4, mat_row), json={"title": "Reading: lists, part 1"})
check("it can be renamed", q(accounts.ClassItem, id=mat_row)[0].title == "Reading: lists, part 1")
teacher.post("/api/class/%d/item/%d" % (C4, mat_row), json={"hidden": True})
check("  and hidden from students",
      "Reading: lists" not in kid1.get("/class/%d" % C4).get_data(as_text=True)
      and "Reading: lists" in teacher.get("/teacher/class/%d" % C4).get_data(as_text=True))
teacher.post("/api/class/%d/item/%d" % (C4, mat_row), json={"hidden": False})
# A heading with only a material under it is not empty.
teacher.post("/api/class/%d/group" % C4, json={"title": "Readings"})
_ids = [int(i) for i, _, _ in order()]
_g = _ids[0]
teacher.post("/api/class/%d/order" % C4, json={"items": [_g, mat_row] + [i for i in _ids if i not in (_g, mat_row)]})
check("a heading with only a material under it still shows",
      ">Readings</h2>" in kid1.get("/class/%d" % C4).get_data(as_text=True))
r = teacher.delete("/api/class/%d/item/%d" % (C4, mat_row))
check("a material can be deleted",
      r.status_code == 200 and q(accounts.ClassItem, id=mat_row) == [])
teacher.delete("/api/class/%d/item/%d" % (C4, _g))

# ------------------------------------------------------------------ pictures
print("\nPictures in descriptions")
import io                                                    # noqa: E402
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KINDS = {"png": PNG, "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 64,
         "gif": b"GIF89a" + b"\x00" * 64,
         "webp": b"RIFF\x40\x00\x00\x00WEBPVP8 " + b"\x00" * 64}


def upload(c, data, name="pic.png"):
    return c.post("/api/image", data={"image": (io.BytesIO(data), name)},
                  content_type="multipart/form-data")


r = upload(teacher, PNG)
url = (r.get_json() or {}).get("url", "")
check("a teacher uploads a picture and is given its address",
      r.status_code == 200 and re.fullmatch(r"/img/\w+", url) is not None, r.get_json())
got = stranger.get(url)
check("  which serves it back, as it was", got.status_code == 200 and got.data == PNG
      and got.headers["Content-Type"] == "image/png")
check("  kept by browsers, never sniffed into anything else, never run",
      "immutable" in got.headers.get("Cache-Control", "")
      and got.headers.get("X-Content-Type-Options") == "nosniff"
      and "sandbox" in got.headers.get("Content-Security-Policy", ""))
for kind, data in KINDS.items():
    r = upload(teacher, data, "x.bin")
    check("  a %s is known by its bytes, whatever its name" % kind.upper(),
          r.status_code == 200 and stranger.get(r.get_json()["url"]).headers["Content-Type"]
          == "image/" + kind)
check("a student cannot upload one", upload(kid1, PNG).status_code == 403)
check("  nor anyone signed out", upload(stranger, PNG).status_code == 403)
check("a page dressed up as a picture is refused",
      upload(teacher, b"<html><script>alert(1)</script>", "evil.png").status_code == 400)
check("  and so is an SVG, which can carry script",
      upload(teacher, b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
             "x.svg").status_code == 400)
check("one over 4 MB is refused", upload(teacher, PNG + b"\x00" * 4_000_000).status_code == 413)
check("an address that isn't one is a 404", stranger.get("/img/nope").status_code == 404)

page = teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)
check("the description box has the toolbar, as quickpulsepro's does",
      "easymde@2.18.0/dist/easymde.min.js" in page and "easymde@2.18.0/dist/easymde.min.css" in page
      and re.search(r'"link", "upload-image"', page) is not None and '"bold", "italic"' in page)
check("  its picture button and drag-and-drop upload to /api/image",
      "uploadImage: true" in page and "imageUploadFunction: uploadImage" in page
      and 'fetch("/api/image", { method: "POST", body: form })' in page)
check("  with Add picture for when the toolbar can't load",
      'class="js-pic" type="file"' in page)
check("  and the preview is rendered the way students see it",
      "previewRender: function (text, preview) {\n        window.FlaskIDENotes.render(preview, text);" in page)

# ---------------------------------------------------------- tidying away
print("\nTidying never loses a student's work")
teacher.post("/api/assignment/%s/archive" % HELLO)
check("an archived assignment leaves the students' page",
      "Hello World" not in kid1.get("/class/%d" % C4).get_data(as_text=True))
check("  and the teacher's list, for the Archived part of the page",
      re.search(r"Archived <span class=\"count\">1</span>",
                teacher.get("/teacher/class/%d" % C4).get_data(as_text=True)) is not None)
check("  but what they turned in is still on their My work page",
      "Hello World" in kid1.get("/my").get_data(as_text=True))
teacher.post("/api/assignment/%s/archive" % HELLO)

r = teacher.post("/api/assignment/%s/copy" % HELLO, json={"class": C7})
d = r.get_json() or {}
COPY = d.get("slug")
c = q(accounts.Assignment, slug=COPY)[0] if COPY else None
check("Copy to makes P7 its own assignment",
      r.status_code == 200 and c is not None and COPY != HELLO
      and (c.title, c.file_map(), c.out_of) == ("Hello World", a.file_map(), 10), d)
check("  on top of P7's page", order(cid=C7)[0][1] == COPY)
check("  with its own live lesson",
      len(q(accounts.LiveSession, assignment_id=c.id)) == 1
      and q(accounts.LiveSession, assignment_id=c.id)[0].code
      != q(accounts.LiveSession, assignment_id=a.id)[0].code)
check("  with its description",
      q(accounts.ClassItem, assignment_id=c.id)[0].description == DESC)
check("  and nothing students did comes with it",
      q(accounts.Submission, assignment_id=c.id) == [])
check("  while the original stays in P4", [s for _, s, _ in order()].count(HELLO) == 1)
check("P7's student sees the copy, P4's doesn't see P7",
      'href="/a/%s"' % COPY in kid2.get("/class/%d" % C7).get_data(as_text=True)
      and kid1.get("/class/%d" % C7).status_code == 404)
check("only into the teacher's own class",
      teacher.post("/api/assignment/%s/copy" % HELLO, json={"class": 99999}).status_code == 404)

r = teacher.post("/api/assignment/%s/class" % LISTS, json={"class": CX})
check("Move puts it on top of the other class",
      r.status_code == 200 and order(cid=CX)[0][1] == LISTS
      and LISTS not in [s for _, s, _ in order()])
r = teacher.post("/api/assignment/%s/class" % LISTS, json={"class": ""})
check("  and taking it out of classes puts it back on the dashboard",
      r.status_code == 200 and 'data-slug="%s"' % LISTS in teacher.get("/teacher").get_data(as_text=True))
page = teacher.get("/teacher/%s" % HELLO).get_data(as_text=True)
check("the assignment page says its class, and offers Move and Copy",
      'href="/teacher/class/%d"' % C4 in page and 'id="class-move"' in page
      and 'id="class-copy"' in page)
check("  and Post to Classroom starts on the class's Classroom class",
      'var classCourse = "%s";' % P4 in page)

# Delete: nobody turned the copy in, so it can go — off P7's page with it,
# and its lesson let go (Postgres refuses a delete that leaves it pointing).
cid = c.id
r = teacher.delete("/api/assignment/" + COPY)
check("deleting an assignment takes it off its class's page",
      r.status_code == 200 and q(accounts.ClassItem, assignment_id=cid) == [])
check("  and lets its live lesson go rather than blocking the delete",
      q(accounts.LiveSession, assignment_id=cid) == [])

# The roster: someone leaves P4.
roster[P4].pop()
r = teacher.post("/api/class/%d/roster" % C4)
check("Sync roster drops a student who left",
      r.get_json().get("students") == 1
      and [e.email for e in q(accounts.Enrollment, class_id=C4)] == ["kid1@school.org"])
check("  only for the teacher", kid1.post("/api/class/%d/roster" % C4).status_code == 403)
check("a class with no Classroom class can't sync, and says so",
      teacher.post("/api/class/%d/roster" % CX).status_code == 409)

r = teacher.delete("/api/class/%d" % C4)
check("deleting a class keeps its assignments, back on the dashboard",
      r.status_code == 200 and q(accounts.Assignment, slug=HELLO)
      and 'data-slug="%s"' % HELLO in teacher.get("/teacher").get_data(as_text=True))
check("  with every student's work and score",
      q(accounts.Submission, student_id=KID1)[0].score == 8)
check("  and the class is gone from the student's menu",
      "Intro — P4" not in kid1.get("/new").get_data(as_text=True))

# A class_items table from before descriptions: the column must be added,
# or every class page fails on the first request after the deploy.
import sqlalchemy                                            # noqa: E402
_old = sqlalchemy.create_engine("sqlite:///" + os.path.join(tempfile.mkdtemp(), "old.db"))
with _old.begin() as _c:
    _c.execute(sqlalchemy.text(
        "CREATE TABLE class_items (id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL, "
        "assignment_id INTEGER, title VARCHAR(200) NOT NULL, hidden INTEGER NOT NULL, "
        "position INTEGER NOT NULL, created_at DATETIME NOT NULL)"))
    _c.execute(sqlalchemy.text(
        "INSERT INTO class_items VALUES (1, 1, NULL, 'Topic', 0, 0, '2026-10-08 10:00:00')"))
accounts.create_all(_old)
with _old.connect() as _c:
    _d = _c.execute(sqlalchemy.text("SELECT description FROM class_items")).fetchall()
check("an older class_items table gets descriptions, empty", _d == [("",)], _d)
with _old.connect() as _c:
    _k = _c.execute(sqlalchemy.text("SELECT kind FROM class_items")).fetchall()
check("  and a kind, empty: still the heading it was", _k == [("",)], _k)

bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
