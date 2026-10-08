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


# ------------------------------------------------------ the notes pane
print("\nThe project's notes")

def poll_json():
    return stranger.get("/api/live/%s?v=-1" % CODE).get_json()

base = poll_json()
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": base.get("body"), "filename": base.get("filename"),
                       "notes": "# Today\nRoutes, [docs](https://example.org)",
                       "seq": 4200})
got = poll_json()
check("notes pushed with the open file reach the class",
      r.status_code == 200 and got.get("notes", "").startswith("# Today"),
      repr(got.get("notes")))
check("  while the open file is still what the mirror shows",
      got.get("body") == base.get("body"))

# An editor still running the old code sends no notes, and must not wipe
# the ones already there.
teacher.post("/api/live/%s/push" % CODE,
             json={"body": "typing on", "seq": 4201})
check("a push without notes leaves them in place",
      poll_json().get("notes", "").startswith("# Today"),
      repr(poll_json().get("notes")))

page = stranger.get("/live/%s" % CODE).get_data(as_text=True)
# The editor's light/dark button, on the student's page too: a room
# projecting in light had no way to put a laptop in it.
check("a student's lesson page has the light/dark button",
      'id="theme"' in page
      and re.search(r"^\s*themeSwitch\(\);", open(os.path.join(FLASKIDE, "static", "live.js")).read(), re.M))
_live_js = open(os.path.join(FLASKIDE, "static", "live.js")).read()
_play_js = open(os.path.join(FLASKIDE, "static", "play.js")).read()
check("  and the New tab button, hidden for a SQL lesson",
      'id="run-tab" class="btn" type="button" hidden' in page
      and re.search(r"^\s*runTabBtn\.hidden = isSql\(\);", _live_js, re.M)
      and re.search(r'^\s*runTabBtn\.addEventListener\("click", runInNewTab\);', _live_js, re.M))
check("  which hands all their own files to /play under the key /play reads",
      re.search(r'localStorage\.setItem\("flaskide-play", JSON\.stringify\(\{\s*files: allFiles\(\),',
                _live_js)
      and 'var PLAY_KEY = "flaskide-play";' in _play_js
      and re.search(r'^\s*window\.open\("/play", "flaskide-play"\);', _live_js, re.M))
check("a student who joins now gets them in the page",
      re.search(r'^\s*notes: "# Today', page, re.M) is not None)
check("  with a pane to show them in",
      'id="live-notes-view"' in page and 'id="live-notes"' in page)

r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "x", "notes": "#" * (F.MAX_FILE_BYTES + 1),
                       "seq": 4202})
check("oversized notes are refused", r.status_code == 413, r.status_code)

teacher.post("/api/live/%s/push" % CODE,
             json={"body": base.get("body"), "filename": base.get("filename"),
                   "notes": "", "seq": 4300})
check("a project with no notes clears them",
      poll_json().get("notes") == "", repr(poll_json().get("notes")))


# ------------------------------------------- slides, output and the page
print("\nSlides, and what the teacher's Run made")

base = poll_json()
PAGE = json.dumps({"path": "/about", "html": "<h1>About</h1>"})
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": base.get("body"), "filename": base.get("filename"),
                       "notes": "## Two", "slide": "2/4",
                       "output": "Running. Routes:\n", "page": PAGE,
                       "seq": 4400})
got = poll_json()
check("the slide a push names reaches the class",
      r.status_code == 200 and got.get("slide") == "2/4", repr(got.get("slide")))
check("  and so does what the teacher's console says",
      got.get("output") == "Running. Routes:\n", repr(got.get("output")))
check("  and the page their preview is showing",
      got.get("page") == PAGE, repr(got.get("page"))[:60])

teacher.post("/api/live/%s/push" % CODE,
             json={"body": "typing on", "seq": 4401})
got = poll_json()
check("a push from an older editor leaves all three alone",
      got.get("slide") == "2/4" and got.get("output") == "Running. Routes:\n"
      and got.get("page") == PAGE,
      "an old tab would wipe them every 400ms")

teacher.post("/api/live/%s/push" % CODE,
             json={"body": "x", "slide": "<b>9</b>", "seq": 4402})
check("a slide that is not N/M is stored as none",
      poll_json().get("slide") == "", repr(poll_json().get("slide")))

# A runaway loop. Refusing it would take the code down with it, and the
# mirror would freeze for as long as the loop ran.
flood = "".join("line %d\n" % i for i in range(20000))
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "while True: print()", "output": flood,
                       "seq": 4403})
got = poll_json()
check("huge output is trimmed, not refused",
      r.status_code == 200 and got.get("body") == "while True: print()",
      r.status_code)
check("  keeping the end of it, which is the part anyone reads",
      got.get("output", "").endswith("line 19999\n")
      and len(got["output"].encode()) <= F.LIVE_OUTPUT_BYTES,
      len(got.get("output", "")))

r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "big page", "page": "x" * (F.MAX_FILE_BYTES + 1),
                       "seq": 4404})
got = poll_json()
check("an oversized page is dropped, and the code still lands",
      r.status_code == 200 and got.get("body") == "big page"
      and got.get("page") == "", (r.status_code, len(got.get("page") or "")))

teacher.post("/api/live/%s/push" % CODE,
             json={"body": "x", "slide": "3/5", "output": "hi\n",
                   "page": PAGE, "seq": 4405})
again = teacher.post("/api/live/start", json={"body": "x"}).get_json()
check("a reload is told which slide the class is on",
      again.get("slide") == "3/5", repr(again.get("slide")))
page = stranger.get("/live/%s" % CODE).get_data(as_text=True)
check("a late joiner gets all three in the page",
      re.search(r'^\s*slide: "3/5"', page, re.M) is not None
      and re.search(r'^\s*output: "hi\\n"', page, re.M) is not None
      and re.search(r'^\s*page: "\{', page, re.M) is not None)
check("  with a slide marker, and tabs for the teacher's console and page",
      'id="live-slide"' in page and 'id="out-teacher"' in page
      and 'id="teacher-output"' in page and 'id="page-teacher"' in page)
_tframe = re.search(r'<iframe id="teacher-page"[^>]*>', page)
check("  the teacher's page in its own frame, with nothing allowed",
      _tframe is not None and 'sandbox=""' in _tframe.group(0),
      _tframe.group(0) if _tframe else "no frame")
teacher.post("/api/live/%s/push" % CODE,
             json={"body": base.get("body"), "filename": base.get("filename"),
                   "notes": "", "slide": "", "output": "", "page": "",
                   "seq": 4500})


# ------------------------------------------------ the teacher's caret
print("\nThe teacher's caret")

teacher.post("/api/live/%s/push" % CODE,
             json={"body": "a = 1\nb = 2", "cursor": "1:3", "seq": 4600})
check("the caret a push names reaches the class",
      poll_json().get("cursor") == "1:3", repr(poll_json().get("cursor")))
teacher.post("/api/live/%s/push" % CODE,
             json={"body": "a = 1\nb = 22", "seq": 4601})
check("  a push from an older editor leaves it alone",
      poll_json().get("cursor") == "1:3", repr(poll_json().get("cursor")))
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "a = 1", "cursor": "<b>", "seq": 4602})
check("  one that is not line:ch is stored as none, not refused",
      r.status_code == 200 and poll_json().get("cursor") == ""
      and poll_json().get("body") == "a = 1", repr(poll_json().get("cursor")))
teacher.post("/api/live/%s/push" % CODE,
             json={"body": "a = 1\nb = 2", "cursor": "0:1-1:3", "seq": 4604})
check("a highlighted block reaches the class as anchor-head",
      poll_json().get("cursor") == "0:1-1:3", repr(poll_json().get("cursor")))
r = teacher.post("/api/live/%s/push" % CODE,
                 json={"body": "a = 1", "cursor": "123456:1-1:1", "seq": 4605})
check("  one too long for the column is stored as none, not refused",
      r.status_code == 200 and poll_json().get("cursor") == ""
      and poll_json().get("body") == "a = 1",
      "Postgres would refuse 25 characters and the push would be lost")
check("  and the longest one allowed fits the column",
      len("99999:99999-99999:99999")
      <= accounts.LiveSession.__table__.c.cursor.type.length)
teacher.post("/api/live/%s/push" % CODE,
             json={"body": "a = 1", "cursor": "0:2", "seq": 4606})
page = stranger.get("/live/%s" % CODE).get_data(as_text=True)
check("  and a late joiner gets it in the page",
      re.search(r'^\s*cursor: "0:2"', page, re.M) is not None)
teacher.post("/api/live/%s/push" % CODE,
             json={"body": base.get("body"), "filename": base.get("filename"),
                   "cursor": "", "seq": 4700})


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
check("  nor a copy of what the class's notes pane shows",
      'id="class-view"' not in r.get_data(as_text=True))
r = teacher.get("/")
check("the teacher's editor has a pane showing the slide the class is on",
      'id="class-view"' in r.get_data(as_text=True)
      and 'id="class-notes"' in r.get_data(as_text=True))

# Hide code moved off the toolbar into the dialog a teacher's Share opens.
# On the toolbar, a tick left on from an earlier demo was invisible until a
# student opened the link and found no source.
_tp = r.get_data(as_text=True)
_ask = _tp.find('id="share-ask"')
check("a teacher's Share asks first, with Hide code inside that dialog",
      _ask != -1 and _tp.find('id="hide-code"') > _ask,
      "share-ask at %d, hide-code at %d" % (_ask, _tp.find('id="hide-code"')))
_sp = student.get("/").get_data(as_text=True)
check("  and a student gets neither", 'id="share-ask"' not in _sp
      and 'id="hide-code"' not in _sp)

# The join code on the teacher's bar is a button that copies /live/<code>.
_chip = re.search(r'<(\w+) id="live-code"', _tp)
check("the live code chip is a button", _chip and _chip.group(1) == "button",
      _chip.group(1) if _chip else "missing")
_app = open(os.path.join(HERE, "..", "static", "app.js")).read()
check("  that copies the class's whole link",
      re.search(r'liveChip\.addEventListener\("click"', _app)
      and 'location.origin + "/live/"' in _app)

# The notes panes neither grow nor shrink, so a console printing above them
# cannot take their height. The preview took it from the teacher's copy
# because its basis was `auto`, its own content.
_css = open(os.path.join(HERE, "..", "static", "style.css")).read()
for _sel in (".live-right .live-notes", ".pane-right .class-view"):
    _rule = re.search(re.escape(_sel) + r"\s*\{([^}]*)\}", _css)
    check("%s is a fixed size" % _sel,
          _rule and re.search(r"flex:\s*0 0 \d+%", _rule.group(1)),
          _rule.group(1).strip() if _rule else "no rule")
check("  and the preview beside them takes only what is left",
      re.search(r"\.pane-right #preview-view\s*\{\s*flex:\s*1 1 0;", _css))


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


def starter_of(page):
    """What the page tells live.js to start the student's editor with."""
    m = re.search(r"^\s*starter: (.*?),?$", page, re.M)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return "<not JSON: %s>" % m.group(1)   # fail the check, don't crash

# THE STARTER, as the handout link would give it. A lesson for an assignment
# used to hand every student an empty editor, so the class retyped the
# starter the teacher had already written for them.
check("a lesson for an assignment starts the class on its app.py",
      starter_of(stranger.get("/live/%s" % LESSON).get_data(as_text=True))
      == '# starter app')
check("  signed in with no draft of it yet, the same",
      starter_of(student.get("/live/%s" % LESSON).get_data(as_text=True))
      == '# starter app')
r = stranger.get("/api/live/%s" % LESSON)
check("  and it is in the page, never on the poll",
      "starter" not in r.get_json() and '# starter app' not in r.get_data(as_text=True),
      "the poll is the teacher's channel; the starter is the student's")

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

# THE DRAFT, NOT THE STARTER, once they have one. Saving here overwrites the
# draft's file with the live editor, so a student who did half of it from the
# link this morning and was handed the bare starter now would lose the
# morning on their first Save.
_mine = starter_of(student.get("/live/%s" % LESSON).get_data(as_text=True))
check("a student with a draft of the assignment starts from their draft",
      _mine == '# my work', repr(_mine))
check("  while everyone else still gets the starter",
      starter_of(stranger.get("/live/%s" % LESSON).get_data(as_text=True))
      == '# starter app')

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

# THE REST OF THE PROJECT, AS TABS. The live page was app.py alone, so a
# student could not see the template the lesson was about, and a Run of an
# app that rendered it failed on a file sitting in their own project. The
# page is handed the same files the handout link would open — their
# draft's — and a save carries the tabs back.
def page_value(page, key):
    m = re.search(r"^\s*%s: (.*?),?$" % key, page, re.M)
    try:
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return "<not JSON: %s>" % m.group(1)


def kept_now():
    db = F.SessionLocal()
    try:
        return db.query(accounts.Draft).filter_by(slug=KEPT).first().file_map()
    finally:
        db.close()


r = student.post("/api/live/%s/keep" % LESSON,
                 json={"code": "# my work",
                       "files": {"templates/home.html": "<h1>mine</h1>",
                                 "static/site.css": "h1 { color: red }"}})
check("a save from the live page keeps what they typed in the other tabs",
      r.status_code == 200 and kept_now() == {
          "app.py": "# my work", "templates/home.html": "<h1>mine</h1>",
          "static/site.css": "h1 { color: red }"}, kept_now())
check("  and hands back the project as saved, for Turn in",
      r.get_json().get("files") == kept_now(), r.get_json().get("files"))
# An empty map is an old editor tab from before the tabs, which sent `{}`
# on every save. Taken literally it would delete every template.
r = student.post("/api/live/%s/keep" % LESSON,
                 json={"code": "# my work", "files": {}})
check("  while an empty map leaves the files alone",
      r.status_code == 200 and "static/site.css" in kept_now(), sorted(kept_now()))
r = student.post("/api/live/%s/keep" % LESSON,
                 json={"code": "# my work", "files": {"../x.html": "no"}})
check("  and a file name the editor would refuse is refused here too",
      r.status_code == 400 and "../x.html" not in kept_now(), r.status_code)

# Their draft's files — static/site.css is in it and not in the assignment —
# so this cannot pass on the assignment's alone. The entry is left out: it
# is `starter`, and a second copy in the tabs would be two app.py's.
_mine_page = student.get("/live/%s" % LESSON).get_data(as_text=True)
check("the live page hands the student their project's other files",
      page_value(_mine_page, "starterFiles")
      == {k: v for k, v in kept_now().items() if k != "app.py"},
      page_value(_mine_page, "starterFiles"))
check("  and a student with no draft gets the assignment's",
      page_value(stranger.get("/live/%s" % LESSON).get_data(as_text=True),
                 "starterFiles") == {"templates/home.html": "<h1>hi</h1>"})
check("  naming app.py as the file the pane starts on",
      page_value(_mine_page, "entry") == "app.py", page_value(_mine_page, "entry"))

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
check("  and starts the student's editor empty, as it always did",
      starter_of(page) == "", repr(starter_of(page)))

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

# The live editor starts from the same file Save writes back to. Seeded from
# app.py in a SQL lesson, the student would start on the wrong thing — and
# their first Save would put it into query.sql.
_sql = starter_of(student.get("/live/%s" % sql_lesson).get_data(as_text=True))
check("a SQL lesson starts the student on their query.sql",
      _sql == "SELECT a FROM t;", repr(_sql))
_sql = starter_of(stranger.get("/live/%s" % sql_lesson).get_data(as_text=True))
check("  and a newcomer on the assignment's query.sql",
      _sql == "SELECT 1;", repr(_sql))

# THE DATABASE. The live editor holds one file, and the student's Run used
# to send only that — so in a SQL lesson every Run stopped at "There is no
# schema.sql", and nobody on the live page had ever seen a query result.
def schema_of(page):
    # schema.sql reaches the page as one of the student's tabs now
    return (page_value(page, "starterFiles") or {}).get("schema.sql")

check("a SQL lesson gives the student's Run the assignment's schema.sql",
      schema_of(stranger.get("/live/%s" % sql_lesson).get_data(as_text=True))
      == "CREATE TABLE t (a);")
# Their draft's schema made different from the assignment's, or this could
# not tell the two apart.
_mine = dict(kept_sql, **{"schema.sql": "CREATE TABLE t (a, b);"})
student.post("/api/draft/%s" % r.get_json()["slug"], json={"files": _mine})
check("  and their own draft's copy once they have one",
      schema_of(student.get("/live/%s" % sql_lesson).get_data(as_text=True))
      == "CREATE TABLE t (a, b);",
      "the same file /a/<slug> would run their query against")

# And again on the update path, which is a different branch entirely.
r = student.post("/api/live/%s/keep" % sql_lesson,
                 json={"code": "SELECT a, b FROM t;"})
kept_sql = r.get_json()["files"]
check("  saving again still writes query.sql",
      kept_sql.get("query.sql") == "SELECT a, b FROM t;"
      and "app.py" not in kept_sql,
      sorted(kept_sql))
check("  and the page names query.sql as the entry, so Run is SQL",
      page_value(student.get("/live/%s" % sql_lesson).get_data(as_text=True),
                 "entry") == "query.sql")
# With the tabs, the page's own `entry` says which file the code is. Even
# a page claiming app.py cannot turn a SQL draft into a Flask one: the
# project already saved decides.
r = student.post("/api/live/%s/keep" % sql_lesson,
                 json={"code": "SELECT 2;", "entry": "app.py",
                       "files": {"schema.sql": "CREATE TABLE t (a, b);"}})
kept_sql = r.get_json()["files"]
check("  and a page that names the wrong entry cannot change the kind",
      kept_sql.get("query.sql") == "SELECT 2;" and "app.py" not in kept_sql,
      sorted(kept_sql))

# A SQL lesson with no assignment has no files to say which kind it is.
# The teacher's open file says, as it always did on this page — and Save
# then has to land in that same file.
teacher.post("/api/live/%s/stop" % sql_lesson)
bare_sql = teacher.post("/api/live/start",
                        json={"body": "SELECT 1;", "filename": "query.sql",
                              "assignment": ""}).get_json()["code"]
check("a SQL lesson with no assignment starts the pane on query.sql",
      page_value(stranger.get("/live/%s" % bare_sql).get_data(as_text=True),
                 "entry") == "query.sql")
r = student.post("/api/live/%s/keep" % bare_sql,
                 json={"code": "SELECT 3;", "entry": "query.sql"})
check("  and saving it keeps query.sql, not an app.py full of SQL",
      r.status_code == 200 and r.get_json()["files"] == {"query.sql": "SELECT 3;"},
      r.get_json())


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


# ------------------------------------------- reopening yesterday's lesson
#
# A lesson that ended — Stop, signing out, or the overnight sweep — used to
# be gone for good: the link the class had from yesterday only ever said
# "Lesson ended". Now the teacher opens that same link and presses "Teach
# this lesson again". It is never offered anywhere else: a reopened lesson
# lands on every screen still showing its host_page, which is the "sign in and
# I'm live" bug if it ever happens without the teacher choosing it. (Go
# live once offered "your last lesson", which was whichever was most recent
# rather than the one meant, and left the editor showing whatever was open.)
print("\nReopening yesterday's lesson")

def set_row(code, **fields):
    db = F.SessionLocal()
    try:
        db.query(accounts.LiveSession).filter_by(code=code).update(fields)
        db.commit()
    finally:
        db.close()

def item_id(slug):
    db = F.SessionLocal()
    try:
        return db.query(accounts.Assignment).filter_by(slug=slug).first().id
    finally:
        db.close()


def lesson_row(code):
    db = F.SessionLocal()
    try:
        return db.query(accounts.LiveSession).filter_by(code=code).first()
    finally:
        db.close()

check("Go live offers no lesson of its own accord",
      "recent" not in teacher.get("/api/live/assignments").get_json(),
      "it offered the most recent lesson, not the one the teacher meant")

# Yesterday's lesson: for the homework, ended by the sweep a day ago.
set_row(LESSON, ended=1, updated_at=F._live_now() - F.timedelta(days=1))
host_page = teacher.get("/live/%s" % LESSON).get_data(as_text=True)
_teach = re.search(r'<a id="teach-again"[^>]*href="([^"]*)"', host_page)
check("its teacher, opening its link, can teach it again",
      _teach is not None and "Teach this lesson again" in host_page,
      "the link the class still has could never be used again")
check("  into the editor, with the lesson and its assignment's starter",
      _teach is not None and _teach.group(1).replace("&amp;", "&")
      in ("/?teach=%s&a=%s" % (LESSON, hw), "/?a=%s&teach=%s" % (hw, LESSON)),
      _teach.group(1) if _teach else "")
check("  and is not offered End lesson for a lesson already over",
      'id="live-stop"' not in host_page)
check("  nor a connection chip that never connects",
      'id="live-state"' not in host_page)
host_page = student.get("/live/%s" % LESSON).get_data(as_text=True)
check("a student opening the same link is offered nothing of the kind",
      'id="teach-again"' not in host_page)
host_page = other.get("/live/%s" % LESSON).get_data(as_text=True)
check("  nor is another teacher", 'id="teach-again"' not in host_page)

r = other.post("/api/live/start", json={"body": "x", "reopen": LESSON})
check("another teacher cannot reopen it", r.status_code == 404, r.status_code)
check("  and it stays ended", lesson_row(LESSON).ended == 1)

r = teacher.post("/api/live/start", json={"body": "x", "resume": LESSON})
check("a reload's resume still cannot reopen it",
      r.get_json().get("resumed") is False and lesson_row(LESSON).ended == 1,
      r.get_json())

r = teacher.post("/api/live/start", json={"body": "day two", "reopen": LESSON})
got = r.get_json()
check("the teacher can reopen it", r.status_code == 200, r.status_code)
check("  under the same code, so yesterday's link works again",
      got.get("code") == LESSON, got)
check("  still for the same assignment, so Turn in goes where it went",
      got.get("assignment") == hw, got)
check("  and it survives the sweep that ended it overnight",
      lesson_row(LESSON).ended == 0,
      "start sweeps after it commits: a stale updated_at would end it again")
r = stranger.get("/api/live/%s" % LESSON)
check("  and the class's host_page is told it is back on",
      r.get_json().get("ended") is False, r.get_json())
host_page = teacher.get("/live/%s" % LESSON).get_data(as_text=True)
check("while it is open the link still takes its teacher back in",
      "Teach this lesson</a>" in host_page.replace("\n", "").replace("  ", "")
      and 'id="live-stop"' in host_page)

other_open = teacher.post("/api/live/start", json={"body": "x"}).get_json()
check("  (pressing Go live now carries on in the reopened one)",
      other_open.get("code") == LESSON, other_open)

# Two open rows for one teacher: the newest wins every later Go live and
# reload, which is not the one the class is looking at.
set_row(LESSON, ended=1)
newer = teacher.post("/api/live/start", json={"body": "x"}).get_json()["code"]
teacher.post("/api/live/start", json={"body": "x", "reopen": LESSON})
check("reopening closes whatever else was open, leaving one",
      open_lessons(TEACHER) == 1 and lesson_row(newer).ended == 1,
      "%d open" % open_lessons(TEACHER))
teacher.post("/api/live/%s/stop" % LESSON)


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
# What goes in is their own browser's copy, or — only when there is none —
# the starting point the PAGE was rendered with (L.starter: their draft or
# the assignment's starter). Traced through one variable, and nothing else
# may feed it: not the poll's data, not the mirror.
assigned = re.findall(r"\b(?:var\s+)?%s\s*=\s*([^;]+);" % re.escape(arg),
                      live_code) if arg else []
source_ok = (len(assigned) == 1
             and re.fullmatch(r"kept !== null \? kept : \(L\.starter \|\| \"\"\)",
                              assigned[0].strip()) is not None)
kept_ok = re.search(r"\bkept\s*=\s*window\.localStorage\.getItem\(DRAFT_KEY\)",
                    live_code) is not None
check("  and what goes in is their browser's copy, else the page's starter",
      source_ok and kept_ok,
      "mine.setValue(%s) = %s" % (arg or "nothing", assigned))

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


# `mainSource()` is the entry's document, whichever tab is showing.
# Resolved to the editor that document belongs to, so a mainSource() that
# read the mirror fails here rather than slipping past as unknown.
main_ok = (re.search(r"function mainSource\(\) \{ return docs\[MAIN\]\.getValue\(\); \}",
                     live_code) is not None
           and re.findall(r"docs\[MAIN\] *= *([^;]+);", live_code) == ["mine.getDoc()"])
_real_code = live_code
live_code = live_code.replace("mainSource()",
                              "mine.getValue()" if main_ok else "?mainSource()")
saved_from = editors_behind("code")
live_code = _real_code
check("  and what is saved to their projects is their editor, not the mirror",
      bool(saved_from) and saved_from == {"mine"},
      "saved from: %s" % sorted(saved_from))

# THE OTHER TABS ARE THEIRS TOO. Every one is a document made here, from
# the page or their browser — and none is ever filled from the mirror or
# the poll's data, nor written into after it is made.
doc_fills = re.findall(r"docs\[[^\]]+\] *= *([^;]+);", live_code)
check("  and every other tab is filled from the page or their browser",
      bool(doc_fills) and all("mirror" not in f and "data." not in f
                              for f in doc_fills),
      doc_fills)
check("  and never written into afterwards",
      not re.search(r"docs\[[^\]]+\]\.(setValue|replaceRange)\(", live_code))
check("  every save carries those tabs, never an empty map",
      "files: {}" not in live_code
      and len(re.findall(r"files: dataFiles\(\)", live_code)) == 2
      and "files: allFiles()" in live_code,
      "the live autosave sent {} and every one came back 400")
check("  with tabs on the page to switch between them",
      'id="mine-tabs"' in page and "starterFiles:" in page)

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


def rule(selector):
    """The declarations of the one rule whose selector list is exactly this."""
    m = re.search(r"(?m)^%s \{([^}]*)\}" % re.escape(selector), css)
    return m.group(1) if m else ""


# THE STUDENT'S PREVIEW IS STACKED, like the editor's. preview.js
# double-buffers, adding a second iframe on the first Run; left in the flow
# it sat under the first, over the console and the notes, and the student's
# page was painted across the panes beneath while the preview stayed blank.
check("the live preview's two frames sit on top of each other",
      declares(rule(".preview-wrap iframe"), "position", "absolute")
      and declares(rule(".preview-wrap"), "position", "relative")
      and declares(rule(".preview-wrap iframe.is-back"), "opacity", "0"),
      "otherwise the page paints over the console and the notes")
# THE CONSOLE IS A STRIP, the notes the bigger share. At 28% the console
# took more of the column than the notes, which is where the lesson is.
_con = re.search(r"flex: 0 0 (\d+)%", rule(".live-console"))
_notes = re.search(r"flex: 0 0 (\d+)%", rule(".live-right .live-notes"))
check("  and the console is a strip, smaller than the notes under it",
      _con and _notes and int(_con.group(1)) <= 20
      and int(_con.group(1)) < int(_notes.group(1)),
      "console %s, notes %s" % (_con and _con.group(1), _notes and _notes.group(1)))


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

# An ended lesson used to stop the polling, and that is what left a class on
# yesterday's code: they opened the link before their teacher pressed Go
# live, saw "Lesson ended", and nothing ever asked again. It keeps asking now,
# slowly — see the poll run for real under "an ended lesson keeps checking".

# Resuming (see "Resuming after a reload" above): the editor's half.
_app_code = code_only(open(os.path.join(HERE, "..", "static", "app.js")).read())
check("the editor sends the remembered code when it resumes",
      re.search(r"startLive\(undefined, resumeCode\)", _app_code) is not None
      and "resume: resume" in _app_code)
check("  and forgets it when the server says that lesson is over",
      re.search(r"data\.resumed === false\)\s*\{[^}]*forgetLive\(\);", _app_code) is not None)
check("  and forgets it on any page with no Go live button",
      re.search(r'\}\s*else\s*\{\s*try\s*\{\s*sessionStorage\.removeItem\("flaskide-live-host"\);', _app_code)
      is not None)
# Only the tab that went live, on the page it went live from, rejoins. The
# marker was shared by the whole browser, so any editor the teacher opened
# while live took over the broadcast with its own file — the class watched
# an untitled default template while the teacher typed in another tab.
check("the lesson is remembered per tab, not for the whole browser",
      'sessionStorage.setItem(HOST_KEY, JSON.stringify({ code: code, path: location.pathname }));'
      in _app_code and "localStorage.setItem(HOST_KEY" not in _app_code
      and 'localStorage.setItem("flaskide-live-host"' not in _app_code,
      "any editor tab would take over the class's screens")
check("  and rejoined only on the page it went live from",
      'return saved && saved.path === location.pathname ? saved.code : null;' in _app_code
      and "var resumeCode = liveToResume();" in _app_code)
check("  and the old shared marker is cleared, so it can never rejoin anything",
      "try { localStorage.removeItem(HOST_KEY); }" in _app_code)

# The notes pane: the editor sends the project's first .md on every push,
# and changing only the notes still counts as something to push — otherwise
# a teacher editing the notes while another file is open would send nothing.
_push = code_only(open(os.path.join(HERE, "..", "static", "app.js")).read())
_push_fn = _push[_push.index("function pushNow"):]
_push_fn = _push_fn[:_push_fn.index("\n    }\n")]
check("the editor sends the notes with every push",
      "notes: notes" in _push_fn and "var notes = liveNotes();" in _push_fn)
check("  and a change to the notes alone is pushed",
      re.search(r"var stamp = [^;]*\bnotes\b", _push_fn) is not None,
      "editing the notes with another file open would reach nobody")
check("  and they are the project's first .md",
      re.search(r"function notesFile\(\)[\s\S]{0,200}tabOrder\(\)\.filter\(window\.FlaskIDENotes\.isMarkdown\)[\s\S]{0,80}md\[0\]", _push) is not None
      and re.search(r"function liveNotes\(\)\s*\{\s*var md = notesFile\(\);", _push) is not None)
_mirror_fn = live_code[live_code.index("function showMirror"):]
_mirror_fn = _mirror_fn[:_mirror_fn.index("\n  }\n")]
check("the live page shows them on every update, not only the first",
      "showNotes(data);" in _mirror_fn)
check("  and on the page's first paint, before any poll",
      re.search(r"showMirror\(\{[^}]*notes: L\.notes", live_code) is not None,
      "the first poll answers 304, so a late joiner would never see them")
_notes_fn = live_code[live_code.index("function showNotes"):]
_notes_fn = _notes_fn[:_notes_fn.index("\n  }\n")]
check("  through the slide viewer, which re-renders only when the slide changes",
      "notesSlides.show(data.notes, jump);" in _notes_fn
      and "if (text === drawn) return Promise.resolve(true);"
      in open(os.path.join(HERE, "..", "static", "notes.js")).read(),
      "a re-render every second replaces the link a student is clicking")
check("  and jumps to the teacher's slide only when the teacher moves",
      re.search(r"if \(slide !== teacherSlide\) \{\s*teacherSlide = slide;", _notes_fn)
      is not None,
      "typing on the same slide would drag back every student who read ahead")

# ------------------------------------- slides, output and the page, built
def fn_body(src, name):
    at = src.find("function " + name + "(")
    if at < 0:
        return ""
    end = src.find("\n  }\n", at)
    return src[at:end] if end > 0 else src[at:]

# The teacher's console and page go in their own <pre> and frame. The
# student's console and preview are theirs exactly as their editor is.
_tout = fn_body(live_code, "showTeacherOutput")
check("the teacher's console is written only into its own pane",
      "teacherOut.textContent = data.output" in _tout
      and not re.search(r"outputEl[^;]*data\.output|data\.output[^;]*outputEl|write\(data\.output",
                        live_code),
      "the student's own console must never be given it")
_tpage = fn_body(live_code, "showTeacherPage")
check("the teacher's page goes only into its own frame",
      "teacherFrame.srcdoc = " in _tpage
      and not re.search(r"preview\.\w+\([^)]*(html|data\.page)", live_code)
      and live_code.count(".srcdoc") == 1,
      "the student's own preview must never be given it")
check("  with links that cannot navigate the frame",
      "'<base target=\"_blank\">' + html" in _tpage)
check("  and only when it changes",
      "if (data.page === shownPage) return;" in _tpage,
      "a srcdoc every second flashes white on thirty screens")
check("neither comes to the front by itself, each only gets a dot",
      "showOutputTab(" not in _tout and "showPageTab(" not in _tpage
      and 'outTeacherTab.classList.add("has-new")' in _tout
      and 'pageTeacherTab.classList.add("has-new")' in _tpage,
      "every teacher Run took the class away from their own app")
check("  and their own Run brings both of theirs back",
      re.search(r"async function run\(\)[\s\S]{0,200}showOutputTab\(false\);\s*showPageTab\(false\);",
                live_code) is not None)
check("  and a late joiner is offered them, not switched to them",
      re.search(r"showMirror\(\{[^}]*initial: true", live_code) is not None
      and "showTeacherPage(data, data.initial);" in live_code
      and "showTeacherOutput(data, data.initial);" in live_code)
check("the editor sends its caret with every push, and moving it counts",
      "cursor: cursor, seq: nextSeq()" in _push_fn
      and re.search(r"var stamp = [^;]*\bcursor\b", _push_fn) is not None,
      "a caret moved without typing would reach nobody")
check("  but none for a notes file, which the class reads rendered",
      re.search(r"if \((docs\[name\]|editor) && !window\.\w+Notes\.isMarkdown\(name\)\)",
                _push_fn) is not None)
check("the mirror draws the caret on every update",
      re.search(r"showCaret\(typeof data\.cursor", _mirror_fn) is not None
      and re.search(r"showMirror\(\{[^}]*cursor: L\.cursor", live_code)
      is not None)
_caret_fn = fn_body(live_code, "showCaret")
check("  as a widget, so the mirror still takes no cursor",
      "setBookmark(at, { widget: mark" in _caret_fn
      and "mirror.setCursor" not in live_code
      and "mirror.setSelection" not in live_code)
check("  and follows it, unless the student has just scrolled",
      "if (Date.now() >= followAfter) mirror.scrollIntoView(show" in _caret_fn
      and re.search(r'\["wheel", "touchmove", "mousedown"\][\s\S]{0,160}'
                    r'followAfter = Date\.now\(\) \+ FOLLOW_PAUSE_MS',
                    live_code) is not None,
      "a student reading line 4 would be yanked to line 40 every keystroke")
check("the editor sends a highlighted block as anchor-head",
      re.search(r"somethingSelected\(\)\) \{\s*var from = editor"
                r"\.getCursor\(\"anchor\"\);\s*cursor = from\.line \+ \":\" \+ "
                r"from\.ch \+ \"-\" \+ cursor;", _push_fn) is not None,
      "dragging across a block to talk about it would show nobody anything")
check("  and the mirror paints it yellow as a mark, not a selection",
      'mirror.markText(from, to, { className: "mirror-pick" })' in _caret_fn
      and ".live-mirror .mirror-pick" in _css)
check("  in order even when dragged upwards",
      "CodeMirror.cmpPos(other, at) > 0" in _caret_fn,
      "markText with from after to marks nothing")
check("  and cleared with the caret",
      "if (pickMark) { pickMark.clear(); pickMark = null; }"
      in fn_body(live_code, "clearCaret"),
      "every highlight would stay yellow forever")
check("  clearing the old caret before the text is replaced",
      re.search(r"data\.body !== mirror\.getValue\(\)\) \{\s*clearCaret\(\);",
                _mirror_fn) is not None,
      "a removed line's handle throws, and the poll would stop")

_live_html = open(os.path.join(FLASKIDE, "templates", "live.html")).read()
check("the console starts folded",
      'class="subpane live-console is-folded"' in _live_html
      and re.search(r"\n  openConsole\(false\);", live_code) is not None)
check("  and an error opens it",
      'if (cls === "err") openConsole(true);' in fn_body(live_code, "write"),
      "a mistake written into a folded pane is one nobody sees")
check("  and so does Run in a SQL lesson, where it holds the results",
      re.search(r"async function run\(\)[\s\S]{0,260}if \(isSql\(\)\) openConsole\(true\);",
                live_code) is not None)

check("the editor sends slide, console and page with every push",
      "slide: slide, output: output, page: page," in _push_fn
      and re.search(r"var stamp = [^;]*\bslide\b[^;]*\boutput\b[^;]*\bpage\b", _push_fn)
      is not None,
      "moving a slide, or a Run, would otherwise reach nobody")
check("  the WHOLE notes go out, so students can move through the slides",
      "var notes = liveNotes();" in _push_fn
      and len(re.findall(r"(?<![\w.])notes\s*=(?!=)", _push_fn)) == 1
      and "notes: notes," in _push_fn,
      "one slide at a time, nobody could read ahead or go back to a question")
check("  and the notes tab, if open, mirrors the teacher's slide, not the file",
      "if (name === notesFile()) text = onSlide;" in _push_fn,
      "the mirror would put every slide on screen at once")
check("  and nothing of a Run is sent before the first one",
      re.search(r"function liveOutput\(\)\s*\{\s*if \(!hasRun \|\| !out\) return \"\";", _push) is not None
      and re.search(r"function livePage\(\)\s*\{\s*if \(!hasRun\) return \"\";", _push) is not None)
_lp = _push[_push.index("function livePage"):]
_lp = _lp[:_lp.index("\n    }\n")]
check("  the page is what the preview shows, at the path it shows it for",
      "JSON.stringify({ path: preview.path || \"/\", html: preview.shown })" in _lp)
check("  and a SQL lesson sends its results grid instead",
      re.search(r"if \(isSql\(\)\)[\s\S]{0,200}\$\(\"sql-results\"\)[\s\S]{0,200}sql: true", _lp) is not None,
      "a SQL lesson's answer never touches the console")
_pv = code_only(open(os.path.join(HERE, "..", "static", "preview.js")).read())
check("the preview remembers the page it painted, before the shim",
      "this.shown = res.body;\n      await this._paint(res.body, true);" in _pv
      and 'this.shown = "";\n        await this._show(' in _pv,
      "an image would leave the last page standing as 'the page'")

# A student's SQL Run on the live page, built.
_run = fn_body(live_code, "run")
check("the live Run sends every tab, schema.sql and templates included",
      "var project = allFiles();" in _run
      and re.search(r"function allFiles\(\) \{\s*var out = dataFiles\(\);\s*"
                    r"out\[MAIN\] = mainSource\(\);\s*return out;", live_code)
      is not None,
      "render_template found nothing when Run sent app.py alone")
check("  and SQL or Flask is the student's entry file, from the server",
      "function isSql() { return MAIN === L.sqlEntry; }" in live_code
      and "var MAIN = L.entry" in live_code
      and '"query.sql"' not in code_only(live_code))
check("  prints the query results, not the schema's table list",
      "writeSqlResults(out.results);" in _run and "out.tables" not in _run,
      "tables is names and row counts; printed as results it was blank lines")
check("  and with no database says so rather than 'add a schema.sql'",
      re.search(r"if \(isSql\(\) && !project\[\"schema\.sql\"\]\) \{[\s\S]{0,400}return;", _run)
      is not None,
      "writing the lesson's database is the teacher's move, not the student's")

import shutil
import subprocess

# And for real: the bridge's own SQL run (as the browser receives it — see
# test_sql.py), handed to the live page's own printer in node.
sys.path.insert(0, HERE)
_tsql = open(os.path.join(HERE, "test_sql.py")).read()
_ns = {"__name__": "lifted", "ROOT": __import__("pathlib").Path(FLASKIDE),
       "re": re, "sys": sys, "types": __import__("types")}
for _name in ("unescape_template_literal", "load_bridge"):
    _m = re.search(r"^def %s\([\s\S]*?(?=^\S)" % _name, _tsql, re.M)
    exec(_m.group(0), _ns)
_bridge = _ns["load_bridge"](tempfile.mkdtemp(prefix="flaskide-live-"))
_out = json.loads(_bridge._flaskide_run_sql(json.dumps({
    "schema.sql": "CREATE TABLE pet (id INTEGER, name TEXT, owner TEXT);"
                  "INSERT INTO pet VALUES (1, 'Rex', 'Ana'), (22, 'Bo', NULL);",
    "query.sql": "SELECT id, name, owner FROM pet; UPDATE pet SET id = 3 WHERE id = 1;"})))
_print = fn_body(live_code, "writeSqlResults")
_print = _print and _print + "\n  }"       # fn_body stops before the brace
if shutil.which("node") and _print:
    harness = ("var lines = [];\nfunction write(t) { lines.push(t); }\n%s\n"
               "writeSqlResults(%s);\nconsole.log(JSON.stringify(lines.join('')));"
               % (_print, json.dumps(_out.get("results"))))
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    try:
        shown = json.loads(res.stdout)
    except ValueError:
        shown = ""
    check("a real query's rows reach the student's console",
          "id | name | owner" in shown and "22 | Bo   | NULL" in shown
          and "1  | Rex  | Ana" in shown,
          repr(shown or res.stderr[-300:]))
    check("  with a row count, and what an UPDATE changed",
          "2 rows" in shown and "1 changed" in shown, repr(shown))
else:
    check("node is available to run writeSqlResults", False, "brew install node")

# The splitter, run for real on the notes this feature was asked for.
notes_js = open(os.path.join(HERE, "..", "static", "notes.js")).read()
if shutil.which("node"):
    # Cut where the author drew a ---, and nowhere else. The first version
    # cut at every `## ` heading, and this sample is what it got wrong: the
    # ### slide was glued onto the one before it, the slide with two ##
    # sections was cut in half, and the --- straight under a line of text
    # did not end its slide at all.
    sample = (
        "# Looping Over a List\n\n---\n\n## for Each Item\n\n"
        "```python\n## a comment\nfor e in enemies:\n    print(e)\n```\n\n"
        "```text\n---\n```\n\n---\n\n"
        "## enumerate()\n\nPosition and item.\n\n## zip()\n\nTwo lists.\n\n---\n\n"
        "### still a slide of its own\nNo blank line before the rule.\n---\n"
        "## ✏ Mini Assignment\n\n> Extension\n")
    harness = "var window = {};\n" + notes_js + """
var N = window.FlaskIDENotes;
console.log(JSON.stringify({
  cut: N.slides(%s),
  none: N.slides("# Just notes\\n\\n## A section\\n\\n## Another\\n"),
  crlf: N.slides("## A\\r\\nx\\r\\n---\\r\\n## B\\r\\ny")
}));
""" % json.dumps(sample)
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    try:
        got = json.loads(res.stdout)
    except ValueError:
        got = {}
    cut = got.get("cut") or []
    check("notes split into slides at each --- and nowhere else",
          len(cut) == 5 and cut[0] == "# Looping Over a List"
          and cut[1].startswith("## for Each Item")
          and cut[4].startswith("## ✏ Mini Assignment"),
          repr([c[:20] for c in cut] or res.stderr[-200:]))
    check("  a slide holding two ## sections stays one slide",
          len(cut) > 2 and cut[2].startswith("## enumerate()")
          and cut[2].endswith("Two lists."),
          repr(cut[2] if len(cut) > 2 else ""))
    check("  a slide headed by ### is its own slide",
          len(cut) > 3 and cut[3].startswith("### still a slide of its own"),
          repr(cut[3] if len(cut) > 3 else ""))
    check("  a --- straight under a line of text still ends the slide",
          len(cut) > 3 and cut[3].endswith("No blank line before the rule."),
          repr(cut[3] if len(cut) > 3 else ""))
    check("  ## and --- inside a code fence do not cut it",
          len(cut) > 1 and "## a comment" in cut[1]
          and "```text\n---\n```" in cut[1],
          "a line of output would cut a slide in half")
    check("  the --- itself is not shown on either side",
          all(not c.startswith("---") and not c.endswith("---") for c in cut),
          repr(cut[1][-12:] if len(cut) > 1 else ""))
    check("  notes with ## headings but no --- are not slides at all",
          got.get("none") == [], repr(got.get("none")))
    check("  Windows line endings split the same way",
          got.get("crlf") == ["## A\nx", "## B\ny"], repr(got.get("crlf")))
else:
    check("node is available to run the slide splitter", False,
          "brew install node")

# Show all, and the slide controls in the Class sees pane head.
r = teacher.get("/")
_page = r.get_data(as_text=True)
_cv = _page.find('id="class-view"')
check("the slide controls sit in the Class sees pane, not the top bar",
      -1 < _cv < _page.find('id="live-slides"') < _page.find('id="class-notes"'),
      "the top bar had no room for them")
check("  and no Show all: students move through the slides themselves",
      'id="slide-whole"' not in _page and "wholeNotes" not in _push,
      "it sent the whole file as one page, which the class now always has")
_stop_fn = fn_body(_push, "stopLive")
check("  the arrows' [hidden] really hides them",
      re.search(r"\.slide-ctl \.btn\[hidden\]\s*\{\s*display:\s*none",
                open(os.path.join(HERE, "..", "static", "style.css")).read())
      is not None,
      ".btn sets display, so [hidden] alone shows them anyway")
# The teacher sees what the class's Notes pane shows, fed from what is sent.
check("the teacher sees the slide the class is sent to",
      "paintClassView(onSlide, slide);" in _push_fn
      and _push_fn.index("onSlide = cut[slideAt];")
          < _push_fn.index("paintClassView(onSlide, slide);")
          < _push_fn.index("if (stamp === lastSent) return;"),
      "fed anything but what is sent, it can show a slide the class is not on")
_class_fn = fn_body(_push, "paintClassView")
check("  re-rendered only when it changes",
      "if (notes === classShownNotes && slide === classShownSlide) return;"
      in _class_fn,
      "pushNow runs every tick; re-rendering resets the teacher's scroll")
check("  and put away when the lesson ends",
      re.search(r"function paintLive\(\)[\s\S]*?\} else \{[\s\S]*?paintClassView\(null, \"\"\);",
                _push) is not None)

# ----------------------------------------- a link to another site
# Clicked in the preview — editor or live, both use preview.js — it has to
# open a new tab. It used to set only the status chip's hover title, so a
# student's link to MDN did nothing anyone could see. Driven in node: the
# shim really receives the click, and the Preview really handles the message.
_pv_src = open(os.path.join(HERE, "..", "static", "preview.js")).read()
_shim = re.search(r"const SHIM = (`<script>[\s\S]*?<\\/script>`);", _pv_src)
if shutil.which("node") and _shim:
    _harness = """
var sent = [], listeners = {}, opened = [], notes = [], gone = [], blockAll = false;
var document = { addEventListener: function (t, f) { listeners[t] = f; } };
var parent = { postMessage: function (m) { sent.push(m); } };
var location = { pathname: "/" };
var SHIM = %s;
eval(SHIM.replace(/^<script>/, "").replace(/<\\/script>$/, ""));
function click(href, resolved) {
  var a = { getAttribute: function () { return href; }, href: resolved || href };
  var e = { target: { closest: function () { return a; } }, defaultPrevented: false,
            preventDefault: function () { this.defaultPrevented = true; } };
  sent = [];
  listeners.click(e);
  return { stopped: e.defaultPrevented, msg: sent[0] || null };
}
var window = { FlaskIDERuntime: {}, open: function (url, where) {
  if (blockAll) return null;
  opened.push([url, where]); return { opener: "editor" }; } };
%s
var W = {};
var p = Object.create(window.FlaskIDEPreview.prototype);
p.frames = [{ contentWindow: W }]; p.live = 0;
p.onNote = function (t, failed) { notes.push([t, !!failed]); };
p.go = function (path) { gone.push(path); };
function deliver(msg) { p._fromPage({ data: msg, source: W }); }
var out = {};
var ext = click("https://developer.mozilla.org/", "https://developer.mozilla.org/");
out.extStopped = ext.stopped; out.extMsg = ext.msg;
deliver(ext.msg);
var proto = click("//example.com/x", "https://example.com/x");
out.protoMsg = proto.msg;
var route = click("/about", "about:srcdoc");
out.routeMsg = route.msg;
deliver(route.msg);
var js = click("javascript:alert(1)");
deliver(js.msg);
out.openedBeforeBlock = opened.slice();
blockAll = true;
deliver(ext.msg);
p._fromPage({ data: ext.msg, source: {} });   // a frame nobody is looking at
out.opened = opened; out.notes = notes; out.gone = gone;
console.log(JSON.stringify(out));
""" % (_shim.group(1), _pv_src)
    _res = subprocess.run(["node", "-e", _harness], capture_output=True, text=True)
    try:
        _got = json.loads(_res.stdout)
    except ValueError:
        _got = {}
    _notes = _got.get("notes") or []
    check("a link to another site opens it in a new tab",
          _got.get("extStopped") is True
          and _got.get("openedBeforeBlock") == [["https://developer.mozilla.org/", "_blank"]],
          repr(_got or _res.stderr[:400]))
    check("  and the console says so",
          len(_notes) > 0 and _notes[0][0].startswith("Opened in a new tab")
          and _notes[0][1] is False, repr(_notes[:1]))
    check("  a //host link is another site too, not a route in the app",
          (_got.get("protoMsg") or {}).get("kind") == "external"
          and (_got.get("protoMsg") or {}).get("href") == "https://example.com/x",
          repr(_got.get("protoMsg")))
    check("  a link to one of the app's own routes still goes to the app",
          _got.get("gone") == ["/about"], repr(_got.get("gone")))
    check("  a javascript: link opens nothing, and says so",
          len(_notes) > 1 and "nothing opened" in _notes[1][0] and _notes[1][1] is True,
          repr(_notes[1:2]))
    check("  a blocked pop-up says so, loudly enough to open the console",
          len(_notes) == 3 and "blocked" in _notes[2][0] and _notes[2][1] is True,
          repr(_notes[2:]))
    check("  and a frame that is not on screen cannot open anything",
          len(_got.get("opened") or []) == 1, repr(_got.get("opened")))
else:
    check("node runs the preview's link handling", False,
          "brew install node" if _shim else "SHIM not found in preview.js")

# ------------------------------------- reopening, as the browsers do it
print("\nReopening, in the browsers")

_app_now = code_only(open(os.path.join(FLASKIDE, "static", "app.js")).read())
# This file's fn_body finds a function's end by its indent, which suits the
# top-level ones it was written for; teachAgain sits one level in.
_m_teach = re.search(r"function teachAgain\(code, slug\) \{[\s\S]*?\n    \}\n", _app_now)
_teach_fn = _m_teach.group(0) if _m_teach else ""
check("app.js reopens only from Teach this lesson again",
      'startLive(undefined, "", code);' in _teach_fn
      and len(re.findall(r'(?<!function )startLive\([^)]*,[^)]*,', _app_now)) == 1
      and "offerReopen" not in _app_now,
      "a reopen from anywhere else is the teacher back on the air unasked")
check("  and only when the link asked for it",
      re.search(r'if \(teach\) \{[\s\S]{0,200}?history\.replaceState\([\s\S]{0,120}?teachAgain\(teach, teachFor\);',
                _app_now) is not None,
      "left in the address bar, a reload would load the starter over the lesson")
check("  and the reload path never asks for one",
      'startLive(undefined, resumeCode);' in _app_now)

# What it does, run for real: the project goes into the editor BEFORE the
# lesson reopens, so the first push the class sees is the lesson's code and
# not whatever the editor happened to be showing.
if shutil.which("node") and _teach_fn:
    harness = """
var log = [], files = {"app.py": "default"}, current = "app.py";
var editor = {v: "default", setValue: function (t) { this.v = t; }, getValue: function () { return this.v; }};
function loadStarter(inc) { log.push("starter"); files = {};
  Object.keys(inc).forEach(function (n) { files[n] = inc[n]; }); current = "app.py"; editor.setValue(files["app.py"]); }
function openFile(n) { files[current] = editor.getValue(); current = n; editor.setValue(files[n]); log.push("switch " + n); }
function paintTabs() {}
function startLive(a, r, code) { files[current] = editor.getValue();
  log.push("live " + code + " " + (files["app.py"] !== undefined ? files["app.py"] : "-")
  + " " + (files["notes.md"] !== undefined ? files["notes.md"] : "-")); }
var replies = %s;
function fetch(url) { return Promise.resolve({json: function () {
  return Promise.resolve(replies[url.split("?")[0]]); }}); }
%s
var which = process.argv[1];
teachAgain("abc", which === "noassign" ? "" : "hw1");
setTimeout(function () { console.log(JSON.stringify(log)); }, 50);
"""
    def run_teach(which, last):
        h = harness % (json.dumps({
            "/api/live/assignment/hw1": {"title": "HW", "files": {"app.py": "starter code", "notes.md": "# notes"}},
            "/api/live/abc": last}), _teach_fn)
        res = subprocess.run(["node", "-e", h, which], capture_output=True, text=True)
        return json.loads(res.stdout) if res.returncode == 0 else [res.stderr[-200:]]
    got = run_teach("assign", {"body": "yesterday's end", "filename": "app.py"})
    check("teach again loads the starter, then yesterday's code, then goes live",
          got == ["starter", "live abc yesterday's end # notes"], got)
    got = run_teach("assign", {"body": "## edited notes", "filename": "notes.md"})
    check("  a lesson that ended on the notes leaves the notes as written",
          got == ["starter", "live abc starter code # notes"], got)
    got = run_teach("noassign", {"body": "x = 1", "filename": "app.py"})
    check("  and with no assignment it still brings the code back",
          got == ["live abc x = 1 -"], got)
else:
    check("node is available to run teachAgain", False, "brew install node")

_live_now_js = code_only(open(os.path.join(FLASKIDE, "static", "live.js")).read())
# THE BUG: one `seen` for both the draft's version and the lesson's, so the
# first poll wrote the lesson's version over the draft's and every Save from
# a student with an earlier draft was refused as "changed in another tab".
check("live.js keeps the draft's version apart from the lesson's",
      len(re.findall(r'\bvar seen\b', _live_now_js)) == 1
      and "payload.base = draftSeen" in _live_now_js
      and re.search(r'function saw\(data\) \{[^}]*draftSeen = data\.version',
                    _live_now_js) is not None,
      "a reopened lesson would refuse every student's first Save")

# Which copy a student's editor starts from, run for real. Lifted from
# `var kept = null;` to the line that decides, and run against a stand-in
# localStorage — a reopened lesson has the same code, so the same keys, as
# yesterday.
_m = re.search(r'(  var kept = null;.*?  var start = kept !== null \? kept : '
               r'\(L\.starter \|\| ""\);)', _live_now_js, re.S)
if shutil.which("node") and _m:
    harness = """
var cases = %s, out = {};
Object.keys(cases).forEach(function (k) {
  var c = cases[k], store = Object.assign({}, c.store);
  var window = {localStorage: {
    getItem: function (n) { return n in store ? store[n] : null; },
    setItem: function (n, v) { store[n] = String(v); },
    removeItem: function (n) { delete store[n]; }}};
  var DRAFT_KEY = "pyide-live-abc", L = c.L;
  %s
  out[k] = {start: start, base: store[DRAFT_KEY + "-base"] || null,
            files: store[DRAFT_KEY + "-files"] || null};
});
console.log(JSON.stringify(out));
""" % (json.dumps({
        "homework_since": {"L": {"draftVersion": 9, "starter": "last night"},
                           "store": {"pyide-live-abc": "yesterday",
                                     "pyide-live-abc-files": "{}",
                                     "pyide-live-abc-base": "4"}},
        "nothing_since": {"L": {"draftVersion": 4, "starter": "server"},
                          "store": {"pyide-live-abc": "typed here",
                                    "pyide-live-abc-base": "4"}},
        "kept_before_this": {"L": {"draftVersion": 9, "starter": "server"},
                             "store": {"pyide-live-abc": "typed here"}},
        "signed_out": {"L": {"draftVersion": None, "starter": ""},
                       "store": {"pyide-live-abc": "typed here",
                                 "pyide-live-abc-base": "4"}},
    }), _m.group(1))
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    got = json.loads(res.stdout or "{}") if res.returncode == 0 else {}
    h = got.get("homework_since", {})
    check("their draft saved elsewhere since: the draft wins, not this browser",
          h.get("start") == "last night", h or res.stderr[-300:])
    check("  and the old copy is let go, so a reload does not bring it back",
          h.get("base") == "9" and h.get("files") is None, h)
    n = got.get("nothing_since", {})
    check("nothing saved since: this browser's typing wins, as always",
          n.get("start") == "typed here", n)
    k = got.get("kept_before_this", {})
    check("a copy kept before this existed still wins",
          k.get("start") == "typed here", k)
    check("  and is stamped, so tomorrow it can be told apart",
          k.get("base") == "9", k)
    o = got.get("signed_out", {})
    check("signed out, with no draft: this browser's typing wins",
          o.get("start") == "typed here", o)
else:
    check("node is available to run the live page's start-up", bool(_m),
          "brew install node" if _m else "the block in live.js moved")

# ------------------------------------------------ the slide viewer, run
# notes.js's slideView, in node, with just enough of a DOM to hold it. It is
# what the editor, a shared link and the class's live page all show notes
# through, so how it cuts, numbers and moves is checked by running it.
print("\nThe slide viewer, run")
_notes_src = open(os.path.join(HERE, "..", "static", "notes.js")).read()
if shutil.which("node"):
    harness = r"""
function El(tag) {
  this.tag = tag; this.children = []; this.hidden = false; this.disabled = false;
  this.textContent = ""; this.className = ""; this.handlers = {}; this.scrollTop = 0;
  this._html = ""; this.renders = 0;
}
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.insertBefore = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.setAttribute = function () {};
El.prototype.addEventListener = function (ev, fn) { this.handlers[ev] = fn; };
El.prototype.querySelectorAll = function () { return []; };
Object.defineProperty(El.prototype, "innerHTML", {
  get: function () { return this._html; },
  set: function (v) { this._html = v; this.renders++; } });
var document = { createElement: function (t) { return new El(t); } };
var window = { marked: { parse: function (s) { return s; } },
               DOMPurify: { sanitize: function (s) { return s; } } };
""" + _notes_src + r"""
var N = window.FlaskIDENotes;
var pane = new El("div"), body = pane.appendChild(new El("div"));
var v = N.slideView(body), bar = v.bar;
var prev = bar.children[0], pos = bar.children[1], next = bar.children[2];
var moves = [];
v.onMove(function (i) { moves.push(i); });
var deck = "# One\n\n---\n\n## Two\n\n---\n\n## Three";
var out = {};
(async function () {
  await v.show(deck);
  out.first = [body.innerHTML, pos.textContent, bar.hidden, prev.disabled];
  next.handlers.click(); await null; await null;
  out.next = [body.innerHTML, pos.textContent, moves.slice()];
  await v.show(deck, 2);
  out.snap = [body.innerHTML, moves.slice()];
  var before = body.renders;
  await v.show(deck);
  out.sameAgain = body.renders - before;
  await v.show(deck.replace("## Three", "## Three, edited"));
  out.edited = [body.innerHTML, v.at()];
  await v.show("# Just one page\n\nNo dividers.");
  out.whole = [body.innerHTML, bar.hidden];
  console.log(JSON.stringify(out));
})();
"""
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    try:
        got = json.loads(res.stdout)
    except ValueError:
        got = {}
    check("notes with --- open on the first slide, with arrows under them",
          got.get("first") == ["# One", "1 / 3", False, True],
          repr(got.get("first") or res.stderr[-300:]))
    check("  ▶ moves on, and says so to whoever is listening",
          got.get("next") == ["## Two", "2 / 3", [1]], repr(got.get("next")))
    check("  being sent to a slide is not reported as the reader moving",
          got.get("snap") == ["## Three", [1]],
          "the live page would take its own snapping for a student wandering off")
    check("  the same notes again do not re-render",
          got.get("sameAgain") == 0,
          "every poll would replace the slide under the student's hand")
    check("  editing a slide keeps the reader on it",
          got.get("edited") == ["## Three, edited", 2], repr(got.get("edited")))
    check("  notes with no --- are shown whole, with no arrows",
          got.get("whole") == ["# Just one page\n\nNo dividers.", True],
          repr(got.get("whole")))
else:
    check("node is available to run the slide viewer", False, "brew install node")

# ---------------------------------------- a lesson's link, made ahead
print("\nA lesson's link, made ahead from the assignment page")
ahead = teacher.post("/api/assignment", json={
    "title": "Tomorrow",
    "files": {'app.py': 'from flask import Flask\n', "notes.md": "# Tomorrow\n"}}).get_json()["slug"]
page = teacher.get("/teacher/" + ahead).get_data(as_text=True)
_ahead = re.search(r'id="live-url" type="text" readonly value="[^"]*/live/([a-z0-9]+)"', page)
check("the assignment page shows a live lesson link under the handout link",
      _ahead is not None
      and page.index("The link to hand out") < page.index("The live lesson link"))
AHEAD = _ahead.group(1) if _ahead else ""
again = re.search(r'/live/([a-z0-9]+)"', teacher.get("/teacher/" + ahead).get_data(as_text=True))
check("  the same link every time the page is opened",
      again is not None and again.group(1) == AHEAD,
      "the link posted in Classroom yesterday would no longer be the lesson")
_r = lesson_row(AHEAD)
check("  made ended and never pushed: not on anyone's screen yet",
      _r is not None and _r.ended == 1 and _r.version == 0
      and _r.assignment_id is not None)
check("  and not the teacher's open lesson, so Go live elsewhere is untouched",
      teacher.post("/api/live/start", json={"resume": AHEAD}).get_json().get("resumed") is False)
poll = stranger.get("/api/live/" + AHEAD).get_json()
check("a student opening it early is told it has not started",
      poll.get("ended") is True and poll.get("waiting") is True, repr(poll)[:120])
# (and that their page keeps checking, slowly: the poll, run for real, below)
host = teacher.get("/live/" + AHEAD).get_data(as_text=True)
check("its teacher, opening it, is offered Start this lesson",
      "Start this lesson" in host and "Ready when you are" in host)
r = teacher.get("/teacher/%s/live" % ahead)
check("Go live on the dashboard opens the editor on that lesson",
      r.status_code == 302 and ("teach=" + AHEAD) in r.headers.get("Location", "")
      and ("a=" + ahead) in r.headers.get("Location", ""),
      r.headers.get("Location", r.status_code))
check("  and the assignments list has a Go live for each assignment",
      ('/teacher/%s/live' % ahead) in teacher.get("/teacher").get_data(as_text=True))
check("  which nobody else can use",
      student.get("/teacher/%s/live" % ahead).status_code == 404
      and other.get("/teacher/%s/live" % ahead).status_code == 404)
r = teacher.post("/api/live/start", json={"reopen": AHEAD, "body": "print(1)",
                                          "filename": "main.py"})
teacher.post("/api/live/%s/push" % AHEAD, json={"body": "print(1)", "seq": 50})
poll = stranger.get("/api/live/" + AHEAD).get_json()
check("starting it puts the same code on the air",
      r.get_json().get("code") == AHEAD and poll.get("ended") is False
      and poll.get("waiting") is False, repr(poll)[:120])
teacher.post("/api/live/%s/stop" % AHEAD)
check("  and once taught, it is not 'not started' any more",
      stranger.get("/api/live/" + AHEAD).get_json().get("waiting") is False)
fresh = teacher.post("/api/live/start", json={"body": "x"}).get_json()["code"]
teacher.post("/api/live/%s/stop" % fresh)
check("a lesson ended before its first push is not 'not started' either",
      stranger.get("/api/live/" + fresh).get_json().get("waiting") is False,
      "its link would say Ready when you are, not Teach this lesson again")

# Posted ahead, then started from the editor's own Go live, not the dashboard.
ahead2 = teacher.post("/api/assignment", json={
    "title": "Thursday", "files": {'app.py': 'from flask import Flask\n'}}).get_json()["slug"]
posted = re.search(r'/live/([a-z0-9]+)"',
                   teacher.get("/teacher/" + ahead2).get_data(as_text=True)).group(1)
got = teacher.post("/api/live/start", json={"body": "print('t')",
                                            "assignment": ahead2}).get_json()
check("Go live in the editor on an assignment uses the link posted ahead",
      got.get("code") == posted,
      "the class would be live under a new code while the posted link said "
      "'not started' all period")
check("  and it is on the air", stranger.get("/api/live/" + posted).get_json().get("ended") is False)
teacher.post("/api/live/%s/stop" % posted)
again = teacher.post("/api/live/start", json={"body": "print('t')",
                                              "assignment": ahead2}).get_json()
# The link is posted once — Classroom, the class page — and must last the
# unit. Going live from the editor a second time used to make a new code, and
# the class sat on the posted link reading "this lesson has ended".
check("  and a link already taught is picked up again too, not replaced",
      again.get("code") == posted, repr(again.get("code")))
check("    back on the air, under the link the class has",
      stranger.get("/api/live/" + posted).get_json().get("ended") is False)
check("    with what the editor has now, not last time's file",
      stranger.get("/api/live/" + posted).get_json().get("body") == "print('t')")
check("    and the assignment page still shows that same link",
      "/live/%s\"" % posted in teacher.get("/teacher/" + ahead2).get_data(as_text=True))
teacher.post("/api/live/%s/stop" % posted)
nothing = teacher.post("/api/live/start", json={"body": "x"}).get_json()
check("  Go live with no assignment still starts fresh",
      nothing.get("code") not in ("", None, posted), repr(nothing.get("code")))
teacher.post("/api/live/%s/stop" % nothing.get("code"))

# ------------------------------- a lesson never changes its assignment
print("\nA lesson's code always belongs to its assignment")
# The bug: Go live on assignment B while A's lesson was still open carried
# on in A's lesson, relabelled B. B's live link then said "taught" and its
# Teach again loaded B's notes with A's code.
asg_a = teacher.post("/api/assignment", json={"title": "A", "files": {"app.py": "x = 1"}}).get_json()["slug"]
asg_b = teacher.post("/api/assignment", json={"title": "B", "files": {"app.py": "x = 1"}}).get_json()["slug"]
la = teacher.post("/api/live/start", json={"body": "print('A')", "assignment": asg_a}).get_json()["code"]
teacher.post("/api/live/%s/push" % la, json={"body": "print('A taught')", "seq": 99})
lb = teacher.post("/api/live/start", json={"body": "print('B')", "assignment": asg_b}).get_json()["code"]
check("Go live on another assignment, with one still open, is a new lesson",
      lb != la, "it carried on in A's lesson and relabelled it B")
row_a = lesson_row(la)
check("  the old one ends, still A's, with A's code",
      row_a.ended == 1 and row_a.body == "print('A taught')"
      and row_a.assignment_id == item_id(asg_a))
check("  and B's live link is B's lesson, not A's",
      re.search(r'/live/([a-z0-9]+)"', teacher.get("/teacher/" + asg_b).get_data(as_text=True)).group(1) == lb)
same = teacher.post("/api/live/start", json={"body": "x", "assignment": asg_b}).get_json()["code"]
check("Go live again on the same assignment still carries on in its lesson", same == lb)
resumed = teacher.post("/api/live/start", json={"resume": lb}).get_json()
check("  and a reload's resume does too", resumed.get("code") == lb)
teacher.post("/api/live/%s/stop" % lb)

# The repair: forget what the lesson last had on screen, keep the link.
RESET = "/api/assignment/%s/live/reset" % asg_a
page = teacher.get("/teacher/" + asg_a).get_data(as_text=True)
check("a taught lesson's page offers Start from the starter next time", 'id="live-reset"' in page)
check("  only its teacher can", student.post(RESET).status_code == 403
      and other.post(RESET).status_code in (403, 404))
r = teacher.post(RESET)
row_a = lesson_row(la)
check("  it forgets the code, and keeps the link",
      r.status_code == 200 and row_a.body == "" and row_a.code == la
      and re.search(r'/live/([a-z0-9]+)"', teacher.get("/teacher/" + asg_a).get_data(as_text=True)).group(1) == la)
check("  so Teach again loads only the starter (nothing to lay over it)",
      stranger.get("/api/live/%s?v=-1" % la).get_json().get("body") == "")
teacher.post("/api/live/start", json={"reopen": la, "body": "x"})
check("  and is refused while the lesson is live", teacher.post(RESET).status_code == 409)
teacher.post("/api/live/%s/stop" % la)
check("a lesson made ahead and never taught does not offer it",
      'id="live-reset"' not in teacher.get("/teacher/" + teacher.post(
          "/api/assignment", json={"title": "C", "files": {"app.py": "x = 1"}}).get_json()["slug"]).get_data(as_text=True))

# ------------------------------------------ whose typing a browser keeps
# One Chrome profile shared by two students in a lab: the second used to
# open the lesson to the first one's typing, and a Save made it theirs.
# live.js's choice of key, lifted and run against a stand-in localStorage.
_km = re.search(r'(  var ANON_KEY = .*?\n  \}\n)', _live_now_js, re.S)
if shutil.which("node") and _km:
    harness = """
var cases = %s, out = {};
Object.keys(cases).forEach(function (k) {
  var c = cases[k], store = Object.assign({}, c.store);
  var window = {localStorage: {
    getItem: function (n) { return n in store ? store[n] : null; },
    setItem: function (n, v) { store[n] = String(v); },
    removeItem: function (n) { delete store[n]; }}};
  var L = c.L;
  %s
  out[k] = {key: DRAFT_KEY, store: store};
});
console.log(JSON.stringify(out));
""" % (json.dumps({
        "signed_out": {"L": {"code": "abc", "me": None},
                       "store": {"flaskide-live-abc": "typed signed out"}},
        "signs_in": {"L": {"code": "abc", "me": 7},
                     "store": {"flaskide-live-abc": "typed signed out",
                               "flaskide-live-abc-files": "{}", "flaskide-live-abc-base": "3",
                               "flaskide-live-abc-slug": "someones"}},
        "next_student": {"L": {"code": "abc", "me": 8},
                         "store": {"flaskide-live-abc-u7": "student 7's work",
                                   "flaskide-live-abc-u7-slug": "d7"}},
        "has_own": {"L": {"code": "abc", "me": 7},
                    "store": {"flaskide-live-abc-u7": "mine", "flaskide-live-abc": "a stranger's"}},
    }), _km.group(1))
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    got = json.loads(res.stdout or "{}") if res.returncode == 0 else {}
    o = got.get("signed_out", {})
    check("signed out: typing kept under the lesson's code, as before",
          o.get("key") == "flaskide-live-abc"
          and o.get("store") == {"flaskide-live-abc": "typed signed out"}, o or res.stderr[-300:])
    i = got.get("signs_in", {})
    check("signed in: under their own account",
          i.get("key") == "flaskide-live-abc-u7", i)
    check("  taking over what was typed before signing in",
          (i.get("store") or {}).get("flaskide-live-abc-u7") == "typed signed out"
          and (i.get("store") or {}).get("flaskide-live-abc-u7-base") == "3"
          and "flaskide-live-abc" not in (i.get("store") or {}), i)
    check("  but never a draft somebody else saved",
          "flaskide-live-abc-u7-slug" not in (i.get("store") or {}), i)
    n = got.get("next_student", {})
    check("the next student in the same browser starts clean",
          n.get("key") == "flaskide-live-abc-u8"
          and "flaskide-live-abc-u8" not in (n.get("store") or {})
          and (n.get("store") or {}).get("flaskide-live-abc-u7") == "student 7's work", n)
    h = got.get("has_own", {})
    check("their own kept typing wins over anything signed out",
          (h.get("store") or {}).get("flaskide-live-abc-u7") == "mine", h)
else:
    check("node is available to run the live page's storage key", bool(_km),
          "brew install node" if _km else "the block in live.js moved")
_lv = F.app.test_client()
with _lv.session_transaction() as _s:
    _s["uid"] = STUDENT
_html = _lv.get("/live/" + LESSON).get_data(as_text=True)
check("the page tells live.js who is signed in, by id",
      ("me: %d," % STUDENT) in _html
      and "me: null," in stranger.get("/live/" + LESSON).get_data(as_text=True))

# ------------------------------------------ an ended lesson keeps checking
# live.js's start-up mirror and its poll, lifted and run in node against
# scripted answers. What the class sees, what the chip says, and how soon it
# asks again — the three things that left a class on yesterday's code.
_pm = re.search(r'(  var everLive = !L\.ended;.*?\n  poll\(\);\n)', _live_now_js, re.S)
if shutil.which("node") and _pm:
    harness = """
var scripts = %s, out = {};
function settle() { return new Promise(function (r) { setImmediate(r); }); }
async function run(name) {
  var c = scripts[name], answers = c.answers.slice(), log = [];
  var shownPageId = "";
  var L = c.L, seen = -1, shown = [], state = "", next = null, moved = null;
  var stateChip = {get textContent() { return state; }};
  function setState(t) { state = t; }
  function showMirror(d) { shown.push(d.body); seen = d.version; }
  var location = {replace: function (u) { moved = u; }};
  function setTimeout(fn, ms) { next = {fn: fn, ms: ms}; }
  function fetch() {
    var a = answers.shift();
    if (a === 304) return Promise.resolve({status: 304, ok: false});
    return Promise.resolve({status: 200, ok: true,
                            json: function () { return Promise.resolve(a); }});
  }
  %s
  for (;;) {
    for (var i = 0; i < 6; i++) await settle();
    log.push({shown: shown.slice(), state: state, next: next ? next.ms : null,
              moved: moved});
    if (!next || !answers.length) break;
    var n = next; next = null; n.fn();
  }
  out[name] = log;
}
(async function () {
  for (var k of Object.keys(scripts)) await run(k);
  console.log(JSON.stringify(out));
})();
""" % (json.dumps({
        # Opened before the teacher went live: yesterday's row, ended.
        "early": {"L": {"ended": True, "body": "yesterday", "version": 5},
                  "answers": [{"ended": True, "waiting": False, "body": "yesterday", "version": 5},
                              {"ended": False, "body": "today", "version": 9}]},
        # Watched it live, then the teacher ended it, then taught it again.
        "watched": {"L": {"ended": False, "body": "live", "version": 5},
                    "answers": [{"ended": True, "body": "final", "version": 6},
                                {"ended": False, "body": "again", "version": 7}]},
        "made_ahead": {"L": {"ended": True, "waiting": True, "body": "", "version": 0},
                       "answers": [{"ended": True, "waiting": True, "body": "", "version": 0}]},
        "older_link": {"L": {"ended": True, "body": "old", "version": 5},
                       "answers": [{"moved": "NEW1", "ended": True}]},
    }), _pm.group(1))
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    got = json.loads(res.stdout or "{}") if res.returncode == 0 else {}
    e = got.get("early", [{}, {}])
    check("opened before the teacher goes live: no leftover code on screen",
          e[0].get("shown") == [] and e[0].get("state") == "Not started yet",
          e or res.stderr[-300:])
    check("  and it keeps checking every few seconds",
          e[0].get("next") == 5000, e)
    check("  so the class gets today's code when the teacher goes live",
          len(e) > 1 and e[1].get("shown") == ["today"] and e[1].get("state") == "Live"
          and e[1].get("next") == 1000, e)
    w = got.get("watched", [{}, {}])
    check("watched it end: the last code stays on screen",
          w[0].get("shown") == ["live", "final"] and w[0].get("state") == "Lesson ended", w)
    check("  and it keeps checking, so teaching it again brings the class along",
          w[0].get("next") == 5000 and len(w) > 1
          and w[1].get("shown")[-1:] == ["again"] and w[1].get("state") == "Live", w)
    m = got.get("made_ahead", [{}])
    check("made ahead and never taught: told it has not started, checked slowly",
          m[0].get("state") == "Not started yet" and m[0].get("next") == 15000, m)
    o = got.get("older_link", [{}])
    check("an older link for the assignment goes on to its lesson, and stops asking",
          o[0].get("moved") == "/live/NEW1" and o[0].get("next") is None, o)
    # The slides page (lesson.js) polls the same way. Its poll drives the
    # slide viewer, so it is read rather than run: it must follow a moved
    # link, and keep asking after an ended lesson.
    _lj = open(os.path.join(FLASKIDE, "static", "lesson.js")).read()
    check("the slides page follows an older link on, too",
          re.search(r'if \(data\.moved\) \{\s*moving = true;\s*location\.replace\("/live/"',
                    _lj) is not None)
    check("  and keeps checking after the lesson ends",
          re.search(r'if \(data\.ended\) \{[^}]*pace = ENDED_MS;[^}]*return;', _lj) is not None
          and 'throw new Error("ended")' not in _lj
          and "setTimeout(poll, pace);" in _lj)
else:
    check("node is available to run the live page's poll", bool(_pm),
          "brew install node" if _pm else "the block in live.js moved")


# ------------------------------------- one assignment, one lesson, every link
# Before Go live reused a taught lesson, teaching one again made a new code,
# so an assignment can have older lesson rows whose links are still out —
# posted in Classroom for one section. A class on one of those sat looking
# at another section's code from yesterday while the teacher taught in the
# new one. Every link for the assignment now leads to its newest lesson.
print("\nOlder links for an assignment lead to its lesson")
from urllib.parse import parse_qs, urlparse                   # noqa: E402
db = F.SessionLocal()
try:
    db.query(accounts.LiveSession).filter_by(host_id=TEACHER).update({"ended": 1})
    db.commit()
finally:
    db.close()
asg_old = teacher.post("/api/assignment", json={"title": "Lists", "files": {"app.py": "starter\n"}}).get_json()["slug"]
_go = teacher.get("/teacher/%s/live" % asg_old).headers.get("Location", "")
OLD = parse_qs(urlparse(_go).query).get("teach", [""])[0]
teacher.post("/api/live/start", json={"reopen": OLD, "body": "yesterday's code"})
teacher.post("/api/live/%s/stop" % OLD)
db = F.SessionLocal()
try:
    _o = db.query(accounts.LiveSession).filter_by(code=OLD).first()
    _new = accounts.LiveSession(
        code="newer1", app=F.APP_NAME, host_id=TEACHER, host_name="T", title="Lists",
        body="the other section's code", filename="main.py", version=50, ended=1,
        assignment_id=_o.assignment_id,
        started_at=_o.started_at + F.timedelta(hours=1))
    db.add(_new)
    db.commit()
finally:
    db.close()
r = stranger.get("/live/" + OLD)
check("an older link for the assignment opens its newest lesson",
      r.status_code == 302 and r.headers.get("Location", "").endswith("/live/newer1"),
      (r.status_code, r.headers.get("Location")))
check("  for its teacher too, so Teach again teaches where the class is",
      teacher.get("/live/" + OLD).headers.get("Location", "").endswith("/live/newer1"))
check("  the newest one opens as itself",
      stranger.get("/live/newer1").status_code == 200)
d = stranger.get("/api/live/%s?v=-1" % OLD).get_json()
check("a page already open on the older link is told where it moved",
      d.get("moved") == "newer1" and "body" not in d, d)
check("  and the newest is told nothing of the kind",
      "moved" not in stranger.get("/api/live/newer1?v=-1").get_json())
check("the assignment page's own link is the newest",
      "/live/newer1" in teacher.get("/teacher/" + asg_old).get_data(as_text=True))

# Teach again from the older link, as an old bookmark would.
r = teacher.post("/api/live/start", json={"reopen": OLD, "body": "today's code"}).get_json()
check("reopening the older one goes live in the newest instead",
      r.get("code") == "newer1" and lesson_row("newer1").ended == 0
      and lesson_row("newer1").body == "today's code" and lesson_row(OLD).ended == 1, r)
teacher.post("/api/live/newer1/stop")

# An older row left open (yesterday, never ended), then Go live on the
# assignment: the class is on the newest, so that is where it goes.
set_row(OLD, ended=0)
r = teacher.post("/api/live/start", json={"assignment": asg_old, "body": "starter\n"}).get_json()
check("Go live with an older lesson still open moves to the newest",
      r.get("code") == "newer1" and lesson_row(OLD).ended == 1
      and lesson_row("newer1").ended == 0 and lesson_row("newer1").body == "starter\n", r)
check("  leaving one open lesson, not two", open_lessons(TEACHER) == 1)
check("a resume of an ended lesson still gets nothing",
      teacher.post("/api/live/start", json={"resume": OLD}).get_json().get("resumed") is False)
teacher.post("/api/live/newer1/stop")
# The editor reloaded while an older row was the one open: carrying on there
# would be teaching where every link sends the class away from.
set_row(OLD, ended=0)
r = teacher.post("/api/live/start", json={"resume": OLD, "body": "mid-lesson"}).get_json()
check("a resume of an older open lesson carries on in the newest",
      r.get("code") == "newer1" and lesson_row(OLD).ended == 1
      and lesson_row("newer1").body == "mid-lesson", r)
teacher.post("/api/live/newer1/stop")

_plain = teacher.post("/api/live/start", json={"assignment": "", "body": "x"}).get_json()["code"]
teacher.post("/api/live/%s/stop" % _plain)
check("a lesson with no assignment opens as itself",
      stranger.get("/live/" + _plain).status_code == 200
      and "moved" not in stranger.get("/api/live/%s?v=-1" % _plain).get_json())

bad = results.count(False)
print("\n%s (%d checks, %d failed)"
      % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
sys.exit(1 if bad else 0)
