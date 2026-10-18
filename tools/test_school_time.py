#!/usr/bin/env python3
"""Every time the server writes out is on the school's clock, not UTC.

    python3 tools/test_school_time.py

WHY THIS FILE EXISTS

Times are stored in UTC, and for a long while they were also shown in UTC:
a student in Pennsylvania who saved at 2:15 PM read "Saved 06:15 PM", and
"turned in" and "feedback" times on every page were four or five hours
ahead. Nothing failed — every one was a valid time, just the wrong one —
so it went unnoticed until a teacher looked at a clock.

So this pins:

  * `_local` turns a stored UTC time into New York time by default, summer
    (EDT) and winter (EST) both, and reads a naive time as UTC, which is
    what SQLite hands back;
  * SCHOOL_TIMEZONE moves it, for a school somewhere else;
  * a student's Save answers with the school's time;
  * no time is written out any other way — a new `.strftime` with a clock
    in it, in app.py or a template, would be UTC again, silently.
"""
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "time.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@example.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
os.environ.pop("SCHOOL_TIMEZONE", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


summer = datetime(2026, 7, 14, 18, 15, tzinfo=timezone.utc)
winter = datetime(2026, 1, 14, 18, 15, tzinfo=timezone.utc)
late = datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc)
check("summer: 18:15 UTC is 02:15 PM in New York (EDT)",
      P._local(summer, "%I:%M %p") == "02:15 PM", P._local(summer, "%I:%M %p"))
check("winter: 18:15 UTC is 01:15 PM in New York (EST)",
      P._local(winter, "%I:%M %p") == "01:15 PM", P._local(winter, "%I:%M %p"))
check("an evening save is on the evening's day, not tomorrow's",
      P._local(late, "%b %d at %I:%M %p") == "Oct 20 at 10:30 PM",
      P._local(late, "%b %d at %I:%M %p"))
check("a naive time, as SQLite returns it, is read as UTC",
      P._local(summer.replace(tzinfo=None), "%I:%M %p") == "02:15 PM")
check("templates have it as the `local` filter",
      P.app.jinja_env.filters.get("local") is P._local)

# Another school's zone, in a fresh process, since SCHOOL_TZ is read once.
out = subprocess.run(
    [sys.executable, "-c", "import app, datetime as d; print(app._local("
     "d.datetime(2026, 7, 14, 18, 15, tzinfo=d.timezone.utc), '%I:%M %p'))"],
    cwd=PYIDE, capture_output=True, text=True,
    env=dict(os.environ, SCHOOL_TIMEZONE="America/Los_Angeles"))
check("SCHOOL_TIMEZONE moves it (Los Angeles: 11:15 AM)",
      out.stdout.strip().splitlines()[-1:] == ["11:15 AM"], (out.stdout + out.stderr).strip()[-120:])

# A student's Save, through the real route.
db = P.SessionLocal()
try:
    user = accounts.User(google_sub="s1", email="kid@example.org", name="Kid")
    db.add(user)
    db.commit()
    uid = user.id
finally:
    db.close()
student = P.app.test_client()
with student.session_transaction() as s:
    s["uid"] = uid
slug = student.post("/api/draft", json={"files": {"app.py": "print(1)\n"},
                                        "title": "Mine"}).get_json()["slug"]
before = datetime.now(ZoneInfo("America/New_York"))
r = student.post("/api/draft/" + slug, json={"files": {"app.py": "print(2)\n"}})
after = datetime.now(ZoneInfo("America/New_York"))
said = (r.get_json() or {}).get("saved_at")
check("a student's Save says the time on the school's clock",
      said in (before.strftime("%I:%M %p"), after.strftime("%I:%M %p")),
      (said, before.strftime("%I:%M %p")))

# Every clock written out goes through _local. Dates alone are allowed
# (Skyward's due date is one the teacher typed, already local).
loose = []
for name in ["app.py"] + ["templates/" + f for f in
                          os.listdir(os.path.join(PYIDE, "templates"))]:
    with open(os.path.join(PYIDE, name), encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if "strftime(" in line and "%I" in line and "def _local" not in line:
                loose.append("%s:%d" % (name, n))
check("no time is written out except through _local", not loose, loose)

failed = results.count(False)
print("%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                     len(results), failed))
sys.exit(1 if failed else 0)
