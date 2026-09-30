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
  var rescue = null;
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
  /* WHICH KIND OF PROJECT THIS IS, read off the files.
   *
   * app.py's kind_of() has the same rule, and the two have to agree: this one
   * decides what Run does, that one decides what the server will accept. If
   * they ever disagree the editor runs a project one way and saves it as the
   * other, and nothing reports anything.
   *
   * There is no stored flag and no toggle. A project containing query.sql IS
   * a SQL project -- so adding that file is how you become one, and the chip
   * follows the files rather than the files following the chip. */
  var SQL_ENTRY = cfg.sqlEntry || "query.sql";
  var SCHEMA = cfg.schema || "schema.sql";

  function isSql() { return SQL_ENTRY in files; }

  function modeFor(name) {
    if (/\.sql$/.test(name)) return "text/x-sql";
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
          applyKind();
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
    applyKind();
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

  /* Has anything been typed since this project was opened?
     Compared against the files the page was served with rather than a dirty
     flag, so that typing a character and deleting it again does not count --
     and so that a signed-in student whose draft has already autosaved is not
     asked about work that is safely saved. */
  function changedFromStarter() {
    var now = readProject().files;
    var was = cfg.files || {};
    var names = Object.keys(now).concat(Object.keys(was));
    for (var i = 0; i < names.length; i++) {
      if (now[names[i]] !== was[names[i]]) return true;
    }
    return false;
  }

  function touched() {
    if (account && account.noteEdit) account.noteEdit();
    if (rescue && rescue.noteEdit) rescue.noteEdit();
  }

  async function run() {
    if (running) return;
    running = true;
    var btn = $("run");
    if (btn) btn.disabled = true;
    clearOutput();

    var project = readProject();
    if (isSql()) {
      try {
        await runSqlProject(project);
      } finally {
        running = false;
        if (btn) btn.disabled = false;
      }
      return;
    }
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

  /* ----------------------------------------------------------------- SQL */

  async function runSqlProject(project) {
    var pane = $("sql-results");
    try {
      var res = await runtime.runSql(project.files, function (note) {
        if (note) say(note + "\n", "dim");
      });

      if (!res.ok) {
        if (pane) pane.innerHTML = "";
        say("\n" + res.error + "\n", "err");
        /* The statement it came from. A query file holds several, and
           "near FORM: syntax error" does not say which one -- so the one
           that failed is printed under the message rather than left for the
           student to find by reading all of them. */
        if (res.statement) {
          say("\nin this statement:\n", "dim");
          say(res.statement + "\n");
        }
        /* Whatever DID run still goes on screen. A file of six queries with
           a typo in the fifth should still show you the first four. */
        if (res.results && res.results.length) {
          paintSql(res.results, res.tables || []);
          say("\n" + res.results.length + " statement(s) ran before it.\n",
              "dim");
        }
        return;
      }

      paintSql(res.results, res.tables);
      var n = res.results.length;
      say(n === 1 ? "1 statement.\n" : n + " statements.\n", "dim");
      if (!n) {
        say("\nquery.sql has no statements in it yet -- only comments.\n",
            "dim");
      }
    } catch (err) {
      say("\n" + (err && err.message ? err.message : String(err)) + "\n",
          "err");
    }
  }

  function paintSql(results, tables) {
    var pane = $("sql-results");
    if (!pane) return;
    pane.innerHTML = "";

    (results || []).forEach(function (r) {
      var block = document.createElement("div");
      block.className = "sql-result";

      var head = document.createElement("div");
      head.className = "sql-result-head";
      var stmt = document.createElement("pre");
      stmt.className = "sql-stmt";
      stmt.textContent = r.statement;
      head.appendChild(stmt);

      var count = document.createElement("span");
      count.className = "sql-count";
      if (r.columns) {
        count.textContent = r.rows.length === 1 ? "1 row"
                                                : r.rows.length + " rows";
      } else {
        /* SQLite reports -1 for a statement whose row count it does not
           track. Saying "-1 rows changed" is worse than saying nothing. */
        count.textContent = r.changed >= 0 ? r.changed + " changed" : "done";
      }
      head.appendChild(count);
      block.appendChild(head);

      if (r.columns) block.appendChild(sqlTable(r));
      pane.appendChild(block);
    });

    /* What the tables are called, under the results. Half of learning SQL is
       remembering the names, and the schema is otherwise a file away. */
    if (tables && tables.length) {
      var foot = document.createElement("div");
      foot.className = "sql-schema";
      foot.appendChild(document.createTextNode("In the database: "));
      tables.forEach(function (tbl, i) {
        if (i) foot.appendChild(document.createTextNode(", "));
        var code = document.createElement("code");
        code.textContent = tbl.name;
        foot.appendChild(code);
        foot.appendChild(document.createTextNode(" (" + tbl.rows + ")"));
      });
      pane.appendChild(foot);
    }
  }

  function sqlTable(r) {
    var wrap = document.createElement("div");
    wrap.className = "sql-table-wrap";

    if (!r.rows.length) {
      var none = document.createElement("div");
      none.className = "sql-empty";
      none.textContent = "No rows. (" + r.columns.join(", ") + ")";
      wrap.appendChild(none);
      return wrap;
    }

    var table = document.createElement("table");
    table.className = "sql-table";
    var thead = document.createElement("thead");
    var hrow = document.createElement("tr");
    r.columns.forEach(function (name) {
      var th = document.createElement("th");
      th.textContent = name;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var body = document.createElement("tbody");
    r.rows.forEach(function (row) {
      var tr = document.createElement("tr");
      row.forEach(function (value) {
        var td = document.createElement("td");
        /* NULL IS NOT THE EMPTY STRING. Rendering both as a blank cell is
           wrong on the exact day LEFT JOIN is taught, because the whole
           lesson is the row that has nothing on one side. */
        if (value === null) {
          td.className = "sql-null";
          td.textContent = "NULL";
        } else {
          /* textContent, never innerHTML: a row could hold anything, and
             this grid must not run it. */
          td.textContent = String(value);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);

    if (r.clipped) {
      var note = document.createElement("div");
      note.className = "sql-clipped";
      note.textContent = "Showing the first " + r.rows.length +
        " rows. Add a LIMIT, or a WHERE, to see fewer.";
      wrap.appendChild(note);
    }
    return wrap;
  }

  /* What the chrome says about the project. Called whenever the files change,
     because adding or deleting query.sql is what changes the kind. */
  function applyKind() {
    var sql = isSql();
    document.body.classList.toggle("is-sql", sql);

    var chip = $("mode-chip");
    if (chip) {
      chip.textContent = sql ? "SQL" : "Flask";
      chip.title = sql
        ? "A SQL project: query.sql runs against the database schema.sql builds."
        : "A Flask app: app.py runs and the preview shows its pages.";
    }

    var title = $("right-title");
    if (title) title.textContent = sql ? "Results" : "Preview";

    /* The button always offers the OTHER kind, which is what makes it read
       as a switch. */
    var swap = $("switch-kind");
    if (swap) {
      swap.textContent = sql ? "+ Flask app" : "+ SQL";
      swap.href = sql ? "/" : "/sql";
      swap.title = "Start a new " + (sql ? "Flask app" : "SQL project") +
        ". This one stays where it is.";
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
   * Shared with the live-lesson editor, so they live in tabstops.js — read
   * the comment there before unbinding Tab: this editor used to insert
   * literal tab characters, and Python rejects the mix with a TabError. */
  var indentToTabStop = window.FlaskIDETabStops.indentToTabStop;
  var backspaceToTabStop = window.FlaskIDETabStops.backspaceToTabStop;

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

    /* Completion of the student's own names, in .py files only — the open
       file is asked on every keystroke, because switching tabs changes it
       under the same editor. Every .py in the project counts, so a name
       defined in models.py is offered in app.py. */
    window.FlaskIDEComplete.attach(editor, function () {
      return !cfg.readonly && window.FlaskIDEComplete.isPy(current);
    }, function () {
      files[current] = editor.getValue();
      return Object.keys(files).filter(window.FlaskIDEComplete.isPy)
        .map(function (name) { return files[name]; });
    });

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

    applyKind();
    runtime.setOutput(function (text) { say(text); });

    /* Leaving for the other kind throws away anything unsaved, so it asks --
       but only when there IS something to lose. A confirm on every press is
       a confirm people learn to click through. */
    var switcher = $("switch-kind");
    if (switcher) {
      switcher.addEventListener("click", function (e) {
        if (!changedFromStarter()) return;
        if (!window.confirm(
              "Start a new project? What is open here has unsaved changes, " +
              "and they will be lost.")) {
          e.preventDefault();
        }
      });
    }

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
      /* The safety net for anyone not signed in — before the account module,
         so a rescued project is in the editor before autosave forms an
         opinion about what the project is. */
      rescue = window.IDERescue.attach({
        app: "flaskide",
        cfg: {
          signedIn: cfg.signedIn,
          assignmentSlug: cfg.assignmentSlug,
          draftSlug: cfg.draftSlug,
          draftFresh: cfg.draftFresh
        },
        readAll: function () { return readProject().files; },
        writeAll: function (incoming) {
          Object.keys(files).forEach(function (name) { delete files[name]; });
          Object.keys(incoming).forEach(function (name) {
            files[name] = incoming[name];
          });
          /* Which kind of project this is comes from the files themselves,
             and the entry names come from the server rather than being
             typed again here. */
          var flaskEntry = cfg.entry || "app.py";
          var entry = files[SQL_ENTRY] !== undefined ? SQL_ENTRY : flaskEntry;
          if (files[entry] === undefined) files[entry] = "";
          current = entry;
          editor.setValue(files[current]);
          editor.setOption("mode",
                           /\.py$/i.test(current) ? "python" : "text/plain");
          paintTabs();
          applyKind();
        },
        onRestored: function () { touched(); }
      });

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
  // ------------------------------------------------------------ teach live
  //
  // Go live and carry on working. Whatever file is open here is what the
  // class sees at /live/<code>; switching tabs switches what they are
  // watching, which is what a teacher means by "look at this bit".
  //
  // The file is sent WHOLE, every time, rather than as a diff. A diff stream
  // is smaller and needs every update to arrive, in order — which polling
  // cannot promise. Sending the whole file means a student whose wifi drops
  // ten updates is correct again on the eleventh, and a student who joins in
  // the middle needs no catch-up path at all.

  var liveBtn = $("go-live");
  var liveChip = $("live-code");

  if (liveBtn) {
    var liveCode = null;
    var liveTimer = null;
    var lastSent = null;
    var lastVersion = 0;
    var liveFor = "";           // assignment title, for the chip's tooltip
    var PUSH_MS = 400;

    /* A stamp that only ever goes up, and the server refuses anything lower
       than the row already has. Two pushes overtaking each other on a slow
       connection would otherwise leave the OLDER text on screen with the
       newer version number, and the class would sit looking at a line that
       had already been fixed.

       Date.now() rather than a counter starting at 1, so that reloading this
       page mid-lesson does not start numbering below what the row has
       reached — which would get every push after the reload rejected, with
       the mirror silently frozen and the button still saying Live. The
       max() covers a machine whose clock is behind the one that started it. */
    function nextSeq() {
      lastVersion = Math.max(Date.now(), lastVersion + 1);
      return lastVersion;
    }

    /* The project's notes: its first .md in tab order. Sent on every push so the class keeps
       them beside the lesson whichever tab is open here — before this, they
       reached the class only while the .md tab was selected. */
    function liveNotes() {
      var md = tabOrder().filter(window.FlaskIDENotes.isMarkdown);
      if (!md.length) return "";
      return md[0] === current ? editor.getValue() : (files[md[0]] || "");
    }

    function pushNow() {
      if (!liveCode) return;
      var name = current;
      var text = (name === current) ? editor.getValue() : (files[name] || "");
      var notes = liveNotes();
      var stamp = name + "\u0000" + text + "\u0000" + notes;
      if (stamp === lastSent) return;      // nothing typed since last time
      lastSent = stamp;
      fetch("/api/live/" + encodeURIComponent(liveCode) + "/push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text, filename: name, notes: notes,
                               seq: nextSeq() })
      }).then(function (res) {
        if (res.status === 403 || res.status === 409) stopLive(true);
      }).catch(function () {
        // A dropped push is fine: the next one carries the whole file.
      });
    }

    function paintLive() {
      if (liveCode) {
        liveBtn.textContent = "End lesson";
        liveBtn.classList.add("btn-live-on");
        liveChip.hidden = false;
        liveChip.textContent = liveCode;
        liveChip.title = "Your class joins at /live and types " + liveCode
          + (liveFor ? "\nThey can turn in to: " + liveFor
                     : "\nNo assignment, so they cannot turn work in.");
      } else {
        liveBtn.textContent = "Go live";
        liveBtn.classList.remove("btn-live-on");
        liveChip.hidden = true;
      }
    }

    function stopLive(quietly) {
      var code = liveCode;
      liveCode = null;
      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
      lastSent = null;
      paintLive();
      try { localStorage.removeItem("flaskide-live-host"); } catch (e) {}
      if (code && !quietly) {
        fetch("/api/live/" + encodeURIComponent(code) + "/stop", { method: "POST" });
      }
    }

    /* Which assignment this lesson is for, asked once when Go live is
       pressed.

       IT IS NOT A NICETY. Turning work in needs a draft with an assignment
       on it, so a lesson with none is a lesson the class cannot hand
       anything in from — and nothing about that is visible while it is
       happening. Asking here is the one moment the teacher is thinking
       about the lesson anyway. */
    function chooseAssignment() {
      return fetch("/api/live/assignments")
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var list = (data && data.assignments) || [];
          if (!list.length) return "";       // nothing published yet
          /* WORDED AS WHAT IT DOES. "Which assignment is this lesson for?"
             read like it was about to open the assignment, and it is not —
             it decides where the CLASS's work goes when they press Save.
             Loading the starter is offered separately below, because that
             one does replace what is on screen. */
          var lines = ["Where should the class turn this work in?",
                       "(This does not change what is in your editor.)", "",
                       "0 — nowhere (they can still save, but not turn in)"];
          list.forEach(function (a, i) {
            lines.push((i + 1) + " — " + a.title);
          });
          var pick = window.prompt(lines.join("\n"), "1");
          if (pick === null) return null;    // cancelled: do not go live
          var n = parseInt(pick, 10);
          if (!n || n < 1 || n > list.length) return "";
          return list[n - 1].slug;
        })
        .catch(function () { return ""; });
    }

    /* Open an assignment's starter in the editor.
     *
     * ASKED, NEVER SILENT. This replaces everything open, so a teacher who
     * pressed Go live in the middle of a lesson to resume a broadcast would
     * otherwise lose what they were demonstrating. It is offered only when
     * an assignment was actually chosen, and only on a fresh Go live — the
     * reload-resume path never reaches here.
     */
    function offerStarter(slug) {
      if (!slug) return Promise.resolve();
      return fetch("/api/live/assignment/" + encodeURIComponent(slug))
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.error) return;
          if (!window.confirm(
                "Open the starter for \u201c" + data.title + "\u201d?\n\n"
                + "This replaces what is in your editor now.")) {
            return;
          }
          loadStarter(data.files);
        })
        .catch(function () { /* the lesson still goes live without it */ });
    }

    function loadStarter(incoming) {
      incoming = incoming || {};
      Object.keys(files).forEach(function (name) { delete files[name]; });
      Object.keys(incoming).forEach(function (name) {
        files[name] = incoming[name];
      });
      /* A FlaskIDE project is one of two kinds, and which one it is comes
         from the files themselves. Opening a SQL assignment must not leave
         the editor pointed at an app.py that is not there.
         
         The two entry names come from the server, never typed again here:
         the app decides what its entry files are called, and a second copy
         of those strings in the editor is a second thing to keep in step.
         test_app.py checks for exactly that. */
      var flaskEntry = cfg.entry || "app.py";
      var entry = files[SQL_ENTRY] !== undefined ? SQL_ENTRY : flaskEntry;
      if (files[entry] === undefined) files[entry] = "";
      current = entry;
      editor.setValue(files[current]);
      editor.setOption("mode", /\.py$/i.test(current) ? "python" : "text/plain");
      paintTabs();
      applyKind();
      touched();
    }

    function startLive(assignment, resume) {
      var name = current;
      var text = (name === current) ? editor.getValue() : (files[name] || "");
      fetch("/api/live/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(assignment === undefined
          ? { body: text, filename: name, resume: resume || "",
              title: ($("title") && $("title").value) || "Live lesson" }
          /* `assignment` present — even as "" — is what tells the server this
             was a deliberate choice. Left out, a resumed session keeps the
             assignment it already had rather than silently losing it on a
             page reload, which would leave the class unable to hand in with
             nothing on screen to say why. */
          : { body: text, filename: name, assignment: assignment,
              title: ($("title") && $("title").value) || "Live lesson" })
      }).then(function (res) { return res.json(); })
        .then(function (data) {
          if (resume && data.error) return;   // no alert for a quiet resume
          if (data.error) { window.alert(data.error); return; }
          if (data.resumed === false) {
            // That lesson is over. Forget it, and stay off the air.
            try { localStorage.removeItem("flaskide-live-host"); } catch (e) {}
            return;
          }
          liveCode = data.code;
          liveFor = data.assignment_title || "";
          lastVersion = data.version || 0;
          lastSent = null;
          try { localStorage.setItem("flaskide-live-host", liveCode); } catch (e) {}
          paintLive();
          pushNow();
          liveTimer = setInterval(pushNow, PUSH_MS);
        })
        .catch(function () {
          if (resume) return;
          window.alert("Could not start the live lesson. Check your connection.");
        });
    }

    liveBtn.addEventListener("click", function () {
      if (liveCode) {
        if (window.confirm("End the lesson? Your class stops seeing this editor.")) {
          stopLive(false);
        }
      } else {
        chooseAssignment().then(function (slug) {
          if (slug === null) return;        // they cancelled the chooser
          // Offer the starter first, so the file that goes out on the very
          // first push is the one they are about to teach from.
          offerStarter(slug).then(function () { startLive(slug); });
        });
      }
    });

    /* Reloading the editor mid-lesson must not silently stop the broadcast.
       The session is still open server-side — /api/live/start hands back the
       one already running rather than inventing a second code — so this puts
       the button back into its Live state and resumes pushing. */
    try {
      // Resuming after a reload: no assignment argument at all, so the
      // server keeps whatever the session already had. The code is sent so
      // the server can refuse anything but that same lesson — see live_start.
      var resumeCode = localStorage.getItem("flaskide-live-host");
      if (resumeCode) startLive(undefined, resumeCode);
    } catch (e) { /* storage blocked: press Go live again */ }
  } else {
    /* No Go live button: signed out, or not a teacher. Whatever lesson this
       browser remembers is not one this person can resume, so forget it
       here rather than let it wait for the next teacher to sign in. */
    try { localStorage.removeItem("flaskide-live-host"); } catch (e) {}
  }
})();
