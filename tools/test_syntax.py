"""The syntax card: Python's message, said so a beginner can fix it (FlaskIDE).

    python3 tools/test_syntax.py

When a student presses Run the page asks Python, before running anything,
whether it can read the project's .py files (_flaskide_check in flask.js).
If not, a card
over the editor says what is wrong in plain words (syntax.js), with Python's
own message under it.

WHAT IS ACTUALLY BEING GUARDED

  The words match the Python students really have.
      Every sentence is chosen by matching Python's message, and Python
      rewords its messages between versions. So the mistakes below are run
      through Pyodide's own Python (borrowed from ../pyide/node_modules,
      the same Pyodide version this app loads), and each
      must get its own sentence. A Pyodide upgrade that rewords one fails
      here rather than showing a class the vague fallback.

  Every rule still fires.
      A rule no real message matches any more is dead weight that looks like
      coverage. Each one must be hit by at least one mistake below.

  Syntax only.
      The check compiles and never runs, so a program that reads fine — even
      one that is wrong, or would crash — gets no card, and nothing in it is
      executed by the check.

  Both pages check before they run.
      The editor and the class's live page, before a game loads or anything
      is pushed into Python.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-58s %s" % ("ok" if condition else "FAIL", label, detail))


# Each: (the student's code, a phrase their sentence must contain).
CASES = [
    ('print("hi"\nx = 1\n', "missing a closing `)`"),
    ('x = [1, 2\nprint(x)\n', "missing a closing `]`"),
    ('d = {"a": 1\n', "missing a closing `}`"),
    ('print("hi"))\n', "extra `)`"),
    ('x = (1, 2]\n', "closed with `)`"),
    ('if x > 3\n    print(x)\n', "needs a colon `:`"),
    ('for i in range(3)\n    print(i)\n', "needs a colon `:`"),
    ('def f()\n    return 1\n', "needs a colon `:`"),
    ('if x:\n    pass\nelse if y:\n    pass\n', "as one word: `elif`"),
    ('else:\n    pass\n', "has no `if` right above it"),
    ('elif x:\n    pass\n', "has no `if` right above it"),
    ('print("hi)\n', "never ends"),
    ('s = """abc\n', "three quotes"),
    ('x = [1 2 3]\n', "comma `,` is missing"),
    ('if x = 3:\n    pass\n', "use `==` to compare"),
    ('f(x) = 3\n', "must be a variable name. To compare"),
    ('x == 3 = y\n', "must be a variable name."),
    ('True = 1\n', "keeps for itself"),
    ('if x > 3:\nprint(x)\n', "inside an `if` go in by 4 spaces"),
    ('for i in range(3):\nprint(i)\n', "inside a `for` go in by 4 spaces"),
    ('def f():\nreturn 1\n', "inside a `def` or `class`"),
    ('class A:\npass\n', "inside a `def` or `class`"),
    ('x = 1\n    y = 2\n', "is indented, but nothing above it"),
    ('if x:\n        a = 1\n    b = 2\n', "doesn't line up"),
    ('if x:\n\ta = 1\n        b = 2\n', "mixes tabs and spaces"),
    ('print "hi"\n', "needs parentheses"),
    ('print(\u201chi\u201d)\n', "curly quote"),
    ('x = 2y\n', "runs straight into letters"),
    ('return 5\n', "inside a `def`"),
    ('break\n', "inside a loop"),
    ('continue\n', "inside a loop"),
    ('try:\n    x = 1\nprint(x)\n', "needs an `except:` or `finally:`"),
    ('import\n', "needs the name"),
    ('x = f"{}"\n', "f-string"),
    ('whlie x < 3:\n    pass\n', "did you mean `while`"),
    ('fro i in range(3):\n    pass\n', "did you mean `for`"),
    ('x = 5 +\n', "ends in the middle"),
]

# Programs Python can read. No card for any of them, however wrong.
READS = [
    'print(1 / 0)\n',                       # crashes when run
    'print(undefined_name)\n',              # crashes when run
    'total = 0\nfor i in range(10):\n    total = i\nprint(total)\n',  # wrong logic
    'print("RAN-THE-PROGRAM")\n',           # must not be run by the check
]

# FlaskIDE has no node_modules of its own; PyIDE's, beside it, has the same
# Pyodide. Absent, this fails saying so, as the node checks do without node.
PYODIDE = os.path.join(os.path.dirname(ROOT), "pyide", "node_modules", "pyodide", "pyodide.mjs")

# _flaskide_check, lifted out of flask.js's BRIDGE (a JS template string, so
# its `\\` are one backslash to Python). Run on its own: the rest of the
# bridge needs Flask, which would mean the network.
_flask_js = open(os.path.join(ROOT, "static", "flask.js")).read()
_m = re.search(r"\ndef _flaskide_check\(files_json\):[\s\S]*?\n    return ''\n", _flask_js)
CHECK_PY = "import json\n" + (_m.group(0).replace("\\\\", "\\") if _m else "")

if not shutil.which("node"):
    check("node is available to run Pyodide", False, "brew install node")
elif not os.path.exists(PYODIDE):
    check("Pyodide is beside this, in ../pyide/node_modules", False,
          "check out pyide next to flaskide, or npm install pyodide there")
else:
    harness = """
import { loadPyodide } from %s;
import fs from "fs";
globalThis.window = {};
eval(fs.readFileSync(%s, "utf8"));
const py = await loadPyodide();
let printed = "";
py.setStdout({ batched: s => { printed += s + "\\n"; } });
py.runPython(%s);
const S = window.FlaskIDESyntax;
// What FlaskIDERuntime.check does, minus booting Flask.
S.check = (py, source, others) => {
  py.globals.set("_files_json", JSON.stringify(Object.assign({ "app.py": source }, others || {})));
  const raw = py.runPython("_flaskide_check(_files_json)");
  return raw ? JSON.parse(raw) : null;
};
const cases = %s, reads = %s;
const out = { version: py.runPython("import sys; sys.version.split()[0]"), cases: [], reads: [] };
for (const [src] of cases) {
  const info = S.check(py, src, {});
  out.cases.push(info ? Object.assign({ said: S.explain(info) }, info) : null);
}
for (const src of reads) out.reads.push(S.check(py, src, {}));
out.printed = printed;
out.helper = S.check(py, "import helper\\nprint(helper.f())\\n",
  { "helper.py": "def f(:\\n    return 1\\n", "words.txt": "(((" });
out.helperSaid = out.helper ? S.explain(out.helper).friendly : "";
out.dataOnly = S.check(py, "print(1)\\n", { "words.txt": "((( not python" });
out.rules = S.RULES.map(r => String(r[0]));
out.ruleHits = S.RULES.map(r => out.cases.some(c => c && r[0].test(c.msg)));
console.log(JSON.stringify(out));
""" % (json.dumps(PYODIDE), json.dumps(os.path.join(ROOT, "static", "syntax.js")),
       json.dumps(CHECK_PY),
       json.dumps([[c] for c, _ in CASES]), json.dumps(READS))
    res = subprocess.run(["node", "--input-type=module", "-e", harness],
                         capture_output=True, text=True, cwd=ROOT)
    try:
        got = json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    print("\nThe words, against Pyodide's own Python %s" % got.get("version", "?"))
    check("Pyodide ran the check", bool(got.get("cases")), res.stderr[-300:])
    for (src, want), info in zip(CASES, got.get("cases") or []):
        said = (info or {}).get("said", {})
        ok = bool(info) and said.get("known") and want in said.get("friendly", "")
        check("  %s" % json.dumps(src)[:44], ok,
              "" if ok else "%r -> %r" % ((info or {}).get("msg"), said.get("friendly")))
    check("Python's own message is always shown with it",
          all(c and c["said"]["python"].startswith(c["kind"] + ": " + c["msg"])
              for c in got.get("cases") or [None]))

    print("\nEvery rule still fires")
    for rule, hit in zip(got.get("rules", []), got.get("ruleHits", [])):
        check("  " + rule[:56], hit, "no real message matches it any more")

    print("\nSyntax only")
    check("code Python can read gets no card, however wrong it is",
          got.get("reads") == [None] * len(READS), repr(got.get("reads")))
    check("  and the check runs none of it", "RAN-THE-PROGRAM" not in got.get("printed", ""),
          "the check executed the student's program")
    h = got.get("helper") or {}
    check("an error in helper.py is found before main.py imports it",
          h.get("file") == "helper.py" and h.get("line") == 1)
    check("  and the card says which file", "of helper.py" in got.get("helperSaid", ""))
    check("the lifted check is the one in flask.js", bool(_m),
          "_flaskide_check moved or was renamed")
    check("a data file is never read as Python", got.get("dataOnly") is None)

# ------------------------------------------------------------ the wiring
print("\nThe wiring")
syntax_js = open(os.path.join(ROOT, "static", "syntax.js")).read()
for page, js in (("editor", "app.js"), ("live page", "live.js")):
    src = open(os.path.join(ROOT, "static", js)).read()
    run = src[src.index("async function run()"):]
    run = run[:run.index("\n  }\n")]
    at = run.find("var bad = await runtime.check(")
    later = run.find("await runtime.run(")
    check("the %s checks before it loads the app" % page,
          -1 < at < later, "a typo would surface as a traceback from inside Flask")
    check("  and stops there when Python can't read it",
          re.search(r"if \(bad\) \{[^}]*syntaxCard\.show\(bad\);\s*return;\s*\}", run) is not None)
    check("  and still prints Python's message in the console",
          re.search(r"if \(bad\) \{[^}]*?\w+\(\"SyntaxError in \"", run) is not None)
check("flask.js offers the check, and a broken one says null",
      re.search(r"async function check\(files, report\)[\s\S]*?catch \(e\) \{\s*return null;",
                _flask_js) is not None
      and "check, PROJECT" in _flask_js)
for tpl in ("index.html", "live.html"):
    page = open(os.path.join(ROOT, "templates", tpl)).read()
    check("%s loads syntax.js" % tpl, "filename='syntax.js'" in page)
_code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", syntax_js)   # code, not comments
check("the card is built as text, never innerHTML", "innerHTML" not in _code,
      "the message quotes the student's own characters")
# Over the output pane, where Run's result would have gone — not the editor,
# and not under Python's raw message: one message to read.
for js, host in {'app.js': 'host: $("preview-view"),', 'live.js': 'host: $("output-view"),'}.items():
    src = open(os.path.join(ROOT, "static", js)).read()
    at = src.find("window.FlaskIDESyntax.attach({")
    check("the card covers the output pane (%s)" % js,
          at > -1 and src[at:at + 200].find(host) > -1,
          "it sat over the editor, under the friendly message's raw twin")
live_src = open(os.path.join(ROOT, "static", "live.js")).read()
live_run = live_src[live_src.index("async function run()"):]
live_run = live_run[:live_run.index("\n  }\n")]
check("  the live page opens its folded console before showing it",
      re.search(r"if \(bad\) \{[^}]*?openConsole\(true\);[^}]*?syntaxCard\.show\(bad\)",
                live_run) is not None,
      "the card would be put inside a pane that is folded shut")
check("  and fills it", re.search(r"\.syntax-card \{[^}]*inset: 8px",
                                  open(os.path.join(ROOT, "static", "style.css")).read()) is not None)
check("the card goes away as soon as they type",
      'ed.on("change", onChange)' in syntax_js)

failed = results.count(False)
print("\n%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                       len(results), failed))
sys.exit(1 if failed else 0)
