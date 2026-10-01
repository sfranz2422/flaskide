#!/usr/bin/env python3
"""Name completion finds the same names Python's own parser does.

    python3 tools/test_complete.py

WHY THIS COMPARES AGAINST `ast`

static/complete.js finds a student's names with a small scanner rather than
by asking Python, because Pyodide is not loaded until the first Run and
completion that waited for it would be missing while the typos are being
made. A scanner is exactly the kind of code that is right on the three
examples its author thought of and wrong on the fourth. So every program
below is handed to both — the shipped JavaScript, run in node, and the same
`ast` walk PyIDE uses — and the two answers have to agree exactly.

A name the scanner misses is a suggestion that never appears. A name it
invents (`self` from `self.x = 1`, `int` from `x: int = 5`, `a` from
`a[0] = 1`) is a suggestion for something that does not exist, which is
worse: it is the typo this feature is supposed to prevent, offered helpfully.
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
COMPLETE = (ROOT / "static" / "complete.js").read_text()

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-58s %s" % ("ok" if ok else "FAIL", label, detail))


def done():
    bad = results.count(False)
    print("\n%s (%d checks, %d failed)"
          % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
    sys.exit(1 if bad else 0)


def by_ast(source):
    """PyIDE's collector: the reference answer."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            a = node.args
            for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
                names.add(arg.arg)
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                names.add(al.asname or al.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return sorted(n for n in names if not n.startswith("_"))


PROGRAMS = {
    "a Flask app": '''
from flask import Flask, render_template, request, redirect
import sqlite3 as db

app = Flask(__name__)
TASKS = ["write", "test"]


@app.route("/")
def index():
    count: int = len(TASKS)
    return render_template("index.html", tasks=TASKS, count=count)


@app.route("/add", methods=["POST"])
def add_task(limit=10, *extra, verbose: bool = False, **options):
    title = request.form.get("title", "").strip()
    if title and len(TASKS) < limit: TASKS.append(title)
    return redirect("/")
''',
    "unpacking, loops and comprehensions": '''
first, (second, *rest) = [1, (2, 3, 4)]
for row, col in [(0, 1)]:
    total = row + col
squares = [n * n for n in range(5) if n % 2]
pairs = {k: v for k, v in {"a": 1}.items()}
while (line := input()) != "q":
    total += 1
''',
    "things that look like names but are not": '''
class Player:
    def __init__(self, name):
        self.name = name
        self.score = 0

grid = [[0] * 3 for _ in range(3)]
grid[0][1] = 5
settings = {}
settings["theme"] = "dark"
scores[0] = 1                  # defined elsewhere; this defines nothing
board[1][2].owner = "x"
result = len("x = 1")          # x = 2 in a comment
message = """
y = 3 inside a string
"""
if total == 3 or total >= 4 or total != 5:
    pass
print(sep="", end="\\n")
''',
    "with, except, lambda, chained": '''
import os.path, json
from math import (floor,
                  ceil as up)
with open("f") as handle, open("g") as (other):
    data = json.load(handle)
try:
    risky = 1 / 0
except ZeroDivisionError as err:
    a = b = c = 0
key = lambda item, reverse=False: item
n = 1; m = 2
n += 1
long_name = \\
    5
''',
}

if not shutil.which("node"):
    check("node is available", False, "brew install node")
    done()

script = COMPLETE + """
const progs = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
for (const k of Object.keys(progs)) out[k] = window.FlaskIDEComplete.names(progs[k]);
console.log(JSON.stringify(out));
"""
res = subprocess.run(["node", "-e", "var window = {};" + script],
                     input=json.dumps(PROGRAMS), capture_output=True, text=True)
try:
    got = json.loads(res.stdout)
except ValueError:
    check("complete.js runs in node", False, res.stderr[-400:])
    done()

for label, src in PROGRAMS.items():
    want = by_ast(src)
    have = got.get(label, [])
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    check("%s: the same names as ast" % label, not missing and not extra,
          ("missing %s " % missing if missing else "")
          + ("invented %s" % extra if extra else ""))

# Half-typed code is the normal state of a file being written; the scanner
# must not throw on it, or suggestions vanish exactly while typing.
res = subprocess.run(
    ["node", "-e", "var window = {};" + COMPLETE + """
console.log(JSON.stringify(window.FlaskIDEComplete.names('def broken(a, b\\n  x = "unclosed\\nfor ')));
"""], capture_output=True, text=True)
check("half-typed code gives names rather than an error",
      res.returncode == 0 and "broken" in res.stdout, res.stdout or res.stderr[-200:])

# Both editors actually offer it, and only for Python.
app_js = (ROOT / "static" / "app.js").read_text()
live_js = (ROOT / "static" / "live.js").read_text()
index = (ROOT / "templates" / "index.html").read_text()
live = (ROOT / "templates" / "live.html").read_text()
check("the editor loads complete.js", "complete.js" in index)
check("  and attaches it to the editor, for .py files only",
      "FlaskIDEComplete.attach(editor" in app_js
      and "FlaskIDEComplete.isPy(current)" in app_js)
check("the live page loads it and the popup",
      "complete.js" in live and "show-hint.min.js" in live
      and "show-hint.min.css" in live)
# For .py tabs only, as in the editor — the live pane has tabs now, so a
# SQL lesson is no longer the only place a word is not a Python name: a
# template or a stylesheet is open half the time.
check("  and attaches it to the student's own editor, for .py tabs only",
      "FlaskIDEComplete.attach(mine" in live_js
      and "return window.FlaskIDEComplete.isPy(active);" in live_js)
# Their own .py files, read from their own documents — never the mirror,
# which would be the copy button by another route.
_src = live_js[live_js.index("FlaskIDEComplete.attach(mine"):]
_src = _src[:_src.index("});")]
check("  with the student's own code as the only source",
      "docs[n].getValue()" in _src and "mirror" not in _src
      and "/\\.py$/i.test(n)" in _src)

done()
