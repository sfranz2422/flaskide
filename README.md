# FlaskIDE

A browser-based Flask editor for a second-semester web class. Third of three,
after [PyIDE](https://github.com/sfranz2422/pyide) (Python, console and games)
and WebIDE (HTML, CSS and JavaScript) — same shape, same habits, a different
thing being taught.

**The student's Flask app does not run on a server.** Not a small one; none.
It runs in their browser, and the pieces below say how.

---

## The whole idea in one paragraph

Flask is a *server* framework, so the obvious reading is that an IDE for it
needs real hosting: a container per student, a port, a process to kill when
they close the tab. That is the reading that makes this expensive, and it is
wrong. Flask is a **WSGI application**, and a WSGI application is a Python
function you can call. You do not need a socket to exercise one —
`app.test_client()` calls it directly and hands back the response, in pure
Python, with no network anywhere.

So: Pyodide runs the student's `app.py` in the browser. The preview is an
iframe. Every link click and form submission inside that iframe is
intercepted, turned into a `test_client` request, and the response is painted
back into the iframe. To the student it is a website that responds to them. To
the machine it is a function call.

## Verified before a line was written

Measured in a real browser on Pyodide 314.0.6, against a real app, before this
repo existed — because the whole plan rests on it:

| | |
|---|---|
| `micropip.install("flask")` | **397 ms** — Jinja2, MarkupSafe and click come from Pyodide's own package set, not PyPI |
| Versions | Flask 3.1.3, Werkzeug 3.1.8, Jinja2 3.1.6, Python 3.14.2 |
| Routes and variable rules | `/greet/Steve` → `<p>Hello, Steve!</p>` |
| Templates from **files** | `templates/index.html` extending `base.html`, with blocks, loops and filters |
| `url_for('static', …)` | resolves, and `/static/style.css` serves with `text/css; charset=utf-8` |
| POST forms | `a=17, b=25` → `total = 42` |
| Redirects | `302`, `Location: /` |
| State across requests | a pet appended by a POST appeared on the next `GET /` |
| Unknown route | `404` |

The template case is the one that mattered most. Students write
`templates/index.html`, not `render_template_string`, and that needs Flask to
find files on Pyodide's virtual filesystem. It does, inheritance included.

## Three things learned on the way in

**`allow-forms` is not optional, and its absence is silent.** With
`sandbox="allow-scripts"` alone the browser blocks a form submission *before
any listener runs*: the submit event never fires, so the interception never
gets to `preventDefault`. The form does nothing. No error, no console
warning. Measured with a probe iframe either way — zero submit events with
`allow-scripts`, one with `allow-scripts allow-forms`.

It costs nothing in isolation. `allow-same-origin` is the one that would
matter, and it stays off.

*I first wrote this up as something WebIDE had got wrong. It is not.*
WebIDE's preview already uses `allow-scripts allow-forms`, and the comment
above its iframe says almost exactly what the one in `preview.js` says — it
hit this when forms were added there and wrote down the answer. I asserted
otherwise without reading the file. (WebIDE's `static/runner.js` docstring
still says `allow-scripts`, which is now the only stale copy of the claim
anywhere and is worth a one-line fix there.)

**Emscripten will not let you delete the directory you are standing in.**
Loading a project ends with `os.chdir` into it, so a student's
`open("data.txt")` means what they expect. That leaves the process inside
the directory the *next* Run has to remove. Linux allows that; Emscripten
raises `OSError: [Errno 10] Resource busy: '/project'`. So the first Run
worked and the second died — which is the worst shape a bug can take in an
editor, because it looks like the student's edit broke it.

This is the limit of "Pyodide is a CPython, so a logic error here is a logic
error there". That holds for logic and not for filesystem semantics, and no
amount of running the bridge on CPython would have found it — only pressing
Run twice in a browser did. `tools/test_bridge.py` now checks the invariant
instead of the symptom: at the moment the tree is removed, the process must
not be standing in it. That is testable anywhere, and it is the thing that
was actually wrong.

**Top-level `await` needs `runPythonAsync` semantics.** PyIDE's console mode
compiles the student's program first, to report syntax errors nicely, and that
compile does not allow top-level await — so `await micropip.install("flask")`
fails with `SyntaxError on line 2: 'await' outside function`. The runtime here
installs Flask itself rather than making the student do it, so this never
reaches them; it is written down because it cost an hour to find.

**`werkzeug.__version__` no longer exists** in Werkzeug 3.x. Anything that
wants a version number uses `importlib.metadata.version("werkzeug")`. Older
tutorials will tell students otherwise.

---

## Layout

```
static/flask.js     boots Pyodide, installs Flask, runs the student's app,
                    and answers requests through test_client
static/preview.js   the iframe: intercepts links and forms, routes them
                    through flask.js, paints what comes back
static/app.js       the editor shell (tabs, Run, the console)
templates/          this site's own pages — not the student's
app.py              the Flask app that SERVES the IDE. Nothing to do with
                    the Flask app a student writes, which never comes here.
accounts.py         identical file to PyIDE's and WebIDE's, on purpose
```

**`app.py` and the student's `app.py` are different programs**, and that is
the most confusing thing about this repository. This one is a real server on
Render, serving the editor. Theirs runs in their browser and never touches
this machine. Everything under `static/` that says "flask" is about theirs.

## A project is several files, because Flask is

`app.py` on its own is not a Flask project — the first template makes it
`templates/`, and the first stylesheet makes it `static/`. So multi-file is
not a feature to add later here the way it was for PyIDE; it is the starting
point. Files are tabs, and the folder is implied by the name:
`templates/index.html` is a tab called `templates/index.html`.

## Two kinds of project: Flask, and SQL

The **+ SQL** button opens a SQL project. Same editor, same accounts, same
Publish and Turn in, same Render service — the bill does not change, because
none of this runs on the server. Pyodide is already there for Flask, and
`sqlite3` is in Python's standard library, so SQL mode downloads *nothing
extra*: it is cheaper to start than Flask mode, which has to `micropip
install flask`.

**A project's kind is read off its files.** One containing `query.sql` is a
SQL project; anything else is a Flask app. Nothing is stored — no `kind`
column, no flag — because `drafts` and `assignments` are shared with PyIDE and
WebIDE, so a column here would be a migration in three repositories for a fact
the files already state, and a second source of truth that can disagree with
the first. `kind_of()` in `app.py` and `isSql()` in `app.js` are the same rule
written twice; **if you change one, change the other.**

The chip beside the project name is a *label*, not a switch. Adding
`query.sql` is how a project becomes a SQL project, so a control there could
only ever disagree with the files.

### schema.sql builds a real database

Any project holding a `schema.sql` gets `data.db` built from it, from scratch,
**before every Run** — in both kinds. That is the one rule, and it is what
lets SQL live in this editor rather than a separate one:

- A **SQL project** runs `query.sql` against it, one statement at a time, and
  each statement gets its own table of results.
- A **Flask app** opens it with `sqlite3.connect("data.db")` — ordinary
  Python, nothing invented, transferable to any machine. The starter's `app.py`
  carries the pattern commented out.

So a class can learn the query on its own, then put a page in front of it.

Rebuilt every Run means a student cannot wreck it: delete every row, drop
every table, press Run, it is back. It also means anything they `INSERT` while
experimenting is gone next Run, which the starter says in its first comment.

### SQLite ignores foreign keys unless you ask

`PRAGMA foreign_keys = ON`, **on every connection**. Without it SQLite stores
a course taught by teacher 4242, who does not exist, and reports success; the
`REFERENCES` in the schema is remembered and not enforced. It is a property of
the connection, not of the file, so it has to be set again by anything else
that opens the same database — including a student's own `sqlite3.connect()`
in a Flask route. That is why the commented starter sets it and says why.

The editor's own connections set it. `tools/test_sql.py` proves it by
inserting a bad row and requiring the refusal.

### The dataset

`examples/schema.sql` — teachers, students, courses, enrollments — is shaped
for what has to be taught rather than for realism:

| | |
|---|---|
| one-to-many | three teachers have two courses each |
| `JOIN` vs `LEFT JOIN` | 8 rows against 9 — Petrov teaches nothing |
| many-to-many | `enrollments`, one row per student per course |
| `GROUP BY`, `AVG` | students take different numbers of courses |

Petrov is the point of the whole file. Give that row a course and the
difference between `JOIN` and `LEFT JOIN` becomes invisible, which is why
`tools/test_sql.py` fails if anybody does.

They are real `.sql` files, not Python strings, so they can be opened, run
against `sqlite3` and edited — and so the tests can run them.

## Accounts

Shares PyIDE's database and the `users` / `assignments` / `drafts` /
`submissions` tables, with an `app` column keeping each editor's work apart —
exactly as WebIDE does. `accounts.py` is the same file in all three
repositories, so one sign-in is one person across every class.

There is no `databases:` block in `render.yaml` for the same reason: paste
PyIDE's internal connection string at deploy time.

---

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Sign-in is off unless the Google variables are set, and everything except
saving works without it.

## Tests

```bash
python3 tools/test_bridge.py    # the runtime, on real Flask, no browser
python3 tools/test_app.py       # this server, the file rules, the wiring
python3 tools/test_sql.py       # SQL mode, on real SQLite
python3 tools/test_tabstops.py  # Tab and Backspace in the editor
```

`test_bridge.py` lifts the Python out of `static/flask.js` and runs it on
CPython. Pyodide is a CPython, so a logic error there is a logic error in the
browser, found in a second rather than after a page load.

`test_app.py` covers the half that is easy to get wrong silently: that every
`$("id")` in the editor's JavaScript matches an element that actually exists
in the template, and that every script the page loads is a file in the repo.
Neither failure produces an error — the button is simply dead, or the editor
simply does not start, and the page renders perfectly either way.

`test_sql.py` runs the starter's queries on real SQLite and checks what the
dataset claims: that `LEFT JOIN` returns more rows than `JOIN`, that exactly
one teacher has none, that a bad foreign key is refused, that a 21,952-row
runaway is clipped instead of handed to the browser, and that a Flask route
can read the same `data.db`.

**It executes the bridge the way the browser receives it** — template literal
unescaped — rather than reading `static/flask.js` as if it were Python. That
is not pedantry. JavaScript eats one level of escaping on the way through, so
`\\*` in the file arrives at Python as `\*`; written singly, the
comment-stripping regex arrives as `/*.*?*/` and raises `re.error: multiple
repeat` at import, on the first Run, before a student has typed anything. A
test reading the file as Python would have passed.
