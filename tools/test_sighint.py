"""What goes in the brackets: the hint above a call while it is typed (FlaskIDE).

    python3 tools/test_sighint.py

WHAT IS ACTUALLY BEING GUARDED

  The hint is right about Python.
      The table in sighint.js is written by hand, in beginner's words. Every
      entry is checked against Python itself: the function or method exists
      on that type, and the number of slots it shows is a number Python
      accepts. A hint that says append(position, item) would teach the
      mistake it is there to prevent.

  Flask's entries are Flask's.
      The Flask, request and sqlite3 table is checked against the installed
      Flask and sqlite3 the same way: each exists, with slots it accepts.

  It finds the call the cursor is in, and the slot being typed.
      Not a call inside a string, not in a comment, not a `def` line; the
      bold slot follows commas and `name=`; their own functions win.

  It never writes anything.
      No insert, no replace: a hint that typed for them would be the copy
      button this app does not have.
"""
import ast
import builtins
import inspect
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


JS = os.path.join(ROOT, "static", "sighint.js")
sighint = open(JS).read()

if not shutil.which("node"):
    check("node is available to run sighint.js", False, "brew install node")
    sys.exit(1)


def node(expr_js):
    harness = ("var window = {}, document = {};\n" + sighint
               + "\nvar S = window.FlaskIDESigHint;\n"
               + "var KAY = null;\n"
               + "console.log(JSON.stringify(" + expr_js + "));")
    res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    try:
        return json.loads(res.stdout)
    except ValueError:
        print(res.stderr[-400:])
        return None


# ---------------------------------------------------------- right about Python
print("\nThe table is right about Python")
tables = node("{functions: S.FUNCTIONS, methods: S.METHODS}") or {}
MODULES = {"random": random, "math": math, "time": time}
TYPES = {"list": list, "str": str, "dict": dict, "set": set, "file": io.TextIOWrapper}


def accepts(fn, params):
    """Can Python take a call with this many plain arguments?"""
    plain = [p for p in params if not p.startswith("*")]
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True                     # no signature to ask; existence is enough
    try:
        sig.bind(*range(len(plain)))
        return True
    except TypeError:
        pass
    # keyword-only on Python's side (print's sep=, sorted's key=): bind those
    # by name, the way a student would write them
    kw = {p.split("=")[0]: 0 for p in plain if "=" in p}
    pos = [0 for p in plain if "=" not in p]
    try:
        sig.bind(*pos, **kw)
        return True
    except TypeError:
        return False


bad = []
for name, entry in (tables.get("functions") or {}).items():
    if "." in name:
        mod, attr = name.split(".")
        fn = getattr(MODULES[mod], attr, None)
    else:
        fn = getattr(builtins, name, None)
    if fn is None:
        bad.append(name + " does not exist")
        continue
    for form in entry["forms"]:
        if not accepts(fn, form):
            bad.append("%s(%s)" % (name, ", ".join(form)))
check("every function in the table exists, with slots Python accepts",
      not bad and tables.get("functions"), "; ".join(bad))

bad = []
for name, entries in (tables.get("methods") or {}).items():
    for e in entries:
        kind = TYPES.get(e["kind"])
        fn = getattr(kind, name, None) if kind else None
        if fn is None:
            bad.append("%s.%s does not exist" % (e["kind"], name))
            continue
        for form in e["forms"]:
            if not accepts(fn, ["self"] + form):
                bad.append("%s.%s(%s)" % (e["kind"], name, ", ".join(form)))
check("every method in the table exists on its type, with slots it accepts",
      not bad and tables.get("methods"), "; ".join(bad))
check("  append takes ONE thing: the item, never a position",
      (tables.get("methods") or {}).get("append", [{}])[0].get("forms") == [["item"]],
      "the mistake this hint exists to stop")

# ------------------------------------------------------------- Flask's
print("\nFlask's entries are Flask's")
import sqlite3                                              # noqa: E402
import flask                                                # noqa: E402
import werkzeug.datastructures as wds                       # noqa: E402

flask_tables = node(
    "(function () { var out = {functions: {}, methods: {}};"
    " ['Flask','render_template','redirect','url_for','abort','jsonify','flash','sqlite3.connect']"
    ".forEach(function (n) { var h = S.lookup(S.openCall(n + '('), {functions:{},methods:{}}, false, null, true);"
    " out.functions[n] = h.length ? h[0].forms : null; });"
    " ['route','get','execute','fetchall','fetchone','commit','cursor'].forEach(function (n) {"
    " out.methods[n] = S.lookup(S.openCall('x.' + n + '('), {functions:{},methods:{}}, false, null, true)"
    ".map(function (h) { return {kind: h.kind, forms: h.forms}; }); });"
    " return out; })()") or {}
FLASK_OWNERS = {
    "Flask": flask.Flask, "render_template": flask.render_template,
    "redirect": flask.redirect, "url_for": flask.url_for, "abort": flask.abort,
    "jsonify": flask.jsonify, "flash": flask.flash, "sqlite3.connect": sqlite3.connect,
}
METHOD_OWNERS = {
    ("app", "route"): flask.Flask.route,
    ("request.form / request.args", "get"): wds.MultiDict.get,
    ("sqlite3", "execute"): sqlite3.Cursor.execute,
    ("sqlite3", "fetchall"): sqlite3.Cursor.fetchall,
    ("sqlite3", "fetchone"): sqlite3.Cursor.fetchone,
    ("sqlite3", "commit"): sqlite3.Connection.commit,
    ("sqlite3", "cursor"): sqlite3.Connection.cursor,
}
bad = []
for name, forms in (flask_tables.get("functions") or {}).items():
    if not forms:
        bad.append(name + " has no hint")
        continue
    for form in forms:
        if not accepts(FLASK_OWNERS[name], form):
            bad.append("%s(%s)" % (name, ", ".join(form)))
check("every Flask function hinted is Flask's, with slots it accepts",
      not bad and flask_tables.get("functions"), "; ".join(bad))
bad = []
for name, entries in (flask_tables.get("methods") or {}).items():
    flaskish = [e for e in entries if (e["kind"], name) in METHOD_OWNERS]
    if not flaskish:
        bad.append(name + " has no Flask/sqlite3 hint")
    for e in flaskish:
        for form in e["forms"]:
            if not accepts(METHOD_OWNERS[(e["kind"], name)], ["self"] + form):
                bad.append("%s.%s(%s)" % (e["kind"], name, ", ".join(form)))
check("every Flask and sqlite3 method hinted exists, with slots it accepts",
      not bad and flask_tables.get("methods"), "; ".join(bad))

# ------------------------------------------------------ finding the call
print("\nFinding the call, and the slot")
CASES = [
    # (code up to the cursor, expected hint lines, with the bold slot in *)
    ("my_list = [1,2,3]\nmy_list.append(", ["list .append(*item*)"]),
    ("my_list.insert(0, ", ["list .insert(position, *item*)"]),
    ("x = input(", ["input(*prompt*)"]),
    ('print("a, (b", ', ["print(**values*, sep=' ', end='\\n')"]),
    ("for i in range(1, 10, ", ["range(stop)", "range(start, stop)", "range(start, stop, *step*)"]),
    ("n = random.randint(1, ", ["random.randint(low, *high*)"]),
    ("d.pop(", ["list .pop(*position=-1*)", "dict .pop(*key*, default)"]),
    ("print(sep=", ["print(*values, *sep=' '*, end='\\n')"]),
    ("def greet(name, greeting='hi'):\n    pass\ngreet('Al', ", ["greet(name, *greeting='hi'*)"]),
    ("class P:\n    def walk(self, steps):\n        pass\np.walk(", [".walk(*steps*)"]),
    ("def print(x):\n    pass\nprint(", ["print(*x*)"]),
    ("def draw(shape, **opts):\n    pass\ndraw('box', color=", ["draw(shape, ***opts*)"]),
    ("from kaypy import *\nadd([pos(10, ", []),          # no kaypy in FlaskIDE
    ("return render_template('index.html', ", ["render_template(template_name, ***values*)"]),
    ("name = request.form.get(", ["request.form / request.args .get(*name*, default=None)",
                                  "dict .get(*key*, default=None)"]),
    ("@app.route(", ["app .route(*path*, methods=['GET'])"]),
    ("conn.execute('SELECT * FROM t WHERE id = ?', ", ["sqlite3 .execute(sql, *values=()*)"]),
    ("db = sqlite3.connect(", ["sqlite3.connect(*database_file*)"]),
    ("x = get(", []),                     # kaypy's get(), but no kaypy here
    ("# print(", []),
    ("print(1,  # see input(", []),       # in a comment, though print( is open
    ("# call input(\nx = len(", ["len(*thing*)"]),   # a comment's ( is not a call
    ("def input(prompt, ", []),           # writing a function, not calling one
    ("s = 'print(", []),
    ("if (x > 3 and ", []),
    ("my_list.append(4)", []),
]
lines = node("""%s.map(function (c) {
  var call = S.openCall(c);
  if (!call) return [];
  var own = S.ownDefs([c]);
  return S.lookup(call, own, false, KAY, true).map(function (h) {
    return h.forms.map(function (f) {
      var on = S.activeIndex(f, call);
      return (h.kind && h.kind !== "yours" ? h.kind + " " : "") + h.label + "("
        + f.map(function (p, i) { return i === on ? "*" + p + "*" : p; }).join(", ") + ")";
    });
  }).reduce(function (a, b) { return a.concat(b); }, []);
})""" % json.dumps([c for c, _ in CASES])) or []
for (code, want), got in zip(CASES, lines):
    check("  %s" % json.dumps(code)[-40:], got == want, "" if got == want else "got %r" % got)
check("all the cases ran", len(lines) == len(CASES))

# --------------------------------------------------- their own functions
print("\nTheir own functions, as Python reads them")
PROGRAMS = [
    "def area(width, height):\n    return width * height\n",
    "def greet(name, greeting='hi', *rest, loud=False, **opts):\n    pass\n",
    "class Dog:\n    def __init__(self, name):\n        self.name = name\n"
    "    def bark(self, times=1):\n        pass\n",
    "def typed(x: int, y: float = 2.0) -> int:\n    return x\n",
    "def defaults(d={'a': 1}, t=(1, 2)):\n    pass\n",
    "if True:\n    def inner(a, b):\n        pass\n",
    "def joined(items, sep=', ', end=')'):\n    pass\n",
]
got = node("%s.map(function (p) { return S.ownDefs([p]); })" % json.dumps(PROGRAMS)) or []


def by_ast(src):
    fns, methods = {}, {}
    for node_ in ast.walk(ast.parse(src)):
        if isinstance(node_, ast.FunctionDef):
            a = node_.args
            ps = [x.arg for x in a.posonlyargs + a.args]
            first_default = len(ps) - len(a.defaults)
            out = []
            for i, p in enumerate(ps):
                out.append(p + ("=" + ast.unparse(a.defaults[i - first_default])
                                if i >= first_default else ""))
            if a.vararg:
                out.append("*" + a.vararg.arg)
            for k, d in zip(a.kwonlyargs, a.kw_defaults):
                out.append(k.arg + ("=" + ast.unparse(d) if d is not None else ""))
            if a.kwarg:
                out.append("**" + a.kwarg.arg)
            if out and out[0] in ("self", "cls"):
                methods[node_.name] = out[1:]
            else:
                fns[node_.name] = out
    return fns, methods


def norm(params):
    # ast spells strings with single quotes and no spaces after commas inside
    return [re.sub(r"\s+", "", p).replace('"', "'") for p in params]


for src, g in zip(PROGRAMS, got):
    fns, methods = by_ast(src)
    same = ({k: norm(v) for k, v in fns.items()}
            == {k: norm(v["forms"][0]) for k, v in g["functions"].items()}
            and {k: norm(v) for k, v in methods.items()}
            == {k: norm(v["forms"][0]) for k, v in g["methods"].items()})
    check("  " + src.split("\n")[0][:52], same,
          "" if same else "ast %r / scanner %r" % ((fns, methods), g))

# ---------------------------------------------------------- the wiring
print("\nThe wiring")
code_only = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", sighint)
check("it never writes into the editor",
      not re.search(r"replaceRange|replaceSelection|setValue|\.insert\(", code_only),
      "a hint that types for them is a copy button")
check("it takes no clicks", re.search(
    r"\.sig-hint\s*\{[^}]*pointer-events:\s*none",
    open(os.path.join(ROOT, "static", "style.css")).read()) is not None)
check("it sits above the line, where completion's list never opens",
      "box.style.top = (c.top - h - 2)" in sighint)
check("Escape puts it away", 'e.key === "Escape" && box' in sighint)
for page, js, ed in (("editor", "app.js", "editor"), ("live page", "live.js", "mine")):
    src = open(os.path.join(ROOT, "static", js)).read()
    _a = src[src.index("window.FlaskIDESigHint.attach(%s, {" % ed):] if (
        "window.FlaskIDESigHint.attach(%s, {" % ed) in src else ""
    check("the %s attaches it, with Flask's table on" % page,
          _a[:_a.find("});")].count("flask: true") == 1)
live = open(os.path.join(ROOT, "static", "live.js")).read()
_att = live[live.index("window.FlaskIDESigHint.attach(mine"):]
_att = _att[:_att.index("});")]
check("  and on the live page reads only the student's own tabs",
      "docs[n].getValue()" in _att and "mirror" not in _att,
      "the teacher's functions would be offered by another route")
for tpl in ("index.html", "live.html"):
    page = open(os.path.join(ROOT, "templates", tpl)).read()
    check("%s loads sighint.js before the page's own script" % tpl,
          -1 < page.find("filename='sighint.js'")
          < page.find("filename='%s'" % ("app.js" if tpl == "index.html" else "live.js")))
check("kaypy's hints are never on in FlaskIDE",
      "var kaypyOn = !opts.flask && KAYPY.test(cm.getValue());" in sighint)

failed = results.count(False)
print("\n%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                       len(results), failed))
sys.exit(1 if failed else 0)
