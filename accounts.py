"""
PyIDE — signing in, saved projects, assignments and turning work in.

Everything here is *additive*. With no Google credentials configured the app
behaves exactly as it always has: anonymous students open a link, write code,
press Run, and share a snapshot. Signing in only ever adds abilities — it is
never required to use the editor, and an anonymous student's experience is
untouched.

Four tables, chosen so they cannot collide with WebIDE, which lives in the
same database and already owns `projects`:

    users        one row per person who has ever signed in
    assignments  a starter project a teacher hands out, with a link
    drafts       a student's living copy — this is what autosaves
    submissions  what a student turned in, and when

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
    Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
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
