#!/usr/bin/env python3
"""The editor's own server: pages, share links, and the file rules.

    python3 tools/test_app.py

This is about the app that SERVES the editor, not the app a student writes.
The student's never comes here — it runs in their browser — so there is
nothing in this file about Flask-in-Pyodide. That is tools/test_bridge.py.

THE PART WORTH THE MOST

`validate_files`. Every other editor of Steve's forbids a slash in a file
name outright, because their projects are flat. A Flask project cannot be:
`render_template("index.html")` opens `templates/index.html` and will not
find it anywhere else. So names here carry a folder, and the moment a file
name can contain a slash, "../" becomes a thing somebody might send.

It is written as a whitelist — one optional folder, and only the two Flask
itself looks in — because a blacklist of traversal tricks is a thing you can
be wrong about and a whitelist is not. The cases below are the ones a
blacklist gets wrong.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# SQLite in a temp dir: the repo folder may be on a filesystem that cannot
# take the locks SQLite wants, and a test that fails for that reason teaches
# nothing.
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _db.name

import app as A                                                   # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-56s %s" % ("ok" if ok else "FAIL", label, detail))


def done():
    bad = results.count(False)
    print("\n%s (%d checks, %d failed)"
          % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
    os.unlink(_db.name)
    sys.exit(1 if bad else 0)


client = A.app.test_client()

# ------------------------------------------------------------- the page
r = client.get("/")
check("the editor loads", r.status_code == 200, "%d bytes" % len(r.data))
page = r.data.decode()

for want, why in [
    ("window.FLASKIDE", "the config the editor reads"),
    ("flask.js", "the runtime"),
    ("preview.js", "the iframe bridge"),
    ('sandbox="allow-scripts allow-forms"', "forms, which half a unit needs"),
    ("templates/index.html", "the starter's template"),
]:
    check("  serves %s" % why, want in page, want)

check("  and nothing left over from WebIDE",
      "WEBIDE" not in page and "runner.js" not in page and "sprites" not in page)

r = client.get("/healthz")
check("there is a health check for Render", r.status_code == 200)

# ------------------------------------------------------- the starter runs
#
# Not "is it there" — is it a project. A starter that does not run is the
# first thing every student sees, and they will assume they broke it.
check("the starter has an %s" % A.ENTRY, A.ENTRY in A.STARTER)
check("  and templates for it to render",
      any(n.startswith("templates/") for n in A.STARTER))
files, err = A.validate_files(A.STARTER)
check("  and passes the project rules it is shipped under", err is None, err or "")

import ast                                                        # noqa: E402
try:
    ast.parse(A.STARTER[A.ENTRY])
    parsed = True
except SyntaxError as e:                                          # noqa: BLE001
    parsed, err = False, str(e)
check("  and its Python parses", parsed, "" if parsed else err)

# The starter's templates must name each other correctly, or the first Run
# is a TemplateNotFound and the student thinks the editor is broken.
import re                                                         # noqa: E402
extended = set(re.findall(r'{%\s*extends\s+"([^"]+)"', "".join(A.STARTER.values())))
missing = [t for t in extended if ("templates/" + t) not in A.STARTER]
check("  and every {% extends %} names a file that exists", not missing, str(missing))

rendered = set(re.findall(r'render_template\(\s*"([^"]+)"', A.STARTER[A.ENTRY]))
absent = [t for t in rendered if ("templates/" + t) not in A.STARTER]
check("  and every render_template names one too", not absent, str(absent))

# --------------------------------------------------------- the file rules
GOOD = ["app.py", "templates/index.html", "static/style.css", "helper.py",
        "templates/a_b-c.html", "static/script.js"]
BAD = [
    "../secret.py",                 # the obvious one
    "templates/../../etc/passwd",   # the one a "no .." check often misses
    "static/../app.py",             # traversal that stays inside the name
    "/etc/passwd",                  # absolute
    "a/b/c.html",                   # two folders deep
    "lib/thing.py",                 # a folder Flask does not look in
    "templates\\evil.html",         # a Windows-shaped path
    ".hidden.py",                   # a dotfile
    "templates/",                   # a folder, not a file
    "no_extension",
]

wrong = [n for n in GOOD if not A.FILE_NAME.match(n)]
check("every legitimate name is allowed", not wrong, str(wrong))
leaked = [n for n in BAD if A.FILE_NAME.match(n)]
check("and every escape attempt is refused", not leaked, str(leaked))

files, err = A.validate_files({"templates/x.html": "<p>hi</p>"})
check("a project with no %s is refused" % A.ENTRY, files is None and A.ENTRY in err,
      (err or "")[:60])

files, err = A.validate_files({"app.py": "x", "templates\\y.html": "z"})
check("a backslash gets a sentence about slashes", files is None and "slash" in err,
      (err or "")[:64])

files, err = A.validate_files({"app.py": "x", "lib/y.py": "z"})
check("a folder Flask ignores is refused, naming the ones that work",
      files is None and "templates" in err and "static" in err,
      (err or "")[:70])

# --------------------------------------------------------- share round-trip
payload = {
    "files": dict(A.STARTER),
    "title": "Pet List",
    "author": "Steve",
}
r = client.post("/api/share", json=payload)
check("sharing a project works", r.status_code == 200, r.data[:70])
slug = r.get_json().get("url", "").rstrip("/").split("/")[-1]
check("  and returns a link", bool(slug), slug)

r = client.get("/s/%s" % slug)
check("the shared link opens", r.status_code == 200)
shown = r.data.decode()
check("  read-only", "readonly" in shown or "Edit a copy" in shown)
check("  with every file in it",
      all(n in shown for n in A.STARTER), "%d files" % len(A.STARTER))
check("  including the folder in the name", "templates/base.html" in shown)

r = client.get("/s/%s/raw/app.py" % slug)
check("a single file can be fetched raw", r.status_code == 200 and
      b"Flask(__name__)" in r.data)

r = client.get("/s/nosuchid")
check("an unknown link is a 404, not a crash", r.status_code == 404)

# A traversal attempt through the share API must be refused, not stored.
r = client.post("/api/share", json={
    "files": {"app.py": "x", "../evil.py": "y"}, "title": "t", "author": "a"})
check("sharing cannot smuggle a path out of the project",
      r.status_code >= 400, "%d" % r.status_code)

# ----------------------------------------------------------- the two apps
#
# This repository has two things called app.py and it is the most confusing
# thing in it. The README says so; this makes sure it keeps saying so.
readme = (ROOT / "README.md").read_text()
check("the README warns about the two app.py files",
      "different programs" in readme and "never" in readme)

# ------------------------------------------------- the editor's own wiring
#
# app.js was written by hand against a template that was transformed rather
# than written, so every $("id") in it is a small bet that the element
# survived. A missed one is not an error anybody sees: addEventListener is
# never reached, and the button is simply dead. Ask both sides instead.
#
# The TEMPLATE is read rather than the rendered page, because half these
# elements only appear for a teacher or a signed-in student and rendering
# anonymously would report them all missing.
template = (ROOT / "templates" / "index.html").read_text()
ids = set(re.findall(r'id="([^"]+)"', template))

js_files = ["app.js", "account.js", "notes.js"]
dangling = []
for name in js_files:
    text = (ROOT / "static" / name).read_text()
    for wanted in set(re.findall(r'\$\(\s*"([^"]+)"\s*\)', text)):
        if wanted not in ids:
            dangling.append("%s wants #%s" % (name, wanted))
check("every element the editor's JavaScript reaches for exists",
      not dangling, "; ".join(sorted(dangling)[:3]))
check("  (and the scan found something to scan)",
      len(ids) > 15 and "run" in ids, "%d ids in the template" % len(ids))

# The reverse: a script the page loads that is not in the repo is a 404 and
# a dead editor, and the page still renders perfectly.
for src in re.findall(r"filename='([^']+)'", template):
    check("  static/%s exists" % src, (ROOT / "static" / src).is_file())

# ------------------------------------------------- class names, both sides
#
# THE UNSTYLED CLASS. `paintTabs` set "tab-active" while the stylesheet had
# only ".tab-on", so the open file had no highlight at all — for the whole
# life of the editor. Nothing errors; the strip renders, and simply stops
# telling a student which file they are editing. Both files look correct on
# their own, which is exactly why nobody finds it by reading them.
#
# PyIDE and WebIDE both say tab-on on both sides. This one drifted in the
# port, and a port is when this always happens.
css = (ROOT / "static" / "style.css").read_text()
styled = set(re.findall(r"\.([A-Za-z][\w-]*)", css))

applied = set()
for name in ("app.js", "account.js", "notes.js", "preview.js"):
    path = ROOT / "static" / name
    if not path.is_file():
        continue
    text = path.read_text()
    # The whole right-hand side, then every literal in it. Matching only the
    # first string after `className =` was the first version of this check,
    # and it could not see the bug it exists for: the line reads
    # `"tab" + (open ? " tab-on" : "")`, so it collected "tab" and stopped.
    for rhs in re.findall(r'className\s*=\s*([^;]+);', text):
        for lit in re.findall(r'"([^"]*)"', rhs):
            applied |= set(lit.split())
    for one in re.findall(r'classList\.(?:add|toggle|remove)\(\s*"([^"]+)"', text):
        applied.add(one)

unstyled = sorted(c for c in applied if c and c not in styled)
check("every class the editor applies has a CSS rule", not unstyled, str(unstyled))
check("  (and it applies some)", len(applied) >= 8, "%d classes" % len(applied))

# ------------------------------------------- publish edits what it published
#
# Publish used to POST a new assignment every single press, so a teacher
# revising a task ended up with three links and no way to tell which one the
# class was holding. Nothing errored — it did exactly what it was told, three
# times. Wanting a second, separate assignment has a better path: share the
# project to yourself and publish the copy, which arrives named "Copy of ...".
#
# Three editors share a teacher and a workflow but not a file, so the fix had
# to be made three times. That is the reason for the check: the next person to
# change one of them will not think to look at the other two.
account = (ROOT / "static" / "account.js").read_text()

check("publishing twice updates rather than duplicating",
      "if (cfg.editingAssignment)" in account
      and "updateAssignment(btn, read, say)" in account)
check("  and the button says so afterwards",
      'btn.textContent = "Update assignment"' in account)
check("  remembering what it just published",
      "cfg.editingAssignment = out.data.slug" in account)
check("  with one shared update function",
      account.count("function updateAssignment(") == 1
      and account.count('/api/assignment/" + encodeURIComponent') == 1)

check("this editor's table is its own, not WebIDE's",
      A.Project.__tablename__ == "flask_projects", A.Project.__tablename__)
check("and it books into the shared account tables under its own name",
      A.APP_NAME == "flaskide", A.APP_NAME)

# ------------------------------------------------- find and replace is wired
#
# Ctrl-F / Cmd-F comes from CodeMirror's own addons, which means the whole
# feature is four files in the template and nothing else. Three ways that
# goes wrong, none of which raises:
#
#   * search.js without searchcursor.js — search.js USES it and does not
#     fetch it, so Ctrl-F throws inside CodeMirror and the key does nothing.
#   * search.js without dialog.js — same, for the prompt.
#   * everything but dialog.min.css — and this is the nasty one. The feature
#     WORKS. Find, next, replace, all of it. The bar asking for the search
#     term is just an unstyled input floating over the code, so it ships.
template_text = (ROOT / "templates" / "index.html").read_text()
for addon in ("addon/dialog/dialog.min.js",
              "addon/search/searchcursor.min.js",
              "addon/search/search.min.js",
              "addon/dialog/dialog.min.css"):
    check("the editor loads %s" % addon.split("/")[-1],
          addon in template_text)

# Order matters: search.js reads CodeMirror.fromTextArea's searchcursor at
# call time, but registers against the API that searchcursor installs.
check("  and searchcursor is loaded before search",
      template_text.find("searchcursor.min.js") <
      template_text.find("addon/search/search.min.js"))

# The bar CodeMirror builds is about 130px wide for the search term, which
# is four or five characters of it. Sized here rather than left alone.
style_text = (ROOT / "static" / "style.css").read_text()
EDITOR_SCRIPT = "app.js"
# THE ADDONS MUST LOAD BEFORE THE EDITOR IS BUILT.
#
# search.js calls CodeMirror.defineOption("search", {bottom: false}), and a
# default set by defineOption only reaches editors made AFTER it runs. An
# editor built first has options.search undefined, and search.js then reads
# `cm.options.search.bottom` with no guard:
#
#     TypeError: Cannot read properties of undefined (reading 'bottom')
#
# Found by loading the addons into the deployed editor by hand, where the
# editor already existed: Ctrl-F threw that, which names neither the addon
# nor the option nor anything a person would search for. In the page the
# order is right; this is here so it stays right.
# The SCRIPT TAG, not the string. An earlier version searched for "app.js"
# and matched a comment mentioning it near the top of the template, so the
# check compared a comment's position and failed on a correctly ordered page.
EDITOR_TAG = "filename='%s'" % EDITOR_SCRIPT
check("  (and the editor's script tag was found at all)",
      EDITOR_TAG in template_text, EDITOR_TAG)
check("  and the addons load before %s builds the editor" % EDITOR_SCRIPT,
      template_text.find("addon/search/search.min.js")
      < template_text.find(EDITOR_TAG),
      "search.js at %d, %s at %d"
      % (template_text.find("addon/search/search.min.js"), EDITOR_TAG,
         template_text.find(EDITOR_TAG)))

check("  and the search bar is given a usable width",
      ".CodeMirror-dialog input" in style_text)


# ---------------------------------------------------------------- SQL mode
#
# FlaskIDE holds two kinds of project. Everything below is a way that split
# ships half-done and looks fine on the screen you happen to be looking at.

r = client.get("/sql")
check("there is a SQL project to open", r.status_code == 200, "%d" % r.status_code)
sql_page = r.data.decode()

# The kind is DERIVED, not stored. app.js has the same rule, and if the two
# ever disagree the editor runs a project one way while the server saves it
# as the other, with nothing raised anywhere.
for files, want in [({"app.py": "x"}, "flask"),
                    ({"query.sql": "x"}, "sql"),
                    ({"app.py": "x", "schema.sql": "y"}, "flask"),
                    ({"query.sql": "x", "schema.sql": "y"}, "sql")]:
    check("  kind_of(%s) is %s" % (sorted(files), want),
          A.kind_of(files) == want, A.kind_of(files))

js = (ROOT / "static" / "app.js").read_text()
check("  and app.js decides it the same way, off query.sql",
      'SQL_ENTRY in files' in js and 'cfg.sqlEntry' in js,
      "app.js does not read the kind off the files")
check("  using the name the server sent, not one typed again",
      '"query.sql"' not in js.replace('cfg.sqlEntry || "query.sql"', ""),
      "query.sql is hard-coded somewhere in app.js besides the fallback")

# Either entry is a project; neither is not.
for files, ok in [({"app.py": "x"}, True), ({"query.sql": "x"}, True),
                  ({"schema.sql": "x"}, False)]:
    got, err = A.validate_files(files)
    check("  validate_files(%s) %s" % (sorted(files),
                                       "accepts" if ok else "refuses"),
          (err is None) == ok, err or "accepted")

# The starter has to be a working project, not two empty files. It is read
# from examples/ at import time, so a missing one is a boot failure rather
# than an empty editor -- but a TRUNCATED one is neither.
check("  the SQL starter is a real project",
      set(A.SQL_STARTER) == {"query.sql", "schema.sql"}, str(sorted(A.SQL_STARTER)))
check("    with a schema that makes tables",
      A.SQL_STARTER["schema.sql"].count("CREATE TABLE") >= 4,
      "%d CREATE TABLEs" % A.SQL_STARTER["schema.sql"].count("CREATE TABLE"))
check("    and queries to run against them",
      A.SQL_STARTER["query.sql"].upper().count("SELECT") >= 4)
check("    and it is served by /sql",
      "CREATE TABLE teachers" in sql_page)

# CodeMirror colours .sql only if the mode is loaded. Without it the file is
# plain grey text -- no error, nothing in the console, just a worse editor.
check("  CodeMirror's sql mode is loaded", "mode/sql/sql.min.js" in template)
check("    before app.js builds the editor",
      template.find("mode/sql/sql.min.js") < template.find("filename='app.js'"))
check("    and app.js asks for it on a .sql file",
      '"text/x-sql"' in js)

# The chip is a LABEL. A control here could only ever disagree with the files.
check("  the mode chip is a span, not a button",
      '<span id="mode-chip"' in template)

check("  there is a button to the other kind", 'id="switch-kind"' in template)
check("    and it asks before throwing unsaved work away",
      "changedFromStarter" in js and "preventDefault" in js)

# The panes. A missed toggle leaves an address bar floating over a grid of
# query results, which is why this is one body class and not four toggles.
css = (ROOT / "static" / "style.css").read_text()
check("  a body class swaps the preview for the results",
      "body.is-sql .preview-frame" in css and "body.is-sql .trail" in css)
check("    and hides the results pane in Flask mode",
      "body:not(.is-sql) .sql-pane" in css)
check("    with app.js setting that class", 'classList.toggle("is-sql"' in js)

# THE UNSTYLED CLASS. Every class app.js builds a node with is a bet that a
# rule exists. A typo renders an unstyled rectangle saying the right words.
import re as _re
built = set()
for value in _re.findall(r'className = "([^"]+)"', js):
    built |= set(value.split())
styled = set(_re.findall(r"\.([A-Za-z][\w-]*)", css))
unstyled = sorted(c for c in built if c not in styled)
check("  every class the results grid builds has a CSS rule", not unstyled,
      str(unstyled))
check("    (and the scan found classes to check)", len(built) >= 8,
      "%d classes" % len(built))

# NULL is not the empty string, and the LEFT JOIN lesson is the row with
# nothing on one side.
check("  NULL is rendered as the word, not an empty cell",
      '"NULL"' in js and "sql-null" in js)
# A database row can hold anything a student typed, and the grid must never
# run it. textContent everywhere; innerHTML only ever to empty a pane.
_writes = _re.findall(r"innerHTML\s*=\s*([^;]+);", js)
check("  and a value never reaches the page as HTML",
      all(w.strip() in ('""', "''") for w in _writes),
      str([w.strip() for w in _writes if w.strip() not in ('""', "''")]))
check("    (and innerHTML is used, so the rule is doing work)",
      len(_writes) >= 1, "%d assignments" % len(_writes))

check("  the runtime exposes runSql",
      "runSql" in (ROOT / "static" / "flask.js").read_text())

done()
