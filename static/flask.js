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
    module-level list really starts empty.

    THE CHDIR IS NOT TIDINESS, IT IS THE WHOLE THING WORKING TWICE

    Loading a project ends with os.chdir into it, so that a student's
    open("data.txt") means what they expect. That leaves the process
    standing inside the directory this function then has to delete.

    Linux does not mind: you may remove the directory you are in, and the
    process simply ends up with a working directory that no longer exists.
    Emscripten's filesystem does mind, and raises

        OSError: [Errno 10] Resource busy: '/project'

    So the first Run worked and the second one died, which is the worst
    shape a bug can have in an editor — it looks like the student's edit
    broke it. Stepping out first costs one line.
    """
    global _flaskide_app
    _flaskide_app = None
    os.chdir("/")
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


_FLASKIDE_DB = "data.db"
_FLASKIDE_SCHEMA = "schema.sql"
_FLASKIDE_QUERY = "query.sql"


def _flaskide_sql_statements(text):
    """Split SQL into statements, dropping the ones that are only comments.

    NOT text.split(";"). A semicolon inside a string literal or a comment is
    not the end of a statement, and splitting there produces two fragments
    that are each a syntax error -- on a file that is perfectly valid. The
    standard library already knows where a statement ends, so ask it.

    Comment-only chunks are dropped because the last thing in a student's
    file is very often a trailing note, and executing it reports an extra
    empty result table under their real ones.
    """
    import sqlite3
    out, start = [], 0
    for i, ch in enumerate(text):
        # Only a semicolon can end a statement, so only there is it worth
        # asking. Cutting per LINE instead was the first version, and it put
        # two statements written on one line into a single chunk -- which
        # SQLite refuses with "You can only execute one statement at a time",
        # an error naming nothing a student could act on.
        if ch != ";":
            continue
        chunk = text[start:i + 1]
        # False while the semicolon is inside a string or a comment, which is
        # the whole reason this is not text.split(";").
        if sqlite3.complete_statement(chunk):
            out.append(chunk)
            start = i + 1
    tail = text[start:]
    if tail.strip():
        out.append(tail)
    return [s.strip() for s in out if _flaskide_sql_has_code(s)]


def _flaskide_sql_has_code(chunk):
    """Is there anything here but comments and whitespace?

    THE DOUBLED BACKSLASHES BELOW ARE NOT A TYPO. This whole bridge is a
    JavaScript template literal, and JavaScript eats one level of escaping
    before Python ever sees the text: \\* here arrives as \* there. Written
    singly, the regex arrives as /*.*?*/ -- "nothing to repeat" -- and every
    Run dies at import time, before a student has typed anything.
    """
    import re
    bare = re.sub(r"/\\*.*?\\*/", " ", chunk, flags=re.S)
    bare = re.sub(r"--[^\\n]*", " ", bare)
    return bool(bare.strip().strip(";"))


def _flaskide_connect():
    """A connection to the project's database, with the constraints on.

    SQLITE DOES NOT ENFORCE FOREIGN KEYS UNLESS YOU ASK, PER CONNECTION.

    A schema can declare REFERENCES on every column and SQLite will happily
    insert a course taught by teacher 4242, who does not exist, and report
    success. The declaration is remembered and ignored. It is off by default
    for backward compatibility, it is a property of the connection and not of
    the file, and it has to be turned on again by anything else that opens
    the same database -- including a student's own sqlite3.connect() in a
    Flask app, which is why the starter says so in a comment.
    """
    import sqlite3
    con = sqlite3.connect(_FLASKIDE_DB)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _flaskide_build_db(files):
    """Rebuild data.db from schema.sql. Run with the cwd inside the project.

    Every Run, from nothing. A student can delete every row, drop every
    table, or write something that half-succeeds, and the next Run puts it
    back exactly as the file describes. The cost is that anything they
    INSERT by hand is gone too, which is said out loud in the starter.

    Returns None when there is no schema.sql -- a plain Flask project that
    wants no database is not an error.
    """
    import os
    if _FLASKIDE_SCHEMA not in files:
        return None

    # Belt and braces, and said plainly: _flaskide_clear() has already
    # rmtree'd the whole project directory by the time anything reaches here,
    # so in the normal path this line finds nothing to delete. It is kept
    # because "the database is rebuilt from scratch" is a promise the starter
    # makes to students, and it should not depend on a detail of a function
    # three calls up that is really about something else.
    if os.path.exists(_FLASKIDE_DB):
        os.remove(_FLASKIDE_DB)

    con = _flaskide_connect()
    try:
        for stmt in _flaskide_sql_statements(files[_FLASKIDE_SCHEMA]):
            try:
                con.execute(stmt)
            except Exception as err:
                return {"ok": False,
                        "error": "schema.sql: %s" % err,
                        "statement": stmt}
        con.commit()
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = []
        for name in names:
            count = con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0]
            tables.append({"name": name, "rows": count})
        return {"ok": True, "tables": tables}
    finally:
        con.close()


#: No student query may return more than this many rows to the page. A
#: SELECT with a join written the wrong way round is the normal way to ask
#: for a million rows by accident, and the browser's answer to a million-row
#: table is to stop responding -- which reads as "the editor crashed".
_FLASKIDE_MAX_ROWS = 500


def _flaskide_run_sql(files_json):
    """Write the files, rebuild the database, and run query.sql.

    Each statement gets its own result: columns and rows for the ones that
    select, a count for the ones that change something. An error names the
    statement it came from, because the file holds several and "syntax error
    near FORM" does not say which one.
    """
    import json
    import os

    _flaskide_clear()
    files = json.loads(files_json)
    _flaskide_write(files)
    os.chdir(_FLASKIDE_PROJECT)

    built = _flaskide_build_db(files)
    if built is None:
        return json.dumps({"ok": False, "error":
                           "There is no schema.sql, so there is no database "
                           "to query. It is the file that describes the "
                           "tables."})
    if not built["ok"]:
        return json.dumps({"ok": False, "error": built["error"],
                           "statement": built.get("statement", "")})

    if _FLASKIDE_QUERY not in files:
        return json.dumps({"ok": False, "error":
                           "There is no query.sql. It is the file that gets "
                           "run."})

    con = _flaskide_connect()
    results = []
    try:
        for stmt in _flaskide_sql_statements(files[_FLASKIDE_QUERY]):
            try:
                cur = con.execute(stmt)
            except Exception as err:
                return json.dumps({"ok": False, "error": str(err),
                                   "statement": stmt, "results": results,
                                   "tables": built["tables"]})
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = cur.fetchmany(_FLASKIDE_MAX_ROWS + 1)
                clipped = len(rows) > _FLASKIDE_MAX_ROWS
                rows = rows[:_FLASKIDE_MAX_ROWS]
                results.append({
                    "statement": stmt,
                    "columns": columns,
                    # Anything SQLite can hold that JSON cannot -- bytes from
                    # a BLOB, mostly -- becomes its repr rather than blowing
                    # up the whole run on the way out.
                    "rows": [[_flaskide_sql_value(v) for v in row]
                             for row in rows],
                    "clipped": clipped,
                })
            else:
                results.append({"statement": stmt, "changed": cur.rowcount})
        con.commit()
    finally:
        con.close()

    return json.dumps({"ok": True, "results": results,
                       "tables": built["tables"]})


def _flaskide_sql_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return "<%d bytes>" % len(value)
    return str(value)


def _flaskide_write(files):
    """Write a project's files into /project, making folders as needed."""
    import os
    for name, text in files.items():
        path = os.path.join(_FLASKIDE_PROJECT, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)


def _flaskide_load(files_json):
    """Write the files, import app.py, and find the Flask object in it."""
    from flask import Flask
    global _flaskide_app

    _flaskide_clear()
    files = json.loads(files_json)
    _flaskide_write(files)

    if "app.py" not in files:
        return json.dumps({
            "ok": False,
            "error": "There is no app.py. A Flask project needs one, and it "
                     "is the file that gets run.",
        })

    os.chdir(_FLASKIDE_PROJECT)

    # BEFORE the import, not after. A student's app.py may open the database
    # at import time -- a module-level connection is the obvious way to write
    # one -- and building it afterwards would make that fail on the first Run
    # and work on the second, which is the worst shape a bug can have.
    #
    # A project with no schema.sql gets no database and that is not an error:
    # most Flask projects here do not want one.
    built = _flaskide_build_db(files)
    if built is not None and not built["ok"]:
        return json.dumps({"ok": False, "error": built["error"]})

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
    return json.dumps({"ok": True, "routes": routes,
                       "tables": (built or {}).get("tables", [])})


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

  /* Run a SQL project: rebuild the database from schema.sql, then run
     query.sql statement by statement.
     Boots Pyodide the same way a Flask run does, and waits the same way --
     the first Run of a session is slow for both because that is when Python
     arrives. sqlite3 itself costs nothing extra: it is in Pyodide's standard
     library, so unlike Flask there is no package to install. */
  async function runSql(files, note) {
    const py = await boot(note);
    py.globals.set("_files_json", JSON.stringify(files));
    const raw = await py.runPythonAsync("_flaskide_run_sql(_files_json)");
    py.globals.delete("_files_json");
    return JSON.parse(raw);
  }

  window.FlaskIDERuntime = { boot, run, runSql, request, setOutput, isReady,
                             PROJECT };
})();
