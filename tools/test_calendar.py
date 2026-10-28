#!/usr/bin/env python3
"""The week's calendar at the top of a class's page.

    python3 tools/test_calendar.py

THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE, as calendar.js is.

WHAT IS BEING GUARDED

  The teacher pastes one block of text — "Monday:", its to-do, "Tuesday:",
      its to-do — and calendar.js makes it a row of day cards. node runs the
      real calendar.js here: which lines start a day, which belong to one,
      the title above the first day, dates, and which card is today.

  A line that merely starts with a day's name ("Friday quiz", "Monday's
      homework") is a to-do, not a new day. Reading it as a day would split
      a day in two with no sign anything went wrong.

  A dated day is today only on its date, so last week's calendar left up
      points at nothing rather than the wrong Wednesday.

  Only the class's teacher can set it, and "Also post to" reaches only
      their own classes — one that isn't theirs refuses the whole save, so
      nothing is posted to half the list.

  Students see it at the top of the class's page, under the banner, and
      not at all when there is none. The teacher's page has the button.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "calendar.db")
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


print("reading the text (node, the real calendar.js)")
if not shutil.which("node"):
    print("  FAIL node is needed: brew install node")
    sys.exit(1)

WEEK = """Week of Oct 27
Bring your laptop charged

**Monday:**
Loops worksheet
Friday quiz on loops
Monday's homework is page 4
Tuesday: Lab day
- finish the guessing game
  - stretch: keep score
Wed 10/29:
1. Read [chapter 4](https://example.com)
## Thursday
thurs - no school
Fri (Oct 31) — Quiz
Saturday
"""

harness = r"""
const C = require(%s);
const out = {};
const w = C.parse(%s);
out.title = w.title;
out.days = w.days.map(d => ({ name: d.name, date: d.date, when: d.when, lines: d.lines }));
out.items = w.days[1].lines.map(C.asItem);
out.numbered = C.asItem("1. Read it");
// Today: an undated week by weekday; a dated one only on its date.
const undated = C.parse("Monday:\nx\nWednesday:\ny\n").days;
out.wedUndated = C.todayIn(undated, new Date(2026, 9, 28));   // a Wednesday
out.thuUndated = C.todayIn(undated, new Date(2026, 9, 29));
const dated = C.parse("Mon 10/27:\nx\nWed 10/29:\ny\n").days;
out.onDate = C.todayIn(dated, new Date(2026, 9, 29));
out.wrongWeek = C.todayIn(dated, new Date(2026, 10, 5));      // the next Wednesday
out.none = C.parse("just some words\nand more").days.length;
out.empty = C.parse("").days.length;
out.crlf = C.parse("Monday:\r\nA\r\nTuesday:\r\nB").days.map(d => d.lines.join("|"));
console.log(JSON.stringify(out));
""" % (json.dumps(os.path.join(ROOT, "static", "calendar.js")), json.dumps(WEEK))
res = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=60)
try:
    got = json.loads(res.stdout)
except ValueError:
    got = {}
check("node ran calendar.js", got, res.stderr[-300:])
days = got.get("days", [])
check("each day is a card, in the order written",
      [d["name"] for d in days] == ["Monday", "Tuesday", "Wednesday", "Thursday",
                                    "Thursday", "Friday", "Saturday"],
      [d["name"] for d in days])
check("anything above the first day is the title",
      got.get("title") == "Week of Oct 27\nBring your laptop charged", got.get("title"))
check("**Monday:** with markdown around it is a day", days and days[0]["name"] == "Monday")
check("a line starting with a day's name is that day's to-do, not a new day",
      days and days[0]["lines"] == ["Loops worksheet", "Friday quiz on loops",
                                    "Monday's homework is page 4"], days and days[0]["lines"])
check("text after the colon is the day's first line",
      len(days) > 1 and days[1]["lines"][0] == "Lab day")
check("  and a bullet the teacher typed keeps its indent",
      got.get("items") == ["- Lab day", "- finish the guessing game", "  - stretch: keep score"],
      got.get("items"))
check("a numbered line becomes an item", got.get("numbered") == "- Read it")
check("a date after the day is kept, and read",
      len(days) > 2 and days[2]["date"] == "10/29" and days[2]["when"] == {"month": 9, "day": 29},
      len(days) > 2 and days[2])
check("  in brackets, by the month's name, with a dash after it",
      len(days) > 5 and days[5]["date"] == "Oct 31" and days[5]["when"] == {"month": 9, "day": 31}
      and days[5]["lines"] == ["Quiz"], len(days) > 5 and days[5])
check("## Thursday and 'thurs - …' are both days", len(days) > 4
      and days[3]["lines"] == [] and days[4]["lines"] == ["no school"])
check("a day on its own line with nothing under it is still a day",
      len(days) > 6 and days[6]["lines"] == [])
check("undated: today is the day with today's name",
      got.get("wedUndated") == 1 and got.get("thuUndated") == -1,
      (got.get("wedUndated"), got.get("thuUndated")))
check("dated: today only on its date, never on the same weekday a week on",
      got.get("onDate") == 1 and got.get("wrongWeek") == -1,
      (got.get("onDate"), got.get("wrongWeek")))
check("text with no day in it has no days (the preview says so)",
      got.get("none") == 0 and got.get("empty") == 0)
check("Windows line endings read the same", got.get("crlf") == ["A", "B"], got.get("crlf"))


print("saving it")


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


def calendar_of(cid):
    db = P.SessionLocal()
    try:
        return db.get(accounts.Course, cid).calendar
    finally:
        db.close()


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy Lee"))
P4 = add(accounts.Course(app=P.APP_NAME, teacher_id=TEACHER, name="P4 Intro"))
P7 = add(accounts.Course(app=P.APP_NAME, teacher_id=TEACHER, name="P7 Intro"))
THEIRS = add(accounts.Course(app=P.APP_NAME, teacher_id=OTHER, name="Their class"))
ELSEWHERE = add(accounts.Course(app="otheride", teacher_id=TEACHER, name="Another editor's"))
add(accounts.Enrollment(class_id=P4, email="amy@school.org", name="Amy Lee"))
teacher, other, amy = client(TEACHER), client(OTHER), client(AMY)

check("a class starts with no calendar", calendar_of(P4) == "")
html = amy.get("/class/%d" % P4).get_data(as_text=True)
check("  and the student's page shows none", 'class="class-calendar"' not in html)
html = teacher.get("/teacher/class/%d" % P4).get_data(as_text=True)
check("the teacher's class page has Add a calendar", ">Add a calendar<" in html
      and 'id="calendar"' in html and "calendar.js" in html)
check("  offering the teacher's other classes, and only theirs",
      'value="%d"' % P7 in html and 'value="%d"' % THEIRS not in html
      and 'value="%d"' % ELSEWHERE not in html)

r = teacher.post("/api/class/%d/calendar" % P4, json={"calendar": "\n" + WEEK + "\n\n"})
check("the teacher saves the week", r.status_code == 200, r.get_data(as_text=True)[:80])
check("  stored as typed, ends trimmed", calendar_of(P4) == WEEK.strip())
check("  on that class only", calendar_of(P7) == "")
html = amy.get("/class/%d" % P4).get_data(as_text=True)
check("the student's page shows it under the banner, above the assignments",
      'class="class-calendar"' in html and "calendar.js" in html
      and html.index('class="class-banner"') < html.index('class="class-calendar"'))
check("  with the text, escaped, for calendar.js to draw",
      'data-cal="Week of Oct 27' in html and "[chapter 4](https://example.com)" in html)
html = teacher.get("/teacher/class/%d" % P4).get_data(as_text=True)
check("the teacher's button says Edit calendar now", ">Edit calendar<" in html)

r = teacher.post("/api/class/%d/calendar" % P4, json={"calendar": "Monday:\nA", "also": [P7]})
check("Also post to puts the same week on the other period",
      r.status_code == 200 and calendar_of(P4) == "Monday:\nA" and calendar_of(P7) == "Monday:\nA"
      and r.get_json().get("posted") == 2, r.get_json())
r = teacher.post("/api/class/%d/calendar" % P4, json={"calendar": "Monday:\nB", "also": [P7, THEIRS]})
check("another teacher's class in the list refuses the whole save",
      r.status_code == 404 and calendar_of(P4) == "Monday:\nA" and calendar_of(P7) == "Monday:\nA"
      and calendar_of(THEIRS) == "")
r = teacher.post("/api/class/%d/calendar" % P4, json={"calendar": "Monday:\nB", "also": [ELSEWHERE]})
check("  so does their own class in another editor",
      r.status_code == 404 and calendar_of(ELSEWHERE) == "")
check("also that isn't a list of classes is refused",
      teacher.post("/api/class/%d/calendar" % P4,
                   json={"calendar": "x", "also": "%d" % P7}).status_code == 400)
check("another teacher can't set it",
      other.post("/api/class/%d/calendar" % P4, json={"calendar": "x"}).status_code == 404
      and calendar_of(P4) == "Monday:\nA")
check("a student can't",
      amy.post("/api/class/%d/calendar" % P4, json={"calendar": "x"}).status_code == 403)
check("something that isn't text is refused",
      teacher.post("/api/class/%d/calendar" % P4, json={"calendar": 5}).status_code == 400)
check("one too long is refused",
      teacher.post("/api/class/%d/calendar" % P4,
                   json={"calendar": "x" * (P.MAX_DESCRIPTION + 1)}).status_code == 413)
r = teacher.post("/api/class/%d/calendar" % P4, json={"calendar": ""})
check("Clear takes it off", r.status_code == 200 and calendar_of(P4) == "")
check("  and off the student's page",
      'class="class-calendar"' not in amy.get("/class/%d" % P4).get_data(as_text=True))

print("an earlier database")
check("the column has its ALTER TABLE, defaulting to no calendar",
      any(t == "classes" and c == "calendar" and "DEFAULT ''" in ddl
          for t, c, ddl in accounts.LATER_COLUMNS))

print("the same in all three")
for name in ("static/calendar.js", "tools/test_calendar.py"):
    mine = open(os.path.join(ROOT, name), "rb").read()
    for repo in ("pyide", "webide", "flaskide"):
        there = os.path.join(os.path.expanduser("~"), repo)
        if os.path.realpath(there) == os.path.realpath(ROOT) or not os.path.isdir(there):
            continue
        path = os.path.join(there, name)
        check("%s is the same in %s" % (name, repo),
              os.path.exists(path) and open(path, "rb").read() == mine)

print()
print("ok" if all(results) else "FAIL", "%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
