/* FlaskIDE — running a student's Flask app in their own browser.
 *
 * Flask is a server framework, so an IDE for it looks like it needs a server
 * per student. It does not. A Flask app is a WSGI application, and a WSGI
 * application is a function you can call: `app.test_client()` calls it
 * directly and hands back the response, in pure Python, with no socket and
 * no network anywhere.
 *
 * So this boots Pyodide, installs Flask into it, writes the student's files
 * onto the virtual filesystem, imports their app, and then answers requests
 * by calling it. What the browser sees is a website. What is happening is a
 * function call.
 *
 * WHY THE FILES GO ON A REAL FILESYSTEM RATHER THAN BEING PASSED IN
 *
 * Because `render_template("index.html")` opens a file. Jinja's loader walks
 * `templates/`, `{% extends "base.html" %}` opens another one, and
 * `url_for('static', filename='style.css')` expects a directory. Handing
 * Flask the text of a template instead would mean reimplementing its loader,
 * and would diverge the moment a student wrote something the reimplementation
 * had not thought of. Pyodide has a filesystem; this uses it, and what runs
 * is Flask's own code doing its own thing.
 *
 * WHY EVERY RUN GETS A NEW INTERPRETER STATE
 *
 * Module-level code runs once per import. A student who fixes a typo in a
 * route and presses Run again must get their fix, not the module Python
 * cached the first time — and every Flask tutorial has module-level state in
 * it (a list of posts, a counter) that has to start over too. So a run
 * clears the project directory, drops the student's modules out of
 * `sys.modules`, and imports again. Pyodide itself is kept: booting it costs
 * seconds, and importing a module costs milliseconds.
 */

(function () {
  "use strict";

  const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.6/full/";
  const PROJECT = "/project";

  let pyodide = null;
  let booting = null;
  let onOutput = () => {};

  /* ---------------------------------------------------------------- boot */

  async function boot(report) {
    if (pyodide) return pyodide;
    if (booting) return booting;

    booting = (async () => {
      report && report("Loading Python…");
      const py = await loadPyodide({
        indexURL: PYODIDE_URL,
        stdout: (line) => onOutput(line + "\n"),
        stderr: (line) => onOutput(line + "\n"),
      });

      report && report("Loading Flask…");
      await py.loadPackage("micropip");
      // Installed here rather than by the student. It is also why the
      // student's program never needs a top-level `await`, which PyIDE's
      // console compile step does not allow.
      await py.runPythonAsync(
        'import micropip\nawait micropip.install("flask")\n'
      );

      await py.runPythonAsync(BRIDGE);
      pyodide = py;
      report && report("");
      return py;
    })();

    return booting;
  }

  /* ------------------------------------------------------------- the run */

  /**
   * Put the student's files in place and import their app.
   * `files` is { "app.py": "...", "templates/index.html": "..." }.
   * Resolves to { ok: true, routes: [...] } or { ok: false, error: "..." }.
   */
  async function run(files, report) {
    const py = await boot(report);
    onOutput("");
    py.globals.set("_files_json", JSON.stringify(files));
    const raw = await py.runPythonAsync("_flaskide_load(_files_json)");
    return JSON.parse(raw);
  }

  /**
   * One request against the student's app.
   * Resolves to { status, headers, body, isText }.
   */
  async function request(method, path, form) {
    if (!pyodide) throw new Error("nothing is running yet");
    pyodide.globals.set("_req_json", JSON.stringify({
      method: method || "GET",
      path: path || "/",
      form: form || null,
    }));
    const raw = await pyodide.runPythonAsync("_flaskide_request(_req_json)");
    return JSON.parse(raw);
  }

  function setOutput(fn) { onOutput = fn || (() => {}); }

  function isReady() { return pyodide !== null; }

  /* --------------------------------------------------------- the Python */

  const BRIDGE = `
import base64, io, json, os, shutil, sys, traceback

_FLASKIDE_PROJECT = "${PROJECT}"
_flaskide_app = None


def _flaskide_clear():
    """A run starts from nothing, so a deleted file is really deleted and a
    module-level list really starts empty."""
    global _flaskide_app
    _flaskide_app = None
    if os.path.isdir(_FLASKIDE_PROJECT):
        shutil.rmtree(_FLASKIDE_PROJECT)
    os.makedirs(_FLASKIDE_PROJECT, exist_ok=True)
    if _FLASKIDE_PROJECT not in sys.path:
        sys.path.insert(0, _FLASKIDE_PROJECT)
    # Anything the student imported last time, including app itself. Left in
    # place, a fixed typo would not take effect until the tab was reloaded.
    for name in [n for n, m in list(sys.modules.items())
                 if getattr(m, "__file__", None)
                 and str(m.__file__).startswith(_FLASKIDE_PROJECT)]:
        sys.modules.pop(name, None)


def _flaskide_load(files_json):
    """Write the files, import app.py, and find the Flask object in it."""
    from flask import Flask
    global _flaskide_app

    _flaskide_clear()
    files = json.loads(files_json)

    for name, text in files.items():
        path = os.path.join(_FLASKIDE_PROJECT, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    if "app.py" not in files:
        return json.dumps({
            "ok": False,
            "error": "There is no app.py. A Flask project needs one, and it "
                     "is the file that gets run.",
        })

    os.chdir(_FLASKIDE_PROJECT)
    try:
        import importlib
        module = importlib.import_module("app")
    except Exception:
        return json.dumps({"ok": False, "error": _flaskide_trace()})

    found = [v for v in vars(module).values() if isinstance(v, Flask)]
    if not found:
        return json.dumps({
            "ok": False,
            "error": "app.py ran, but there is no Flask app in it. Somewhere "
                     "near the top you need:\\n\\n"
                     "    from flask import Flask\\n"
                     "    app = Flask(__name__)",
        })

    _flaskide_app = found[0]

    # Let the student's own mistakes out.
    #
    # By default Flask catches an exception raised inside a route and returns
    # its own "500 Internal Server Error" page — five words of boilerplate,
    # no file, no line, no exception name. On a real server that is correct:
    # you do not show strangers your traceback. In a classroom it is the
    # worst possible answer, because the one thing the student needs is the
    # line they got wrong, and instead they get a page that looks like the
    # editor broke.
    #
    # Propagating instead means the exception reaches _flaskide_request,
    # which prints their frames and only theirs. Specific handlers a student
    # registers with @app.errorhandler still run; this only bypasses the
    # generic catch-all.
    _flaskide_app.config["PROPAGATE_EXCEPTIONS"] = True

    routes = []
    for rule in _flaskide_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        verbs = sorted(rule.methods - {"HEAD", "OPTIONS"})
        routes.append({"path": str(rule), "methods": verbs})
    routes.sort(key=lambda r: r["path"])
    return json.dumps({"ok": True, "routes": routes})


def _flaskide_request(req_json):
    """One request, through Flask's own test client."""
    req = json.loads(req_json)
    if _flaskide_app is None:
        return json.dumps({"status": 0, "headers": {}, "body":
                           "Nothing is running.", "isText": True})

    client = _flaskide_app.test_client()
    try:
        if req["method"].upper() == "POST":
            r = client.post(req["path"], data=req.get("form") or {})
        else:
            r = client.get(req["path"])
    except Exception:
        return json.dumps({"status": 500, "headers": {},
                           "body": _flaskide_trace(), "isText": True})

    kind = r.headers.get("Content-Type", "")
    text = kind.startswith("text/") or "json" in kind or "javascript" in kind
    if text:
        body = r.get_data(as_text=True)
    else:
        # An image the student put in static/. Handed over as a data: URL,
        # because the iframe has no origin to fetch it from.
        body = base64.b64encode(r.get_data()).decode("ascii")

    return json.dumps({
        "status": r.status_code,
        "headers": {k: v for k, v in r.headers.items()},
        "body": body,
        "isText": text,
    })


def _flaskide_trace():
    """The student's traceback, without the engine's half of it.

    A traceback from here starts with importlib and this file, which is
    several frames of machinery the student did not write and cannot act on.
    Only the frames inside their own project are theirs to read.
    """
    kind, value, tb = sys.exc_info()
    frames = traceback.extract_tb(tb)
    mine = [f for f in frames
            if f.filename.startswith(_FLASKIDE_PROJECT)]
    out = io.StringIO()
    if mine:
        out.write("Traceback (most recent call last):\\n")
        for f in mine:
            where = os.path.relpath(f.filename, _FLASKIDE_PROJECT)
            out.write('  File "%s", line %d, in %s\\n'
                      % (where, f.lineno, f.name))
            if f.line:
                out.write("    %s\\n" % f.line.strip())
    out.write("%s: %s" % (kind.__name__, value))
    return out.getvalue()
`;

  window.FlaskIDERuntime = { boot, run, request, setOutput, isReady, PROJECT };
})();
