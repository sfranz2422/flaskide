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
```

`test_bridge.py` lifts the Python out of `static/flask.js` and runs it on
CPython. Pyodide is a CPython, so a logic error there is a logic error in the
browser, found in a second rather than after a page load.

`test_app.py` covers the half that is easy to get wrong silently: that every
`$("id")` in the editor's JavaScript matches an element that actually exists
in the template, and that every script the page loads is a file in the repo.
Neither failure produces an error — the button is simply dead, or the editor
simply does not start, and the page renders perfectly either way.
