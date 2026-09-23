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
import re
import secrets
from datetime import datetime, timezone

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
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

import accounts

APP_NAME = "flaskide"       # this editor, in the shared account tables

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

MAX_FILES = 16
MAX_FILE_BYTES = 200_000          # per file
MAX_FILES_TOTAL = 600_000         # all files together
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters
ID_LENGTH = 7

# The file that IS the project. Without it there is nothing to run.
ENTRY = "app.py"

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

    if ENTRY not in files:
        return None, ("A project needs an %s — that is the file that runs."
                      % ENTRY)
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
    return {"entry": ENTRY, "folders": list(FOLDERS)}


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
        return oauth.google.authorize_redirect(target)
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
        db.commit()
        session["uid"] = user.id
    finally:
        db.close()

    return redirect(session.pop("after_login", "") or url_for("index"))


@app.get("/logout")
def logout():
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
    )
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

        draft.files = json.dumps(files)
        draft.title = clean(data.get("title"), 200) or draft.title
        draft.updated_at = accounts.now()
        db.commit()
        return jsonify(saved_at=draft.updated_at.strftime("%I:%M %p"))
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
            return redirect(url_for("edit_assignment", slug=item.slug))

        if user is None:
            ctx = user_context(db)
            ctx.update(
                files=item.file_map(),
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
                files=item.files,
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
        db.commit()
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

        detached = db.query(accounts.Draft).filter_by(assignment_id=item.id).all()
        for draft in detached:
            draft.assignment_id = None       # their work becomes their own
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

        # keep the draft in step, so the saved copy matches what was submitted
        draft.files = json.dumps(files)
        draft.updated_at = accounts.now()

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
                       again=row.times_submitted > 1)
    finally:
        db.close()


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
                   .order_by(accounts.Assignment.created_at.desc()).all())
        live = [a for a in items if not a.archived]
        filed = [a for a in items if a.archived]
        counts = {}
        for item in items:
            counts[item.id] = db.query(accounts.Submission).filter_by(
                assignment_id=item.id).count()
        ctx = user_context(db)
        ctx.update(assignments=live, archived=filed, counts=counts,
                   show_archived=show_archived)
        return render_template("teacher.html", **ctx)
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
        handed_in = [{
            "name": student.display_name(),
            "email": student.email,
            "when": sub.submitted_at.strftime("%b %d at %I:%M %p"),
            "times": sub.times_submitted,
            "url": url_for("view_shared", slug=sub.snippet_slug),
        } for sub, student in rows]

        # Anyone who opened the assignment but never pressed Turn in.
        started = (db.query(accounts.User)
                     .join(accounts.Draft,
                           accounts.Draft.owner_id == accounts.User.id)
                     .filter(accounts.Draft.assignment_id == item.id,
                             accounts.Draft.owner_id != item.teacher_id).all())
        done = {s["email"] for s in handed_in}
        not_yet = sorted({u.email: u.display_name() for u in started
                          if u.email not in done}.values())

        ctx = user_context(db)
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


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
