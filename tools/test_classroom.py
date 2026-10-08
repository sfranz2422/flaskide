#!/usr/bin/env python3
"""Connecting a teacher's Google Classroom, and grading through it. FlaskIDE.

    python3 tools/test_classroom.py

Needs `cryptography` (pip install -r requirements.txt): the stored token is
encrypted, and checking that is half the point of this file.

WHY THIS FILE EXISTS

The connection is a credential that can post to a teacher's classes and
grade them, kept for weeks. The ways of getting it wrong are all quiet:

  * stored in the clear, a copy of the database is a key to every
    connected teacher's Classroom;
  * a teacher who unticks one box on Google's consent screen gets a token
    that works today and fails the day grades are sent;
  * a teacher who picks their personal Gmail from the account chooser
    connects classes that are not the ones they teach here;
  * a token Google has stopped honouring makes the dashboard fail the same
    way forever, unless it is forgotten so Connect is offered again;
  * a student must never be shown any of this.

Google is never called. `_google_post` and `_google_get` are the only two
functions in app.py that reach it, and both are replaced here.
"""
import os
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

try:
    import cryptography                                      # noqa: F401
except ImportError:
    sys.exit("test_classroom.py needs `cryptography`: pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))
APPDIR = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "classroom.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)

sys.path.insert(0, APPDIR)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

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


def link_row():
    db = P.SessionLocal()
    try:
        return db.query(accounts.ClassroomLink).filter_by(user_id=TEACHER).first()
    finally:
        db.close()


# ------------------------------------------------------------ a fake Google
ALL = " ".join(P.CLASSROOM_SCOPES)
google = {"email": "teacher@school.org", "scope": ALL, "refresh": 200,
          "refresh_error": "", "courses": 200}
calls = []


def fake_post(url, data):
    calls.append(("POST", url, dict(data)))
    if url == P.GOOGLE_TOKEN_URL and data.get("grant_type") == "authorization_code":
        return 200, {"access_token": "AT-1", "refresh_token": "RT-secret",
                     "scope": google["scope"]}
    if url == P.GOOGLE_TOKEN_URL and data.get("grant_type") == "refresh_token":
        if google["refresh_error"]:
            return 400, {"error": google["refresh_error"]}
        return google["refresh"], {"access_token": "AT-2"}
    if url == P.GOOGLE_REVOKE_URL:
        return 200, {}
    return 404, {}


def fake_get(url, token, params=None):
    calls.append(("GET", url, token))
    if url == P.GOOGLE_USERINFO_URL:
        return 200, {"email": google["email"]}
    if url == P.CLASSROOM_API + "/courses":
        if google["courses"] != 200:
            return 403, {"error": {"message": "Google Classroom API has not been "
                                              "used in project 123 or it is disabled."}}
        return 200, {"courses": [
            {"id": "c1", "name": "Programming 1", "section": "Period 2",
             "alternateLink": "https://classroom.google.com/c/c1"},
            {"id": "c2", "name": "Intro to Programming", "section": ""}]}
    return 404, {}


# The Classroom side of the fake: two classes doing the same work — Period 4
# and Period 7 — each with its own roster and, once posted, its own
# coursework. Period 4's roster is split over two pages (a second page
# silently dropped would be students silently ungraded).
P4, P7 = "123456", "777777"
room = {
    P4: {"name": "Programming 1 — Period 4", "work": None, "gone": False,
         "roster": [[{"userId": "u-other", "profile": {"emailAddress": "someone@school.org"}}],
                    [{"userId": "u-kid", "profile": {"emailAddress": "KID1@school.org"}},
                     {"userId": "u-kid3", "profile": {"emailAddress": "kid3@school.org"}}]]},
    P7: {"name": "Programming 1 — Period 7", "work": None, "gone": False,
         "roster": [[{"userId": "u-kid2", "profile": {"emailAddress": "kid2@school.org"}}]]},
}
patches = []


def fake_classroom_get(url, params):
    for cid, c in room.items():
        base = P.CLASSROOM_API + "/courses/" + cid
        if url == base:
            return 200, {"id": cid, "name": c["name"]}
        if url == base + "/topics":
            # Period 4's topics, two pages of them. Period 7 plays a
            # connection made without the topics permission.
            if cid != P4:
                return 403, {"error": {"message": "Request had insufficient authentication scopes."}}
            page = int(params.get("pageToken") or 0)
            pages = [[{"topicId": "111", "name": "Unit 1: Loops"}],
                     [{"topicId": "222", "name": "Unit 2: Lists"}]]
            data = {"topic": pages[page]}
            if page + 1 < len(pages):
                data["nextPageToken"] = str(page + 1)
            return 200, data
        if url == base + "/students":
            page = int(params.get("pageToken") or 0)
            data = {"students": c["roster"][page]}
            if page + 1 < len(c["roster"]):
                data["nextPageToken"] = str(page + 1)
            return 200, data
        if c["work"] and url == base + "/courseWork/w-%s" % cid:
            if c.get("broken"):
                return 500, {"error": {"message": "Internal error encountered."}}
            if c["gone"]:
                return 404, {"error": {"message": "Requested entity was not found."}}
            return 200, {"id": "w-" + cid, "state": c["work"].get("state"),
                         **({"scheduledTime": c["work"]["scheduledTime"]}
                            if c["work"].get("scheduledTime") else {})}
        if c["work"] and url == base + "/courseWork/w-%s/studentSubmissions" % cid:
            if c["gone"]:
                return 404, {"error": {"message": "Requested entity was not found."}}
            # Google keeps a draft's submissions to itself: there is nothing
            # to grade until it is assigned.
            if c["work"].get("state") == "DRAFT":
                return 400, {"error": {"message": "@CourseWorkNotModifiable"}}
            return 200, {"studentSubmissions": [
                {"id": "s-" + st["userId"], "userId": st["userId"]}
                for page in c["roster"] for st in page]}
    return None


def fake_api(method, url, token, body=None, params=None):
    calls.append((method, url, token, body, params))
    for cid, c in room.items():
        if method == "POST" and url == P.CLASSROOM_API + "/courses/%s/courseWork" % cid:
            c["work"] = body
            c["gone"] = False            # posted again: it exists again
            return 200, {"id": "w-" + cid,
                         "alternateLink": "https://classroom.google.com/c/%s/a/w" % cid}
    if method == "PATCH" and "/studentSubmissions/" in url:
        patches.append((url.split("/courses/")[1].split("/")[0],
                        url.rsplit("/", 1)[1], body, params))
        return 200, {}
    if method == "PATCH" and "/courseWork/w-" in url:
        cid = url.split("/courses/")[1].split("/")[0]
        if "state" in (params or {}).get("updateMask", ""):
            # Google's rule: DRAFT to PUBLISHED, and never back.
            if room[cid]["work"].get("state") == "PUBLISHED":
                return 400, {"error": {"message": "@CourseWorkNotModifiable"}}
            room[cid]["work"]["state"] = body["state"]
            room[cid]["work"].pop("scheduledTime", None)
        return 200, {}
    return 404, {}


_plain_get = fake_get


def fake_get_all(url, token, params=None):
    hit = fake_classroom_get(url, params or {})
    if hit is not None:
        calls.append(("GET", url, token))
        return hit
    return _plain_get(url, token, params)


P._google_post = fake_post
P._google_get = fake_get_all
P._google_api = fake_api


def revoked():
    return [c for c in calls if c[0] == "POST" and c[1] == P.GOOGLE_REVOKE_URL]


TEACHER = add_user("t1", "teacher@school.org", "Mr Franz")
STUDENT = add_user("s1", "kid@school.org", "A Student")
teacher = client(TEACHER)
student = client(STUDENT)
stranger = client()


# ------------------------------------------------------- with Google unset
print("\nWith no Google sign-in configured")

check("there is no Connect route", teacher.get("/classroom/connect").status_code == 404)
check("  and no Classroom box on the dashboard",
      "Google Classroom" not in teacher.get("/teacher").get_data(as_text=True))

os.environ["GOOGLE_CLIENT_ID"] = "client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "client-secret"


# --------------------------------------------------------------- connecting
print("\nConnecting")

page = teacher.get("/teacher").get_data(as_text=True)
check("a teacher's dashboard offers Connect Google Classroom",
      "Connect Google Classroom" in page)
check("a student cannot start it", student.get("/classroom/connect").status_code == 404)
r = stranger.get("/classroom/connect")
check("  nor someone signed out, who is sent to sign in",
      r.status_code == 302 and "/login" in r.headers["Location"])

r = teacher.get("/classroom/connect")
to = urlparse(r.headers.get("Location", ""))
q = {k: v[0] for k, v in parse_qs(to.query).items()}
check("a teacher is sent to Google's consent screen",
      r.status_code == 302 and to.netloc == "accounts.google.com", to.netloc)
# Written out, not read from app.py: compared with its own list, this check
# could never fail. Each one is needed by a later step — listing classes,
# posting work and grading it, finding the students, matching them by email.
WANTED = {
    "openid", "email",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.profile.emails",
    # optional: only fills the topic dropdown when posting
    "https://www.googleapis.com/auth/classroom.topics.readonly",
}
check("  asking for every Classroom permission at once",
      set(q.get("scope", "").split()) == WANTED, q.get("scope"))
check("  offline, so grades can be sent later",
      q.get("access_type") == "offline" and q.get("prompt") == "consent")
check("  with the account chooser on their school address",
      q.get("login_hint") == "teacher@school.org")
check("  and back to /classroom/callback",
      q.get("redirect_uri", "").endswith("/classroom/callback"))
with teacher.session_transaction() as s:
    state = s.get("classroom_state")
check("  with a state only this browser knows", state and q.get("state") == state)

src = open(os.path.join(APPDIR, "app.py")).read()
check("students' sign-in still asks for nothing more than it did",
      'client_kwargs={"scope": "openid email profile"}' in src)


def callback(c, **args):
    with c.session_transaction() as s:
        s["classroom_state"] = "S"
    args.setdefault("state", "S")
    return c.get("/classroom/callback", query_string=args)


r = teacher.get("/classroom/callback", query_string={"state": "forged", "code": "x"})
check("a reply that did not start in this browser is refused",
      r.status_code == 400 and link_row() is None, r.status_code)

r = callback(teacher, error="admin_policy_enforced")
check("a school admin's block is explained, and who to ask",
      r.status_code == 400 and "IT department" in r.get_data(as_text=True))
check("  on a page about Classroom, not about signing in",
      "Connect again" in r.get_data(as_text=True)
      and "without signing in" not in r.get_data(as_text=True))
r = callback(teacher, error="access_denied")
check("pressing Cancel on Google's screen is explained",
      "allow FlaskIDE to use your Classroom" in r.get_data(as_text=True))

google["scope"] = "openid email https://www.googleapis.com/auth/classroom.courses.readonly"
calls.clear()
r = callback(teacher, code="abc")
check("a token with a box unticked is refused, and why",
      r.status_code == 400 and "leave all the boxes ticked" in r.get_data(as_text=True))
check("  and nothing is stored", link_row() is None)
check("  and Google is told to forget it", len(revoked()) == 1)
google["scope"] = ALL

google["email"] = "mrfranz.personal@gmail.com"
calls.clear()
r = callback(teacher, code="abc")
check("connecting a different Google account is refused",
      r.status_code == 400 and "mrfranz.personal@gmail.com" in r.get_data(as_text=True))
check("  and nothing is stored, and Google is told to forget it",
      link_row() is None and len(revoked()) == 1)
google["email"] = "Teacher@School.org"          # Google may differ in case

r = callback(teacher, code="abc")
# ALL is the required permissions only, so this is also a teacher who
# unticked topics, or connected before topics were asked for.
check("topics are asked for but not required to connect",
      "classroom.topics.readonly" not in google["scope"]
      and "https://www.googleapis.com/auth/classroom.topics.readonly"
      in P.CLASSROOM_OPTIONAL_SCOPES)
check("the right account, everything ticked: connected",
      r.status_code == 302 and "classroom=connected" in r.headers["Location"],
      r.status_code)
row = link_row()
check("  a link is stored for this teacher", row is not None)
check("  and the token in the database is not the token",
      row is not None and "RT-secret" not in row.refresh_token)
check("    but decrypts to it",
      row is not None
      and P._token_box().decrypt(row.refresh_token.encode()).decode() == "RT-secret")

page = teacher.get("/teacher?classroom=connected").get_data(as_text=True)
check("the dashboard says which account is connected",
      "Connected as <strong>Teacher@School.org</strong>" in page)


# ------------------------------------------------------------ their classes
print("\nTheir classes")

r = teacher.get("/api/classroom/courses")
names = [c["name"] for c in (r.get_json() or {}).get("courses", [])]
check("a connected teacher's classes are listed",
      names == ["Programming 1", "Intro to Programming"], names)
check("  using a fresh access token, not the stored one",
      ("GET", P.CLASSROOM_API + "/courses", "AT-2") in calls)
check("a student cannot list them",
      student.get("/api/classroom/courses").status_code == 403)

google["courses"] = 403
r = teacher.get("/api/classroom/courses")
check("Google's own reason reaches the teacher when it refuses",
      r.status_code == 502 and "has not been used in project"
      in (r.get_json() or {}).get("error", ""))
google["courses"] = 200

google["refresh_error"] = "invalid_grant"
r = teacher.get("/api/classroom/courses")
check("a token Google stopped honouring is forgotten",
      r.status_code == 409 and link_row() is None, r.status_code)
check("  so the dashboard offers Connect again",
      "Connect Google Classroom" in teacher.get("/teacher").get_data(as_text=True))
google["refresh_error"] = ""

callback(teacher, code="abc")
P.app.secret_key = "a different key entirely, as after a rotation"
# A new key signs everyone out too, so the teacher signs in again first.
r = client(TEACHER).get("/api/classroom/courses")
check("after SECRET_KEY changes, the unreadable token is forgotten",
      r.status_code == 409 and link_row() is None, r.status_code)
P.app.secret_key = "k" * 32


# ------------------------------------------------------------ disconnecting
print("\nDisconnecting")

callback(teacher, code="abc")
calls.clear()
r = teacher.post("/classroom/disconnect")
check("Disconnect forgets the connection", link_row() is None)
check("  and withdraws it at Google too",
      len(revoked()) == 1 and revoked()[0][2].get("token") == "RT-secret")
callback(teacher, code="abc")
check("a student's Disconnect touches nothing",
      student.post("/classroom/disconnect").status_code == 404
      and link_row() is not None)

# -------------------------------------------------- posting and sending grades
print("\nPosting to Classroom and sending grades")

hw = teacher.post("/api/assignment", json={
    "files": {"app.py": "# starter app\n"}, "title": "Loops"}).get_json()["slug"]
KIDS = {}
for n, email in enumerate(["kid1@school.org", "kid2@school.org", "kid3@school.org",
                           "kid4@school.org"]):
    uid = add_user("k%d" % n, email, "Kid %d" % (n + 1))
    kid = client(uid)
    kid.get("/a/%s" % hw)
    db = P.SessionLocal()
    d = db.query(accounts.Draft).filter_by(owner_id=uid).first()
    db.close()
    kid.post("/api/submit", json={"draft": d.slug,
                                  "files": {"app.py": "print(%d)\n" % n}})
    KIDS[email] = uid


def sub_of(email):
    db = P.SessionLocal()
    try:
        return db.query(accounts.Submission).filter_by(student_id=KIDS[email]).first()
    finally:
        db.close()


def assignment():
    db = P.SessionLocal()
    try:
        return db.query(accounts.Assignment).filter_by(slug=hw).first()
    finally:
        db.close()


def posts():
    db = P.SessionLocal()
    try:
        return [(p.course_id, p.work_id, p.course_name) for p in
                db.query(accounts.ClassroomPost).filter_by(
                    assignment_id=assignment().id).order_by(accounts.ClassroomPost.id)]
    finally:
        db.close()


POST = "/api/assignment/%s/classroom/post" % hw
SYNC = "/api/assignment/%s/classroom/sync" % hw
PERIODS = "/api/assignment/%s/classroom/periods" % hw
FB = "/api/assignment/%s/feedback" % hw

page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("a connected teacher's assignment page offers Post to Classroom",
      'id="gc-post"' in page)
r = teacher.post(POST, json={"course": P4})
check("it cannot be posted before it has points",
      r.status_code == 400 and "out of" in r.get_json()["error"], r.status_code)
teacher.post("/api/assignment/%s/out-of" % hw, json={"out_of": 10})
check("a student cannot post it", student.post(POST, json={"course": P4}).status_code == 403)
r = teacher.post(POST, json={"course": "../evil"})
check("a class id that is not one is refused", r.status_code == 400)

t4 = teacher.get("/api/classroom/courses/%s/topics" % P4).get_json()
check("a class's topics are listed for the dropdown, every page of them",
      t4.get("topics") == [{"id": "111", "name": "Unit 1: Loops"},
                           {"id": "222", "name": "Unit 2: Lists"}], t4)
t7 = teacher.get("/api/classroom/courses/%s/topics" % P7).get_json()
check("  a connection without the topics permission is told to reconnect",
      t7.get("reconnect") is True and t7.get("topics") == []
      and t7.get("connect_url", "").endswith("/classroom/connect"), t7)
check("  only for a teacher",
      student.get("/api/classroom/courses/%s/topics" % P4).status_code == 403)
check("  and only for a class id that is one",
      teacher.get("/api/classroom/courses/../topics").status_code in (400, 404))
r = teacher.post(POST, json={"course": P4, "topic": "x/../y"})
check("a topic id that is not one is refused before Google is asked",
      r.status_code == 400 and room[P4]["work"] is None)

calls.clear()
r = teacher.post(POST, json={"course": P4, "topic": "222"})
check("  posted under the topic chosen",
      (room[P4]["work"] or {}).get("topicId") == "222" and r.get_json().get("topic") == "222",
      (room[P4]["work"] or {}).get("topicId"))
check("the teacher posts it to Period 4", r.status_code == 200
      and r.get_json().get("course") == "Programming 1 — Period 4",
      r.get_data(as_text=True)[:90])
w = room[P4]["work"] or {}
check("  as a published assignment worth 10 points",
      w.get("state") == "PUBLISHED" and w.get("workType") == "ASSIGNMENT"
      and w.get("maxPoints") == 10, w)
link = ((w.get("materials") or [{}])[0].get("link") or {}).get("url", "")
check("  telling students it opens in FlaskIDE",
      "FlaskIDE" in (w.get("description") or ""), w.get("description"))
check("  carrying the link students open it from",
      link.endswith("/a/%s" % hw), link)
check("  and it remembers where it went",
      posts() == [(P4, "w-" + P4, "Programming 1 — Period 4")], posts())
r = teacher.post(POST, json={"course": P4})
check("posting to the same class twice is refused, so it never sees two",
      r.status_code == 409 and len(posts()) == 1)

r = teacher.post(POST, json={"course": P7, "draft": True, "link": "live"})
check("the same assignment can also go to Period 7",
      r.status_code == 200 and [p[0] for p in posts()] == [P4, P7], posts())
check("  with no topic when none was chosen, as before topics existed",
      "topicId" not in room[P7]["work"])
check("  as its own Classroom assignment",
      room[P7]["work"] is not None and room[P7]["work"].get("maxPoints") == 10)
check("  posted as a draft when asked, for the teacher to assign there later",
      room[P7]["work"].get("state") == "DRAFT" and r.get_json().get("draft") is True,
      room[P7]["work"].get("state"))
_live = re.search(r'id="live-url" type="text" readonly value="([^"]+)"',
                  teacher.get("/teacher/%s" % hw).get_data(as_text=True))
_p7link = ((room[P7]["work"].get("materials") or [{}])[0].get("link") or {}).get("url", "")
check("  linked to the live lesson when asked: the assignment page's own live link",
      _live is not None and _p7link == _live.group(1) and "/live/" in _p7link
      and r.get_json().get("link") == "live", _p7link)
check("  and told in Classroom that it is a live lesson",
      "follow the lesson live" in room[P7]["work"].get("description", ""))
check("  while Period 4, not asked, got the assignment link as before",
      link.endswith("/a/%s" % hw) and "follow the lesson live" not in
      (room[P4]["work"] or {}).get("description", ""))
check("the page has the topic dropdown, hidden until a class is chosen",
      'id="gc-topic" class="field" hidden' in teacher.get("/teacher/%s" % hw).get_data(as_text=True))
check("the page offers the choice, the assignment ticked",
      'name="gc-link" value="assignment" checked' in
      teacher.get("/teacher/%s" % hw).get_data(as_text=True))
check("the page offers the draft box, ticked",
      'id="gc-draft" checked' in teacher.get("/teacher/%s" % hw).get_data(as_text=True))
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("the page names both classes, and offers Sync",
      "<strong>Programming 1 — Period 4</strong>" in page
      and "<strong>Programming 1 — Period 7</strong>" in page and 'id="gc-sync"' in page)
check("  each on its own line",
      page.count("<li><strong>Programming 1 — Period ") == 2
      and '<ul class="gc-posts">' in page)
check("  and the picker leaves out the classes it is already in",
      '"%s", "%s"' % (P4, P7) in page)

calls.clear()
teacher.post("/api/assignment/%s/out-of" % hw, json={"out_of": 20})
patched = sorted(c[1].split("/courses/")[1].split("/")[0] for c in calls
                 if c[0] == "PATCH" and "/courseWork/w-" in c[1]
                 and c[3] == {"maxPoints": 20} and c[4] == {"updateMask": "maxPoints"})
check("changing the points changes them in every class it went to",
      patched == [P4, P7], patched)

r = teacher.get(PERIODS)
d = r.get_json() or {}
names = {c["id"]: c["name"] for c in d.get("classes", [])}
by = {int(k): names.get(v) for k, v in (d.get("by_student") or {}).items()}
check("the results page is told who is in which period",
      by.get(sub_of("kid1@school.org").id) == "Programming 1 — Period 4"
      and by.get(sub_of("kid2@school.org").id) == "Programming 1 — Period 7", by)
check("  finding them on the roster's second page",
      by.get(sub_of("kid3@school.org").id) == "Programming 1 — Period 4")
check("  and leaving out a student in neither",
      sub_of("kid4@school.org").id not in by)
check("a student cannot ask", student.get(PERIODS).status_code == 403)
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("each result row can be put in its period",
      'class="res-row" data-sub="%d"' % sub_of("kid1@school.org").id in page
      and 'id="period-tabs"' in page)

for email, score in (("kid1@school.org", "17"), ("kid2@school.org", "15"),
                     ("kid4@school.org", "12")):
    teacher.post(FB, json={"submission": sub_of(email).id, "feedback": "", "score": score})
# kid3 is in Period 4 but not scored, and must not be sent as anything —
# least of all 0, or a blank that wipes a grade typed into Classroom.

r = teacher.post(SYNC)
out = r.get_json() or {}
check("Sync with Period 7 still a draft sends Period 4's only",
      r.status_code == 200 and out.get("sent") == 1
      and [p[0] for p in patches] == [P4], (out, patches))
check("  naming Period 7 as waiting to be assigned",
      out.get("waiting") == ["Programming 1 — Period 7"], out.get("waiting"))
check("  without calling its students missing from the class",
      out.get("unmatched") == ["Kid 4"], out.get("unmatched"))

# The teacher assigns it in Classroom. Nothing tells PyIDE; the next Sync
# has to notice by itself.
room[P7]["work"]["state"] = "PUBLISHED"
patches.clear()
r = teacher.post(SYNC)
out = r.get_json() or {}
check("Sync sends the scores", r.status_code == 200 and out.get("sent") == 2, out)
check("  once it is assigned there", out.get("waiting") == [], out.get("waiting"))
check("  each to its own period's assignment, as a draft, matched by email",
      sorted(patches) == sorted([
          (P4, "s-u-kid", {"draftGrade": 17.0}, {"updateMask": "draftGrade"}),
          (P7, "s-u-kid2", {"draftGrade": 15.0}, {"updateMask": "draftGrade"})]),
      patches)
check("  naming the student who is in neither class",
      out.get("unmatched") == ["Kid 4"], out.get("unmatched"))
check("  and sending nothing for the one with no score",
      not any(p[1] == "s-u-kid3" for p in patches))
check("  and remembering what went", sub_of("kid1@school.org").score_synced == 17.0
      and sub_of("kid2@school.org").score_synced == 15.0)
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("the page shows it is in Classroom",
      '<span class="fb-sync small">✓ in Classroom</span>' in page)
teacher.post(FB, json={"submission": sub_of("kid1@school.org").id,
                       "feedback": "", "score": "18"})
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("  and that a changed score is not, until the next Sync",
      '<span class="fb-sync small">not in Classroom yet</span>' in page)

check("a student cannot sync", student.post(SYNC).status_code == 403)

room[P7]["gone"] = True
patches.clear()
r = teacher.post(SYNC)
out = r.get_json() or {}
check("one class's assignment deleted in Classroom: the other still syncs",
      r.status_code == 200 and [p[0] for p in patches] == [P4], (out, patches))
check("  the deleted one is named", out.get("gone") == ["Programming 1 — Period 7"],
      out.get("gone"))
check("  and forgotten, so it can be posted there again",
      [p[0] for p in posts()] == [P4])
room[P4]["gone"] = True
r = teacher.post(SYNC)
check("all of them deleted: said so, and every post forgotten",
      r.status_code == 409 and "gone from Google Classroom" in r.get_json()["error"]
      and posts() == [])
check("  so the page offers Post again",
      'id="gc-post"' in teacher.get("/teacher/%s" % hw).get_data(as_text=True))

# Deleted in Classroom with no Sync since: the editor still thinks it is
# posted. Posting again must notice, rather than refuse "already posted".
UNLINK = "/api/assignment/%s/classroom/unlink" % hw
r = teacher.post(POST, json={"course": P4})
teacher.post(SYNC)
check("posted to Period 4 again, and synced",
      r.status_code == 200 and sub_of("kid1@school.org").score_synced is not None)
room[P4]["gone"] = True
r = teacher.post(POST, json={"course": P4})
check("posting again where it was deleted in Classroom posts it fresh",
      r.status_code == 200 and [p[0] for p in posts()] == [P4]
      and room[P4]["gone"] is False, r.get_data(as_text=True)[:120])
check("  and its grades are marked not in Classroom, for the new one",
      sub_of("kid1@school.org").score_synced is None
      and sub_of("kid1@school.org").score == 18)
r = teacher.post(POST, json={"course": P4})
check("posting where it still exists is refused, and says Unlink",
      r.status_code == 409 and "Unlink" in r.get_json()["error"])

# Unlink: forget one class here, keep everything else.
teacher.post(SYNC)
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
pid = None
db = P.SessionLocal()
try:
    pid = db.query(accounts.ClassroomPost).filter_by(assignment_id=assignment().id).first().id
finally:
    db.close()
check("each posted class has an Unlink button",
      'class="linkbtn gc-unlink" data-post="%d"' % pid in page)
check("a student cannot unlink", student.post(UNLINK, json={"post": pid}).status_code == 403)
check("  nor can a post id that is not this assignment's",
      teacher.post(UNLINK, json={"post": pid + 999}).status_code == 404
      and teacher.post(UNLINK, json={"post": "x"}).status_code == 404)
code_before = assignment().code
calls.clear()
r = teacher.post(UNLINK, json={"post": pid})
# Asked first: everything after reads through the assignment.
_kept = assignment() is not None and assignment().code == code_before
check("Unlink keeps the assignment, the work and the scores",
      _kept and sub_of("kid1@school.org") is not None
      and sub_of("kid1@school.org").score == 18)
check("  and forgets that class", _kept and r.status_code == 200 and posts() == []
      and r.get_json().get("left") == 0, r.get_data(as_text=True)[:120])
check("  marking the scores not in Classroom, ready for a new post",
      sub_of("kid1@school.org").score_synced is None)
check("  and nothing is asked of Google: the Classroom side is untouched",
      calls == [], calls)
check("  and the page offers Post again",
      "Posted to" not in teacher.get("/teacher/%s" % hw).get_data(as_text=True))

# A SQL assignment is a FlaskIDE assignment like any other: it posts and its
# scores go across the same way. Nothing in grading looks at the files.
room[P4]["gone"] = room[P7]["gone"] = False
sql = teacher.post("/api/assignment", json={
    "files": {"query.sql": "SELECT 1;\n"}, "title": "Joins"}).get_json()["slug"]
kid1 = client(KIDS["kid1@school.org"])
kid1.get("/a/%s" % sql)
db = P.SessionLocal()
item = db.query(accounts.Assignment).filter_by(slug=sql).first()
d = db.query(accounts.Draft).filter_by(owner_id=KIDS["kid1@school.org"],
                                       assignment_id=item.id).first()
db.close()
kid1.post("/api/submit", json={"draft": d.slug,
                               "files": {"query.sql": "SELECT name FROM t;\n"}})
teacher.post("/api/assignment/%s/out-of" % sql, json={"out_of": 5})
r = teacher.post("/api/assignment/%s/classroom/post" % sql, json={"course": P4})
check("a SQL assignment posts to Classroom like a Flask one",
      r.status_code == 200 and (room[P4]["work"] or {}).get("title") == "Joins"
      and (room[P4]["work"] or {}).get("maxPoints") == 5,
      r.get_data(as_text=True)[:80])
db = P.SessionLocal()
ssub = db.query(accounts.Submission).filter_by(
    student_id=KIDS["kid1@school.org"], assignment_id=item.id).first()
db.close()
teacher.post("/api/assignment/%s/feedback" % sql,
             json={"submission": ssub.id, "feedback": "", "score": "4"})
patches.clear()
r = teacher.post("/api/assignment/%s/classroom/sync" % sql)
check("  and its scores sync the same way",
      r.status_code == 200 and (r.get_json() or {}).get("sent") == 1
      and patches == [(P4, "s-u-kid", {"draftGrade": 4.0}, {"updateMask": "draftGrade"})],
      (r.get_json(), patches))

# A post the first version made lived in four columns on the assignment.
# The first look at the assignment moves it into classroom_posts.
db = P.SessionLocal()
it = db.query(accounts.Assignment).filter_by(slug=hw).first()
it.classroom_course_id, it.classroom_course_name = P4, "Programming 1 — Period 4"
it.classroom_work_id, it.classroom_url = "w-old", "https://classroom.google.com/old"
db.commit()
db.close()
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
a = assignment()
check("a post from the first version is carried over",
      posts() == [(P4, "w-old", "Programming 1 — Period 4")], posts())
check("  and the old columns emptied, so it is carried over once",
      (a.classroom_course_id, a.classroom_work_id) == ("", ""))
check("  and the page shows it as posted",
      "Posted to" in page and "<strong>Programming 1 — Period 4</strong>" in page)


# ------------------------------------------------- assigning a draft from here
print("\nPost now: assigning a Classroom draft from PyIDE")

STATES = "/api/assignment/%s/classroom/states" % hw
PUBLISH = "/api/assignment/%s/classroom/publish" % hw
db = P.SessionLocal()
try:
    for _p in db.query(accounts.ClassroomPost).filter_by(assignment_id=assignment().id):
        teacher.post(UNLINK, json={"post": _p.id})       # the carried-over one above
finally:
    db.close()
check("with nothing posted, there is nothing to ask Google",
      teacher.get(STATES).get_json() == {"states": [], "gone": []})
teacher.post(POST, json={"course": P4, "draft": True})
teacher.post(POST, json={"course": P7, "draft": True})
room[P7]["work"]["scheduledTime"] = "2026-10-12T11:00:00Z"
db = P.SessionLocal()
try:
    ids = {p.course_id: p.id for p in db.query(accounts.ClassroomPost)
           .filter_by(assignment_id=assignment().id)}
finally:
    db.close()
page = teacher.get("/teacher/%s" % hw).get_data(as_text=True)
check("each posted class has a Post now button, hidden until Google answers",
      all('class="linkbtn gc-publish" data-post="%d"' % ids[c] in page for c in (P4, P7))
      and 'data-name="Programming 1 — Period 4" hidden' in page)
check("  and the page asks which are drafts",
      '"/classroom/states"' in page and '"/classroom/publish"' in page)
d = teacher.get(STATES).get_json()
check("the page is told Period 4 is a draft and Period 7 is scheduled",
      sorted((s["id"], s["state"]) for s in d["states"])
      == sorted([(ids[P4], "draft"), (ids[P7], "scheduled")]), d)
check("a student cannot ask", student.get(STATES).status_code == 403)
room[P7]["broken"] = True
d = teacher.get(STATES).get_json()
check("a class Google won't answer for is listed as unknown, with Google's reason",
      {"id": ids[P7], "state": "unknown", "why": "Internal error encountered."}
      in d["states"] and len(d["states"]) == 2, d)
room[P7]["broken"] = False
check("  and the page has a word for every state, assigned included",
      all(w in page for w in ('draft: "· draft"', 'scheduled: "· scheduled"',
                              'posted: "· assigned"', "unknown: \"· couldn't check\"")))

check("a student cannot assign it",
      student.post(PUBLISH, json={"post": ids[P4]}).status_code == 403
      and room[P4]["work"]["state"] == "DRAFT")
check("  nor can a post id that is not this assignment's",
      teacher.post(PUBLISH, json={"post": ids[P4] + 999}).status_code == 404
      and teacher.post(PUBLISH, json={"post": "x"}).status_code == 404)
# A real post, but another assignment's: Post now on this page must not
# assign it, whoever owns it.
other = teacher.post("/api/assignment", json={
    "files": {"app.py": "# other\n"}, "title": "Other"}).get_json()["slug"]
teacher.post("/api/assignment/%s/out-of" % other, json={"out_of": 5})
teacher.post("/api/assignment/%s/classroom/post" % other,
             json={"course": P4, "draft": True})
db = P.SessionLocal()
try:
    _oa = db.query(accounts.Assignment).filter_by(slug=other).first()
    other_post = db.query(accounts.ClassroomPost).filter_by(assignment_id=_oa.id).first().id
finally:
    db.close()
room[P4]["work"]["state"] = "DRAFT"          # the other post replaced the fake's P4 work
check("  nor another assignment's post",
      teacher.post(PUBLISH, json={"post": other_post}).status_code == 404
      and room[P4]["work"]["state"] == "DRAFT")
teacher.post("/api/assignment/%s/classroom/unlink" % other, json={"post": other_post})
calls.clear()
r = teacher.post(PUBLISH, json={"post": ids[P4]})
sent = [c for c in calls if c[0] == "PATCH"]
check("Post now assigns Period 4 in Classroom",
      r.status_code == 200 and r.get_json().get("already") is False
      and room[P4]["work"]["state"] == "PUBLISHED", r.get_data(as_text=True)[:120])
check("  by changing its state and nothing else",
      [(c[3], c[4]) for c in sent] == [({"state": "PUBLISHED"}, {"updateMask": "state"})],
      sent)
check("  leaving Period 7 a scheduled draft",
      room[P7]["work"]["state"] == "DRAFT" and room[P7]["work"].get("scheduledTime"))
d = teacher.get(STATES).get_json()
check("  and the page is told Period 4 is assigned now",
      {s["id"]: s["state"] for s in d["states"]}.get(ids[P4]) == "posted", d)
calls.clear()
r = teacher.post(PUBLISH, json={"post": ids[P4]})
check("pressed again (another tab): it is already assigned, and Google is not asked to",
      r.status_code == 200 and r.get_json().get("already") is True
      and not [c for c in calls if c[0] == "PATCH"], calls)
r = teacher.post(PUBLISH, json={"post": ids[P7]})
check("a scheduled one is assigned now when asked",
      r.status_code == 200 and room[P7]["work"]["state"] == "PUBLISHED")
patches.clear()
r = teacher.post(SYNC)
check("  and Sync sends grades to both straight after",
      r.status_code == 200 and r.get_json().get("waiting") == []
      and sorted(p[0] for p in patches) == sorted([P4, P7]), (r.get_json(), patches))

teacher.post(UNLINK, json={"post": ids[P7]})
teacher.post(POST, json={"course": P7, "draft": True})
db = P.SessionLocal()
try:
    p7 = db.query(accounts.ClassroomPost).filter_by(
        assignment_id=assignment().id, course_id=P7).first().id
finally:
    db.close()
room[P7]["gone"] = True
r = teacher.post(PUBLISH, json={"post": p7})
check("deleted in Classroom: said so, and forgotten so it can be posted again",
      r.status_code == 409 and r.get_json().get("gone") is True
      and [p[0] for p in posts()] == [P4], (r.get_data(as_text=True)[:120], posts()))
room[P4]["gone"] = True
d = teacher.get(STATES).get_json()
check("the states list forgets a deleted one too, and names it",
      d.get("gone") == ["Programming 1 — Period 4"] and posts() == [], d)


bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
