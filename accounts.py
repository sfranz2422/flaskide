"""
PyIDE — signing in, saved projects, assignments and turning work in.

Everything here is *additive*. With no Google credentials configured the app
behaves exactly as it always has: anonymous students open a link, write code,
press Run, and share a snapshot. Signing in only ever adds abilities — it is
never required to use the editor, and an anonymous student's experience is
untouched.

Four tables, chosen so they cannot collide with WebIDE, which lives in the
same database and already owns `projects`:

    users          one row per person who has ever signed in
    assignments    a starter project a teacher hands out, with a link
    drafts         a student's living copy — this is what autosaves
    submissions    what a student turned in, and when
    live_sessions  a lesson the class is watching the teacher type
    classroom_links  a teacher's connection to their Google Classroom

`snippets`, the existing share-link table, is not touched at all. Every link
handed out before today keeps working, and turning work in reuses it to take
an immutable snapshot, so what a student submitted cannot change afterwards.
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no look-alike characters
ID_LENGTH = 7


def new_id(db, model, column="slug") -> str:
    """A short random id, retried on the (very unlikely) collision."""
    for _ in range(12):
        candidate = "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if not db.query(model.id).filter(getattr(model, column) == candidate).first():
            return candidate
    raise RuntimeError("could not allocate an id")


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Who
# --------------------------------------------------------------------------

class User(Base):
    """Someone who has signed in with Google.

    `google_sub` rather than the email address is the real identity: Google
    guarantees it never changes and is never reused, whereas a school can
    rename a mailbox. The email is stored to display and to match against the
    teacher list, but it is not what rows hang off.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    google_sub = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(320), index=True, nullable=False)
    name = Column(String(160), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=now)
    last_seen = Column(DateTime, nullable=False, default=now)

    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]


# --------------------------------------------------------------------------
# What was set
# --------------------------------------------------------------------------

class Assignment(Base):
    """A starter project a teacher publishes and hands out as a link.

    The starter code lives here rather than pointing at a draft, so a teacher
    can carry on editing their own copy without quietly changing what the
    class was given.

    `app` exists because WebIDE will want assignments too, and one table
    serving both is better than two that drift apart.
    """
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    slug = Column(String(16), unique=True, index=True, nullable=False)
    app = Column(String(16), nullable=False, default="pyide")
    teacher_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(200), nullable=False, default="Untitled assignment")
    code = Column(Text, nullable=False, default="")
    files = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=now)
    closed = Column(Integer, nullable=False, default=0)
    # Tidied away rather than destroyed. An archived assignment keeps every
    # submission and every student's work; it just stops filling up the
    # dashboard months after the class moved on.
    archived = Column(Integer, nullable=False, default=0)

    def file_map(self) -> dict:
        return _as_map(self.files)


# --------------------------------------------------------------------------
# What a student is working on
# --------------------------------------------------------------------------

class Draft(Base):
    """A student's living project. This is the thing autosave writes to.

    Deliberately not called a snapshot: it changes as they type, and there is
    exactly one per student per assignment, found again by that pair rather
    than by a link the student has to keep hold of. Losing the link was the
    whole problem.
    """
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("owner_id", "assignment_id", name="uq_draft_owner_assignment"),
    )

    id = Column(Integer, primary_key=True)
    slug = Column(String(16), unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    assignment_id = Column(Integer, ForeignKey("assignments.id"),
                           index=True, nullable=True)
    # Which editor this belongs to. PyIDE and WebIDE share this database and
    # one sign-in, but a Python project cannot be opened in the web editor, so
    # each app only ever lists and opens its own.
    app = Column(String(16), nullable=False, default="pyide", index=True)
    title = Column(String(200), nullable=False, default="Untitled")
    code = Column(Text, nullable=False, default="")
    files = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now)

    def file_map(self) -> dict:
        return _as_map(self.files)


# --------------------------------------------------------------------------
# What was handed in
# --------------------------------------------------------------------------

class Submission(Base):
    """A student's work as it stood the moment they pressed Turn in.

    `snippet_slug` points at an ordinary share snapshot, so a submission is
    frozen — a student can carry on editing their draft and what you are
    marking does not move under you. Turning in again replaces this row and
    points it at a fresh snapshot.
    """
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_one_per_student"),
    )

    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"),
                           index=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    snippet_slug = Column(String(16), nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=now)
    times_submitted = Column(Integer, nullable=False, default=1)

    #: The teacher's comment on it, shown on the student's My work page.
    #: On this row rather than the snapshot, so it SURVIVES a re-submit —
    #: turning in again updates this row in place — and the teacher's
    #: dashboard says "turned in again since your feedback" by comparing
    #: submitted_at with feedback_at. NULL feedback_at means none was given.
    feedback = Column(Text, nullable=False, default="")
    feedback_at = Column(DateTime, nullable=True)
    #: Whether the student has seen the current feedback. Writing new
    #: feedback clears it; the student opening My work sets it.
    feedback_seen = Column(Integer, nullable=False, default=0)


# --------------------------------------------------------------------------
# Google Classroom
# --------------------------------------------------------------------------

class ClassroomLink(Base):
    """A teacher's standing permission to post to their Google Classroom.

    Only teachers ever have one. Students sign in with the plain
    openid/email/profile they always have; the Classroom permissions are asked
    for separately, by the teacher, from the dashboard.

    One per teacher PER APP, because the refresh token belongs to the OAuth
    client that obtained it, and the three editors are three Render services
    that may each have their own GOOGLE_CLIENT_ID. A token got by PyIDE is
    refused by Google if WebIDE presents it.

    `refresh_token` is ENCRYPTED, with a key derived from the app's
    SECRET_KEY, which lives in Render's environment and not in this
    database. A copy of the database alone is not a working key to anyone's
    classes. The cost: changing SECRET_KEY makes every stored token
    unreadable, and each teacher has to press Connect again. That is all.
    """
    __tablename__ = "classroom_links"
    __table_args__ = (
        UniqueConstraint("user_id", "app", name="uq_classroom_user_app"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    app = Column(String(16), nullable=False, default="pyide")
    refresh_token = Column(Text, nullable=False)
    #: The Google account that granted it. Usually the teacher's sign-in
    #: address; recorded so the dashboard can say which account is connected.
    google_email = Column(String(320), nullable=False, default="")
    connected_at = Column(DateTime, nullable=False, default=now)


# --------------------------------------------------------------------------
# Teaching live
# --------------------------------------------------------------------------

class LiveSession(Base):
    """A lesson the class is watching: the teacher's editor, mirrored.

    WHY THIS IS A TABLE AND NOT A DICTIONARY IN MEMORY

    Every one of these apps runs `gunicorn --workers 2`: two separate
    processes, each with its own memory, and nothing routes a given person to
    a given one. Kept in a module-level dict, the teacher's keystrokes would
    land in whichever worker served that request and be invisible to half the
    class — and which half would change from poll to poll. It would work
    perfectly on a laptop with one worker and fail in front of thirty people.

    The same argument rules out WebSockets here: a socket lives in one worker,
    so broadcasting across both needs a message broker, which is another
    Render service and another bill. Polling a row costs nothing new.

    ONE ROW PER SESSION, REWRITTEN IN PLACE. No history is kept, because what
    a live mirror is for is what is on the screen now. `version` counts up on
    every push and is what students poll against, so the usual reply is a bare
    304-shaped "nothing new" rather than the whole program.
    """
    __tablename__ = "live_sessions"

    id = Column(Integer, primary_key=True)
    #: What students type in to join. Short and unambiguous, because it gets
    #: read off a projector and typed by someone at the back.
    code = Column(String(16), unique=True, index=True, nullable=False)
    app = Column(String(16), nullable=False, default="pyide", index=True)
    host_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    host_name = Column(String(160), nullable=False, default="")
    title = Column(String(200), nullable=False, default="Live lesson")

    #: The assignment this lesson is for, if the teacher picked one.
    #:
    #: WITHOUT IT THE CLASS CANNOT HAND ANYTHING IN. Turning work in needs a
    #: draft with an assignment on it — see Submission and /api/submit — and
    #: a project saved from the live page had none, so the button could never
    #: appear. Nothing about that was visible: the lesson worked, the saving
    #: worked, and the hand-in was simply impossible.
    #:
    #: With it set, a student's save on the live page creates or finds the
    #: SAME draft row the assignment link would have made, so a student who
    #: also opened /a/<slug> has one copy of the work rather than two.
    assignment_id = Column(Integer, ForeignKey("assignments.id"),
                           index=True, nullable=True)

    #: What the class sees. `body` is the teacher's current file, whole —
    #: not a diff. A diff stream is smaller and needs every update to arrive
    #: in order and none to be missed, which polling cannot promise. Sending
    #: the whole file means a student who misses ten polls is still correct
    #: on the eleventh, and a student who joins late needs no catch-up path
    #: at all: the first poll IS the catch-up.
    body = Column(Text, nullable=False, default="")
    filename = Column(String(200), nullable=False, default="main.py")

    #: Counts up on every push, and is BOTH what students poll against and
    #: what rejects a push that arrived late.
    #:
    #: The teacher's browser sends a stamp that only ever increases, and the
    #: update is conditional on it being higher than the row's. Without that,
    #: two pushes overtaking each other on a slow connection would leave the
    #: OLDER text in the row with the HIGHER version — and the class would sit
    #: looking at a line the teacher had already fixed, with nothing to
    #: correct it until the next keystroke.
    #:
    #: BigInteger because the stamp is a millisecond clock reading, about
    #: 1.8e12, and Postgres INTEGER stops at 2.1e9. As a plain Integer this
    #: works on SQLite in development and raises NumericValueOutOfRange on
    #: the first push in production.
    version = Column(BigInteger, nullable=False, default=0)

    #: A few lines the teacher chose to hand the class — highlighted and sent
    #: with "Send to students". The ONLY thing a student can put into their
    #: own editor with a button; the mirror stays type-it-yourself. Empty
    #: means nothing is out, and "take it back" is writing it empty.
    #:
    #: `snippet_seq` is the push stamp it went out with, so a student's page
    #: can tell a new snippet from the one it already showed (or they closed)
    #: — the same text sent twice is still a second send. BigInteger for the
    #: same reason as `version`.
    #:
    #: Sending also moves `version`, which is what makes it arrive at all:
    #: students poll against `version` and get a bare 304 otherwise.
    snippet = Column(Text, nullable=False, default="")
    snippet_seq = Column(BigInteger, nullable=False, default=0)

    #: The project's notes — its first .md file, whole — sent with every push
    #: whichever file is open. `body` is only the open file, so notes used to
    #: reach the class only while the teacher had the .md tab selected, and
    #: vanished the moment they went back to the code they were explaining.
    #: Empty when the project has none.
    notes = Column(Text, nullable=False, default="")

    #: Where the teacher is in those notes when they are cut into slides, as
    #: the class should read it: "3/5". Only the current slide goes out in
    #: `notes`, so this is the one thing that says there are others. Empty
    #: when the notes are not slides, which is every lesson before this.
    slide = Column(String(16), nullable=False, default="")

    #: What the teacher's last Run printed, the tail of it, so the class can
    #: see the program they just watched being written actually work. Text
    #: only: a kaypy game's picture is drawn on the teacher's canvas and is
    #: not sent, only whatever it printed. Empty until they press Run.
    output = Column(Text, nullable=False, default="")

    #: The teacher's rendered page after their last Run, as HTML, for the
    #: apps whose Run makes a page rather than text: WebIDE sends the page it
    #: built, FlaskIDE the response its preview is showing. The class sees it
    #: in a sandboxed frame beside their own. PyIDE has no page and never
    #: sets it. Empty until the teacher presses Run.
    page = Column(Text, nullable=False, default="")

    #: Where the teacher's caret is in `body`, as "line:ch" counted from 0,
    #: so the class can see where they are typing and the mirror can follow
    #: it. Empty when there is nothing to point at: a notes file, which the
    #: class reads rendered rather than as text, or an editor from before
    #: this existed. Rides on the ordinary push, so it costs no extra
    #: requests — a caret moved without typing is simply one more push.
    cursor = Column(String(24), nullable=False, default="")

    started_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now)
    #: Set when the teacher stops. The row stays so that a student still on
    #: the page is told the lesson ended, rather than watching a mirror that
    #: has quietly stopped moving.
    ended = Column(Integer, nullable=False, default=0)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _as_map(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


# Columns added after a table first shipped, with the DDL to add each one.
# create_all() makes missing tables but never missing columns, so a database
# from an earlier deploy needs these. Every default has to leave existing rows
# correct: an assignment that existed before archiving did is not archived.
LATER_COLUMNS = [
    ("assignments", "archived",
     "ALTER TABLE assignments ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"),
    # Everything that existed before two editors shared these tables was
    # PyIDE's, so 'pyide' is the only default that makes an existing row true.
    # BOTH tables need this. Leaving `assignments` out was a real bug: the
    # column is in the model, so every query selects it, and on a database
    # whose `assignments` table predates the column that is an immediate
    # UndefinedColumn on the dashboard, the assignment link and turning in.
    ("drafts", "app",
     "ALTER TABLE drafts ADD COLUMN app VARCHAR(16) NOT NULL DEFAULT 'pyide'"),
    ("assignments", "app",
     "ALTER TABLE assignments ADD COLUMN app VARCHAR(16) NOT NULL "
     "DEFAULT 'pyide'"),
    # Live lessons shipped before they could be tied to an assignment. NULL
    # is the right default: a lesson that existed before this has no
    # assignment, which is exactly what it was.
    ("live_sessions", "assignment_id",
     "ALTER TABLE live_sessions ADD COLUMN assignment_id INTEGER"),
    # Sent snippets. Empty and 0 are true of every earlier lesson: nothing
    # was ever sent in them.
    ("live_sessions", "snippet",
     "ALTER TABLE live_sessions ADD COLUMN snippet TEXT NOT NULL DEFAULT ''"),
    ("live_sessions", "snippet_seq",
     "ALTER TABLE live_sessions ADD COLUMN snippet_seq BIGINT NOT NULL "
     "DEFAULT 0"),
    # Notes shown beside the lesson. Empty is true of every earlier lesson:
    # none of them sent any.
    ("live_sessions", "notes",
     "ALTER TABLE live_sessions ADD COLUMN notes TEXT NOT NULL DEFAULT ''"),
    # Slides and the teacher's output. Empty is true of every earlier
    # lesson: none had slides, and none ever sent what a Run printed.
    ("live_sessions", "slide",
     "ALTER TABLE live_sessions ADD COLUMN slide VARCHAR(16) NOT NULL "
     "DEFAULT ''"),
    ("live_sessions", "output",
     "ALTER TABLE live_sessions ADD COLUMN output TEXT NOT NULL DEFAULT ''"),
    # The teacher's rendered page. Empty is true of every earlier lesson.
    ("live_sessions", "page",
     "ALTER TABLE live_sessions ADD COLUMN page TEXT NOT NULL DEFAULT ''"),
    # The teacher's caret. Empty is true of every earlier lesson: none sent
    # one, and the class's page shows no caret for it.
    ("live_sessions", "cursor",
     "ALTER TABLE live_sessions ADD COLUMN cursor VARCHAR(24) NOT NULL "
     "DEFAULT ''"),
    # Feedback on turned-in work. Empty, NULL and 0 are true of every earlier
    # submission: none had any, and "not seen" is harmless with nothing to
    # see, because the New marker is only shown beside feedback that exists.
    ("submissions", "feedback",
     "ALTER TABLE submissions ADD COLUMN feedback TEXT NOT NULL DEFAULT ''"),
    ("submissions", "feedback_at",
     "ALTER TABLE submissions ADD COLUMN feedback_at TIMESTAMP"),
    ("submissions", "feedback_seen",
     "ALTER TABLE submissions ADD COLUMN feedback_seen INTEGER NOT NULL "
     "DEFAULT 0"),
]


def create_all(engine) -> None:
    """Create only the tables defined here, then bring them up to date.

    Uses this module's own metadata, so it never touches `snippets` or
    anything WebIDE owns in the same database.
    """
    Base.metadata.create_all(engine)

    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table, column, ddl in LATER_COLUMNS:
        try:
            existing = {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            continue
        if column in existing:
            continue
        with engine.begin() as conn:
            try:
                conn.execute(text(ddl))
            except Exception:
                pass


# --------------------------------------------------------------------------
# Who is allowed in
# --------------------------------------------------------------------------

def _split_env(name) -> list:
    raw = os.environ.get(name, "")
    return [part.strip().lower() for part in re.split(r"[,\s]+", raw) if part.strip()]


def allowed_domains() -> list:
    """Email domains permitted to sign in. Empty means no restriction."""
    return [d.lstrip("@") for d in _split_env("ALLOWED_EMAIL_DOMAINS")]


def teacher_emails() -> list:
    """Addresses that get the dashboard.

    Kept in the environment rather than a column on users, so nobody can
    promote themselves by finding a hole in the app. Changing who teaches is
    a deploy setting, not a database write.
    """
    return _split_env("TEACHER_EMAILS")


def email_allowed(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domains = allowed_domains()
    if not domains:
        return True                      # unconfigured: let anyone in (local dev)
    return email.lower().rsplit("@", 1)[1] in domains


def is_teacher(email: str) -> bool:
    return bool(email) and email.lower() in teacher_emails()


def login_configured() -> bool:
    """Is Google sign-in set up at all? If not, the app hides every trace."""
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and
                os.environ.get("GOOGLE_CLIENT_SECRET"))
