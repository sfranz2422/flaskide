#!/usr/bin/env python3
"""The Python half of the runtime, tested without a browser.

    python3 tools/test_bridge.py

`static/flask.js` carries a block of Python in a template string — the part
that writes the student's files down, imports their app, finds the Flask
object in it, and answers requests through `test_client`. That Python is the
whole runtime; the JavaScript around it is plumbing.

Python in a JavaScript string is Python nothing can run, so this pulls the
block back out of `flask.js` and executes it against real Flask on CPython.
Pyodide is a CPython, so a logic error here is a logic error there, and this
finds it in a second rather than after a page load.

WHAT IS CHECKED, AND WHY EACH ONE

  * a project loads and its routes are reported — the editor shows them
  * a second run sees edited files, and module-level state starts over.
    This is the one most likely to be got wrong and least likely to be
    noticed: Python caches modules, so a student who fixes a typo and
    presses Run again would keep getting the old code, and conclude the
    editor is broken.
  * a deleted file is really gone on the next run
  * templates, inheritance, url_for and static files all work off the
    virtual filesystem, because `render_template` opens files
  * GET, POST, redirect and 404 come back with the right status
  * a student's mistake produces a traceback with only THEIR frames in it
  * app.py missing, or present with no Flask object, says so in words
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RUNTIME = ROOT / "static" / "flask.js"

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-56s %s" % ("ok" if ok else "FAIL", label, detail))


def done():
    bad = results.count(False)
    print("\n%s (%d checks, %d failed)"
          % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
    sys.exit(1 if bad else 0)


# ------------------------------------------------- lift the Python back out
text = RUNTIME.read_text()
match = re.search(r"const BRIDGE = `(.*?)`;", text, re.S)
if not match:
    sys.exit("No `const BRIDGE = ...` in static/flask.js — if it was renamed, "
             "this test is checking nothing and would go on passing.")

bridge = match.group(1)
# It lives in a JS template string, so it is written with escaped newlines and
# backticks. Undo exactly what the string literal did to it.
bridge = bridge.replace("\\\\n", "\\n").replace("\\`", "`").replace("\\$", "$")
bridge = bridge.replace("${PROJECT}", "/tmp/flaskide-test-project")

check("the runtime's Python was found and unescaped",
      "_flaskide_load" in bridge and "_flaskide_request" in bridge,
      "%d lines" % bridge.count("\n"))

scope = {}
exec(compile(bridge, "flask.js:BRIDGE", "exec"), scope)
load = scope["_flaskide_load"]
request = scope["_flaskide_request"]


def get(path, method="GET", form=None):
    return json.loads(request(json.dumps(
        {"method": method, "path": path, "form": form})))


# ------------------------------------------------------------- a project
PROJECT = {
    "app.py": '''from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
pets = ["cat", "dog"]


@app.route("/")
def home():
    return render_template("index.html", pets=pets)


@app.route("/add", methods=["POST"])
def add():
    pets.append(request.form["name"])
    return redirect(url_for("home"))
''',
    "templates/base.html": '<!doctype html><title>{% block t %}{% endblock %}</title>'
                           '<link rel="stylesheet" href="{{ url_for(\'static\','
                           ' filename=\'style.css\') }}">{% block b %}{% endblock %}',
    "templates/index.html": '{% extends "base.html" %}{% block t %}Pets{% endblock %}'
                            '{% block b %}<ul>{% for p in pets %}'
                            '<li>{{ p }}</li>{% endfor %}</ul>{% endblock %}',
    "static/style.css": "h1 { color: rebeccapurple }",
}

out = json.loads(load(json.dumps(PROJECT)))
check("a project loads", out.get("ok"), out.get("error", "")[:60])
check("  and its routes are reported",
      [r["path"] for r in out.get("routes", [])] == ["/", "/add"],
      str(out.get("routes")))
check("  with the methods each one takes",
      any(r["path"] == "/add" and r["methods"] == ["POST"]
          for r in out.get("routes", [])))
check("  and the static route is left out of the list",
      all("/static/" not in r["path"] for r in out.get("routes", [])))

# ------------------------------------------------------------- requests
r = get("/")
check("GET / renders a template", r["status"] == 200 and "<li>cat</li>" in r["body"],
      "%s" % r["body"][:70])
check("  through template inheritance", "<!doctype html>" in r["body"])
check("  with url_for resolving the stylesheet",
      'href="/static/style.css"' in r["body"])

r = get("/static/style.css")
check("a static file is served", r["status"] == 200 and "rebeccapurple" in r["body"])
check("  as text, with a type", r["isText"] and
      "css" in r["headers"].get("Content-Type", ""),
      r["headers"].get("Content-Type"))

r = get("/add", "POST", {"name": "bean"})
check("a POST redirects", r["status"] == 302 and
      r["headers"].get("Location") == "/", r["headers"].get("Location"))

r = get("/")
check("  and the change is there on the next request", "<li>bean</li>" in r["body"])

r = get("/nope")
check("an unknown path is a 404", r["status"] == 404)

# ------------------------------------------- THE ONE THAT MATTERS: re-running
#
# Python caches imported modules. Without clearing them, a student's edit
# would have no effect until the tab was reloaded — the single most
# maddening possible bug in an editor, because the editor looks like it is
# lying about what it just ran.
EDITED = dict(PROJECT)
EDITED["app.py"] = PROJECT["app.py"].replace(
    'pets = ["cat", "dog"]', 'pets = ["fish"]')
EDITED["templates/index.html"] = EDITED["templates/index.html"].replace(
    "<li>{{ p }}</li>", "<li>** {{ p }} **</li>")

out = json.loads(load(json.dumps(EDITED)))
check("the project loads a second time", out.get("ok"), out.get("error", "")[:60])
r = get("/")
check("an edit to app.py takes effect on the next Run",
      "fish" in r["body"] and "cat" not in r["body"], r["body"][:70])
check("  and module-level state starts over",
      "bean" not in r["body"], "the pet added by the POST is gone, as it should be")
check("an edit to a template takes effect too", "** fish **" in r["body"])

# A file the student deleted must actually go.
SHRUNK = {k: v for k, v in EDITED.items() if k != "static/style.css"}
load(json.dumps(SHRUNK))
r = get("/static/style.css")
check("a deleted file is really deleted", r["status"] == 404, "got %d" % r["status"])

# ----------------------------------------------------- when they get it wrong
BROKEN = {"app.py": '''from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return 1 / 0
'''}
out = json.loads(load(json.dumps(BROKEN)))
check("an app that imports fine still loads", out.get("ok"))
r = get("/")
check("a crash in a route is reported, not swallowed", r["status"] == 500)
check("  and the traceback names their file and line",
      'File "app.py"' in r["body"] and "ZeroDivisionError" in r["body"],
      r["body"].replace("\n", " ⏎ ")[:80])
check("  without the engine's own frames in it",
      "importlib" not in r["body"] and "flask.js" not in r["body"])

SYNTAX = {"app.py": "from flask import Flask\napp = Flask(__name__\n"}
out = json.loads(load(json.dumps(SYNTAX)))
check("a syntax error is reported as a failure to load", not out.get("ok"))
check("  naming the error", "SyntaxError" in out.get("error", ""),
      out.get("error", "").replace("\n", " ⏎ ")[:70])

out = json.loads(load(json.dumps({"templates/index.html": "<p>hi</p>"})))
check("no app.py says so in words", not out.get("ok") and
      "app.py" in out.get("error", ""), out.get("error", "")[:60])

out = json.loads(load(json.dumps({"app.py": "x = 1\n"})))
check("an app.py with no Flask app says so, and shows the two lines",
      not out.get("ok") and "Flask(__name__)" in out.get("error", ""),
      out.get("error", "").replace("\n", " ⏎ ")[:70])

# --------------------------------------------------- the sandbox attribute
#
# Not something this file can exercise — it needs a browser — but it can
# stop the attribute being quietly narrowed back.
#
# Without `allow-forms` this silently kills every form: the browser blocks the
# submission BEFORE any listener runs, so the submit event never fires and
# preview.js never gets to preventDefault it. Nothing errors. The form just
# does nothing. Measured in a browser: zero submit events with
# `allow-scripts`, one with `allow-scripts allow-forms`.
#
# Somebody "tidying" the attribute down to `allow-scripts` would break half
# a Flask unit and see no failure anywhere. Hence a test with no browser.
for name in ("static/proof.html",):
    html = (ROOT / name).read_text()
    frames = re.findall(r'<iframe[^>]*sandbox="([^"]*)"', html)
    check("%s sandboxes its iframe" % name, bool(frames), str(frames))
    check("  with allow-forms, or every form silently does nothing",
          all("allow-forms" in f for f in frames), str(frames))
    check("  and without allow-same-origin, which is the dangerous one",
          all("allow-same-origin" not in f for f in frames), str(frames))

# Flattened first: the comment is wrapped and prefixed with " * ", so a
# search for a sentence in it otherwise fails on where the line happens to
# break — which is a test failing for a reason that is not about the code.
preview = (ROOT / "static" / "preview.js").read_text()
flat = " ".join(preview.replace("*", " ").split())
check("preview.js says why allow-forms is there",
      "allow-forms" in flat
      and "BEFORE any listener runs" in flat
      and "zero submit events" in flat)

done()
