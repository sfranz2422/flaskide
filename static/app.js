/* FlaskIDE — the editor: tabs, Run, and the pane that shows their site.
 *
 * The interesting parts are elsewhere. flask.js runs the student's app in
 * Pyodide; preview.js turns the iframe into something that behaves like a
 * browser. This is the shell around them, and it is deliberately the same
 * shell as WebIDE's so that a student who used that one in the first
 * semester does not have to learn an editor again in the second.
 *
 * WHAT IS DIFFERENT FROM THE OTHER TWO EDITORS
 *
 * Files here have folders in them. `templates/index.html` is one tab whose
 * name contains a slash, because that is where Flask looks for it and
 * anywhere else it is simply not found. So the tab strip groups by folder
 * and the New file box knows the two names that are allowed.
 *
 * And Run means something different. In WebIDE, Run paints a page. Here it
 * imports a Python module, which either works or raises, and then the app
 * sits there waiting to be asked for a path. So Run reports the routes it
 * found — which is also the fastest way for a student to see that the
 * decorator they just wrote did not take.
 */

(function () {
  "use strict";

  var cfg = window.FLASKIDE || {};
  var runtime = window.FlaskIDERuntime;
  var $ = function (id) { return document.getElementById(id); };

  var files = Object.assign({}, cfg.files || {});
  var current = cfg.entry || "app.py";
  var editor = null;
  var account = null;
  var preview = null;
  var running = false;

  /* ------------------------------------------------------------ output */

  var out = $("output");

  function say(text, cls) {
    if (!out) return;
    var node = document.createElement("span");
    if (cls) node.className = cls;
    node.textContent = text;
    out.appendChild(node);
    out.scrollTop = out.scrollHeight;
  }

  function clearOutput() { if (out) out.textContent = ""; }

  /* ------------------------------------------------------------ editing */

  /* CodeMirror has no mode that is both Jinja and HTML, and a template is
   * both. jinja2 highlights the {% %} and leaves the HTML plain; htmlmixed
   * does the reverse. Templates are mostly HTML with a few tags in them, so
   * htmlmixed is the one that makes a page readable — and Jinja's braces
   * stand out anyway against it. */
  function modeFor(name) {
    if (/\.py$/.test(name)) return "python";
    if (/\.css$/.test(name)) return "css";
    if (/\.(html|htm|jinja2?)$/.test(name)) return "htmlmixed";
    return "text/plain";
  }

  function openFile(name) {
    if (!(name in files)) return;
    if (editor && current in files) files[current] = editor.getValue();
    current = name;
    if (editor) {
      editor.setValue(files[name]);
      editor.setOption("mode", modeFor(name));
      editor.clearHistory();
      editor.focus();
    }
    paintTabs();
  }

  /* Tabs, in an order that matches how Flask thinks: the file that runs
   * first, then the templates, then static. Alphabetical would put
   * app.py after a template called about.html, which is the wrong first
   * thing for a student to see. */
  function tabOrder() {
    var entry = cfg.entry || "app.py";
    var rest = Object.keys(files).filter(function (n) { return n !== entry; });
    rest.sort(function (a, b) {
      var fa = a.indexOf("/") < 0 ? 0 : (a.indexOf("templates/") === 0 ? 1 : 2);
      var fb = b.indexOf("/") < 0 ? 0 : (b.indexOf("templates/") === 0 ? 1 : 2);
      return fa - fb || a.localeCompare(b);
    });
    return (entry in files ? [entry] : []).concat(rest);
  }

  function paintTabs() {
    var strip = $("file-tabs");
    if (!strip) return;
    strip.textContent = "";
    tabOrder().forEach(function (name) {
      var tab = document.createElement("button");
      // tab-on, not tab-active: the stylesheet has always said .tab-on, and
      // PyIDE and WebIDE agree. This file drifted during the port, so the
      // open file had no highlight at all — nothing errors, the strip just
      // stops telling you which file you are editing.
      tab.className = "tab" + (name === current ? " tab-on" : "");
      tab.setAttribute("role", "tab");
      tab.title = name;

      // The folder in grey and the file in full, so a column of
      // templates/... does not read as one long smear of identical prefix.
      var cut = name.lastIndexOf("/");
      if (cut > 0) {
        var dim = document.createElement("span");
        dim.className = "tab-dir";
        dim.textContent = name.slice(0, cut + 1);
        tab.appendChild(dim);
      }
      tab.appendChild(document.createTextNode(name.slice(cut + 1)));

      tab.addEventListener("click", function () { openFile(name); });

      if (!cfg.readonly && name !== (cfg.entry || "app.py")) {
        var x = document.createElement("span");
        x.className = "tab-x";
        x.textContent = "×";
        x.title = "Delete " + name;
        x.addEventListener("click", function (e) {
          e.stopPropagation();
          if (!window.confirm("Delete " + name + "? This cannot be undone."))
            return;
          delete files[name];
          if (current === name) openFile(tabOrder()[0]);
          else paintTabs();
          touched();
        });
        tab.appendChild(x);
      }
      strip.appendChild(tab);
    });
    markOverflow(strip);
  }

  /* Does the strip have more tabs than fit?
   *
   * It scrolls either way — but on macOS the scrollbar is an overlay that
   * stays invisible until you are already scrolling, so a clipped tab just
   * looks like a bug. The class turns on a fade at the right edge, which is
   * the only thing on screen saying "there is more this way".
   */
  function markOverflow(strip) {
    if (!strip) return;
    strip.classList.toggle("has-more", strip.scrollWidth > strip.clientWidth + 1);
  }

  window.addEventListener("resize", function () { markOverflow($("file-tabs")); });

  function newFile() {
    var folders = (cfg.folders || ["templates", "static"]).join(" or ");
    var name = window.prompt(
      "New file.\n\n" +
      "A template goes in templates/ and a stylesheet in static/ — that is " +
      "where Flask looks for them.\n\n" +
      "For example: templates/about.html", "templates/");
    if (name === null) return;
    name = name.trim();
    if (!name) return;
    if (name in files) { openFile(name); return; }

    // The same rule the server enforces, said before the work is done
    // rather than when they press Share and lose the file.
    if (!/^(?:(?:templates|static)\/)?[A-Za-z0-9][A-Za-z0-9 _-]{0,50}\.[A-Za-z0-9]{1,8}$/.test(name)) {
      window.alert(
        "'" + name + "' will not work.\n\n" +
        "Use letters, digits, dashes and underscores, end with an extension " +
        "like .py, .html or .css, and put it either at the top level or in " +
        folders + "/.");
      return;
    }
    files[name] = /\.html?$/.test(name)
      ? "{% extends \"base.html\" %}\n\n{% block body %}\n\n{% endblock %}\n"
      : "";
    openFile(name);
    touched();
  }

  /* -------------------------------------------------------------- running */

  function readProject() {
    if (editor && current in files) files[current] = editor.getValue();
    return {
      files: Object.assign({}, files),
      title: ($("title") && $("title").value) || "Untitled",
      author: ($("author") && $("author").value) || "",
    };
  }

  function touched() {
    if (account && account.noteEdit) account.noteEdit();
  }

  async function run() {
    if (running) return;
    running = true;
    var btn = $("run");
    if (btn) btn.disabled = true;
    clearOutput();

    var project = readProject();
    try {
      var res = await runtime.run(project.files, function (note) {
        if (note) say(note + "\n", "dim");
      });

      if (!res.ok) {
        say("\n" + res.error + "\n", "err");
        return;
      }

      if (!res.routes.length) {
        say("Your app has no routes yet.\n\n", "dim");
        say("A route is a path plus the function that answers it:\n\n" +
            '    @app.route("/")\n' +
            "    def home():\n" +
            '        return "Hello!"\n', "dim");
      } else {
        say("Running. Routes:\n", "dim");
        res.routes.forEach(function (r) {
          say("  " + r.methods.join(",") + "  " + r.path + "\n");
        });
      }
      await preview.go("/");
    } catch (err) {
      say("\n" + (err && err.message ? err.message : String(err)) + "\n", "err");
    } finally {
      running = false;
      if (btn) btn.disabled = false;
    }
  }

  /* --------------------------------------------------------------- share */

  function share() {
    var project = readProject();
    var hide = $("hide-code");
    fetch(cfg.shareUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        files: project.files,
        title: project.title,
        author: project.author,
        hidden: !!(hide && hide.checked),
      }),
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, data: d }; });
    }).then(function (o) {
      if (!o.ok) { say("\n" + (o.data.error || "Could not share that.") + "\n", "err"); return; }
      $("share-url").value = o.data.url;
      $("modal").hidden = false;
      $("share-url").select();
    }).catch(function (e) {
      say("\n" + e.message + "\n", "err");
    });
  }

  function download() {
    var project = readProject();
    var safe = (project.title || "project").replace(/[^A-Za-z0-9 _-]/g, "").trim();
    var entries = Object.keys(project.files).map(function (name) {
      return { name: name, data: project.files[name] };
    });
    // The zip keeps the folders, because a project that unzips flat is a
    // project Flask cannot run.
    window.FlaskIDEZip.download((safe || "project") + ".zip", entries);
  }

  /* ----------------------------------------------------------- tab stops
   *
   * THIS EDITOR WAS INSERTING LITERAL TAB CHARACTERS.
   *
   * With no Tab binding at all, CodeMirror falls back to its own default:
   * defaultTab -> insertTab -> replaceSelection("\t"). Checked against a
   * live CodeMirror 5, not from memory. So every Tab a student pressed put
   * a hard tab in the file, while Enter's auto-indent put spaces — and
   * Python 3 rejects that mixture outright with a TabError, on a line that
   * looks perfectly aligned on screen. In a Flask project the traceback
   * arrives in the preview pane, one step removed from the line that caused
   * it, which makes it about as hard to find as it gets.
   *
   * Binding Tab fixes that on its own. Aligning both keys to stops is the
   * rest of the change: Tab goes to the next multiple of the indent unit
   * rather than always inserting four, and Backspace comes back to the
   * previous one rather than eating a single space at a time.
   *
   * Same pair as PyIDE, WebIDE and the playground. The unit is read from
   * the editor rather than written down, because it is four here and two in
   * WebIDE.
   */
  function spaces(n) {
    return new Array(n + 1).join(" ");
  }

  function indentToTabStop(cm) {
    if (cm.somethingSelected()) {
      cm.indentSelection("add");
      return;
    }
    var unit = cm.getOption("indentUnit");
    // More than one caret: no single column to align to, so fall back to a
    // whole unit at each. Rare enough not to be worth a wrong answer.
    if (cm.listSelections().length > 1) {
      cm.replaceSelection(spaces(unit), "end");
      return;
    }
    var head = cm.getCursor();
    var col = CodeMirror.countColumn(cm.getLine(head.line), head.ch,
                                     cm.getOption("tabSize"));
    // Never 0 and never more than a full unit: at a stop it moves a whole
    // one, off a stop it moves just enough to land on the next.
    cm.replaceSelection(spaces(unit - (col % unit)), "end");
  }

  function backspaceToTabStop(cm) {
    if (cm.somethingSelected() || cm.listSelections().length > 1) {
      return CodeMirror.Pass;
    }
    var head = cm.getCursor();
    var before = cm.getLine(head.line).slice(0, head.ch);

    /* ONLY IN THE INDENTATION, AND ONLY SPACES.
     *
     * With anything but spaces to the left, this is ordinary typing and one
     * press must delete one character — a Backspace that swallowed four
     * characters of a word would be unusable. A literal tab is excluded
     * too, and this editor will have files full of them from before Tab was
     * bound: one tab is one character but four columns, so "delete back to
     * the stop" has two different right answers and the wrong one eats
     * code. Both fall through to CodeMirror. */
    if (before.length === 0 || !/^ +$/.test(before)) {
      return CodeMirror.Pass;
    }

    var unit = cm.getOption("indentUnit");
    var col = before.length;
    var target = (col % unit === 0) ? col - unit : col - (col % unit);
    if (target < 0) target = 0;
    cm.replaceRange("", { line: head.line, ch: target }, head, "+delete");
  }

  /* ---------------------------------------------------------------- boot */

  document.addEventListener("DOMContentLoaded", function () {
    if (!(current in files)) current = Object.keys(files)[0] || current;

    editor = CodeMirror.fromTextArea($("editor"), {
      value: files[current] || "",
      mode: modeFor(current),
      theme: document.documentElement.getAttribute("data-theme") === "light"
        ? "default" : "material-darker",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      // Auto-indent writes spaces, and now so does Tab. Both, or Python
      // gets a file with each kind on different lines.
      indentWithTabs: false,
      readOnly: cfg.readonly ? "nocursor" : false,
      matchBrackets: true,
      autoCloseBrackets: true,
      extraKeys: {
        "Ctrl-Enter": run,
        "Cmd-Enter": run,
        "Ctrl-/": "toggleComment",
        "Cmd-/": "toggleComment",
        Tab: indentToTabStop,
        Backspace: backspaceToTabStop,
        "Shift-Tab": function (cm) { cm.indentSelection("subtract"); },
      },
    });
    editor.setValue(files[current] || "");
    editor.on("change", function () {
      files[current] = editor.getValue();
      touched();
    });

    paintTabs();

    preview = new window.FlaskIDEPreview({
      frame: $("preview"),
      bar: $("preview-path"),
      onStatus: function (code, path) {
        var el = $("preview-status");
        if (!el) return;
        el.textContent = code ? String(code) : "";
        el.className = "status-code" +
          (code >= 500 ? " bad" : code >= 400 ? " warn" : code ? " ok" : "");
        el.title = path;
      },
    });

    runtime.setOutput(function (text) { say(text); });

    if ($("run")) $("run").addEventListener("click", run);
    if ($("preview-back")) $("preview-back").addEventListener("click", function () {
      preview.back();
    });
    if ($("new-file")) $("new-file").addEventListener("click", newFile);
    if ($("share")) $("share").addEventListener("click", share);
    if ($("download")) $("download").addEventListener("click", download);
    if ($("download-menu")) $("download-menu").addEventListener("click", download);
    if ($("clear")) $("clear").addEventListener("click", clearOutput);
    if ($("close-modal")) $("close-modal").addEventListener("click", function () {
      $("modal").hidden = true;
    });
    if ($("copy")) $("copy").addEventListener("click", function () {
      $("share-url").select();
      document.execCommand("copy");
      $("copy").textContent = "Copied";
      setTimeout(function () { $("copy").textContent = "Copy"; }, 1400);
    });

    wireTheme();
    wireFontSize();

    if (window.FlaskIDEAccount) {
      account = window.FlaskIDEAccount.attach({ read: readProject, say: say });
    }
    if (window.FlaskIDENotes && window.FlaskIDENotes.boot) {
      window.FlaskIDENotes.boot();
    }
  });

  /* ------------------------------------------------------ chrome, shared */

  function wireTheme() {
    var btn = $("theme"), glyph = $("theme-glyph");
    if (!btn) return;
    function paint() {
      var light = document.documentElement.getAttribute("data-theme") === "light";
      if (glyph) glyph.textContent = light ? "☀" : "☾";
      if (editor) {
        editor.setOption("theme", light ? "default" : "material-darker");
      }
    }
    paint();
    btn.addEventListener("click", function () {
      var light = document.documentElement.getAttribute("data-theme") === "light";
      var next = light ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("flaskide-theme", next); } catch (e) {}
      paint();
    });
  }

  function wireFontSize() {
    var up = $("font-up"), down = $("font-down"), label = $("font-size");
    if (!up || !down) return;
    function size() {
      var v = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue("--code-size"), 10);
      return isNaN(v) ? 14 : v;
    }
    function set(px) {
      px = Math.max(11, Math.min(32, px));
      document.documentElement.style.setProperty("--code-size", px + "px");
      if (label) label.textContent = String(px);
      try { localStorage.setItem("flaskide-code-size", String(px)); } catch (e) {}
      if (editor) editor.refresh();
    }
    set(size());
    up.addEventListener("click", function () { set(size() + 1); });
    down.addEventListener("click", function () { set(size() - 1); });
  }
})();
