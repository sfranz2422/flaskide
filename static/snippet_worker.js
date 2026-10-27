/* The worker snippets.js runs notes' Python in — its own Pyodide, so a
 * snippet never shares a namespace with the student's program, and a loop
 * that never ends is stopped by ending this worker (snippets.js does that).
 *
 * Each run gets a fresh namespace. Output is sent back as it's printed, so
 * a slow loop shows its lines as they come. Packages a snippet imports
 * (random is built in; numpy isn't) are fetched the first time.
 */
// A MODULE worker (snippets.js starts it with type: "module"), loading
// Pyodide's ES module build. A classic worker's importScripts of pyodide.js
// failed with a NetworkError though the same file fetched fine, and
// Python never started; the module build loads.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/pyodide.mjs";
var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/";

var current = 0;
var started = loadPyodide({ indexURL: PYODIDE }).then(function (py) {
  py.setStdout({ batched: function (s) { postMessage({ type: "out", id: current, text: s + "\n" }); } });
  py.setStderr({ batched: function (s) { postMessage({ type: "out", id: current, text: s + "\n", err: true }); } });
  postMessage({ type: "ready" });
  return py;
}, function (e) {
  postMessage({ type: "failed", message: String(e && e.message || e) });
});

// No one can type into a snippet's input(): say so, instead of hanging.
var SETUP = [
  "def input(prompt=''):",
  "    raise RuntimeError('input() needs someone to type, and code in the notes can\\'t ask. Try this in main.py instead.')",
].join("\n");

/* What a beginner needs from a traceback: the line in their snippet and
   what went wrong — "Line 3: NameError: name 'x' is not defined" — not
   Pyodide's own frames above it. */
function tidy(message) {
  var text = String(message || "");
  var lines = text.trim().split("\n").filter(function (l) { return l.trim(); });
  var last = lines.length ? lines[lines.length - 1].trim() : text;
  var at = null, re = /File "<exec>", line (\d+)/g, m;
  while ((m = re.exec(text))) at = m[1];
  return (at ? "Line " + at + ": " : "") + last;
}

onmessage = function (e) {
  var job = e.data || {};
  started.then(function (py) {
    current = job.id;
    var ns = py.globals.get("dict")();
    return py.loadPackagesFromImports(job.code, { messageCallback: function () {}, errorCallback: function () {} })
      .catch(function () { /* the import itself will say what's missing */ })
      .then(function () {
        py.runPython(SETUP, { globals: ns, filename: "<setup>" });
        return py.runPythonAsync(job.code, { globals: ns, filename: "<exec>" });
      })
      .then(function () {
        postMessage({ type: "done", id: job.id });
      }, function (err) {
        postMessage({ type: "done", id: job.id, error: tidy(err && err.message || err) });
      })
      .finally(function () { ns.destroy(); });
  });
};
