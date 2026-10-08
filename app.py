"""
FlaskIDE — a browser-based Flask editor for a second-semester web class.

**The student's Flask app never runs here.** It runs in their browser: Pyodide
executes `app.py`, and `static/flask.js` answers every request by calling
their app through `app.test_client()`. This server only stores and serves
shared project snapshots, exactly as WebIDE does.

That makes the word "app" ambiguous in this file, so: `app` below is THIS
Flask application, the one serving the editor. The student's Flask app is
never imported, never executed and never reaches this machine.
"""

import json
import os
import pathlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

import accounts
import quiz

APP_NAME = "flaskide"       # this editor, in the shared account tables

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

MAX_FILES = 16
MAX_FILE_BYTES = 200_000          # per file
LIVE_OUTPUT_BYTES = 20_000        # the tail of a Run, sent to the class
MAX_FILES_TOTAL = 600_000         # all files together
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters
ID_LENGTH = 7

# The file that IS the project. Without it there is nothing to run.
ENTRY = "app.py"

# THE TWO KINDS OF PROJECT, AND HOW ONE IS TOLD FROM THE OTHER
#
# FlaskIDE holds Flask apps and it holds SQL projects, and a project's kind is
# not stored anywhere. It is read off the files: a project containing query.sql
# is a SQL project, and anything else is a Flask app.
#
# Derived rather than stored on purpose. A `kind` column would have to be added
# to projects, to drafts and to assignments -- and drafts and assignments are
# SHARED with PyIDE and WebIDE, so a column here is a migration in three apps
# for a fact the files already state. It would also be a second source of truth
# that can disagree with the first, and the failure then is a project whose
# stored kind says Flask while its files say SQL, which nothing can resolve.
SQL_ENTRY = "query.sql"

# Present in either kind: it is what a database gets built from. A Flask app
# with a schema.sql gets a data.db it can open with plain sqlite3, which is the
# whole point of putting SQL in this editor rather than in a separate one.
SCHEMA = "schema.sql"

# A Flask project has folders in it, which WebIDE's projects do not: a
# template lives in templates/ and a stylesheet in static/, and Flask will
# not find them anywhere else. So a name here may carry exactly one folder,
# and only one of the two Flask itself looks in.
#
# Written as a whitelist rather than a check for "..", because a blacklist of
# traversal tricks is a thing you can be wrong about and a whitelist is not.
# Nothing matching this can escape the project directory, contain a slash in
# a surprising place, or name a hidden file.
BARE = r"[A-Za-z0-9][A-Za-z0-9 _-]{0,50}\.[A-Za-z0-9]{1,8}"
FILE_NAME = re.compile(r"^(?:(?:templates|static)/)?%s$" % BARE)

#: The only folders a name may sit in, named here so the error message can
#: say what is allowed rather than only what is not.
FOLDERS = ("templates", "static")

# Every project starts as these three, already wired together, so nobody
# spends week one wondering why their stylesheet isn't loading.
STARTER = {
    "app.py": """from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# A list to play with. It lives in memory, so it resets when you press Run.
pets = ["cat", "dog"]


@app.route("/")
def home():
    return render_template("index.html", pets=pets)


@app.route("/pet/<name>")
def pet(name):
    return render_template("pet.html", name=name)


@app.route("/add", methods=["POST"])
def add():
    name = request.form["name"].strip()
    if name:
        pets.append(name)
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# USING A DATABASE INSTEAD OF A LIST
#
# Add a file called schema.sql to this project, put CREATE TABLE and INSERT
# statements in it, and press Run. It is built into a real database called
# data.db sitting next to this file, from scratch, every single time you Run
# -- so you cannot break it, and anything you INSERT while the app is running
# is gone on the next Run.
#
# Then delete the # from the lines below.
#
# import sqlite3
#
# def query(sql, args=()):
#     con = sqlite3.connect("data.db")
#
#     # SQLite IGNORES FOREIGN KEYS UNLESS YOU ASK, ON EVERY CONNECTION.
#     # Without this line it will happily store a row pointing at a teacher
#     # who does not exist and tell you it worked. The REFERENCES in your
#     # schema is remembered and not enforced.
#     con.execute("PRAGMA foreign_keys = ON")
#
#     # Rows come back as tuples by default, so you write row[0]. This makes
#     # them behave like dicts too, so a template can say {{ row["name"] }}.
#     con.row_factory = sqlite3.Row
#
#     rows = con.execute(sql, args).fetchall()
#     con.close()
#     return rows
#
# @app.route("/teachers")
# def teachers():
#     rows = query("SELECT name, department FROM teachers ORDER BY name")
#     return "<br>".join(r["name"] + " - " + r["department"] for r in rows)
#
# That returns a rough list so you can see it working straight away. Once it
# does, add a template of your own under templates/ and hand the rows to it
# with render_template, exactly the way the pet list above does.
#
# The + SQL button at the top opens a separate project for practising queries
# against that same kind of database, with one already written for you.
""",

    "templates/base.html": """<!doctype html>
<html>
<head>
  <title>{% block title %}My Site{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <h1>My Pet List</h1>
  {% block body %}{% endblock %}
</body>
</html>
""",

    "templates/index.html": """{% extends "base.html" %}

{% block body %}
  <ul>
    {% for p in pets %}
      <li><a href="{{ url_for('pet', name=p) }}">{{ p }}</a></li>
    {% endfor %}
  </ul>

  <form method="post" action="{{ url_for('add') }}">
    <input name="name" placeholder="a new pet">
    <button>Add</button>
  </form>
{% endblock %}
""",

    "templates/pet.html": """{% extends "base.html" %}
{% block title %}{{ name }}{% endblock %}

{% block body %}
  <p>This one is called <strong>{{ name }}</strong>.</p>
  <p><a href="{{ url_for('home') }}">back to the list</a></p>
{% endblock %}
""",

    "static/style.css": """body {
  font-family: system-ui, sans-serif;
  margin: 40px;
  color: #1b2130;
}

h1 { color: #1d4ed8; }

li { margin: 4px 0; }

form { margin-top: 24px; }

input, button { font-size: 16px; padding: 6px 10px; }
""",
}


# The SQL starter, read from examples/ rather than pasted in here.
#
# They are real .sql files on purpose: they can be opened, run against sqlite3
# and edited like anything else, and tools/test_sql.py runs them to check that
# the queries the starter shows actually return what the comments say. A
# hundred lines of CREATE TABLE inside a Python string literal is a file
# nobody can check and nobody wants to edit.
EXAMPLES = pathlib.Path(__file__).resolve().parent / "examples"


def _example(name):
    """One of the starter files, or a loud failure at import time.

    Read once, at startup. A missing example is a deployment that boots and
    then hands every student an empty editor, so it stops the process here
    instead -- Render shows a failed deploy and keeps serving the last good
    one.
    """
    path = EXAMPLES / name
    if not path.is_file():
        raise RuntimeError("examples/%s is missing; the SQL starter needs it"
                           % name)
    return path.read_text()


SQL_STARTER = {
    SQL_ENTRY: _example("query.sql"),
    SCHEMA: _example("schema.sql"),
}


def _database_url() -> str:
    """Render supplies DATABASE_URL; fall back to a local SQLite file."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return "sqlite:///" + os.path.join(os.path.dirname(__file__), "flaskide.db")
    # SQLAlchemy 2.x wants the postgresql:// scheme, Render hands out postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

Base = declarative_base()


class Project(Base):
    __tablename__ = "flask_projects"

    id = Column(Integer, primary_key=True)
    slug = Column(String(16), unique=True, index=True, nullable=False)
    title = Column(String(120), nullable=False, default="Untitled")
    author = Column(String(80), nullable=False, default="")
    # every file in the project, as a JSON object of {filename: contents}
    files = Column(Text, nullable=False, default="{}")
    # A demo snapshot: reachable only at /d/<slug>, which shows the running
    # page and never the source. One flag decides everything — a hidden
    # snapshot is refused by /s, /fork and /raw alike, so there is no second
    # door to forget about and nothing to gain by editing the URL.
    hidden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    @property
    def is_hidden(self) -> bool:
        # rows written before this column existed come back as NULL
        return bool(self.hidden)

    def file_map(self) -> dict:
        try:
            data = json.loads(self.files or "{}")
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}


engine = create_engine(
    _database_url(),
    pool_pre_ping=True,
    connect_args={"check_same_thread": False}
    if _database_url().startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)

# Signing in, saved work, assignments and turning in. Its own metadata, so it
# creates only its own tables and never touches `projects` or PyIDE's.
accounts.create_all(engine)


LATER_COLUMNS = [
    ("hidden", "ALTER TABLE flask_projects ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"),
]


def _add_missing_columns() -> None:
    """Bring an older deployment's table up to date.

    create_all() makes missing tables but never missing columns. Each ALTER
    runs only when its column is absent, so this is safe on every boot — which
    is when it happens, because there is no migration step to remember.
    """
    from sqlalchemy import inspect, text
    try:
        existing = {c["name"] for c in inspect(engine).get_columns("flask_projects")}
    except Exception:
        return
    for name, ddl in LATER_COLUMNS:
        if name in existing:
            continue
        with engine.begin() as conn:
            try:
                conn.execute(text(ddl))
            except Exception:
                pass


_add_missing_columns()


def new_slug(db) -> str:
    """Random short id, retried on the (very unlikely) collision."""
    for _ in range(12):
        slug = "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if not db.query(Project.id).filter_by(slug=slug).first():
            return slug
    raise RuntimeError("could not allocate a share id")


def clean(value, limit) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def kind_of(files):
    """Which kind of project this is, read off the files themselves.

    The client has the same rule in app.js. If you change one, change both --
    a disagreement here means the editor runs a project one way and the server
    saves it as the other.
    """
    return "sql" if SQL_ENTRY in files else "flask"


def validate_files(raw):
    """Check an incoming {name: contents} map. Returns (files, error)."""
    if not isinstance(raw, dict) or not raw:
        return None, "There's nothing to share yet."
    if len(raw) > MAX_FILES:
        return None, "A project can hold at most %d files." % MAX_FILES

    files, total = {}, 0
    for name, body in raw.items():
        name = str(name).strip()
        # A backslash is never legal here, and saying so before the pattern
        # runs means a Windows-shaped path gets a sentence about slashes
        # rather than a sentence about extensions.
        if "\\" in name:
            return None, ("'%s' uses backslashes. Folders here are written "
                          "with a forward slash: templates/index.html" % name)
        if not FILE_NAME.match(name):
            return None, ("'%s' is not a valid file name. Use letters, "
                          "digits, dashes and underscores, end with an "
                          "extension like .py, .html or .css, and put it "
                          "either at the top level or in one of %s."
                          % (name, " or ".join(FOLDERS)))
        if not isinstance(body, str):
            return None, "'%s' could not be read as text." % name
        size = len(body.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            return None, "'%s' is too large to save." % name
        total += size
        if total > MAX_FILES_TOTAL:
            return None, "Those files are too large to save together."
        files[name] = body

    # Either entry will do. Which one decides the kind; having neither means
    # there is nothing to run, whichever kind was intended.
    if ENTRY not in files and SQL_ENTRY not in files:
        return None, ("A project needs an %s (a Flask app) or a %s (a SQL "
                      "project) — that is the file that runs."
                      % (ENTRY, SQL_ENTRY))

    # schema.sql is NOT required for a SQL project here, though the editor
    # cannot run one without it. Saving is not running: a student halfway
    # through writing a schema must be able to keep their work, and the
    # runtime already says plainly what is missing when they press Run.
    return files, None


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = Flask(__name__)

# Signed session cookies. Generated if unset so the app still boots locally,
# but then every restart logs everyone out — set it properly on the server.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",       # Lax, not Strict: the OAuth redirect
                                        # arrives from Google and must carry
                                        # the cookie or login silently fails
    SESSION_COOKIE_SECURE=bool(os.environ.get("DATABASE_URL")),
)


@app.context_processor
def project_shape():
    """What counts as a project, for every page that renders the editor.

    A context processor rather than an argument to each render_template,
    because there are six of those and one of them will eventually be
    written without it. Missing, the editor would let a student make
    `helpers/thing.py` and then refuse to save it, which is a rule you learn
    by losing work.
    """
    return {"entry": ENTRY, "sqlEntry": SQL_ENTRY, "schema": SCHEMA,
            "folders": list(FOLDERS)}


@app.get("/sql")
def new_sql():
    """A new SQL project: the same editor, a different starter.

    A separate address rather than a switch on the current project. The two
    kinds have different entry files, so "switch this project to SQL" would
    have to either throw away what is open or leave a project holding both
    app.py and query.sql, with nothing to say which one Run should run. A
    link that opens a new project has neither problem, and it is what the
    + SQL button does.
    """
    return render_template(
        "index.html",
        files=SQL_STARTER,
        title="Untitled query",
        author="",
        readonly=False,
        authoring=True,
        slug=None,
        shared_at=None,
    )


@app.get("/")
def index():
    return render_template(
        "index.html",
        files=STARTER,
        title="Untitled",
        author="",
        readonly=False,
        # only here can notes be written; shared snapshots and forks show them
        # rendered and never expose the markdown source
        authoring=True,
        slug=None,
        shared_at=None,
    )


def load_visible(db, slug):
    """A snapshot the /s routes are allowed to serve.

    A demo project is not one of them. Changing /d/abc to /s/abc is the first
    thing anyone tries, so the refusal lives here rather than in a template:
    the files never leave the database for a hidden row, whatever the URL says.
    """
    proj = db.query(Project).filter_by(slug=slug).first()
    if proj is None or proj.is_hidden:
        abort(404)
    return proj


@app.get("/s/<slug>")
def view_shared(slug):
    db = SessionLocal()
    try:
        proj = load_visible(db, slug)
        return render_template(
            "index.html",
            files=proj.file_map(),
            title=proj.title,
            author=proj.author,
            readonly=True,
            authoring=False,
            slug=proj.slug,
            shared_at=proj.created_at.strftime("%b %d, %Y at %I:%M %p UTC"),
        )
    finally:
        db.close()


@app.get("/s/<slug>/fork")
def fork_shared(slug):
    """Open a shared snapshot as an editable copy."""
    db = SessionLocal()
    try:
        proj = load_visible(db, slug)
        return render_template(
            "index.html",
            files=proj.file_map(),
            title=f"Copy of {proj.title}",
            author="",
            readonly=False,
            authoring=False,
            slug=None,
            shared_at=None,
        )
    finally:
        db.close()


@app.get("/s/<slug>/raw")
@app.get("/s/<slug>/raw/<path:name>")
def raw_shared(slug, name=None):
    """Plain text of one file, for diffing or feeding to a checker."""
    db = SessionLocal()
    try:
        proj = load_visible(db, slug)
        files = proj.file_map()
        wanted = name or ENTRY
        if wanted not in files:
            abort(404)
        return files[wanted], 200, {"Content-Type": "text/plain; charset=utf-8"}
    finally:
        db.close()


@app.get("/play")
def play():
    """The student's app in a tab of its own: the editor's New tab button.

    Nothing behind it on the server. The editor puts the files in this
    browser's storage and opens this page, which boots its own Python and
    runs its own copy of the app (see play.html and play.js). So there is no
    slug, no row, and nothing here for anyone else to open.
    """
    return render_template("play.html")


@app.post("/api/share")
def create_share():
    data = request.get_json(silent=True) or {}
    author = clean(data.get("author"), 80)

    # a submission nobody can be identified from is no use to a teacher
    if not author:
        return jsonify(error="Put your name in before sharing.",
                       field="author"), 400

    files, file_error = validate_files(data.get("files"))
    if file_error:
        return jsonify(error=file_error), 400

    hidden = bool(data.get("hidden"))

    db = SessionLocal()
    try:
        proj = Project(
            slug=new_slug(db),
            title=clean(data.get("title"), 120) or "Untitled",
            author=author,
            files=json.dumps(files),
            hidden=1 if hidden else 0,
        )
        db.add(proj)
        db.commit()
        route = "view_demo" if hidden else "view_shared"
        return jsonify(
            slug=proj.slug,
            hidden=hidden,
            url=url_for(route, slug=proj.slug, _external=True),
        )
    finally:
        db.close()


# --------------------------------------------------------------------------
# Signing in
# --------------------------------------------------------------------------
# Entirely optional, and sharing one account with PyIDE. With no Google
# credentials set, `oauth` stays None, no sign-in button renders, and every
# route below behaves as it did before any of this existed.

def _announce_login_settings():
    """One line in the logs on boot, so a wrong setting is visible without
    anyone having to fail a sign-in to discover it."""
    if not accounts.login_configured():
        print("[flaskide] Google sign-in: OFF "
              "(set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable)")
        return
    domains = accounts.allowed_domains()
    print("[flaskide] Google sign-in: ON — %s" % (
        ("only " + ", ".join("@" + d for d in domains)) if domains
        else "any Google account (ALLOWED_EMAIL_DOMAINS is empty)"))
    teachers = accounts.teacher_emails()
    print("[flaskide] teachers: %s" % (", ".join(teachers) if teachers
                                     else "NONE SET — nobody can publish"))


_announce_login_settings()

oauth = None
if accounts.login_configured():
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )


def current_user(db):
    """The signed-in user, or None. Never raises."""
    uid = session.get("uid")
    if not uid:
        return None
    return db.query(accounts.User).filter_by(id=uid).first()


def user_context(db):
    """What every template needs to know about who is looking."""
    user = current_user(db)
    return {
        "login_enabled": accounts.login_configured(),
        "user": user,
        "user_name": user.display_name() if user else "",
        "user_email": user.email if user else "",
        "is_teacher": bool(user and accounts.is_teacher(user.email)),
    }


@app.context_processor
def inject_user():
    """Available to every template, so no page can forget who is looking."""
    db = SessionLocal()
    try:
        return user_context(db)
    finally:
        db.close()


def _scheme():
    """Render terminates TLS in front of us, so url_for sees plain http."""
    return "https" if os.environ.get("DATABASE_URL") else "http"


_redirect_logged = [False]


@app.get("/login")
def login():
    if not oauth:
        abort(404)
    nxt = request.args.get("next", "")
    session["after_login"] = nxt if nxt.startswith("/") else ""
    target = url_for("auth_callback", _external=True, _scheme=_scheme())
    # Printed once per worker. Google's redirect_uri_mismatch page never says
    # which URI it objected to, and guessing the host is how an afternoon
    # disappears — so the exact string to paste into the Cloud Console's
    # "Authorized redirect URIs" is in the logs after the first sign-in try.
    if not _redirect_logged[0]:
        _redirect_logged[0] = True
        print(f"[{APP_NAME}] redirect URI sent to Google: {target}", flush=True)
    try:
        # select_account: always show Google's account chooser. Without it
        # Google signs in with whichever account the browser has as its
        # default — on a teacher's laptop that is usually a personal Gmail,
        # and the only way round it was an incognito window. One extra click
        # for a student with one account; the right account for everyone.
        return oauth.google.authorize_redirect(target, prompt="select_account")
    except Exception:
        # Authlib fetches Google's discovery document on the first sign-in of
        # each worker, so a network blip lands here. A student should see a
        # sentence and a way onwards, not a stack trace.
        return render_template(
            "signin_problem.html",
            reason="Couldn't reach Google just now. Try again in a moment."), 503


@app.get("/auth/callback")
def auth_callback():
    if not oauth:
        abort(404)
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        return render_template("signin_problem.html",
                               reason="That sign-in didn't complete."), 400

    info = token.get("userinfo") or {}
    sub = info.get("sub")
    email = (info.get("email") or "").strip()

    # Checked here, on the server, from the verified token — never from
    # anything the browser handed us.
    if not sub or not email or not info.get("email_verified"):
        return render_template("signin_problem.html",
                               reason="Google didn't confirm that address."), 400
    if not accounts.email_allowed(email):
        allowed = accounts.allowed_domains()
        wanted = " or ".join("@" + d for d in allowed)
        return render_template(
            "signin_problem.html",
            reason="You signed in as %s, but this site only accepts %s "
                   "addresses." % (email, wanted),
            allowed=allowed, tried=email), 403

    db = SessionLocal()
    try:
        user = db.query(accounts.User).filter_by(google_sub=sub).first()
        if user is None:
            user = accounts.User(google_sub=sub, email=email,
                                 name=info.get("name") or "")
            db.add(user)
        else:
            user.email = email                   # a school can rename a mailbox
            user.name = info.get("name") or user.name
            user.last_seen = accounts.now()
        # Kept apart for Skyward, which matches on exactly these. A token
        # without them keeps what was there rather than blanking it.
        user.first_name = (info.get("given_name") or user.first_name or "")[:80]
        user.last_name = (info.get("family_name") or user.last_name or "")[:80]
        db.commit()
        session["uid"] = user.id
    finally:
        db.close()

    return redirect(session.pop("after_login", "") or url_for("index"))


@app.get("/logout")
def logout():
    """Signing out ends any lesson this teacher is broadcasting here.

    The browser remembers a lesson so a reload resumes it, and nothing here
    can reach into localStorage to forget it. Ending the lesson is what makes
    that memory harmless: the next sign-in finds nothing open to resume. It
    is also what signing out means — nobody is at the keyboard any more, and
    the class should be told the lesson ended rather than watch a mirror that
    has quietly stopped.
    """
    uid = session.get("uid")
    if uid:
        db = SessionLocal()
        try:
            (db.query(accounts.LiveSession)
               .filter_by(host_id=uid, app=APP_NAME, ended=0)
               .update({"ended": 1, "updated_at": _live_now()},
                       synchronize_session=False))
            db.commit()
        except Exception:
            db.rollback()      # signing out must work even if this does not
        finally:
            db.close()
    session.clear()
    return redirect(request.args.get("next") or url_for("index"))


def _require_teacher(db):
    user = current_user(db)
    if user is None:
        return None, redirect(url_for("login", next=request.path))
    if not accounts.is_teacher(user.email):
        abort(404)                      # don't advertise that it exists
    return user, None


# --------------------------------------------------------------------------
# Saved work
# --------------------------------------------------------------------------
# A draft is a student's living copy: it autosaves as they type and is found
# again by who they are, not by a link they have to keep. Exactly one per
# student per assignment, so opening the link a week later returns them to
# their own work rather than to a fresh starter.

def _draft_payload(db, draft, extra=None):
    ctx = user_context(db)
    # Authoring means "these notes are yours to edit", and it also decides
    # whether the notes pane can be selected at all. You own the notes in your
    # own project; on an assignment they belong to whoever set it.
    owns_notes = ctx["is_teacher"] or draft.assignment_id is None
    ctx.update(
        files=draft.file_map(),
        title=draft.title,
        author=ctx["user_name"],
        readonly=False,
        authoring=owns_notes,
        slug=None,
        shared_at=None,
        draft_slug=draft.slug,
        # Where this tab starts: every save says it, and the server refuses
        # one from a tab another tab has overtaken.
        draft_version=draft.version or 0,
    )
    # HAS THIS COPY BEEN WORKED ON YET?
    #
    # Used by the rescue in the editor: a student who typed while signed out
    # and then signed in gets that work put back, and this decides whether it
    # can happen silently. A draft still identical to the starter has nothing
    # to lose, which is the ordinary case — the draft was made moments ago by
    # the very click that signed them in. Anything else gets asked about,
    # because restoring would destroy real work.
    ctx["draft_fresh"] = True
    if draft.assignment_id:
        starter = db.query(accounts.Assignment).filter_by(
            id=draft.assignment_id).first()
        if starter is not None:
            # Against the starter AS THE STUDENT WAS GIVEN IT, with the
            # answer keys taken out of its notes. Compared with the teacher's
            # copy, no draft of an assignment with questions would ever look
            # untouched, and every sign-in would ask about restoring work.
            ctx["draft_fresh"] = (
                draft.code == starter.code
                and draft.file_map() == quiz.redact_files(starter.file_map()))
    ctx.update(extra or {})
    return ctx


@app.get("/p/<slug>")
def open_draft(slug):
    """A student's own saved project."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return redirect(url_for("login", next=request.path))
        draft = db.query(accounts.Draft).filter_by(
            slug=slug, app=APP_NAME).first()
        if draft is None:
            abort(404)
        # Somebody else's work is simply not found, rather than forbidden —
        # there is no reason to confirm that a link belongs to anyone.
        if draft.owner_id != user.id:
            abort(404)

        assignment = None
        if draft.assignment_id:
            assignment = db.query(accounts.Assignment).filter_by(
                id=draft.assignment_id).first()
        submitted = None
        if assignment:
            submitted = db.query(accounts.Submission).filter_by(
                assignment_id=assignment.id, student_id=user.id).first()

        return render_template("index.html", **_draft_payload(db, draft, {
            "assignment_title": assignment.title if assignment else "",
            "assignment_slug": assignment.slug if assignment else "",
            "submitted_at": submitted.submitted_at.strftime("%b %d at %I:%M %p")
                            if submitted else "",
        }))
    finally:
        db.close()


@app.post("/api/draft")
def start_draft():
    """Keep a project the student started themselves.

    Assignments make a draft automatically, so this covers the other two ways
    into the editor: a new project, or a fork of somebody's share link.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Sign in first, then you can save projects."), 401

        data = request.get_json(silent=True) or {}
        files, file_error = validate_files(data.get("files"))
        if file_error:
            return jsonify(error=file_error), 400

        draft = accounts.Draft(
            slug=accounts.new_id(db, accounts.Draft),
            owner_id=user.id,
            assignment_id=None,
            app=APP_NAME,
            title=clean(data.get("title"), 200) or "Untitled",
            code="",                     # FlaskIDE keeps everything in files
            files=json.dumps(files),
        )
        db.add(draft)
        db.commit()
        return jsonify(slug=draft.slug, url=url_for("open_draft", slug=draft.slug))
    finally:
        db.close()


STALE_TAB = ("This was changed in another tab or window, so this one has "
             "stopped saving to keep that work safe. Reload this page to carry "
             "on from the latest version.")


def _stale(draft, data):
    """A 409 if this write comes from a tab that has fallen behind, else None.

    Behind means: the draft has been written since the version this tab last
    saw, and not by this tab. See Draft.version in accounts.py for why — the
    Classroom link open in a forgotten second tab beside the live lesson.

    A request with no `base` or `tab` is from a page loaded before this guard
    existed — an open tab during the deploy — and is let through as before,
    rather than stranding a student mid-sentence on the day it ships.

    Read then written, not one conditional UPDATE: the race it leaves is two
    tabs saving within the same few milliseconds, which a person with two
    tabs cannot do. The race it closes is minutes wide.
    """
    base, tab = data.get("base"), data.get("tab")
    if base is None or not isinstance(tab, str) or not tab:
        return None
    try:
        base = int(base)
    except (TypeError, ValueError):
        return None
    if base != (draft.version or 0) and draft.writer != tab[:24]:
        return jsonify(error=STALE_TAB, stale=True), 409
    return None


def _written(draft, data):
    """Stamp a write: the next version, and which tab made it."""
    draft.version = (draft.version or 0) + 1
    tab = data.get("tab")
    draft.writer = tab[:24] if isinstance(tab, str) else ""


@app.post("/api/draft/<slug>")
def save_draft(slug):
    """Autosave. Called a moment after the student stops typing."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="not signed in"), 401
        draft = db.query(accounts.Draft).filter_by(
            slug=slug, app=APP_NAME).first()
        if draft is None or draft.owner_id != user.id:
            return jsonify(error="no such project"), 404

        data = request.get_json(silent=True) or {}
        files, file_error = validate_files(data.get("files"))
        if file_error:
            return jsonify(error=file_error), 400

        stale = _stale(draft, data)
        if stale:
            return stale

        draft.files = json.dumps(files)
        draft.title = clean(data.get("title"), 200) or draft.title
        draft.updated_at = accounts.now()
        _written(draft, data)
        db.commit()
        return jsonify(saved_at=draft.updated_at.strftime("%I:%M %p"),
                       version=draft.version)
    finally:
        db.close()


@app.delete("/api/draft/<slug>")
def delete_draft(slug):
    """Throw away one of your own saved projects.

    Only your own, and only the working copy. Anything already turned in stays
    with the teacher — a submission points at its own frozen snapshot.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="not signed in"), 401
        draft = db.query(accounts.Draft).filter_by(
            slug=slug, app=APP_NAME).first()
        if draft is None or draft.owner_id != user.id:
            return jsonify(error="no such project"), 404
        db.delete(draft)
        db.commit()
        return jsonify(ok=True)
    finally:
        db.close()


@app.get("/api/my/projects")
def my_projects():
    """Everything this student has saved in THIS editor, newest first.

    Filtered by app: one sign-in covers both editors, but a Python project
    cannot be opened in the web editor, so neither ever lists the other's.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="not signed in"), 401
        rows = (db.query(accounts.Draft)
                  .filter_by(owner_id=user.id, app=APP_NAME)
                  .order_by(accounts.Draft.updated_at.desc())
                  .limit(60).all())
        titles = {a.id: a.title for a in db.query(accounts.Assignment).all()}
        turned_in = {s.assignment_id for s in db.query(accounts.Submission)
                     .filter_by(student_id=user.id).all()}
        return jsonify(projects=[{
            "slug": d.slug,
            "title": d.title,
            "assignment": titles.get(d.assignment_id, ""),
            "submitted": bool(d.assignment_id and d.assignment_id in turned_in),
            "updated": d.updated_at.strftime("%b %d, %I:%M %p"),
            "url": url_for("open_draft", slug=d.slug),
        } for d in rows])
    finally:
        db.close()


@app.get("/my")
def my_work():
    """A student's own page: their assignments, then their projects.

    Assignments and projects are both drafts underneath, and the window this
    replaced listed them together — so an assignment a student had saved
    from a live lesson and then turned in looked like two things, a project
    and a submission. Here an assignment is one row that says where it
    stands, and the projects are only what is NOT for an assignment.

    Flask apps and SQL projects are both FlaskIDE drafts and both open at
    /p/<slug>, where the editor decides the kind from the files — so they
    share one list, with SQL ones labelled.

    There is no class roster, so the only assignments listed are ones this
    student has opened (that made a draft) or turned in. One they have never
    clicked the link for cannot be known about, and is not shown.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return redirect(url_for("login", next=request.path))

        drafts = (db.query(accounts.Draft)
                    .filter_by(owner_id=user.id, app=APP_NAME)
                    .order_by(accounts.Draft.updated_at.desc()).all())
        subs = {s.assignment_id: s for s in db.query(accounts.Submission)
                .filter_by(student_id=user.id).all()}
        wanted = {d.assignment_id for d in drafts if d.assignment_id} | set(subs)
        # Filtered by app: one sign-in covers all three editors and a
        # submission row does not say which, so another editor's turned-in
        # work is dropped here rather than listed with a link that 404s.
        items = {a.id: a for a in db.query(accounts.Assignment)
                 .filter(accounts.Assignment.id.in_(wanted),
                         accounts.Assignment.app == APP_NAME).all()} if wanted else {}

        def when(t):
            return t.strftime("%b %d at %I:%M %p")

        earned = {}
        for aid in items:
            got = _quiz_earned(db, aid).get(user.id)
            if got is not None:
                earned[aid] = got

        assignments, projects, seen = [], [], set()
        for d in drafts:
            item = items.get(d.assignment_id)
            if item is None:
                # No assignment, or one deleted since: an ordinary project.
                # (Deleting an assignment is refused once anyone has turned
                # in, so nothing handed in is lost by listing it this way.)
                projects.append({"slug": d.slug, "title": d.title or "Untitled",
                                 "sql": _is_sql(d.file_map()),
                                 "updated": when(d.updated_at),
                                 "url": url_for("open_draft", slug=d.slug)})
                continue
            seen.add(item.id)
            assignments.append(_my_assignment(item, d, subs.get(item.id), when,
                                              earned.get(item.id)))
        # Turned in, and then the working copy deleted. What was handed in is
        # still the teacher's, so it still belongs on this list.
        for aid, sub in subs.items():
            item = items.get(aid)
            if item is not None and aid not in seen:
                assignments.append(_my_assignment(item, None, sub, when,
                                                  earned.get(aid)))

        # Seen, now that it is on their screen. After the rows are built, so
        # this visit still shows New and the next one does not.
        fresh = [s for s in subs.values()
                 if (s.feedback or s.score is not None) and not s.feedback_seen]
        for s in fresh:
            s.feedback_seen = 1
        if fresh:
            db.commit()

        return render_template("my.html", assignments=assignments,
                               projects=projects)
    finally:
        db.close()


def _is_sql(files):
    """A SQL project is one with a query.sql — the same test the editor's
    isSql() makes, so this label and the editor that opens cannot disagree."""
    return SQL_ENTRY in files


def _my_assignment(item, draft, sub, when, earned=None):
    return {
        "title": item.title,
        "closed": bool(item.closed),
        "sql": _is_sql(item.file_map()),
        "draft_slug": draft.slug if draft else "",
        # Their copy if they still have one, else the handout link, which
        # makes a fresh copy from the starter.
        "url": (url_for("open_draft", slug=draft.slug) if draft
                else url_for("open_assignment", slug=item.slug)),
        "updated": when(draft.updated_at) if draft else "",
        "submitted": when(sub.submitted_at) if sub else "",
        "times": (sub.times_submitted or 1) if sub else 0,
        # A lesson's turn-in has no snapshot; the lesson itself is the link.
        "turned_in_url": (url_for("view_shared", slug=sub.snippet_slug)
                          if sub and sub.snippet_slug else ""),
        "feedback": (sub.feedback or "") if sub else "",
        "feedback_when": (sub.feedback_at.strftime("%b %d at %I:%M %p")
                          if sub and sub.feedback_at else ""),
        "score": _score_text(sub.score) if sub else "",
        # Points from the questions in the notes, and what the grade comes
        # to with them. The questions count as soon as they are answered,
        # turned in or not, so this is shown with no submission too.
        "quiz": _score_text(earned),
        "total": _score_text(_total(sub.score if sub else None, earned)),
        "out_of": item.out_of or "",
        "feedback_new": bool(sub and (sub.feedback or sub.score is not None)
                             and not sub.feedback_seen),
        # Turned in again after the comment was written: it may be about
        # something they have since fixed, and they should know which.
        "feedback_older": bool(sub and sub.feedback_at
                               and sub.submitted_at > sub.feedback_at),
    }


# --------------------------------------------------------------------------
# Assignments
# --------------------------------------------------------------------------

@app.post("/api/assignment")
def publish_assignment():
    """Turn whatever the teacher is looking at into an assignment link."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can publish an assignment."), 403

        data = request.get_json(silent=True) or {}
        files, file_error = validate_files(data.get("files"))
        if file_error:
            return jsonify(error=file_error), 400

        item = accounts.Assignment(
            slug=accounts.new_id(db, accounts.Assignment),
            app=APP_NAME,
            teacher_id=user.id,
            title=clean(data.get("title"), 200) or "Untitled assignment",
            code="",
            files=json.dumps(files),
        )
        db.add(item)
        db.commit()
        _store_quiz_keys(db, item.id, files.values())
        return jsonify(slug=item.slug,
                       url=url_for("open_assignment", slug=item.slug,
                                   _external=True, _scheme=_scheme()))
    finally:
        db.close()


@app.get("/a/<slug>")
def open_assignment(slug):
    """The link a teacher hands out.

    Signed in, this finds the student's own copy — or makes one the first time
    — and sends them to it. Signed out, it behaves exactly like a fork of a
    shared project: an editable copy that saves nothing. Nobody is locked out
    by a sign-in that won't cooperate five minutes before the bell.
    """
    db = SessionLocal()
    try:
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None:
            abort(404)

        user = current_user(db)

        # The author clicking their own handout link. Without this they get a
        # student's copy of their own assignment: it sits in their project list
        # looking like a duplicate, it counts them among the students who have
        # started, and — worst — editing it changes nothing for the class,
        # because a draft is a copy. So the author lands on the editable
        # assignment instead, which is what they almost always wanted.
        # `?preview=1` still gives the student's view, on purpose.
        if (user is not None and user.id == item.teacher_id
                and request.args.get("preview") != "1"):
            return redirect(url_for("edit_lesson" if _is_lesson(item)
                                    else "edit_assignment", slug=item.slug))

        # A lesson has no code to copy, so no draft: the page is the lesson.
        if _is_lesson(item):
            return _lesson_page(db, item, user)

        if user is None:
            ctx = user_context(db)
            ctx.update(
                files=quiz.redact_files(item.file_map()),
                title=item.title,
                author="",
                readonly=False,
                authoring=False,
                slug=None,
                shared_at=None,
                draft_slug=None,
                assignment_title=item.title,
                assignment_slug=item.slug,
                submitted_at="",
                sign_in_hint=True,
            )
            return render_template("index.html", **ctx)

        draft = db.query(accounts.Draft).filter_by(
            owner_id=user.id, assignment_id=item.id).first()
        if draft is None:
            draft = accounts.Draft(
                slug=accounts.new_id(db, accounts.Draft),
                owner_id=user.id,
                assignment_id=item.id,
                app=APP_NAME,
                title=item.title,
                code="",
                files=json.dumps(quiz.redact_files(item.file_map())),
            )
            db.add(draft)
            db.commit()
        return redirect(url_for("open_draft", slug=draft.slug))
    finally:
        db.close()


@app.get("/teacher/<slug>/edit")
def edit_assignment(slug):
    """Open a published assignment to change it.

    The notes are yours here, so the markdown opens for editing the same way
    it does in a new project. Handing work out is not the last time you can
    touch it.
    """
    db = SessionLocal()
    try:
        user, bounce = _require_teacher(db)
        if bounce:
            return bounce
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            abort(404)
        if _is_lesson(item):
            return redirect(url_for("edit_lesson", slug=item.slug))

        # Not the author's own draft, if one is lying about from before the
        # redirect in open_assignment existed — that is not a student who
        # started.
        started = (db.query(accounts.Draft)
                     .filter(accounts.Draft.assignment_id == item.id,
                             accounts.Draft.owner_id != item.teacher_id)
                     .count())
        ctx = user_context(db)
        ctx.update(
            files=item.file_map(),
            title=item.title,
            author=ctx["user_name"],
            readonly=False,
            authoring=True,          # your notes, your assignment
            slug=None,
            shared_at=None,
            draft_slug=None,
            assignment_title=item.title,
            assignment_slug="",      # no Turn in — you are not a student here
            submitted_at="",
            editing_assignment=item.slug,
            editing_started=started,
        )
        return render_template("index.html", **ctx)
    finally:
        db.close()


@app.post("/api/assignment/<slug>")
def update_assignment(slug):
    """Save changes to a published assignment.

    This changes what students get when they open the link *from now on*.
    Anyone already working keeps their copy exactly as it is — their code is
    theirs, and an edit to the starter must never reach in and overwrite it.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="not allowed"), 403
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            return jsonify(error="no such assignment"), 404

        data = request.get_json(silent=True) or {}
        files, file_error = validate_files(data.get("files"))
        if file_error:
            return jsonify(error=file_error), 400

        item.title = clean(data.get("title"), 200) or item.title
        item.files = json.dumps(files)
        item.updated_at = accounts.now()
        db.commit()
        _store_quiz_keys(db, item.id, files.values())
        # Not the author's own draft, if one is lying about from before the
        # redirect in open_assignment existed — that is not a student who
        # started.
        started = (db.query(accounts.Draft)
                     .filter(accounts.Draft.assignment_id == item.id,
                             accounts.Draft.owner_id != item.teacher_id)
                     .count())
        return jsonify(ok=True, title=item.title, already_started=started)
    finally:
        db.close()


@app.post("/api/assignment/<slug>/archive")
def archive_assignment(slug):
    """Tidy an assignment away, or bring it back. Nothing is destroyed."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="not allowed"), 403
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            return jsonify(error="no such assignment"), 404
        item.archived = 0 if item.archived else 1
        db.commit()
        return jsonify(ok=True, archived=bool(item.archived))
    finally:
        db.close()


@app.delete("/api/assignment/<slug>")
def delete_assignment(slug):
    """Delete an assignment outright — only if nobody has turned anything in.

    The refusal is the point. Submissions are the closest thing this app has
    to a record of a student's work, and no single click should be able to
    wipe them. Students who started but never submitted keep their code: their
    copy is detached and becomes an ordinary saved project.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="not allowed"), 403
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            return jsonify(error="no such assignment"), 404

        handed_in = db.query(accounts.Submission).filter_by(
            assignment_id=item.id).count()
        if handed_in:
            return jsonify(
                error="%d student%s turned work in to this. Archive it instead "
                      "— that hides it and keeps everything."
                      % (handed_in, "" if handed_in == 1 else "s"),
                submissions=handed_in), 409
        # Answers to its questions are marked work too, even from a student
        # who never pressed Turn in.
        answered = (db.query(accounts.QuizAnswer.student_id)
                      .filter_by(assignment_id=item.id).distinct().count())
        if answered:
            return jsonify(
                error="%d student%s answered its questions. Archive it instead "
                      "— that hides it and keeps everything."
                      % (answered, "" if answered == 1 else "s"),
                submissions=answered), 409

        detached = db.query(accounts.Draft).filter_by(assignment_id=item.id).all()
        for draft in detached:
            draft.assignment_id = None       # their work becomes their own
        # Its answer keys go with it. Left behind they point at a deleted
        # assignment, which Postgres refuses outright — the delete would fail.
        (db.query(accounts.QuizQuestion).filter_by(assignment_id=item.id)
           .delete(synchronize_session=False))
        db.delete(item)
        db.commit()
        return jsonify(ok=True, kept_projects=len(detached))
    finally:
        db.close()


# --------------------------------------------------------------------------
# Turning it in
# --------------------------------------------------------------------------

@app.post("/api/submit")
def turn_in():
    """Freeze the student's work and record it against the assignment.

    The frozen copy is an ordinary share snapshot, so what was handed in
    cannot change however much the student keeps tinkering. Turning in again
    replaces the row and points it at a newer snapshot.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Sign in first, then you can turn work in."), 401

        data = request.get_json(silent=True) or {}
        draft = db.query(accounts.Draft).filter_by(
            slug=str(data.get("draft", "")), app=APP_NAME).first()
        if draft is None or draft.owner_id != user.id:
            return jsonify(error="no such project"), 404
        if not draft.assignment_id:
            return jsonify(error="This project isn't part of an assignment."), 400

        item = db.query(accounts.Assignment).filter_by(
            id=draft.assignment_id).first()
        if item is None:
            return jsonify(error="That assignment is gone."), 404
        if item.closed:
            return jsonify(error="That assignment is closed."), 403

        files, file_error = validate_files(data.get("files"))
        if file_error:
            return jsonify(error=file_error), 400

        # A tab that has fallen behind must not hand in its stale copy — nor
        # write it over the newer one, which is what the line after this did.
        stale = _stale(draft, data)
        if stale:
            return stale

        # keep the draft in step, so the saved copy matches what was submitted
        draft.files = json.dumps(files)
        draft.updated_at = accounts.now()
        _written(draft, data)

        snap = Project(
            slug=new_slug(db),
            title=draft.title or item.title,
            author=user.display_name(),
            files=json.dumps(files),
        )
        db.add(snap)
        db.flush()

        row = db.query(accounts.Submission).filter_by(
            assignment_id=item.id, student_id=user.id).first()
        if row is None:
            row = accounts.Submission(assignment_id=item.id, student_id=user.id,
                                      snippet_slug=snap.slug)
            db.add(row)
        else:
            row.snippet_slug = snap.slug
            row.submitted_at = accounts.now()
            row.times_submitted = (row.times_submitted or 1) + 1
        db.commit()
        return jsonify(ok=True,
                       submitted_at=row.submitted_at.strftime("%b %d at %I:%M %p"),
                       again=row.times_submitted > 1, version=draft.version)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Questions in the notes
#
# A ```quiz block in an assignment's notes is a question the student answers
# on the page, once, and is told straight away whether they were right. The
# points go on top of the teacher's score for the work, and Sync sends the
# two together. quiz.py has the format and why the key never reaches a
# student's browser; this is where it is kept and where answers are marked.
# --------------------------------------------------------------------------

def _store_quiz_keys(db, assignment_id, texts):
    """Keep the answer key of every question in these notes.

    Called with every save of the assignment and every live push, so it
    writes only what is new or changed. Two workers saving the same new
    question at once collide on the unique constraint; the loser's rollback
    leaves the winner's row, which is the same key.
    """
    found = {}
    for text in texts:
        if isinstance(text, str):
            for q in quiz.keys(text):
                found[q["qid"]] = q
    if not found:
        return
    have = {row.qid: row for row in db.query(accounts.QuizQuestion).filter(
        accounts.QuizQuestion.assignment_id == assignment_id,
        accounts.QuizQuestion.qid.in_(list(found))).all()}
    for qid, q in found.items():
        fields = {"kind": q["kind"], "prompt": q["prompt"],
                  "choices": json.dumps(q["choices"]),
                  "correct": json.dumps(q["correct"]),
                  "answers": json.dumps(q["answers"]),
                  "points": q["points"]}
        row = have.get(qid)
        if row is None:
            db.add(accounts.QuizQuestion(assignment_id=assignment_id, qid=qid,
                                         **fields))
        elif any(getattr(row, k) != v for k, v in fields.items()):
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = accounts.now()
    try:
        db.commit()
    except Exception:
        db.rollback()


def _quiz_possible(item):
    """The questions in the assignment's notes as saved, for the dashboard's
    "N questions worth P points". Only an aid to choosing Out of: a question
    added in a live lesson and never saved is answerable but not counted
    here."""
    seen = {}
    for q in quiz.file_keys(item.file_map()):
        seen.setdefault(q["qid"], q)
    return list(seen.values())


def _mark(key, response):
    return quiz.is_correct(key.kind, json.loads(key.correct or "[]"),
                           json.loads(key.answers or "[]"), response)


def _quiz_earned(db, assignment_id):
    """{student id: points from questions} for everyone who answered any.

    Marked here, every time, against the key as it is now — never stored —
    so a teacher who fixes a wrong `[x]` fixes everyone's marks with it. A
    student who answered and got all of them wrong is 0, not missing: they
    have a grade."""
    keys = {k.qid: k for k in db.query(accounts.QuizQuestion)
            .filter_by(assignment_id=assignment_id).all()}
    earned = {}
    for a in db.query(accounts.QuizAnswer).filter_by(
            assignment_id=assignment_id).all():
        key = keys.get(a.qid)
        got = key.points if key is not None and _mark(key, a.response) else 0.0
        earned[a.student_id] = round(earned.get(a.student_id, 0.0) + got, 2)
    return earned


def _total(score, earned):
    """The grade: the teacher's score plus the questions' points. None only
    when there is neither — "not graded", which Sync skips."""
    if score is None and earned is None:
        return None
    return round((score or 0) + (earned or 0), 2)


def _quiz_assignment(db, slug):
    return db.query(accounts.Assignment).filter_by(
        slug=clean(slug, 16), app=APP_NAME).first()


@app.post("/api/quiz/answer")
def quiz_answer():
    """A student's answer to one question. One try, and they are told at once.

    The reply says right or wrong and never what the right answer was: the
    student beside them has not answered yet.

    The teacher who set it is marked but not recorded, so they can try their
    own questions from the student's view (?preview=1) without appearing on
    their own dashboard.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Sign in to answer questions."), 401
        data = request.get_json(silent=True) or {}
        item = _quiz_assignment(db, data.get("assignment"))
        if item is None:
            return jsonify(error="No such assignment."), 404
        qid = str(data.get("question", ""))[:16]
        response = data.get("response")
        if not isinstance(response, str) or not response.strip():
            return jsonify(error="Answer the question first."), 400
        response = response.strip()[:2000]

        def find():
            return db.query(accounts.QuizQuestion).filter_by(
                assignment_id=item.id, qid=qid).first()
        key = find()
        if key is None:
            # Saved before this existed, or a race with the save that keeps
            # it: the assignment's own notes are the key's last word.
            _store_quiz_keys(db, item.id, item.file_map().values())
            key = find()
        if key is None:
            return jsonify(error="This question has changed since the page "
                                 "loaded. Reload to get the new one."), 404

        if user.id == item.teacher_id:
            right = _mark(key, response)
            return jsonify(correct=right, earned=key.points if right else 0,
                           points=key.points, response=response, practice=True)

        had = db.query(accounts.QuizAnswer).filter_by(
            assignment_id=item.id, student_id=user.id, qid=qid).first()
        if had is None:
            if item.closed:
                return jsonify(error="That assignment is closed."), 403
            had = accounts.QuizAnswer(assignment_id=item.id, student_id=user.id,
                                      qid=qid, response=response)
            db.add(had)
            try:
                db.commit()
            except Exception:
                # Their other tab, or a double click on the other worker,
                # got there first. That answer is the one that counts.
                db.rollback()
                had = db.query(accounts.QuizAnswer).filter_by(
                    assignment_id=item.id, student_id=user.id, qid=qid).first()
                if had is None:
                    return jsonify(error="That answer wasn't saved. Try again."), 500
        right = _mark(key, had.response)
        return jsonify(correct=right, earned=key.points if right else 0,
                       points=key.points, response=had.response,
                       already=had.response != response)
    finally:
        db.close()


@app.get("/api/quiz/<slug>/mine")
def quiz_mine(slug):
    """What this student has already answered, so the page shows those
    questions locked with their result rather than open for a second try."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="not signed in"), 401
        item = _quiz_assignment(db, slug)
        if item is None:
            return jsonify(error="No such assignment."), 404
        keys = {k.qid: k for k in db.query(accounts.QuizQuestion)
                .filter_by(assignment_id=item.id).all()}
        out = {}
        for a in db.query(accounts.QuizAnswer).filter_by(
                assignment_id=item.id, student_id=user.id).all():
            key = keys.get(a.qid)
            right = key is not None and _mark(key, a.response)
            points = key.points if key is not None else 0
            out[a.qid] = {"response": a.response, "correct": right,
                          "points": points, "earned": points if right else 0}
        return jsonify(answers=out, closed=bool(item.closed))
    finally:
        db.close()


# --------------------------------------------------------------------------
# Lessons
#
# An assignment with no code: notes, cut into slides, with questions in
# them, shown to students full screen (lesson.html, lesson.js). For classes
# that are not programming. It is an ordinary Assignment with kind "lesson"
# and its notes in `files` as lesson.md, so everything built for notes in an
# assignment — answer keys kept off the wire, marking, the dashboard, Google
# Classroom, the live link — works on it without knowing it is a lesson.
#
# Opened from the assignment link a student moves through it at their own
# pace. Opened from the live link it follows the teacher's slide, the way the
# notes pane does in a coding lesson. That is the only difference.
#
# There is no draft: nothing is typed but answers, and those are kept as
# they are given (quiz_answers). Turn in records a Submission with no
# snapshot, so its points go to Classroom the way a coding assignment's do.
# --------------------------------------------------------------------------

LESSON_FILE = "lesson.md"

LESSON_STARTER = """# {title}

Write your notes here. A line with only `---` on it starts a new slide.

---

## A question

Students answer it on the slide, once, and see straight away whether they
were right. The points count when they press Turn in.

```quiz
What does a line with only --- on it do in these notes?
- [ ] Draws a line across the slide
- [x] Starts a new slide
points: 1
```
"""


def _is_lesson(item):
    return item is not None and (item.kind or "code") == "lesson"


def _lesson_notes(item):
    return item.file_map().get(LESSON_FILE, "")


@app.post("/api/lesson")
def create_lesson():
    """A new lesson, from the dashboard's Create lesson. Starts with a page of
    example notes showing a slide and a question, which the teacher writes
    over, rather than a blank file that explains nothing."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can make a lesson."), 403
        data = request.get_json(silent=True) or {}
        title = clean(data.get("title"), 200) or "Untitled lesson"
        item = accounts.Assignment(
            slug=accounts.new_id(db, accounts.Assignment),
            app=APP_NAME, teacher_id=user.id, title=title, kind="lesson",
            code="", files=json.dumps({LESSON_FILE: LESSON_STARTER.format(title=title)}))
        db.add(item)
        db.commit()
        _store_quiz_keys(db, item.id, item.file_map().values())
        return jsonify(slug=item.slug, url=url_for("edit_lesson", slug=item.slug))
    finally:
        db.close()


@app.get("/teacher/<slug>/lesson")
def edit_lesson(slug):
    """The teacher's lesson page: Write (the markdown, with the slides beside
    it as students will see them) and Present (the slides full screen, and
    Go live). `?go=live` arrives from the dashboard's Go live and starts
    presenting live at once."""
    db = SessionLocal()
    try:
        user, bounce = _require_teacher(db)
        if bounce:
            return bounce
        item = db.query(accounts.Assignment).filter_by(slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id or not _is_lesson(item):
            abort(404)
        lesson = _lesson_for(db, user, item)
        ctx = user_context(db)
        ctx.update(item=item, notes=_lesson_notes(item), live_code=lesson.code,
                   live_on=not lesson.ended,
                   live_url=url_for("live_page", code=lesson.code, _external=True,
                                    _scheme=_scheme()),
                   go_live=request.args.get("go") == "live")
        return render_template("lesson_teacher.html", **ctx)
    finally:
        db.close()


@app.post("/api/lesson/<slug>")
def save_lesson(slug):
    """Save the lesson's title and notes. Like editing an assignment, this is
    what students get from now on; answers already given stay, and are
    marked against the keys as they are now (see _quiz_earned)."""
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not _is_lesson(item):
            return jsonify(error="That isn't a lesson."), 400
        data = request.get_json(silent=True) or {}
        notes = data.get("notes")
        if not isinstance(notes, str):
            return jsonify(error="Nothing to save."), 400
        if len(notes.encode("utf-8")) > MAX_FILE_BYTES:
            return jsonify(error="Those notes are too long to save."), 413
        item.title = clean(data.get("title"), 200) or item.title
        item.files = json.dumps({LESSON_FILE: notes})
        item.updated_at = accounts.now()
        db.commit()
        _store_quiz_keys(db, item.id, [notes])
        return jsonify(ok=True, title=item.title)
    finally:
        db.close()


@app.post("/api/lesson/<slug>/turnin")
def turn_in_lesson(slug):
    """A student saying they are done. Nothing is copied — the work IS the
    answers, already kept as given — so the Submission has no snapshot, and
    exists so the teacher sees who finished and Sync sends their points, as
    for any assignment. Pressing it again just moves the time."""
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Sign in first, then you can turn it in."), 401
        item = db.query(accounts.Assignment).filter_by(slug=slug, app=APP_NAME).first()
        if not _is_lesson(item):
            return jsonify(error="No such lesson."), 404
        if item.closed:
            return jsonify(error="That lesson is closed."), 403
        row = db.query(accounts.Submission).filter_by(
            assignment_id=item.id, student_id=user.id).first()
        if row is None:
            row = accounts.Submission(assignment_id=item.id, student_id=user.id,
                                      snippet_slug="")
            db.add(row)
        else:
            row.submitted_at = accounts.now()
            row.times_submitted = (row.times_submitted or 1) + 1
        db.commit()
        return jsonify(ok=True, again=row.times_submitted > 1,
                       submitted_at=row.submitted_at.strftime("%b %d at %I:%M %p"))
    finally:
        db.close()


def _lesson_page(db, item, user, live=None):
    """The student's lesson page, from the assignment link or (with `live`)
    the live link. The notes go with the answer keys taken out, as every
    copy a student is given does."""
    submitted_at = ""
    if user is not None:
        done = db.query(accounts.Submission).filter_by(
            assignment_id=item.id, student_id=user.id).first()
        if done is not None:
            submitted_at = done.submitted_at.strftime("%b %d at %I:%M %p")
    ctx = user_context(db)
    ctx.update(item=item, notes=quiz.redact(_lesson_notes(item)),
               submitted_at=submitted_at, live=live,
               waiting=_waiting(live) if live is not None else False,
               is_host=bool(live is not None and user is not None
                            and user.id == live.host_id))
    return render_template("lesson.html", **ctx)


def _lesson_answers(db, item):
    """{student id: [(question, their answer, right?)]}, for the teacher's
    page, which shows a lesson's answers where a coding assignment has an
    Open link to the code."""
    keys = {k.qid: k for k in db.query(accounts.QuizQuestion)
            .filter_by(assignment_id=item.id).all()}
    out = {}
    for a in (db.query(accounts.QuizAnswer).filter_by(assignment_id=item.id)
                .order_by(accounts.QuizAnswer.answered_at).all()):
        key = keys.get(a.qid)
        prompt = (key.prompt if key is not None else "A question since changed")
        prompt = " ".join(prompt.split("\n")[0].split())[:120]
        out.setdefault(a.student_id, []).append(
            (prompt, a.response, key is not None and _mark(key, a.response)))
    return out


# --------------------------------------------------------------------------
# The teacher's view
# --------------------------------------------------------------------------

@app.get("/teacher")
def teacher_home():
    db = SessionLocal()
    try:
        user, bounce = _require_teacher(db)
        if bounce:
            return bounce
        show_archived = request.args.get("archived") == "1"
        items = (db.query(accounts.Assignment)
                   .filter_by(teacher_id=user.id, app=APP_NAME)
                   .all())
        # Most recently changed first (Assignment.changed): what the teacher
        # is working on now is at the top, not whatever was made last.
        items.sort(key=lambda a: a.changed, reverse=True)
        live = [a for a in items if not a.archived]
        filed = [a for a in items if a.archived]
        counts = {}
        for item in items:
            counts[item.id] = db.query(accounts.Submission).filter_by(
                assignment_id=item.id).count()
        link = _classroom_link(db, user) if classroom_configured() else None
        ctx = user_context(db)
        ctx.update(assignments=live, archived=filed, counts=counts,
                   show_archived=show_archived,
                   classroom_on=classroom_configured(),
                   classroom_email=link.google_email if link else "",
                   classroom_connected=link is not None,
                   classroom_just=request.args.get("classroom") == "connected")
        return render_template("teacher.html", **ctx)
    finally:
        db.close()


#: Long enough for a paragraph or two of real comment; short enough that a
#: paste of a whole program into the box is refused rather than stored.
MAX_FEEDBACK = 5000


def _parse_score(raw):
    """(score or None, error or ""). Empty is "not scored", never 0."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, ""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, "A score has to be a number."
    if value != value or value < 0 or value > 1000:     # NaN, or silly
        return None, "A score has to be between 0 and 1000."
    return round(value, 2), ""


def _score_text(score):
    """8.0 → "8", 7.5 → "7.5", None → "". For pages and the score box."""
    if score is None:
        return ""
    return ("%g" % score)


def _is_synced(sub, total):
    """Whether Classroom has this grade. `total` is the score plus the
    points from the notes' questions (_total), which is what Sync sends."""
    return total is not None and sub.score_synced == total


@app.post("/api/assignment/<slug>/out-of")
def set_out_of(slug):
    """What the assignment is marked out of. Empty means not graded.

    Once posted to Classroom the points there are changed to match, in every
    class it went to, so the grades that go across mean the same thing on
    both sides. Clearing it is refused then: Classroom cannot take grades on
    work with no points, and the next Sync would fail in a way that never
    mentions why.
    """
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        posts = _posts(db, item)
        raw = (request.get_json(silent=True) or {}).get("out_of")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if posts:
                return jsonify(error="It's posted to Google Classroom, so it "
                                     "needs points."), 400
            item.out_of = None
            item.updated_at = accounts.now()
            db.commit()
            return jsonify(ok=True, out_of="")
        try:
            value = int(str(raw).strip())
        except ValueError:
            return jsonify(error="Points have to be a whole number."), 400
        if value < 1 or value > 1000:
            return jsonify(error="Points have to be between 1 and 1000."), 400

        stuck = []
        if posts and value != item.out_of:
            access, why = _classroom_token(db, user)
            for post in posts:
                status = 0
                if access:
                    status, _ = _google_api(
                        "PATCH", "%s/courses/%s/courseWork/%s" % (
                            CLASSROOM_API, post.course_id, post.work_id),
                        access, body={"maxPoints": value},
                        params={"updateMask": "maxPoints"})
                if status != 200:
                    stuck.append(post.course_name or "a class")
        note = ""
        if stuck:
            # Saved here anyway: the teacher's number is the truth, and saying
            # plainly which classes still have the old one is more use than
            # refusing to save it.
            note = ("Saved here, but Google Classroom still says %s points in %s. "
                    "Change it there too." % (item.out_of, ", ".join(stuck)))
        item.out_of = value
        item.updated_at = accounts.now()
        db.commit()
        return jsonify(ok=True, out_of=value, note=note)
    finally:
        db.close()


def _posts(db, item):
    """The Classroom classes this assignment was posted to, oldest first.

    Moves a post the first version wrote into the assignment's own columns
    into classroom_posts, once. Two workers may both try on the same
    request burst; the unique constraint lets one win, and the other's
    rollback leaves exactly the row the winner wrote.
    """
    if item.classroom_work_id:
        have = db.query(accounts.ClassroomPost).filter_by(
            assignment_id=item.id, course_id=item.classroom_course_id).first()
        if have is None:
            db.add(accounts.ClassroomPost(
                assignment_id=item.id, course_id=item.classroom_course_id,
                course_name=item.classroom_course_name,
                work_id=item.classroom_work_id, url=item.classroom_url))
        item.classroom_course_id = item.classroom_course_name = ""
        item.classroom_work_id = item.classroom_url = ""
        try:
            db.commit()
        except Exception:
            db.rollback()
    return (db.query(accounts.ClassroomPost)
              .filter_by(assignment_id=item.id)
              .order_by(accounts.ClassroomPost.posted_at,
                        accounts.ClassroomPost.id).all())


def _own_assignment(db, slug):
    """(user, assignment, None) for the teacher who set it, else a JSON
    error as the third item. Everything that changes an assignment's grading
    goes through here, so none of it can be reached by another teacher."""
    user = current_user(db)
    if user is None or not accounts.is_teacher(user.email):
        return None, None, (jsonify(error="Only the teacher can do that."), 403)
    item = db.query(accounts.Assignment).filter_by(
        slug=slug, app=APP_NAME).first()
    if item is None or item.teacher_id != user.id:
        return None, None, (jsonify(error="No such assignment."), 404)
    return user, item, None


@app.post("/api/assignment/<slug>/feedback")
def give_feedback(slug):
    """The teacher's comment on one student's turned-in work.

    Only the teacher who set the assignment, and only on a submission to it —
    the submission id comes from the page, so it is checked against the
    assignment rather than trusted. Saving an empty box takes the feedback
    back. Either way the student's "seen" is cleared, so changed feedback
    shows as New on their My work page again.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only the teacher can do that."), 403
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            return jsonify(error="No such assignment."), 404

        data = request.get_json(silent=True) or {}
        try:
            sub_id = int(data.get("submission"))
        except (TypeError, ValueError):
            return jsonify(error="No such submission."), 404
        sub = db.query(accounts.Submission).filter_by(
            id=sub_id, assignment_id=item.id).first()
        if sub is None:
            return jsonify(error="No such submission."), 404

        # NOT clean(): that folds every run of whitespace to one space, which
        # would flatten a comment's paragraphs and any code quoted in it.
        text = data.get("feedback", "")
        if not isinstance(text, str):
            return jsonify(error="That feedback could not be read."), 400
        text = text.strip()
        if len(text) > MAX_FEEDBACK:
            return jsonify(error="That's too long — keep it under %d characters."
                           % MAX_FEEDBACK), 413

        # The score rides along with the comment. Absent means leave it
        # alone, so a page from before scores cannot wipe one; empty means
        # take it back. NOT capped at out_of: extra credit is a thing, and
        # Classroom takes a grade above the points too.
        if "score" in data:
            score, why = _parse_score(data.get("score"))
            if why:
                return jsonify(error=why), 400
            sub.score = score

        sub.feedback = text
        # Stamped when there is anything for the student to read, a comment or
        # a score — it is what "turned in again since your feedback" compares
        # against, and a score alone is feedback too.
        has_any = bool(text) or sub.score is not None
        sub.feedback_at = accounts.now() if has_any else None
        sub.feedback_seen = 0
        db.commit()
        earned = _quiz_earned(db, item.id).get(sub.student_id)
        total = _total(sub.score, earned)
        return jsonify(ok=True, feedback=text, score=_score_text(sub.score),
                       total=_score_text(total),
                       synced=_is_synced(sub, total),
                       when=(sub.feedback_at.strftime("%b %d at %I:%M %p")
                             if sub.feedback_at else ""))
    finally:
        db.close()


@app.get("/teacher/<slug>")
def teacher_assignment(slug):
    db = SessionLocal()
    try:
        user, bounce = _require_teacher(db)
        if bounce:
            return bounce
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            abort(404)

        rows = (db.query(accounts.Submission, accounts.User)
                  .join(accounts.User,
                        accounts.Submission.student_id == accounts.User.id)
                  .filter(accounts.Submission.assignment_id == item.id)
                  .order_by(accounts.User.name).all())
        earned = _quiz_earned(db, item.id)
        possible = _quiz_possible(item)
        answers = _lesson_answers(db, item) if _is_lesson(item) else {}
        handed_in = [{
            "name": student.display_name(),
            "email": student.email,
            "when": sub.submitted_at.strftime("%b %d at %I:%M %p"),
            "times": sub.times_submitted,
            # A lesson's turn-in has no snapshot to open; its answers are
            # listed instead.
            "url": (url_for("view_shared", slug=sub.snippet_slug)
                    if sub.snippet_slug else ""),
            "answers": answers.get(student.id, []),
            "id": sub.id,
            "feedback": sub.feedback or "",
            "feedback_when": (sub.feedback_at.strftime("%b %d at %I:%M %p")
                              if sub.feedback_at else ""),
            "seen": bool(sub.feedback_seen),
            # Turning in again keeps the feedback (it is on this row, which a
            # re-submit updates in place), so the teacher needs telling that
            # what they commented on is no longer what is there.
            "again_since": bool(sub.feedback_at
                                and sub.submitted_at > sub.feedback_at),
            "score": _score_text(sub.score),
            "quiz": _score_text(earned.get(student.id)),
            "total": _score_text(_total(sub.score, earned.get(student.id))),
            "synced": _is_synced(sub, _total(sub.score, earned.get(student.id))),
        } for sub, student in rows]

        # Anyone who opened the assignment but never pressed Turn in.
        started = (db.query(accounts.User)
                     .join(accounts.Draft,
                           accounts.Draft.owner_id == accounts.User.id)
                     .filter(accounts.Draft.assignment_id == item.id,
                             accounts.Draft.owner_id != item.teacher_id).all())
        # And anyone who answered questions without ever saving a copy — in
        # a live lesson, say. Their points are real and would otherwise be on
        # no list at all.
        answerers = (db.query(accounts.User)
                       .filter(accounts.User.id.in_(list(earned)))
                       .all()) if earned else []
        done = {s["email"] for s in handed_in}
        not_yet = sorted(
            ({"name": u.display_name(), "quiz": _score_text(earned.get(u.id))}
             for u in {u.email: u for u in started + answerers
                       if u.email not in done and u.id != item.teacher_id
                       }.values()),
            key=lambda n: n["name"])

        ctx = user_context(db)
        ctx.update(posts=_posts(db, item))
        ctx.update(classroom_on=classroom_configured(),
                   classroom_connected=(classroom_configured()
                                        and _classroom_link(db, user) is not None))
        # The lesson's link, under the handout link, for posting ahead.
        lesson = _lesson_for(db, user, item)
        ctx.update(live_url=url_for("live_page", code=lesson.code,
                                    _external=True, _scheme=_scheme()),
                   live_on=not lesson.ended,
                   live_waiting=_waiting(lesson))
        ctx.update(quiz_count=len(possible),
                   quiz_points=_score_text(sum(q["points"] for q in possible)))
        ctx.update(assignment=item, handed_in=handed_in, not_yet=not_yet,
                   share_url=url_for("open_assignment", slug=item.slug,
                                     _external=True, _scheme=_scheme()))
        return render_template("teacher_assignment.html", **ctx)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Demo links — the running page, no source on display
# --------------------------------------------------------------------------
#
# The page still has to reach the browser to run, so this is not encryption
# and is not sold as such. What it removes is every ordinary way of reading
# the source: no editor on the page, no markup holding it, no /raw, no fork,
# no download. Recovering it means opening the network panel on purpose.

def load_demo(db, slug):
    proj = db.query(Project).filter_by(slug=slug).first()
    if proj is None or not proj.is_hidden:
        abort(404)
    return proj


@app.get("/d/<slug>")
def view_demo(slug):
    db = SessionLocal()
    try:
        proj = load_demo(db, slug)
        # Deliberately no file contents in this render: the page asks for them
        # separately, and only once Run is pressed.
        return render_template("demo.html", title=proj.title, slug=proj.slug)
    finally:
        db.close()


@app.get("/d/<slug>/source")
def demo_source(slug):
    """What the demo page fetches when Run is pressed."""
    db = SessionLocal()
    try:
        proj = load_demo(db, slug)
        response = jsonify(files=proj.file_map())
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    finally:
        db.close()


# --------------------------------------------------------------------------
# Google Classroom
#
# A teacher connects their Classroom once, from the dashboard, so FlaskIDE can
# later post an assignment there and send grades back. Teachers only:
# students never see a Classroom permission, and their sign-in stays the
# plain openid/email/profile it has always been.
#
# THIS IS ITS OWN OAUTH FLOW, NOT AUTHLIB'S. Sign-in asks for three harmless
# scopes from everyone; this asks for Classroom ones, from one person, with
# offline access so grades can be sent later without them present. Folding
# it into /auth/callback would put the Classroom consent screen in front of
# every student who signed in, or need a flag in the session to tell the two
# apart — and a stale flag would be a student account wired to Classroom.
#
# THE APP IS NOT VERIFIED BY GOOGLE, deliberately: verification needs a
# domain of our own, and this one is Render's. The teacher sees "Google
# hasn't verified this app" once, and clicks Advanced → Go to FlaskIDE. The
# scopes are "sensitive", not "restricted", so that is all it costs. If a
# school's admin blocks unverified apps, Google says so on its own page and
# sends the teacher back here with error=admin_policy_enforced, which
# /classroom/callback turns into a sentence about whom to ask.
#
# Every call to Google goes through _google_post or _google_get, so the tests
# replace those two and never touch the network.
# --------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CLASSROOM_API = "https://classroom.googleapis.com/v1"

#: Asked for all at once, though listing classes needs only the first, so
#: the teacher sees one consent screen and not another each time a feature
#: arrives. Posting work and grading it needs coursework.students; matching a
#: FlaskIDE student to a Classroom one by email needs rosters and profile.emails.
#: openid and email are there to learn WHICH Google account granted it.
CLASSROOM_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.profile.emails",
]

#: Asked for, but not required. Topics only fill the dropdown when posting;
#: without them an assignment posts with no topic, exactly as it did before
#: topics existed here. So a teacher who unticks this one on Google's screen
#: still connects, and a connection made before it was asked for still
#: posts and syncs — the dropdown just says how to turn topics on.
CLASSROOM_OPTIONAL_SCOPES = [
    "https://www.googleapis.com/auth/classroom.topics.readonly",
]


def classroom_configured():
    """Read at request time, not import, like nothing else here needs to be:
    the tests switch it on after app.py has loaded without authlib."""
    return bool(os.environ.get("GOOGLE_CLIENT_ID")
                and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _google_post(url, data):
    """POST a form to Google. Returns (status, json). Never raises."""
    import requests
    try:
        r = requests.post(url, data=data, timeout=15)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except Exception:
        return 0, {}


def _google_get(url, access_token, params=None):
    """GET from a Google API as the teacher. Returns (status, json)."""
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=15,
                         headers={"Authorization": "Bearer " + access_token})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except Exception:
        return 0, {}


def _google_api(method, url, access_token, body=None, params=None):
    """Any other call to a Google API as the teacher: JSON in, (status, json)
    out. Never raises. The third and last door to Google, replaced in tests
    with the other two."""
    import requests
    try:
        r = requests.request(method, url, json=body, params=params or {},
                             timeout=20,
                             headers={"Authorization": "Bearer " + access_token})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except Exception:
        return 0, {}


def _google_message(data, fallback):
    """Google's own explanation from an error reply, for the teacher only."""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict) and err.get("message"):
        return err["message"]
    return fallback


def _google_list(url, access_token, key, params=None):
    """Every page of a Classroom list. (items, status): status is that of the
    first page that failed, or 200. A class is rarely over a hundred, but a
    second page silently dropped would be students silently left ungraded."""
    items, token, params = [], None, dict(params or {}, pageSize=100)
    for _ in range(50):
        if token:
            params["pageToken"] = token
        status, data = _google_get(url, access_token, params)
        if status != 200:
            return items, status
        items.extend(data.get(key, []))
        token = data.get("nextPageToken")
        if not token:
            break
    return items, 200


def _token_box():
    """Encrypts stored refresh tokens. The key is derived from SECRET_KEY,
    which is in Render's environment and not the database — see
    ClassroomLink in accounts.py for what that buys and what it costs."""
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    digest = hashlib.sha256(("classroom-token:" + app.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _classroom_link(db, user):
    return db.query(accounts.ClassroomLink).filter_by(
        user_id=user.id, app=APP_NAME).first()


def _classroom_token(db, user):
    """A fresh access token for this teacher, or (None, why).

    A refresh token Google no longer honours — the teacher revoked it in
    their Google account, or an admin did — is DELETED here, so the dashboard
    goes back to offering Connect instead of failing the same way forever.
    One that can no longer be decrypted (SECRET_KEY changed) goes the same
    way, for the same reason.
    """
    link = _classroom_link(db, user)
    if link is None:
        return None, "not connected"
    try:
        refresh = _token_box().decrypt(link.refresh_token.encode()).decode()
    except Exception:
        db.delete(link)
        db.commit()
        return None, "Your Classroom connection needs renewing. Connect it again."
    status, data = _google_post(GOOGLE_TOKEN_URL, {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    })
    if status == 200 and data.get("access_token"):
        return data["access_token"], ""
    if data.get("error") == "invalid_grant":
        db.delete(link)
        db.commit()
        return None, ("Google no longer accepts FlaskIDE's connection to your "
                      "Classroom. Connect it again.")
    return None, "Couldn't reach Google just now. Try again in a moment."


def _require_classroom_teacher(db):
    """(user, None) for a teacher on a site with Google configured, else
    (None, response)."""
    if not classroom_configured():
        abort(404)
    user = current_user(db)
    if user is None:
        return None, redirect(url_for("login", next=url_for("teacher_home")))
    if not accounts.is_teacher(user.email):
        abort(404)
    return user, None


@app.get("/classroom/connect")
def classroom_connect():
    db = SessionLocal()
    try:
        user, bounce = _require_classroom_teacher(db)
        if bounce:
            return bounce
        # Ties Google's reply to this browser's request. Without it, a link
        # crafted by anyone could finish a connect flow in a teacher's
        # session with the attacker's own Google account.
        state = secrets.token_urlsafe(24)
        session["classroom_state"] = state
        from urllib.parse import urlencode
        return redirect(GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "redirect_uri": url_for("classroom_callback", _external=True,
                                    _scheme=_scheme()),
            "response_type": "code",
            "scope": " ".join(CLASSROOM_SCOPES + CLASSROOM_OPTIONAL_SCOPES),
            # offline: a refresh token, so grades can go later. consent: ask
            # every time, because Google only hands out a refresh token on a
            # consent screen, and a reconnect without one would store nothing.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            # The account picker opens on the school address they signed in
            # with, not whichever Google account the browser last used.
            "login_hint": user.email,
            "state": state,
        }))
    finally:
        db.close()


#: What Google's ?error= means, in words a teacher can act on.
CLASSROOM_ERRORS = {
    "access_denied": "You didn't allow FlaskIDE to use your Classroom, so "
                     "nothing was connected.",
    "admin_policy_enforced": "Your school's Google admin doesn't allow this "
                             "app to use Google Classroom. Ask your IT "
                             "department to allow it.",
}


def _classroom_problem(reason, status=400):
    return render_template("signin_problem.html", reason=reason,
                           classroom=True), status


@app.get("/classroom/callback")
def classroom_callback():
    db = SessionLocal()
    try:
        user, bounce = _require_classroom_teacher(db)
        if bounce:
            return bounce
        expected = session.pop("classroom_state", None)
        if not expected or request.args.get("state") != expected:
            return _classroom_problem("That Classroom connection didn't come "
                                      "from this page. Start it again from "
                                      "your dashboard.")
        error = request.args.get("error")
        if error:
            return _classroom_problem(CLASSROOM_ERRORS.get(
                error, "Google didn't connect your Classroom (%s)." % error))

        status, data = _google_post(GOOGLE_TOKEN_URL, {
            "code": request.args.get("code", ""),
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": url_for("classroom_callback", _external=True,
                                    _scheme=_scheme()),
            "grant_type": "authorization_code",
        })
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if status != 200 or not access or not refresh:
            return _classroom_problem("Google didn't finish connecting your "
                                      "Classroom. Try again.")

        def give_back():
            _google_post(GOOGLE_REVOKE_URL, {"token": refresh})

        # Google's consent screen has a tick box per permission, and a
        # teacher can untick some. Storing a half-granted token would fail
        # later, at the moment grades are sent, with an error nobody could
        # trace back to this screen. So it is refused now, and said why.
        granted = set((data.get("scope") or "").split())
        missing = [s for s in CLASSROOM_SCOPES if s.startswith("https://")
                   and s not in granted]
        if missing:
            give_back()
            return _classroom_problem(
                "FlaskIDE needs every Classroom permission on that screen to "
                "post assignments and send grades. Connect again and leave "
                "all the boxes ticked.")

        # The school account, not a personal one picked by mistake from the
        # account chooser: grades must go to the classes this teacher signed
        # in to FlaskIDE as the teacher of.
        status, info = _google_get(GOOGLE_USERINFO_URL, access)
        google_email = (info.get("email") or "").strip()
        if status != 200 or google_email.lower() != user.email.lower():
            give_back()
            return _classroom_problem(
                "You connected %s, but you're signed in to FlaskIDE as %s. "
                "Connect again and choose %s."
                % (google_email or "a different Google account", user.email,
                   user.email))

        link = _classroom_link(db, user)
        if link is None:
            link = accounts.ClassroomLink(user_id=user.id, app=APP_NAME,
                                          refresh_token="")
            db.add(link)
        link.refresh_token = _token_box().encrypt(refresh.encode()).decode()
        link.google_email = google_email
        link.connected_at = accounts.now()
        db.commit()
        return redirect(url_for("teacher_home", classroom="connected"))
    finally:
        db.close()


@app.post("/classroom/disconnect")
def classroom_disconnect():
    db = SessionLocal()
    try:
        user, bounce = _require_classroom_teacher(db)
        if bounce:
            return bounce
        link = _classroom_link(db, user)
        if link is not None:
            # Revoked at Google as well as forgotten here, so disconnecting
            # really does withdraw the permission rather than just hiding it.
            try:
                refresh = _token_box().decrypt(link.refresh_token.encode()).decode()
                _google_post(GOOGLE_REVOKE_URL, {"token": refresh})
            except Exception:
                pass
            db.delete(link)
            db.commit()
        return redirect(url_for("teacher_home"))
    finally:
        db.close()


@app.get("/api/classroom/courses")
def classroom_courses():
    """The teacher's active classes. Fetched by the dashboard after it has
    loaded, so a slow or unreachable Google never holds the page up."""
    db = SessionLocal()
    try:
        if not classroom_configured():
            abort(404)
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can do that."), 403
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why, connected=_classroom_link(db, user) is not None), 409
        status, data = _google_get(CLASSROOM_API + "/courses", access, {
            "teacherId": "me", "courseStates": "ACTIVE", "pageSize": 100})
        if status != 200:
            # Google's own words, shown to the teacher only. The likeliest
            # one is "Classroom API has not been used in project … or it is
            # disabled", which is a switch in the Cloud console — and saying
            # so beats any paraphrase of it.
            message = ((data.get("error") or {}).get("message")
                       if isinstance(data.get("error"), dict) else "")
            return jsonify(error=message or "Google wouldn't list your classes."), 502
        return jsonify(courses=[{
            "id": c.get("id", ""),
            "name": c.get("name", ""),
            "section": c.get("section", ""),
            "url": c.get("alternateLink", ""),
        } for c in data.get("courses", [])])
    finally:
        db.close()


@app.get("/api/classroom/courses/<course_id>/topics")
def classroom_topics(course_id):
    """One class's topics, for the dropdown that appears once a class is
    chosen. `reconnect` when Google refuses for want of the topics
    permission — a connection made before it was asked for, or with its box
    unticked — so the page can say what to do instead of showing nothing."""
    db = SessionLocal()
    try:
        if not classroom_configured():
            abort(404)
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can do that."), 403
        if not re.fullmatch(r"[0-9]{1,30}", course_id or ""):
            return jsonify(error="No such class."), 400
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        topics, status = _google_list(
            "%s/courses/%s/topics" % (CLASSROOM_API, course_id), access, "topic")
        if status == 403:
            return jsonify(topics=[], reconnect=True,
                           connect_url=url_for("classroom_connect"))
        if status != 200:
            return jsonify(error="Google wouldn't list that class's topics."), 502
        return jsonify(topics=[{"id": str(t.get("topicId", "")),
                                "name": t.get("name", "")} for t in topics
                               if t.get("topicId")])
    finally:
        db.close()


@app.post("/api/assignment/<slug>/classroom/post")
def classroom_post(slug):
    """Create this assignment in one of the teacher's Classroom classes.

    Google only lets an app grade coursework the app created, so this is not
    a convenience: without it, Sync has nothing it is allowed to write to.
    The Classroom assignment carries the /a/<slug> link, so a student opens
    it from Classroom and lands in their own copy, as from any handout link.

    Once per CLASS, and as many classes as do the work: Period 4 and Period 7
    on the same link each get their own Classroom assignment, which is what
    lets each period's grades go to that period. A second post to the same
    class is refused — the class would see two of everything.

    `draft` posts it as a Classroom draft: the link exists in PyIDE now, and
    the teacher assigns it from Classroom whenever they're ready. Assigning
    it there does not change whose it is — Google still counts it as this
    app's, so Sync can grade it afterwards. A page from before the box
    existed sends no `draft`, and gets what it always got: published.

    `topic` is a topic id from that class (classroom_topics), or nothing
    for none. Google refuses one that is not the class's, and says so.

    `link` is which link the class is given: "assignment" (the default, and
    what a page from before the choice gets) or "live", the lesson's link
    from the assignment page (_lesson_for), for work done in a live lesson.
    Either way it is this assignment's: work turned in from the lesson goes
    to the assignment, so Sync grades it the same.
    """
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not item.out_of:
            return jsonify(error="Set what it's out of first — Classroom only "
                                 "takes grades on work with points."), 400
        asked = request.get_json(silent=True) or {}
        course_id = str(asked.get("course") or "")
        if not re.fullmatch(r"[0-9]{1,30}", course_id):
            return jsonify(error="Choose a class."), 400
        topic = str(asked.get("topic") or "")
        if topic and not re.fullmatch(r"[0-9A-Za-z_-]{1,40}", topic):
            return jsonify(error="That isn't one of the class's topics."), 400
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        # Already posted there — unless the Classroom assignment has since been
        # deleted in Classroom, which is the usual reason to post again. Then
        # the old record is forgotten and this posts fresh, rather than refusing
        # with "already posted" about something that no longer exists.
        already = [p for p in _posts(db, item) if p.course_id == course_id]
        if already:
            status, _ = _google_get("%s/courses/%s/courseWork/%s" % (
                CLASSROOM_API, course_id, already[0].work_id), access)
            if status != 404:
                return jsonify(error="It's already posted to %s. If you deleted it "
                                     "in Classroom, use Unlink first."
                               % (already[0].course_name or "that class")), 409
            _forget_post(db, item, already[0])

        # Asked of Google rather than trusted from the page: the class's name
        # for the dashboard, and proof that this teacher teaches it.
        status, course = _google_get("%s/courses/%s" % (CLASSROOM_API, course_id),
                                     access)
        if status != 200:
            return jsonify(error=_google_message(course, "Google couldn't find "
                                                 "that class.")), 502

        live = asked.get("link") == "live"
        if live:
            link = url_for("live_page", code=_lesson_for(db, user, item).code,
                           _external=True, _scheme=_scheme())
            how = ("Open it to follow the lesson live in %s, and sign in with "
                   "your school account. Press Turn in there when you're done.")
        else:
            link = url_for("open_assignment", slug=item.slug, _external=True,
                           _scheme=_scheme())
            how = ("Open it in %s and sign in with your school account. "
                   "Press Turn in there when you're done.")
        status, work = _google_api(
            "POST", "%s/courses/%s/courseWork" % (CLASSROOM_API, course_id), access,
            body={
                "title": item.title,
                "description": how % "FlaskIDE",
                "materials": [{"link": {"url": link}}],
                "workType": "ASSIGNMENT",
                "state": "DRAFT" if asked.get("draft") is True else "PUBLISHED",
                "maxPoints": item.out_of,
                **({"topicId": topic} if topic else {}),
            })
        if status != 200 or not work.get("id"):
            return jsonify(error=_google_message(work, "Google wouldn't create "
                                                 "the assignment.")), 502

        post = accounts.ClassroomPost(
            assignment_id=item.id, course_id=course_id,
            course_name=(course.get("name") or "")[:200],
            work_id=str(work["id"])[:32],
            url=(work.get("alternateLink") or "")[:300])
        db.add(post)
        item.updated_at = accounts.now()
        db.commit()
        return jsonify(ok=True, course=post.course_name, url=post.url,
                       draft=asked.get("draft") is True,
                       link="live" if live else "assignment", topic=topic)
    finally:
        db.close()


def _forget_post(db, item, post):
    """Stop treating `post` as where this assignment's grades go.

    Only the record here goes: the assignment, its code and notes, every
    student's work and score stay, and nothing in Google Classroom is
    touched. Every score is marked not yet in Classroom, because the
    "✓ in Classroom" it had meant the coursework just forgotten — and a
    re-post to the same class is new coursework, which has none of them.
    The next Sync sends them all again; a class still posted gets the same
    numbers it already has, which changes nothing there."""
    db.delete(post)
    (db.query(accounts.Submission).filter_by(assignment_id=item.id)
       .update({"score_synced": None}, synchronize_session=False))
    item.updated_at = accounts.now()        # a change in Classroom standing
    db.commit()


def _class_lists(db, item, access):
    """Ask Classroom, for every class this assignment was posted to, who is in
    it and which Classroom submission is theirs.

    Returns (classes, gone, drafts, error). `classes` is a list of
    (post, {email: classroom submission id or None}), in posting order.
    `gone` names classes whose Classroom assignment was deleted there; their
    posts are forgotten here, so the page offers Post again rather than
    failing that way on every press. `drafts` holds the posts that are still
    a draft in Classroom — posted ahead of time and not assigned yet. Their
    roster is still listed, so the period tabs work, but every submission id
    is None: a draft has no submissions to grade, and a student in one is
    waiting on the teacher, not missing from the class. `error` is set when
    Google would not answer at all, and then nothing else should be trusted.

    The state is asked of Google every time rather than remembered, because
    the teacher assigns a draft in Classroom and nothing tells us when.
    """
    classes, gone, drafts = [], [], set()
    for post in _posts(db, item):
        base = "%s/courses/%s" % (CLASSROOM_API, post.course_id)
        status, work = _google_get("%s/courseWork/%s" % (base, post.work_id), access)
        if status == 404:
            gone.append(post.course_name or "a class")
            _forget_post(db, item, post)
            continue
        if status != 200:
            return [], [], set(), ("Google wouldn't say how the assignment "
                                   "stands in %s." % (post.course_name or "a class"))
        roster, status = _google_list(base + "/students", access, "students")
        if status != 200:
            return [], [], set(), ("Google wouldn't list the students in %s."
                                   % (post.course_name or "a class"))
        # A scheduled post is a DRAFT too until its time comes, which is what
        # we want: there is nothing to grade in either.
        if work.get("state") == "DRAFT":
            drafts.add(post.id)
            subs = []
        else:
            subs, status = _google_list(
                "%s/courseWork/%s/studentSubmissions" % (base, post.work_id),
                access, "studentSubmissions")
            if status != 200:
                return [], [], set(), ("Google wouldn't list the submissions in %s."
                                       % (post.course_name or "a class"))
        by_user = {s.get("userId"): s.get("id") for s in subs}
        emails = {}
        for st in roster:
            email = ((st.get("profile") or {}).get("emailAddress") or "").lower()
            if email:
                emails[email] = by_user.get(st.get("userId"))
        classes.append((post, emails))
    return classes, gone, drafts, ""


@app.post("/api/assignment/<slug>/classroom/unlink")
def classroom_unlink(slug):
    """Forget one class this assignment was posted to (_forget_post): for a
    Classroom assignment deleted, or no longer wanted, in Classroom. The
    assignment itself, and everything students did, is untouched, so it
    can be posted to that class again, or to another."""
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        try:
            post_id = int((request.get_json(silent=True) or {}).get("post"))
        except (TypeError, ValueError):
            return jsonify(error="No such class."), 404
        post = db.query(accounts.ClassroomPost).filter_by(
            id=post_id, assignment_id=item.id).first()
        if post is None:
            return jsonify(error="No such class."), 404
        name = post.course_name or "that class"
        _forget_post(db, item, post)
        return jsonify(ok=True, course=name, left=len(_posts(db, item)))
    finally:
        db.close()


def _post_state(work):
    """"draft", "scheduled" or "posted", from Google's courseWork. A scheduled
    post is a DRAFT with a scheduledTime: Google assigns it at that time."""
    if work.get("state") != "DRAFT":
        return "posted"
    return "scheduled" if work.get("scheduledTime") else "draft"


@app.get("/api/assignment/<slug>/classroom/states")
def classroom_states(slug):
    """Whether each class's Classroom assignment is still a draft, so the
    page can offer Post now beside it. Asked of Google every time, like
    _class_lists, because the teacher may assign it in Classroom and
    nothing tells us. Fetched after the page loads, for the same reason
    as classroom_periods: Google is slow."""
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not _posts(db, item):
            return jsonify(states=[], gone=[])
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        states, gone = [], []
        for post in _posts(db, item):
            status, work = _google_get("%s/courses/%s/courseWork/%s" % (
                CLASSROOM_API, post.course_id, post.work_id), access)
            if status == 404:
                gone.append(post.course_name or "a class")
                _forget_post(db, item, post)
                continue
            if status != 200:
                # Said, not skipped: a class showing nothing at all reads as
                # "assigned" to the teacher, and that is exactly what we
                # don't know. Google's reason goes with it.
                states.append({"id": post.id, "state": "unknown",
                               "why": _google_message(work, "Google didn't answer.")})
                continue
            states.append({"id": post.id, "state": _post_state(work)})
        return jsonify(states=states, gone=gone)
    finally:
        db.close()


@app.post("/api/assignment/<slug>/classroom/publish")
def classroom_publish(slug):
    """Assign a class's Classroom draft now: Post now on the assignment page.

    ONE WAY ONLY. Google lets an app move its own coursework from DRAFT to
    PUBLISHED and refuses the reverse to everyone, so there is no "back to
    draft" here to offer. It works at all only because PyIDE created the
    coursework (classroom_post) — Google refuses any app's edits to
    coursework another made, which is the same rule Sync lives by.

    A scheduled post is a DRAFT with a time on it; this assigns it now
    rather than at that time, and the page says so before asking.
    """
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        try:
            post_id = int((request.get_json(silent=True) or {}).get("post"))
        except (TypeError, ValueError):
            return jsonify(error="No such class."), 404
        post = db.query(accounts.ClassroomPost).filter_by(
            id=post_id, assignment_id=item.id).first()
        if post is None:
            return jsonify(error="No such class."), 404
        name = post.course_name or "that class"
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        url = "%s/courses/%s/courseWork/%s" % (CLASSROOM_API, post.course_id,
                                              post.work_id)
        status, work = _google_get(url, access)
        if status == 404:
            _forget_post(db, item, post)
            return jsonify(error="It was deleted in Google Classroom, so PyIDE "
                                 "has forgotten %s. Post it again if you want it "
                                 "there." % name, gone=True), 409
        if status != 200:
            return jsonify(error=_google_message(work, "Google wouldn't say how "
                                                 "the assignment stands.")), 502
        # Already assigned — in Classroom, or by another tab. Nothing to do,
        # and saying it worked is the truth.
        if work.get("state") != "DRAFT":
            return jsonify(ok=True, course=name, already=True)
        status, work = _google_api("PATCH", url, access,
                                   body={"state": "PUBLISHED"},
                                   params={"updateMask": "state"})
        if status != 200:
            return jsonify(error=_google_message(work, "Google wouldn't assign "
                                                 "it.")), 502
        item.updated_at = accounts.now()
        db.commit()
        return jsonify(ok=True, course=name, already=False)
    finally:
        db.close()


@app.get("/api/assignment/<slug>/classroom/periods")
def classroom_periods(slug):
    """Which posted class each student is in, so the results page can show
    Period 4 and Period 7 apart. Fetched by the page after it loads: Google
    is slow by page-load standards, and a page that waited on it would be a
    page that sometimes never arrived."""
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not _posts(db, item):
            return jsonify(classes=[], by_student={})
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        classes, gone, _, error = _class_lists(db, item, access)
        if error:
            return jsonify(error=error), 502
        rows = (db.query(accounts.Submission, accounts.User)
                  .join(accounts.User, accounts.Submission.student_id == accounts.User.id)
                  .filter(accounts.Submission.assignment_id == item.id).all())
        by_student = {}
        for sub, student in rows:
            for post, emails in classes:
                if student.email.lower() in emails:
                    by_student[sub.id] = post.id
                    break
        return jsonify(classes=[{"id": p.id, "name": p.course_name or "A class"}
                                for p, _ in classes],
                       by_student=by_student, gone=gone)
    finally:
        db.close()


@app.post("/api/assignment/<slug>/classroom/sync")
def classroom_sync(slug):
    """Send every score to Classroom as a DRAFT grade, each to the class the
    student is in.

    Draft, not assigned: the teacher still sees them in Classroom before the
    class does, and returns them there. A FlaskIDE student is matched to a
    Classroom one by email, which is why the school account matters — a
    student who did the work signed in as someone else cannot be matched,
    and is named in the reply rather than skipped in silence.
    """
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not _posts(db, item):
            return jsonify(error="Post it to Google Classroom first."), 400
        access, why = _classroom_token(db, user)
        if access is None:
            return jsonify(error=why), 409
        classes, gone, drafts, error = _class_lists(db, item, access)
        if error:
            return jsonify(error=error), 502
        if not classes:
            return jsonify(error="That assignment is gone from Google Classroom "
                                 "(%s). Post it again." % ", ".join(gone),
                           gone=True), 409

        rows = (db.query(accounts.Submission, accounts.User)
                  .join(accounts.User, accounts.Submission.student_id == accounts.User.id)
                  .filter(accounts.Submission.assignment_id == item.id).all())
        sent, unmatched, failed = 0, [], []
        waiting = [p.course_name or "a class" for p, _ in classes if p.id in drafts]
        # What goes across is the score PLUS the questions' points, and a
        # student with no score yet but answers given still has a grade.
        earned = _quiz_earned(db, item.id)
        totals = {sub.id: _total(sub.score, earned.get(sub.student_id))
                  for sub, _ in rows}
        for sub, student in rows:
            if totals[sub.id] is None:
                continue
            target, held = None, False
            for post, emails in classes:
                email = student.email.lower()
                if post.id in drafts and email in emails:
                    held = True      # named once, by class, in `waiting`
                    break
                cid = emails.get(email)
                if cid:
                    target = (post, cid)
                    break
            if held:
                continue
            if target is None:
                unmatched.append(student.display_name() or student.email)
                continue
            post, cid = target
            status, data = _google_api(
                "PATCH", "%s/courses/%s/courseWork/%s/studentSubmissions/%s" % (
                    CLASSROOM_API, post.course_id, post.work_id, cid),
                access, body={"draftGrade": totals[sub.id]},
                params={"updateMask": "draftGrade"})
            if status == 200:
                sub.score_synced = totals[sub.id]
                sent += 1
            else:
                failed.append("%s (%s)" % (student.display_name() or student.email,
                                           _google_message(data, "refused")))
        db.commit()
        return jsonify(ok=True, sent=sent, unmatched=unmatched, failed=failed,
                       gone=gone, waiting=waiting, synced=[s.id for s, _ in rows
                               if _is_synced(s, totals[s.id])])
    finally:
        db.close()


# --------------------------------------------------------------------------
# Skyward
#
# Skyward's gradebook takes scores from a file: Assignment Import, template
# "Import Scores and Create Assignments", seven columns and no header row —
#
#     last name, first name, assignment, due date (MMDDYYYY), category,
#     max score, score
#
# It matches a student on the two names alone, against the class picked on
# its own import screen. A row it can't match is refused on its own ("Unable
# to find a matching student") and the rest still go in, which is what makes
# a guessed name safe to send: the worst case is one student left for the
# teacher to type, named in Skyward's preview before anything is saved.
# --------------------------------------------------------------------------

#: What a category code may look like. Skyward's are short codes the
#: district sets per class (N, Prj, Q); anything longer is a typo or a
#: description pasted in by mistake, and would make every row fail.
SKYWARD_CATEGORY = re.compile(r"^[A-Za-z0-9]{1,10}$")


def _split_name(full):
    """(first, last) guessed from one full name: the last word is the last
    name. Wrong for "Ana De La Cruz", which is why it is only a fallback and
    the student is named as guessed."""
    words = (full or "").split()
    if len(words) < 2:
        return "", ""
    return " ".join(words[:-1]), words[-1]


@app.post("/api/assignment/<slug>/skyward")
def skyward_file(slug):
    """The scores as a Skyward import file, with what the teacher should know
    before using it. Returned as JSON (the page saves `csv` as a file) so an
    error, or a list of guessed names, can be shown rather than downloaded.

    `post` narrows it to one Classroom class: Skyward imports into one class
    section at a time, and every other section's students would come back as
    unmatched rows. That class's roster also fills in first and last names
    for students who haven't signed in since names were kept, and keeps
    them, so the next file needs no Google at all.
    """
    import csv
    import io

    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        if not item.out_of:
            return jsonify(error="Set what it's out of first — Skyward needs "
                                 "a max score."), 400
        data = request.get_json(silent=True) or {}
        category = (data.get("category") or "").strip()
        if not SKYWARD_CATEGORY.match(category):
            return jsonify(error="Type the category code Skyward uses for this "
                                 "class, like N, Prj or Q."), 400
        try:
            due = datetime.strptime(str(data.get("due") or ""), "%Y-%m-%d")
        except ValueError:
            return jsonify(error="Pick a due date."), 400

        roster = None              # {email: (first, last)} for one class
        wanted = data.get("post")
        if wanted:
            post = next((p for p in _posts(db, item) if str(p.id) == str(wanted)),
                        None)
            if post is None:
                return jsonify(error="That class isn't one this was posted to."), 400
            access, why = _classroom_token(db, user)
            if access is None:
                return jsonify(error=why), 409
            people, status = _google_list(
                "%s/courses/%s/students" % (CLASSROOM_API, post.course_id),
                access, "students")
            if status != 200:
                return jsonify(error="Google wouldn't list the students in %s."
                                     % (post.course_name or "that class")), 502
            roster = {}
            for st in people:
                prof = st.get("profile") or {}
                email = (prof.get("emailAddress") or "").lower()
                name = prof.get("name") or {}
                if email:
                    roster[email] = ((name.get("givenName") or "").strip(),
                                     (name.get("familyName") or "").strip())

        rows = (db.query(accounts.Submission, accounts.User)
                  .join(accounts.User, accounts.Submission.student_id == accounts.User.id)
                  .filter(accounts.Submission.assignment_id == item.id).all())
        earned = _quiz_earned(db, item.id)
        lines, guessed, ungraded, nameless = [], [], [], []
        for sub, student in rows:
            email = student.email.lower()
            if roster is not None and email not in roster:
                continue                   # another section's student
            total = _total(sub.score, earned.get(sub.student_id))
            if total is None:
                ungraded.append(student.display_name())
                continue
            first, last = student.first_name, student.last_name
            if not (first and last) and roster and all(roster[email]):
                first, last = roster[email]
                student.first_name, student.last_name = first[:80], last[:80]
            if not (first and last):
                first, last = _split_name(student.name)
                if not (first and last):
                    nameless.append(student.display_name())
                    continue               # nothing to match on at all
                guessed.append(student.display_name())
            lines.append([last, first, item.title, due.strftime("%m%d%Y"),
                          category, item.out_of, _score_text(total)])
        db.commit()                        # names learned from the roster

        lines.sort(key=lambda r: (r[0].lower(), r[1].lower()))
        out = io.StringIO()
        csv.writer(out, lineterminator="\r\n").writerows(lines)
        return jsonify(csv=out.getvalue(), count=len(lines),
                       guessed=sorted(guessed), ungraded=sorted(ungraded),
                       nameless=sorted(nameless),
                       filename=_safe_filename(item.title) + " - Skyward.csv")
    finally:
        db.close()


def _safe_filename(title):
    """A title as a file name every OS will save."""
    return re.sub(r'[\\/:*?"<>|]+', "-", title).strip(" .-") or "assignment"


# --------------------------------------------------------------------------
# Teaching live
#
# The teacher presses Go live in their ordinary editor and keeps working the
# way they always do — tabs, notes, Run. Every few hundred milliseconds the
# current file is written to one row. Students open /live/<code>, watch that
# row appear above them, and type their own copy underneath.
#
# THE STUDENT'S OWN EDITOR IS NEVER WRITTEN TO FROM THE WIRE. Nothing that
# arrives from a poll can reach it: the mirror and the student's editor are
# two CodeMirror instances and only the mirror is ever given text. A class
# losing a paragraph of their own work because the teacher typed is the one
# failure that would stop anyone using this twice, so it is arranged to be
# impossible rather than avoided carefully.
#
# There is deliberately no button that copies the teacher's code into the
# student's editor. Typing it is the exercise.
# --------------------------------------------------------------------------

#: How stale a session can get before it is swept. A lesson is an hour; a row
#: still being pushed to is never touched, however old.
LIVE_STALE_HOURS = 12


def _live_now():
    return datetime.now(timezone.utc)


def _find_live(db, code):
    return db.query(accounts.LiveSession).filter_by(
        code=(code or "").strip().lower(), app=APP_NAME).first()


@app.get("/api/live/assignments")
def live_assignments():
    """The teacher's open assignments, for the chooser on Go live.

    Picking one is what makes Turn in possible for the class, so this is not
    decoration: a lesson with no assignment is a lesson nobody can hand
    anything in from.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can start a live lesson."), 403
        rows = (db.query(accounts.Assignment)
                  .filter_by(teacher_id=user.id, app=APP_NAME,
                             archived=0, closed=0)
                  .filter(accounts.Assignment.kind != "lesson")
                  .order_by(func.coalesce(accounts.Assignment.updated_at,
                                          accounts.Assignment.created_at).desc())
                  .limit(40).all())
        return jsonify(assignments=[{"slug": a.slug, "title": a.title}
                                    for a in rows])
    finally:
        db.close()


@app.get("/api/live/assignment/<slug>")
def live_assignment_starter(slug):
    """One assignment's starter, for opening it in the editor on Go live.

    Separate from the list above on purpose: the list is shown every time
    Go live is pressed and is only titles, while this is fetched once and
    only if the teacher says yes to loading it. Sending every starter with
    the list would be up to a few megabytes for a chooser most of which is
    never read.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can do that."), 403
        item, why = _assignment_for(db, user, clean(slug, 16))
        if why or item is None:
            return jsonify(error=why or "No such assignment."), 404
        return jsonify(title=item.title, files=item.file_map())
    finally:
        db.close()


def _assignment_for(db, user, slug):
    """The teacher's own assignment by slug, or (None, reason).

    Checked against teacher_id rather than just the teacher list, so one
    teacher cannot attach a lesson to another's assignment and collect their
    class's work.
    """
    if not slug:
        return None, None
    item = db.query(accounts.Assignment).filter_by(
        slug=slug, app=APP_NAME).first()
    if item is None:
        return None, "No assignment with that link."
    if item.teacher_id != user.id:
        return None, "That is not your assignment."
    if item.closed:
        return None, "That assignment is closed, so nothing could be "\
                     "turned in to it."
    return item, None


def _slug_of_assignment(db, assignment_id):
    if not assignment_id:
        return ""
    row = db.query(accounts.Assignment).filter_by(id=assignment_id).first()
    return row.slug if row else ""


def _title_of_assignment(db, assignment_id):
    if not assignment_id:
        return ""
    row = db.query(accounts.Assignment).filter_by(id=assignment_id).first()
    return row.title if row else ""


def _lesson_for(db, user, item):
    """The live lesson for this assignment, made now if it has none.

    MADE AHEAD, NOT STARTED. A teacher posts the lesson's link in Google
    Classroom the day before, so the link has to exist before the lesson
    does. It is made ended, with version 0 — "not started yet" (see
    _waiting) — and comes on the air the ordinary way: the teacher opens
    it and presses Teach, which reopens this row under the same code.

    The newest lesson already held for the assignment is reused rather than
    a new one made, because the link a class has is the one that must keep
    working (the same rule as Teach this lesson again).
    """
    live = (db.query(accounts.LiveSession)
              .filter_by(host_id=user.id, app=APP_NAME, assignment_id=item.id)
              .order_by(accounts.LiveSession.started_at.desc(),
                        accounts.LiveSession.id.desc()).first())
    if live is None:
        live = accounts.LiveSession(
            code=accounts.new_id(db, accounts.LiveSession, "code"),
            app=APP_NAME, host_id=user.id, host_name=user.display_name(),
            title=item.title, body="", filename="main.py", version=0,
            assignment_id=item.id, ended=1)
        db.add(live)
        db.commit()
    return live


@app.post("/api/assignment/<slug>/live/reset")
def reset_live(slug):
    """Forget what this assignment's lesson last had on screen — its code,
    output and slide — keeping its link, so teaching it again starts from
    the assignment's own starter rather than where the last lesson ended.

    For a lesson that ended in the wrong place, and for the ones the old Go
    live relabelled (see live_start), which hold another assignment's code
    and look, from here, exactly like any other taught lesson."""
    db = SessionLocal()
    try:
        user, item, bounce = _own_assignment(db, slug)
        if bounce:
            return bounce
        live = _lesson_for(db, user, item)
        if not live.ended:
            return jsonify(error="It's live now. End the lesson first."), 409
        live.body = ""
        live.output = ""
        live.cursor = ""
        live.slide = ""
        live.snippet = ""
        live.filename = "main.py"
        db.commit()
        return jsonify(ok=True)
    finally:
        db.close()


def _waiting(live):
    """Made ahead and never taught: ended, with nothing ever pushed. Its
    class is told it has not started, and their page keeps checking, rather
    than being told a lesson that has not happened is over."""
    return bool(live.ended) and not live.version


@app.get("/teacher/<slug>/live")
def teach_assignment_live(slug):
    """Go live on an assignment, from the dashboard: its lesson, made if
    need be, opened in the editor the way Teach this lesson again opens it —
    the starter loaded and the lesson's own code put back on the air."""
    db = SessionLocal()
    try:
        user, bounce = _require_teacher(db)
        if bounce:
            return bounce
        item = db.query(accounts.Assignment).filter_by(
            slug=slug, app=APP_NAME).first()
        if item is None or item.teacher_id != user.id:
            abort(404)
        if _is_lesson(item):
            return redirect(url_for("edit_lesson", slug=item.slug, go="live"))
        live = _lesson_for(db, user, item)
        return redirect(url_for("index", teach=live.code, a=item.slug))
    finally:
        db.close()


@app.post("/api/live/start")
def live_start():
    """Open a session, or hand back the one already running.

    Reusing the open one matters: pressing Go live after a reload should put
    the same code back on the projector, not invent a second one that half
    the class is not looking at.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None or not accounts.is_teacher(user.email):
            return jsonify(error="Only a teacher can start a live lesson."), 403

        data = request.get_json(silent=True) or {}
        body = data.get("body")
        if not isinstance(body, str):
            body = ""
        if len(body.encode("utf-8")) > MAX_FILE_BYTES:
            return jsonify(error="That file is too large to share live."), 413

        wanted = clean(data.get("assignment"), 16)
        item, why = _assignment_for(db, user, wanted)
        if why:
            return jsonify(error=why), 400
        # The first file can be the notes, answer keys and all.
        if quiz.is_notes(data.get("filename")):
            body = quiz.redact(body)

        live = (db.query(accounts.LiveSession)
                  .filter_by(host_id=user.id, app=APP_NAME, ended=0)
                  .order_by(accounts.LiveSession.started_at.desc()).first())

        # A RESUME ONLY EVER REATTACHES. The editor remembers the lesson it
        # was broadcasting so a reload carries on, and used to resume by
        # calling this route like a fresh Go live — so when that lesson had
        # ended (or been swept), a teacher who merely opened the editor was
        # put on their class's screens in a brand-new lesson they never
        # started. It showed up as "sign in and I'm live". Now a resume names
        # the lesson it means, and gets that one, still open, or nothing.
        resume = clean(data.get("resume"), 16)
        if resume and (live is None or live.code != resume):
            return jsonify(resumed=False)

        # REOPENING YESTERDAY'S LESSON. Only ever on the teacher's say-so: they
        # open the lesson's own link, press "Teach this lesson again" there
        # (live.html, as the host), and the editor sends its code here. Never
        # on a resume — that is the "sign in and I'm live" bug above, coming
        # back by a different door. Same row, same code, so the link the class
        # bookmarked works again, and their browsers still hold yesterday's
        # typing under that code.
        reopen = clean(data.get("reopen"), 16)
        if reopen:
            old = _find_live(db, reopen)
            if old is None or old.host_id != user.id:
                return jsonify(error="That lesson isn't one of yours."), 404
            # One open lesson per teacher, always. `live` above is "the newest
            # open one", so a second open row would quietly win every later
            # Go live and reload over the lesson the class is looking at.
            (db.query(accounts.LiveSession)
               .filter(accounts.LiveSession.host_id == user.id,
                       accounts.LiveSession.app == APP_NAME,
                       accounts.LiveSession.ended == 0,
                       accounts.LiveSession.id != old.id)
               .update({"ended": 1, "updated_at": _live_now()},
                       synchronize_session=False))
            old.ended = 0
            live = old

        # GO LIVE ON A DIFFERENT ASSIGNMENT ends the lesson still open. It
        # used to carry on in it and only relabel it with the new assignment,
        # so the row kept the OLD assignment's code under the NEW one's name:
        # from then on that was the new assignment's live lesson, its link
        # said "Teach this lesson again", and teaching it loaded the right
        # notes with the other assignment's code. A lesson's code and its
        # assignment must always belong together. The same assignment, or a
        # resume (which never says which assignment), carries on as before.
        if (live is not None and not reopen and not resume and "assignment" in data
                and live.assignment_id != (item.id if item else None)):
            live.ended = 1
            live.updated_at = _live_now()
            live = None

        # THIS ASSIGNMENT'S OWN LINK, taught before or not. The teacher posts
        # it ahead (_lesson_for) — in Classroom, on the class page — and it
        # has to keep working for the whole unit. This used to reuse only a
        # link never taught, and start a new code for one already taught, on
        # the grounds that anything else was guessing which old lesson was
        # meant. It is not a guess: an assignment has one lesson, the one its
        # page shows, and the newest is that one. The cost of the new code
        # was real and silent — the class sat on the posted link reading
        # "this lesson has ended" while the teacher taught to nobody, and the
        # assignment page swapped to the new link so the old one looked
        # wrong. Go live with no assignment still starts fresh.
        if live is None and item is not None and not reopen:
            own = (db.query(accounts.LiveSession)
                     .filter_by(host_id=user.id, app=APP_NAME,
                                assignment_id=item.id)
                     .order_by(accounts.LiveSession.started_at.desc(),
                               accounts.LiveSession.id.desc()).first())
            if own is not None:
                own.ended = 0
                # 0 is "made ahead, never taught" (_waiting); a taught one
                # moves on so every student's poll sees the new file.
                own.version = (own.version or 0) + 1
                own.body = body
                own.filename = clean(data.get("filename"), 200) or "main.py"
                own.title = clean(data.get("title"), 200) or own.title
                own.host_name = user.display_name()
                live = own

        if live is None:
            live = accounts.LiveSession(
                code=accounts.new_id(db, accounts.LiveSession, "code"),
                app=APP_NAME,
                host_id=user.id,
                host_name=user.display_name(),
                title=clean(data.get("title"), 200) or "Live lesson",
                body=body,
                filename=clean(data.get("filename"), 200) or "main.py",
                # 1, not 0: version 0 on an ended lesson means "made ahead
                # and never taught" (_waiting), and a lesson started here
                # and ended before its first push must not look like that.
                version=1,
                assignment_id=item.id if item else None,
            )
            db.add(live)
        else:
            live.title = clean(data.get("title"), 200) or live.title
            # Resuming after a reload must not quietly drop the assignment —
            # the class would carry on with no way to hand anything in, and
            # nothing would say so. Only an explicit choice changes it.
            if "assignment" in data:
                live.assignment_id = item.id if item else None
        live.updated_at = _live_now()
        db.commit()

        _sweep_live(db)
        return jsonify(code=live.code, version=live.version,
                       assignment=(item.slug if item else
                                   _slug_of_assignment(db, live.assignment_id)),
                       assignment_title=(item.title if item else
                                         _title_of_assignment(db, live.assignment_id)),
                       # so a reload carries on from the same slide rather
                       # than sending the class back to the title
                       slide=live.slide or "",
                       url=url_for("live_page", code=live.code, _external=True))

    finally:
        db.close()


def _sweep_live(db):
    """Close sessions nobody has pushed to for hours.

    Without this the table grows a row per lesson forever, and — worse — a
    teacher who closed the tab last Tuesday still has an "open" session, so
    Go live today reuses a code the class no longer has.
    """
    cutoff = _live_now() - timedelta(hours=LIVE_STALE_HOURS)
    try:
        (db.query(accounts.LiveSession)
           .filter(accounts.LiveSession.ended == 0,
                   accounts.LiveSession.updated_at < cutoff)
           .update({"ended": 1}, synchronize_session=False))
        db.commit()
    except Exception:
        db.rollback()          # a sweep failing must never fail the lesson


@app.post("/api/live/<code>/push")
def live_push(code):
    """The teacher's current file. Called every few hundred milliseconds.

    `seq` is a stamp from the teacher's browser that only ever goes up, and
    the write is conditional on it being higher than what the row already
    has. Two pushes overtaking each other on a slow connection would
    otherwise leave the OLDER text in the row with a HIGHER version, and the
    class would sit looking at a line their teacher had already fixed.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Not signed in."), 403

        live = _find_live(db, code)
        if live is None:
            return jsonify(error="No such live lesson."), 404
        # Only the host, checked against the row rather than against the
        # teacher list: a second teacher must not be able to type into
        # somebody else's lesson.
        if live.host_id != user.id:
            return jsonify(error="This is not your live lesson."), 403
        if live.ended:
            return jsonify(error="That live lesson has ended.", ended=True), 409

        data = request.get_json(silent=True) or {}
        body = data.get("body")
        if not isinstance(body, str):
            return jsonify(error="Nothing to send."), 400
        if len(body.encode("utf-8")) > MAX_FILE_BYTES:
            return jsonify(error="That file is too large to share live."), 413
        try:
            seq = int(data.get("seq", 0))
        except (TypeError, ValueError):
            return jsonify(error="Bad sequence number."), 400

        filename = clean(data.get("filename"), 200) or live.filename

        # THE ANSWER KEYS STOP HERE. The teacher's editor sends its notes as
        # written, `[x]` and `answer:` included; what is stored, and so what
        # every poll hands the class, has them taken out. The keys are kept
        # first, so a question is answerable the moment a student can see it.
        # The open file is redacted too when it is the notes: with the .md tab
        # selected, `body` is the very same text.
        notes = data.get("notes")
        if quiz.is_notes(filename) or isinstance(notes, str):
            if live.assignment_id:
                _store_quiz_keys(db, live.assignment_id,
                                 [notes, body if quiz.is_notes(filename) else ""])
            if quiz.is_notes(filename):
                body = quiz.redact(body)
            if isinstance(notes, str):
                notes = quiz.redact(notes)

        fields = {"body": body, "filename": filename,
                  "version": seq, "updated_at": _live_now()}
        # The project's notes ride along on every push (see LiveSession.notes).
        # Only when sent: an editor tab still running the code from before
        # this existed sends none, and must not wipe them.
        if isinstance(notes, str):
            if len(notes.encode("utf-8")) > MAX_FILE_BYTES:
                return jsonify(error="Those notes are too large to share live."), 413
            fields["notes"] = notes

        # Which slide those notes are, "3/5", or "" when they are not slides.
        # Same rule as notes: only when sent.
        slide = data.get("slide")
        if isinstance(slide, str):
            fields["slide"] = slide if re.fullmatch(r"\d{1,4}/\d{1,4}", slide) else ""

        # Where the teacher's caret is, "line:ch", or what they have
        # highlighted, "anchor-head" as two of those. Same rule as notes: only
        # when sent. Anything else is stored as none rather than refused, so a
        # bad caret can never cost the class the code that came with it.
        # A selection's numbers are one digit shorter so the pair still fits
        # the 24 characters of the cursor column — a longer value would be
        # refused by Postgres and lose the whole push, code and all.
        cursor = data.get("cursor")
        if isinstance(cursor, str):
            fields["cursor"] = (cursor if re.fullmatch(
                r"\d{1,6}:\d{1,6}|\d{1,5}:\d{1,5}-\d{1,5}:\d{1,5}", cursor)
                else "")

        # What the teacher's Run printed to the console. Trimmed here rather
        # than refused: a runaway loop is exactly when the output is huge,
        # and a 413 would throw away the code that came with it, freezing the
        # mirror for as long as the loop ran. The tail is what anyone reads.
        output = data.get("output")
        if isinstance(output, str):
            raw = output.encode("utf-8")
            if len(raw) > LIVE_OUTPUT_BYTES:
                output = raw[-LIVE_OUTPUT_BYTES:].decode("utf-8", "ignore")
            fields["output"] = output

        # The page the teacher's preview is showing. Too big, it is dropped
        # rather than refused, for the same reason as the output: a 413 here
        # would take the code down with it, and the mirror would freeze for
        # the rest of the lesson over a picture nobody asked to be big. Half
        # a page would be worse than none — cut HTML renders as nonsense —
        # so it is all or nothing.
        page = data.get("page")
        if isinstance(page, str):
            fields["page"] = page if len(page.encode("utf-8")) <= MAX_FILE_BYTES else ""

        # One statement, so two workers cannot interleave a read and a write.
        # `version < seq` is what drops a stale push, and it is also why this
        # cannot be an ORM assignment followed by a commit.
        changed = (db.query(accounts.LiveSession)
                     .filter(accounts.LiveSession.id == live.id,
                             accounts.LiveSession.version < seq)
                     .update(fields, synchronize_session=False))
        db.commit()
        if not changed:
            # Not an error: a push that lost the race has nothing to say, and
            # the teacher's browser should carry on rather than retry.
            return jsonify(stale=True, version=live.version)
        return jsonify(version=seq)
    finally:
        db.close()


@app.post("/api/live/<code>/stop")
def live_stop(code):
    db = SessionLocal()
    try:
        user = current_user(db)
        live = _find_live(db, code)
        if live is None:
            return jsonify(error="No such live lesson."), 404
        if user is None or live.host_id != user.id:
            return jsonify(error="This is not your live lesson."), 403
        live.ended = 1
        live.updated_at = _live_now()
        db.commit()
        return jsonify(ended=True)
    finally:
        db.close()


@app.get("/api/live/<code>")
def live_poll(code):
    """What the class asks for, once a second, all lesson.

    Answers 304 when nothing has changed, which is almost every time. Thirty
    students polling is thirty small queries a second and no payload at all
    until a key is pressed.

    No sign-in required, on purpose: a student who cannot get Google to work
    must still be able to follow the lesson.
    """
    db = SessionLocal()
    try:
        live = _find_live(db, code)
        if live is None:
            return jsonify(error="No such live lesson."), 404
        try:
            seen = int(request.args.get("v", -1))
        except (TypeError, ValueError):
            seen = -1

        if seen == live.version and not live.ended:
            return ("", 304)
        return jsonify(
            version=live.version,
            body=live.body,
            filename=live.filename,
            title=live.title,
            host=live.host_name,
            ended=bool(live.ended),
            waiting=_waiting(live),
            notes=live.notes or "",
            slide=live.slide or "",
            output=live.output or "",
            cursor=live.cursor or "",
            page=live.page or "",
        )
    finally:
        db.close()


@app.post("/api/live/<code>/keep")
def live_keep(code):
    """A student saving their own copy from the live page.

    THIS IS NOT /api/draft, AND THE DIFFERENCE IS THE WHOLE POINT.

    /api/draft makes a free-standing project with no assignment on it, and a
    draft with no assignment can never be turned in — the button cannot even
    appear. That is what made handing work in from a live lesson impossible.

    When the lesson has an assignment, this creates or finds the draft for
    (this student, that assignment): the very row /a/<slug> would have made.
    So a student who opened the handout link this morning and joins the
    lesson this afternoon carries on with ONE copy, and whichever way they
    came in, Turn in is there.

    With no assignment on the lesson it behaves exactly like /api/draft, so
    a lesson that is just a lesson still saves.
    """
    db = SessionLocal()
    try:
        user = current_user(db)
        if user is None:
            return jsonify(error="Sign in first, then you can save your work."), 401

        live = _find_live(db, code)
        if live is None:
            return jsonify(error="No such live lesson."), 404

        data = request.get_json(silent=True) or {}
        source = data.get("code", "")
        if not isinstance(source, str) or not source.strip():
            return jsonify(error="There's nothing to save yet."), 400
        if len(source.encode("utf-8")) > MAX_FILE_BYTES:
            return jsonify(error="That program is too large to save."), 413

        # The project's other files, from the tabs on the live page. An EMPTY
        # or missing map means "leave them alone", never "delete them all":
        # the live page has no way to remove a file, so an empty map can only
        # be an editor tab still running the code from before it had tabs —
        # which sent `files: {}` — and taken at its word it would strip the
        # templates out of a Flask assignment without a word.
        rest = data.get("files")
        if not isinstance(rest, dict) or not rest:
            rest = None

        item = None
        if live.assignment_id:
            item = db.query(accounts.Assignment).filter_by(
                id=live.assignment_id).first()

        draft = None
        if item is not None:
            # One per student per assignment — there is a unique constraint
            # on exactly this pair, so looking first is what keeps the insert
            # below from colliding with the handout link.
            draft = db.query(accounts.Draft).filter_by(
                owner_id=user.id, assignment_id=item.id).first()

        # WHICH FILE THE PANE EDITS. FlaskIDE has two kinds of project and
        # they have different entry points; a live save into a SQL assignment
        # must land in query.sql, not create a stray app.py beside it that
        # nothing runs. The project already saved decides when there is one.
        # Only a lesson with no project behind it at all takes the page's
        # word for it (`entry`, which live_page chose from the teacher's file).
        base = (draft.file_map() if draft is not None else
                quiz.redact_files(item.file_map()) if item is not None else {})
        if SQL_ENTRY in base or ENTRY in base:
            entry = SQL_ENTRY if SQL_ENTRY in base else ENTRY
        else:
            entry = data.get("entry") if data.get("entry") in (ENTRY, SQL_ENTRY) \
                else ENTRY

        project = dict(rest if rest is not None else base)
        project[entry] = source
        # Checked whole, the way /api/draft checks it, so a name the editor
        # would refuse cannot get into a project through this door instead.
        project, file_error = validate_files(project)
        if file_error:
            return jsonify(error=file_error), 400

        # FLASKIDE KEEPS EVERYTHING IN `files`, and `code` is always "" — see
        # /api/draft. With no tabs sent, the rest of the project is left
        # exactly as it was: an assignment that ships templates/index.html
        # must not lose it because a student typed in app.py.
        if draft is None:
            # SEEDED FROM THE ASSIGNMENT, exactly as /a/<slug> seeds one
            # (`base` above). Without this a student who joins the lesson
            # without ever opening the handout link gets a project missing
            # every file the assignment shipped — the templates, the schema —
            # and only finds out when render_template cannot find a page.
            draft = accounts.Draft(
                slug=accounts.new_id(db, accounts.Draft),
                owner_id=user.id,
                assignment_id=item.id if item else None,
                app=APP_NAME,
                title=(item.title if item else (live.title or "Live lesson")),
                code="",
                files=json.dumps(project),
            )
            db.add(draft)
        else:
            stale = _stale(draft, data)
            if stale:
                return stale
            draft.files = json.dumps(project)
            draft.updated_at = accounts.now()
        _written(draft, data)

        db.commit()
        return jsonify(
            slug=draft.slug,
            version=draft.version,
            url=url_for("open_draft", slug=draft.slug),
            assignment=(item.slug if item else ""),
            assignment_title=(item.title if item else ""),
            can_turn_in=bool(item),
            # The WHOLE project, not just the file they typed. Turning in
            # replaces a draft's files with what is posted, so a live page
            # that sent only its one editor would drop a style.css the
            # assignment shipped — silently, at the moment it was handed in.
            files=draft.file_map(),
        )
    finally:
        db.close()


@app.get("/live/")
@app.get("/live")
def live_join():
    """Type a code in. The page students are sent to when they have a code."""
    db = SessionLocal()
    try:
        ctx = user_context(db)
        ctx.update(live=None, code="", joined=False, is_host=False,
                   assignment=None, submitted_at="",
                   error=request.args.get("error", ""))
        return render_template("live.html", **ctx)
    finally:
        db.close()


@app.get("/live/<code>")
def live_page(code):
    db = SessionLocal()
    try:
        live = _find_live(db, code)
        if live is None:
            return redirect(url_for("live_join", error="No lesson with that code."))
        user = current_user(db)
        item = None
        submitted_at = ""
        if live.assignment_id:
            item = db.query(accounts.Assignment).filter_by(
                id=live.assignment_id).first()
        # A lesson's class follows it full screen; its teacher still gets
        # the card below, whose button goes to the lesson's Present.
        if _is_lesson(item) and not (user is not None and user.id == live.host_id):
            return _lesson_page(db, item, user, live)
        # If they have already handed this in, the button says so rather than
        # pretending nothing happened — the same wording the editor uses.
        if item is not None and user is not None:
            done = db.query(accounts.Submission).filter_by(
                assignment_id=item.id, student_id=user.id).first()
            if done is not None:
                submitted_at = done.submitted_at.strftime("%b %d at %I:%M %p")

        # WHAT THE STUDENT'S EDITOR STARTS WITH, when their browser has nothing
        # of its own for this lesson. The same as /a/<slug> would give them:
        # their own draft of the assignment if they have one, else its starter
        # — the file its Save writes back to — query.sql when the assignment
        # has one, else app.py (see live_keep); the live editor holds one file.
        #
        # THE DRAFT IS NOT A NICETY. Saving from the live page writes into
        # that draft, replacing that file with the live editor. Started empty,
        # a student who did half the assignment from the link this morning
        # would type one line here, press Save, and lose the morning's work
        # without a word.
        #
        # Rendered into the page, never sent on the poll: it is the student's
        # starting point, like opening the link, not the teacher reaching into
        # their editor.
        starter = ""
        # THE REST OF THE PROJECT, from the same place, shown as tabs beside
        # the entry: templates/, static/, schema.sql. The live page was the
        # entry file alone once, and a student could not see the template the
        # lesson was about — nor run an app that rendered it, because Run sent
        # app.py on its own and render_template had nothing to find. Before
        # that it was worse in a SQL lesson: no schema.sql, so every Run
        # stopped at "There is no schema.sql".
        starter_files = {}
        draft_version = None
        # Which file is the entry, decided here so live.js never has to guess
        # it: the project's own files say, as everywhere else in FlaskIDE.
        # Only a lesson with no assignment has no files to ask, and then the
        # teacher's open file says — the rule this page always used.
        entry = SQL_ENTRY if (live.filename or "").lower().endswith(".sql") \
            else ENTRY
        if item is not None:
            source = quiz.redact_files(item.file_map())
            if user is not None:
                mine = db.query(accounts.Draft).filter_by(
                    owner_id=user.id, assignment_id=item.id).first()
                if mine is not None:
                    source = mine.file_map()
                    draft_version = mine.version or 0
            entry = SQL_ENTRY if SQL_ENTRY in source else ENTRY
            starter = source.get(entry, "")
            starter_files = {k: v for k, v in source.items() if k != entry}

        ctx = user_context(db)
        ctx.update(
            live=live,
            code=live.code,
            joined=True,
            is_host=bool(user is not None and user.id == live.host_id),
            assignment=item,
            submitted_at=submitted_at,
            starter=starter,
            starter_files=starter_files,
            draft_version=draft_version,
            waiting=_waiting(live),
            entry=entry,
            sql_entry=SQL_ENTRY,
            error="",
        )
        return render_template("live.html", **ctx)
    finally:
        db.close()


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
