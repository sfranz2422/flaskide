#!/usr/bin/env python3
"""Code that runs in the notes (static/snippets.js, snippet_worker.js),
against the real Pyodide.

    python3 tools/test_snippets.py

A ```python run block runs in a worker of its own. The worker is run here
in node, with stand-ins for the two things a browser worker has that node
doesn't — importScripts (which loads Pyodide) and postMessage (which here
just records) — so what's tested is the worker's own code:

  * what a snippet prints comes back, a line at a time
  * an error says which line of THE SNIPPET and what went wrong, not
    Pyodide's frames above it
  * input() says plainly that notes can't ask, instead of hanging
  * each run starts fresh: a variable from one run isn't in the next,
    or a student would get different results from the same code
  * stdlib imports work

The same file is in WebIDE and FlaskIDE; this test is too.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKER = os.path.join(ROOT, "static", "snippet_worker.js")
SNIPPETS = os.path.join(ROOT, "static", "snippets.js")
# This repo's Pyodide, or PyIDE's beside it: WebIDE and FlaskIDE have no
# node_modules of their own, and borrow PyIDE's as test_syntax.py does.
PYODIDE_DIR = os.path.join(ROOT, "node_modules", "pyodide")
if not os.path.isdir(PYODIDE_DIR):
    PYODIDE_DIR = os.path.join(os.path.dirname(ROOT), "pyide", "node_modules", "pyodide")

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else "   " + str(detail)[:300]))


if not shutil.which("node"):
    print("  FAIL node is needed: brew install node")
    sys.exit(1)
if not os.path.isdir(PYODIDE_DIR):
    print("  FAIL Pyodide isn't installed: npm install in pyide (node_modules/pyodide), checked out beside this repo")
    sys.exit(1)

RUNS = [
    "for i in range(3):\n    print(i * 2)",
    "x = 1\nprint(y)",
    "name = input('Name? ')",
    "x = 5",
    "print(x)",
    "import random\nrandom.seed(1)\nprint(len(str(random.random())) > 3)",
]

harness = r"""
const vm = require("vm");
const fs = require("fs");
const { loadPyodide } = require(%(pyodide)s);
const sent = [];
const sandbox = {
  importScripts() {},
  loadPyodide: () => loadPyodide(),
  postMessage: (m) => sent.push(m),
  console,
  setTimeout,
};
vm.createContext(sandbox);
// The worker is a module that imports Pyodide from the CDN; here node's own
// Pyodide stands in for it (sandbox.loadPyodide), so the import line goes.
const src = fs.readFileSync(%(worker)s, "utf8").replace(/^import \{ loadPyodide \} from .*$/m, "");
vm.runInContext(src, sandbox);
const runs = %(runs)s;
(async () => {
  // Wait for "ready", then each run in turn, as snippets.js sends them.
  while (!sent.some((m) => m.type === "ready" || m.type === "failed")) await new Promise((r) => setTimeout(r, 50));
  const out = [];
  for (let i = 0; i < runs.length; i++) {
    const id = i + 1;
    sandbox.onmessage({ data: { id, code: runs[i] } });
    while (!sent.some((m) => m.type === "done" && m.id === id)) await new Promise((r) => setTimeout(r, 20));
    const mine = sent.filter((m) => m.id === id);
    out.push({
      text: mine.filter((m) => m.type === "out" && !m.err).map((m) => m.text).join(""),
      err: mine.filter((m) => m.type === "out" && m.err).map((m) => m.text).join(""),
      error: (mine.find((m) => m.type === "done") || {}).error || "",
    });
  }
  console.log(JSON.stringify(out));
  process.exit(0);
})();
""" % {"pyodide": json.dumps(PYODIDE_DIR), "worker": json.dumps(WORKER), "runs": json.dumps(RUNS)}

print("\nThe worker, in node's Pyodide")
res = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=300)
try:
    got = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = []
check("it ran every snippet", len(got) == len(RUNS), res.stderr[-400:])
if len(got) == len(RUNS):
    printed, name_err, asked, setx, readx, imported = got
    check("what a snippet prints comes back", printed["text"] == "0\n2\n4\n" and not printed["error"], printed)
    check("an error names the snippet's own line and what's wrong",
          name_err["error"] == "Line 2: NameError: name 'y' is not defined", name_err)
    check("input() says notes can't ask, instead of hanging",
          "input() needs someone to type" in asked["error"] and asked["error"].startswith("Line 1:"), asked)
    check("each run starts fresh: a variable from the last run isn't there",
          not setx["error"] and "NameError" in readx["error"], (setx, readx))
    check("the standard library imports", imported["text"] == "True\n" and not imported["error"], imported)

print("\nThe page's half")
src = open(SNIPPETS).read()
check("the worker is a module, loading Pyodide's module build (a classic worker's importScripts failed)",
      'new Worker(WORKER, { type: "module" })' in src
      and 'import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/pyodide.mjs"' in open(WORKER).read())
check("a snippet is stopped after a time limit, by ending its worker",
      "TIME_LIMIT = 10000" in src and "stopWorker();" in src and "worker.terminate()" in src)
check("an html block runs in a frame with scripts but no same origin, like WebIDE's preview",
      'out.setAttribute("sandbox", "allow-scripts")' in src and "allow-same-origin" not in src.split("*/", 1)[1])
check("a predict question's JavaScript runs in a frame with scripts but no same origin, and is given up on in time",
      'frame.setAttribute("sandbox", "allow-scripts");' in src and "function runJs(code)" in src
      and "var timer = setTimeout(function () {\n        finish(" in src)
check("predict waits for a prediction before Run works",
      "run.disabled = !!(guess && !guess.value.trim())" in src)

failed = results.count(False)
print("\n" + ("ALL PASSED" if not failed else "SOME FAILED") + " (%d checks, %d failed)" % (len(results), failed))
sys.exit(1 if failed else 0)
