/* Tests in an assignment's notes: reading them, and running them.
 *
 * autograde.py has the format and the reasons. This reads a ```tests block
 * exactly as autograde.parse does — test_autograde.py holds the two to each
 * other — and runs the tests in Pyodide: on the student's page for Check my
 * work, on the teacher's for Check all. Nothing here runs on the server.
 *
 * The app is loaded the way Run loads it (flask.js, _flaskide_load), and
 * each request goes through Flask's own test client, under a time limit so a
 * route that never returns fails its test rather than freezing the page. A
 * SQL project's tests run query.sql the way Run does (_flaskide_run_sql).
 *
 * The global is PyIDETests in all three editors (notes.js looks for it);
 * the tests themselves are each editor's own.
 */
window.PyIDETests = (function () {
  "use strict";

  var FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  var POINTS = /\s*\((\d{1,4}(?:\.\d{1,2})?)\s*points?\)\s*$/i;
  var REQUEST = /^(GET|POST)\s+(\/\S*)\s*(.*)$/i;
  var STATUS = /^\d{3}$/;
  var CONTAINS = /^contains\s+(.+)$/i;
  var CODE = /^(uses|avoids|defines)\s+(.+?)\s*$/i;
  var ROWS = /^returns\s+(\d{1,6})\s+rows?$/i;
  var RESULT = /^result\s+contains\s+(.+)$/i;
  var WORDS = { "for": "a for loop", "while": "a while loop", "if": "an if statement",
                "def": "a function", "function": "a function", "return": "return",
                "else": "else", "elif": "elif", "try": "try / except",
                "list": "a list", "dict": "a dictionary", "class": "a class" };

  function blocks(md) {
    var out = [], lines = String(md || "").split("\n"), i = 0;
    while (i < lines.length) {
      var f = FENCE.exec(lines[i]);
      if (f && f[2].trim().toLowerCase() === "tests") {
        var fence = f[1], body = [];
        i++;
        while (i < lines.length) {
          var g = FENCE.exec(lines[i]);
          if (g && g[1][0] === fence[0] && g[1].length >= fence.length && !g[2].trim()) break;
          body.push(lines[i]);
          i++;
        }
        out.push(body.join("\n"));
      }
      i++;
    }
    return out;
  }

  function label(t) {
    if (t.kind === "request") {
      var said = t.method + " " + t.path + (t.form ? " with " + t.form : "");
      return t.status !== null ? said + " answers " + t.status : said + " shows " + t.expect;
    }
    if (t.kind === "rows") return "The query returns " + t.count + " row" + (t.count === 1 ? "" : "s");
    if (t.kind === "result") return "The query's result contains " + t.expect;
    if (t.kind === "defines") return "Defines " + t.name + "()";
    var word = Object.prototype.hasOwnProperty.call(WORDS, t.name.toLowerCase())
      ? WORDS[t.name.toLowerCase()] : t.name;
    return (t.kind === "uses" ? "Uses " : "Doesn't use ") + word;
  }

  function request(line) {
    var m = REQUEST.exec(line);
    if (!m) return null;
    var rest = m[3].trim(), form = "";
    if (rest.slice(0, 2) === "->") {
      rest = rest.slice(2).trim();
    } else if (!CONTAINS.test(rest)) {
      var parts = rest.split(/\s+/);
      if (parts.length < 2 || parts[0].indexOf("=") < 0) return null;
      form = parts[0];
      rest = rest.slice(rest.indexOf(form) + form.length).trim();
      if (rest.slice(0, 2) === "->") rest = rest.slice(2).trim();
    }
    var t = { kind: "request", method: m[1].toUpperCase(), path: m[2],
              form: form, status: null, expect: "" };
    var c = CONTAINS.exec(rest);
    if (STATUS.test(rest)) t.status = parseInt(rest, 10);
    else if (c) t.expect = c[1].trim();
    else return null;
    return t;
  }

  function parseBlock(body) {
    var tests = [], errors = [];
    String(body || "").split("\n").forEach(function (raw, idx) {
      var line = raw.trim();
      if (!line || line.charAt(0) === "#") return;
      var points = 1, m = POINTS.exec(line), t = null;
      if (m) {
        points = parseFloat(m[1]);
        line = line.slice(0, m.index).replace(/\s+$/, "");
      }
      t = request(line);
      if (!t && (m = ROWS.exec(line))) t = { kind: "rows", count: parseInt(m[1], 10) };
      if (!t && (m = RESULT.exec(line))) t = { kind: "result", expect: m[1].trim() };
      if (!t && (m = CODE.exec(line))) {
        var name = m[2].trim();
        if (name.slice(-2) === "()") name = name.slice(0, -2);
        t = { kind: m[1].toLowerCase(), name: name };
      }
      if (!t) {
        errors.push("Line " + (idx + 1) + " of the tests isn't a test: " + line);
        return;
      }
      t.points = points;
      t.label = label(t);
      tests.push(t);
    });
    return { tests: tests, errors: errors };
  }

  function parse(md) {
    var tests = [], errors = [];
    blocks(md).forEach(function (b) {
      var got = parseBlock(b);
      tests = tests.concat(got.tests);
      errors = errors.concat(got.errors);
    });
    return { tests: tests, errors: errors };
  }

  /* Every test in a project's notes (each .md), as autograde.file_tests. */
  function fromFiles(files) {
    var tests = [], errors = [];
    Object.keys(files || {}).sort().forEach(function (name) {
      if (/\.md$/i.test(name)) {
        var got = parse(files[name]);
        tests = tests.concat(got.tests);
        errors = errors.concat(got.errors);
      }
    });
    return { tests: tests, errors: errors };
  }

  /* Which slide each of fromFiles(files)'s tests is written on, in the same
     order: [{slide, title}] (slide from 1, as the slide counter shows it;
     title the slide's first heading), null for a test in notes with no
     slides. Check my work heads its results with these, so a student told
     "check after every step" sees the step they are on, not one long list.

     The notes are cut by `Notes` (notes.js's slides()), the viewer's own
     cutter, so the numbers can't differ from the ones on screen. If the
     count comes out different from fromFiles' anyway, it returns null and
     the results are shown as one list — an unheaded list beats headings
     over the wrong tests. */
  /* A slide's first heading, skipping fenced code: "# a comment" in a
     Python example is not the slide's title. */
  function heading(text) {
    var fence = null, lines = text.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var f = /^ {0,3}(`{3,}|~{3,})/.exec(lines[i]);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
        continue;
      }
      var h = fence === null && /^ {0,3}#{1,6}[ \t]+(.+?)[ \t#]*$/.exec(lines[i]);
      if (h) return h[1];
    }
    return "";
  }

  function places(files, Notes) {
    if (!Notes || !Notes.slides) return null;
    var out = [];
    Object.keys(files || {}).sort().forEach(function (name) {
      if (!/\.md$/i.test(name)) return;
      var cut = Notes.slides(files[name]);
      if (!cut.length) {
        parse(files[name]).tests.forEach(function () { out.push(null); });
        return;
      }
      cut.forEach(function (text, i) {
        var where = { slide: i + 1, title: heading(text) };
        parse(text).tests.forEach(function () { out.push(where); });
      });
    });
    return out.length === fromFiles(files).tests.length ? out : null;
  }

  /* The Python that runs the tests, defined once per Pyodide after flask.js's
     bridge (it uses _flaskide_load, _flaskide_app and _flaskide_run_sql).
     A plain string, not a template literal: nothing in it is JavaScript's to
     unescape (flask.js says what that costs). */
  var HARNESS = [
    "import ast as _ag_ast, contextlib as _ag_ctx, html as _ag_html, io as _ag_io",
    "import json as _ag_json, re as _ag_re, sys as _ag_sys, time as _ag_time",
    "from urllib.parse import parse_qsl as _ag_qsl",
    "",
    "class _AgTimeUp(Exception): pass",
    "",
    "def _ag_limited(fn, seconds):",
    "    '''fn(), stopped after `seconds`: a route or an import that never",
    "    returns fails its test instead of freezing the page.'''",
    "    deadline = _ag_time.monotonic() + seconds",
    "    ticks = [0]",
    "    def guard(frame, event, arg):",
    "        ticks[0] += 1",
    "        if ticks[0] % 500 == 0 and _ag_time.monotonic() > deadline:",
    "            raise _AgTimeUp()",
    "        return guard",
    "    _ag_sys.settrace(guard)",
    "    try:",
    "        with _ag_ctx.redirect_stdout(_ag_io.StringIO()):",
    "            return fn()",
    "    finally:",
    "        _ag_sys.settrace(None)",
    "",
    "def _ag_norm(text):",
    "    return ' '.join(str(text).split()).lower()",
    "",
    "def _ag_text(body):",
    "    '''A page as a reader sees it: tags out, &amp; and the like undone.'''",
    "    return _ag_html.unescape(_ag_re.sub(r'<[^>]+>', ' ', body))",
    "",
    "def _ag_short(text, n=160):",
    "    text = ' '.join(str(text).split())",
    "    return text if len(text) <= n else text[:n] + '…'",
    "",
    "def _ag_last_line(text):",
    "    lines = [l for l in str(text).strip().splitlines() if l.strip()]",
    "    return lines[-1].strip() if lines else str(text)",
    "",
    "_AG_NODES = {'for': (_ag_ast.For, _ag_ast.comprehension), 'while': (_ag_ast.While,),",
    "             'if': (_ag_ast.If, _ag_ast.IfExp), 'def': (_ag_ast.FunctionDef,),",
    "             'function': (_ag_ast.FunctionDef,), 'return': (_ag_ast.Return,),",
    "             'try': (_ag_ast.Try,), 'class': (_ag_ast.ClassDef,),",
    "             'list': (_ag_ast.List, _ag_ast.ListComp), 'dict': (_ag_ast.Dict, _ag_ast.DictComp)}",
    "",
    "_AG_OPS = {'+': (_ag_ast.Add, _ag_ast.UAdd), '-': (_ag_ast.Sub, _ag_ast.USub), '*': (_ag_ast.Mult,),",
    "           '/': (_ag_ast.Div,), '//': (_ag_ast.FloorDiv,), '%': (_ag_ast.Mod,), '**': (_ag_ast.Pow,),",
    "           '==': (_ag_ast.Eq,), '!=': (_ag_ast.NotEq,), '<': (_ag_ast.Lt,), '<=': (_ag_ast.LtE,),",
    "           '>': (_ag_ast.Gt,), '>=': (_ag_ast.GtE,), 'and': (_ag_ast.And,), 'or': (_ag_ast.Or,),",
    "           'not': (_ag_ast.Not,), 'in': (_ag_ast.In, _ag_ast.NotIn)}",
    "",
    "def _ag_uses(trees, word):",
    "    w = word.strip()",
    "    low = w.lower()",
    "    if low.startswith('import '):",
    "        mod = w.split(None, 1)[1].strip()",
    "        for tree in trees:",
    "            for n in _ag_ast.walk(tree):",
    "                if isinstance(n, _ag_ast.Import) and any(a.name.split('.')[0] == mod for a in n.names):",
    "                    return True",
    "                if isinstance(n, _ag_ast.ImportFrom) and (n.module or '').split('.')[0] == mod:",
    "                    return True",
    "        return False",
    "    # An operator (uses +, uses ==, uses and): found in the code's tree,",
    "    # so a + inside a string doesn't count. Read as a name it could never",
    "    # be found, and the check failed on code that plainly used it.",
    "    ops = _AG_OPS.get(low)",
    "    if ops:",
    "        return any(isinstance(n, ops) for tree in trees for n in _ag_ast.walk(tree))",
    "    kinds = _AG_NODES.get(low)",
    "    for tree in trees:",
    "        for n in _ag_ast.walk(tree):",
    "            if kinds and isinstance(n, kinds):",
    "                return True",
    "            if not kinds and ((isinstance(n, _ag_ast.Name) and n.id == w) or",
    "                              (isinstance(n, _ag_ast.Attribute) and n.attr == w) or",
    "                              (isinstance(n, _ag_ast.alias) and (n.asname or n.name) == w)):",
    "                return True",
    "    return False",
    "",
    "def _ag_request(t, seconds):",
    "    # The run's own client (flask.js keeps one per load), so a login in",
    "    # one test is still logged in for the next, in the order written, as",
    "    # in a browser. A test of `-> contains` follows a redirect, as a",
    "    # browser does after a form; a test of a status sees the status.",
    "    client = _flaskide_client or _flaskide_app.test_client()",
    "    follow = t['status'] is None",
    "    def go():",
    "        if t['method'] == 'POST':",
    "            return client.post(t['path'], data=dict(_ag_qsl(t['form'] or '', keep_blank_values=True)), follow_redirects=follow)",
    "        return client.get(t['path'] + (('?' + t['form']) if t['form'] else ''), follow_redirects=follow)",
    "    try:",
    "        r = _ag_limited(go, seconds)",
    "    except _AgTimeUp:",
    "        return False, 'Still running after %d seconds. Is there a loop that never ends?' % seconds",
    "    except BaseException as e:",
    "        return False, 'The route crashed: %s: %s' % (type(e).__name__, e)",
    "    body = r.get_data(as_text=True)",
    "    if t['status'] is not None:",
    "        if r.status_code == t['status']:",
    "            return True, ''",
    "        hint = ' Is there a route for %s?' % t['path'] if r.status_code == 404 else ''",
    "        return False, 'It answered %d.%s' % (r.status_code, hint)",
    "    want = _ag_norm(t['expect'])",
    "    if want in _ag_norm(body) or want in _ag_norm(_ag_text(body)):",
    "        return True, ''",
    "    if r.status_code != 200:",
    "        return False, 'It answered %d: %s' % (r.status_code, _ag_short(_ag_text(body)) or '(empty)')",
    "    return False, 'It showed: ' + (_ag_short(_ag_text(body)) or '(an empty page)')",
    "",
    "def _flaskide_autograde(files_json, tests_json, seconds=5):",
    "    files = _ag_json.loads(files_json)",
    "    tests = _ag_json.loads(tests_json)",
    "    trees, unreadable = [], None",
    "    for name, text in sorted(files.items()):",
    "        if name.endswith('.py'):",
    "            try:",
    "                trees.append(_ag_ast.parse(text, name))",
    "            except SyntaxError as e:",
    "                unreadable = '%s can\\'t be read: line %s: %s' % (name, e.lineno, e.msg)",
    "    found = {}",
    "    # The app first: requests need it loaded, and a SQL run (below) clears it.",
    "    if any(t['kind'] == 'request' for t in tests) and not unreadable:",
    "        try:",
    "            loaded = _ag_json.loads(_ag_limited(lambda: _flaskide_load(files_json), seconds))",
    "        except _AgTimeUp:",
    "            loaded = {'ok': False, 'error': 'Loading app.py was still running after %d seconds.' % seconds}",
    "        except BaseException as e:",
    "            loaded = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}",
    "        for i, t in enumerate(tests):",
    "            if t['kind'] != 'request':",
    "                continue",
    "            if not loaded.get('ok'):",
    "                found[i] = (False, 'The app didn\\'t load: ' + _ag_last_line(loaded.get('error', '')))",
    "            else:",
    "                found[i] = _ag_request(t, seconds)",
    "    if any(t['kind'] in ('rows', 'result') for t in tests):",
    "        try:",
    "            ran = _ag_json.loads(_ag_limited(lambda: _flaskide_run_sql(files_json), seconds))",
    "        except _AgTimeUp:",
    "            ran = {'ok': False, 'error': 'The query was still running after %d seconds.' % seconds}",
    "        except BaseException as e:",
    "            ran = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}",
    "        last = [r for r in ran.get('results', []) if r.get('columns') is not None]",
    "        last = last[-1] if last else None",
    "        for i, t in enumerate(tests):",
    "            if t['kind'] not in ('rows', 'result'):",
    "                continue",
    "            if not ran.get('ok'):",
    "                found[i] = (False, 'The SQL didn\\'t run: ' + _ag_last_line(ran.get('error', '')))",
    "            elif last is None:",
    "                found[i] = (False, 'query.sql has no SELECT, so there is no result to check.')",
    "            elif t['kind'] == 'rows':",
    "                n = len(last['rows'])",
    "                found[i] = (n == t['count'], '' if n == t['count'] else 'It returned %d row%s.' % (n, '' if n == 1 else 's'))",
    "            else:",
    "                cells = ' | '.join(str(v) for row in last['rows'] for v in row)",
    "                ok = _ag_norm(t['expect']) in _ag_norm(cells)",
    "                found[i] = (ok, '' if ok else 'It returned: ' + (_ag_short(cells) or '(no rows)'))",
    "    results = []",
    "    for i, t in enumerate(tests):",
    "        ok, detail = False, ''",
    "        try:",
    "            if i in found:",
    "                ok, detail = found[i]",
    "            elif unreadable:",
    "                detail = unreadable",
    "            elif t['kind'] == 'request':",
    "                detail = unreadable or 'Not checked.'",
    "            elif t['kind'] == 'defines':",
    "                ok = any(isinstance(n, (_ag_ast.FunctionDef, _ag_ast.AsyncFunctionDef))",
    "                         and n.name == t['name'] for tree in trees for n in _ag_ast.walk(tree))",
    "                if not ok:",
    "                    detail = 'There\\'s no def %s(...) in the code.' % t['name']",
    "            elif t['kind'] in ('uses', 'avoids'):",
    "                used = _ag_uses(trees, t['name'])",
    "                ok = used if t['kind'] == 'uses' else not used",
    "                if not ok:",
    "                    detail = ('It isn\\'t in the code yet.' if t['kind'] == 'uses'",
    "                              else 'The code uses it.')",
    "        except BaseException as e:",
    "            detail = '%s: %s' % (type(e).__name__, e)",
    "        results.append({'label': t['label'], 'ok': bool(ok), 'detail': detail,",
    "                        'points': t['points']})",
    "    earned = round(sum(r['points'] for r in results if r['ok']), 2)",
    "    possible = round(sum(r['points'] for r in results), 2)",
    "    return _ag_json.dumps({'results': results, 'earned': earned, 'possible': possible})",
    ""
  ].join("\n");

  var ready = typeof WeakSet === "function" ? new WeakSet() : null;

  /* Run `tests` against `files` (name → text). `runtime` is
     window.FlaskIDERuntime (or anything with boot() resolving to a Pyodide
     that has flask.js's bridge). Resolves {results, earned, possible}. */
  async function run(runtime, files, tests) {
    var py = await runtime.boot();
    if (!ready || !ready.has(py)) {
      py.runPython(HARNESS);
      if (ready) ready.add(py);
    }
    py.globals.set("_ag_files", JSON.stringify(files));
    py.globals.set("_ag_tests", JSON.stringify(tests));
    try {
      return JSON.parse(await py.runPythonAsync("_flaskide_autograde(_ag_files, _ag_tests)"));
    } finally {
      py.globals.delete("_ag_files");
      py.globals.delete("_ag_tests");
    }
  }

  /* A ```tests block in rendered notes, as a list a student can read: what
     they will be checked on, in words. Left as code when it can't be read. */
  function renderBlocks(root) {
    Array.prototype.forEach.call(root.querySelectorAll("pre > code.language-tests"), function (code) {
      var got = parseBlock(code.textContent);
      if (!got.tests.length) return;
      // With checks_in_notes.js on the page, a card the student checks their
      // work from, results and all; without it, the list of what's checked.
      if (window.IDENotesChecks) {
        code.parentNode.replaceWith(window.IDENotesChecks.card(got.tests, "✔ Tests your code will be checked against"));
        return;
      }
      var box = document.createElement("div");
      box.className = "tests-card";
      var head = document.createElement("div");
      head.className = "tests-head";
      head.textContent = "✔ Tests your code will be checked against";
      box.appendChild(head);
      var list = document.createElement("ul");
      got.tests.forEach(function (t) {
        var li = document.createElement("li");
        li.textContent = t.label + (t.points !== 1 ? "  (" + t.points + " points)" : "");
        list.appendChild(li);
      });
      box.appendChild(list);
      code.parentNode.replaceWith(box);
    });
  }

  return { parse: parse, parseBlock: parseBlock, fromFiles: fromFiles, places: places, run: run,
           renderBlocks: renderBlocks, HARNESS: HARNESS };
})();
