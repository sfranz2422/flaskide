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

  /* Questions in the notes answer into this assignment. On a project that
     is not one, or the teacher's own copy, there is nowhere to record an
     answer, and notes.js says so on the question rather than taking one. */
  window.FlaskIDENotes.setQuizContext({ assignment: cfg.assignmentSlug,
                                        signedIn: cfg.signedIn });
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

  /* A .md TAB IS A VIEW SWITCH, NOT A FILE TO EDIT. The notes render on the
   * right, in the preview's place, and the editor stays on the code — so a
   * student reads the instructions beside the app.py they are writing in.
   * The two take turns in one pane because this editor has no room for a
   * third: the Notes | Preview switch, a code tab, or Run brings the preview
   * back. Before this a .md opened in the editor as raw markdown, editable
   * by anyone, and its questions (quiz.py) were unanswerable lines of text.
   *
   * The author still edits it: Edit source puts the markdown in the editor
   * and the notes re-render as they type, the way PyIDE does it. */
  var syntaxCard = null;      // made once the editor exists; see below
  var notesShown = null;      // the .md on the right, or null for the preview
  var mdSource = false;       // the author has that .md open in the editor
  var lastCode = null;        // the code file to go back to from the source

  function isNotes(name) { return window.FlaskIDENotes.isMarkdown(name); }
  function notesFiles() { return tabOrder().filter(isNotes); }

  function loadIntoEditor(name) {
    if (editor && current in files) files[current] = editor.getValue();
    current = name;
    if (!isNotes(name)) lastCode = name;
    if (editor) {
      editor.setValue(files[name]);
      editor.setOption("mode", modeFor(name));
      editor.clearHistory();
      editor.focus();
    }
  }

  /* Back to code, if the author was editing the notes' source: the editor
     returns to the last code file, so typing never lands in the notes by
     accident once they have moved on. */
  function leaveSource() {
    if (!mdSource) return;
    mdSource = false;
    var btn = $("notes-edit");
    if (btn) btn.textContent = "Edit source";
    var code = lastCode in files ? lastCode
      : tabOrder().filter(function (n) { return !isNotes(n); })[0];
    if (code) loadIntoEditor(code);
  }

  function openFile(name) {
    if (!(name in files)) return;
    if (isNotes(name)) {
      if (notesShown !== name) leaveSource();
      showNotes(name);
      return;
    }
    mdSource = false;
    var btn = $("notes-edit");
    if (btn) btn.textContent = "Edit source";
    loadIntoEditor(name);
    showPreview();
  }

  /* Always as slides when the notes have `---` in them, with ◀ ▶ under
     them (notes.js, slideView) — here, on a shared link, and on the class's
     page in a live lesson alike. Made on first use: the pane is in the page
     only once it has loaded. */
  var notesSlides = null;
  function slidesView() {
    if (!notesSlides && $("notes-body")) {
      notesSlides = window.FlaskIDENotes.slideView($("notes-body"));
    }
    return notesSlides;
  }

  function showNotes(name) {
    notesShown = name;
    var view = $("notes-view"), body = $("notes-body");
    if (!view || !body) return;
    $("notes-name").textContent = name;
    $("preview-view").hidden = true;
    view.hidden = false;
    slidesView().show(name === current && editor ? editor.getValue() : files[name]);
    paintSwitch();
    paintTabs();
  }

  function toggleSource() {
    if (!notesShown) return;
    var btn = $("notes-edit");
    if (mdSource) {
      leaveSource();
      showNotes(notesShown);
      return;
    }
    mdSource = true;
    loadIntoEditor(notesShown);
    if (btn) btn.textContent = "Done";
    paintTabs();
  }

  function showPreview() {
    notesShown = null;
    if ($("notes-view")) $("notes-view").hidden = true;
    if ($("preview-view")) $("preview-view").hidden = false;
    paintSwitch();
    paintTabs();
  }

  /* After the files were replaced wholesale — the rescue, a starter loaded
     on Go live: the notes on show may be gone, or say something new. */
  function refreshNotes() {
    mdSource = false;
    if (notesShown && notesShown in files) showNotes(notesShown);
    else showPreview();
  }

  /* The switch is in both pane heads, so it is always where the eye is. Only
     when the project has notes: with none there is nothing to switch to. */
  function paintSwitch() {
    var has = notesFiles().length > 0;
    Array.prototype.forEach.call(document.querySelectorAll(".view-switch"),
      function (sw) {
        sw.hidden = !has;
        sw.querySelector('[data-view="notes"]').classList.toggle("is-on", !!notesShown);
        var pv = sw.querySelector('[data-view="preview"]');
        pv.classList.toggle("is-on", !notesShown);
        pv.textContent = isSql() ? "Results" : "Preview";
      });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".view-switch [data-view]");
    if (!b) return;
    if (b.dataset.view === "preview") { showPreview(); return; }
    var md = notesFiles();
    if (md.length && !notesShown) showNotes(md[0]);
  });

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

  /* NOTES ARE A BUTTON, NOT A TAB, for anyone reading notes they did not
     write — a student on an assignment, a shared link. They never edit the
     .md, so a tab beside app.py read as another file to type in. A button
     in the top bar, named for the file (instructions.md is "instructions"),
     shows them, and a second press goes back to the preview — as the
     Notes | Preview switch in the pane head does.

     Whoever owns the notes keeps the tab, because Edit source is there —
     EXCEPT WHILE TEACHING LIVE: the teacher's editor is on the projector
     then, and should show the class what their own page has. A function,
     not a flag, because going live and ending a lesson change the answer. */
  function notesAsButtons() { return !cfg.authoring || !!liveCode; }

  function renderNotesButtons() {
    var bar = $("notes-buttons");
    if (!bar) return;
    bar.textContent = "";
    if (!notesAsButtons()) return;
    notesFiles().forEach(function (name) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn notes-btn";
      var on = name === notesShown;
      b.setAttribute("aria-pressed", String(on));
      b.textContent = name.replace(/\.(md|markdown)$/i, "");
      b.title = on ? "Back to the preview" : "Show " + name;
      b.addEventListener("click", function () {
        if (notesShown === name) showPreview();
        else openFile(name);
      });
      bar.appendChild(b);
    });
  }

  function paintTabs() {
    var strip = $("file-tabs");
    if (!strip) return;
    strip.textContent = "";
    renderNotesButtons();
    tabOrder().filter(function (name) {
      return !(notesAsButtons() && isNotes(name));
    }).forEach(function (name) {
      var tab = document.createElement("button");
      // tab-on, not tab-active: the stylesheet has always said .tab-on, and
      // PyIDE and WebIDE agree. This file drifted during the port, so the
      // open file had no highlight at all — nothing errors, the strip just
      // stops telling you which file you are editing.
      // The notes' tab while they are on show; otherwise the file being
      // edited. With the notes up the editor still holds the code, and
      // marking both would leave nobody sure which tab they were on.
      // With the notes up from their button there is no notes tab to
      // light, so the file in the editor stays lit.
      var on = notesShown && !notesAsButtons() ? name === notesShown : name === current;
      tab.className = "tab" + (on ? " tab-on" : "");
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
          if (notesShown === name) { mdSource = false; showPreview(); }
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
    // A new notes file is empty, so there is nothing to read yet: its author
    // is sent straight to the source to write it.
    if (isNotes(name) && cfg.authoring) toggleSource();
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

  /* Whether anything here has been run yet. Until it has, the console and
     the preview hold nothing of the teacher's, and a live lesson sends
     neither — otherwise every class would be shown loading messages, or an
     empty page, as if it were the program. */
  var hasRun = false;

  async function run() {
    if (running) return;
    // Run with the notes up would run into a pane nobody can see, and look
    // like nothing happened.
    if (notesShown) showPreview();
    running = true;
    hasRun = true;
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
      /* Can Python read it at all? Asked before the app is loaded, so a
         missing bracket gets a plain-words card over the editor (syntax.js)
         instead of a traceback from inside Flask. Python's own message
         still goes in the console. */
      syntaxCard.clear();
      var bad = await runtime.check(project.files, function (note) {
        if (note) say(note + "\n", "dim");
      });
      if (bad) {
        say("SyntaxError in " + bad.file + " on line " + bad.line + ": " + bad.msg + "\n"
            + (bad.text.trim() ? "    " + bad.text.trim() + "\n" : ""), "err");
        syntaxCard.show(bad);
        return;
      }
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
  /* ------------------------------------------- the app in a new tab
   *
   * The files go to /play through this browser's storage, not the server:
   * nothing is saved or shared by it, and a signed-out student can use it
   * as freely as Run. /play boots its own Python and runs its own copy of
   * the app — the pages come from Python, and this tab's Python is out of
   * that tab's reach (see play.html).
   *
   * One named tab, reused: pressing it again after an edit reloads that tab
   * with the new files instead of opening another one per press. */
  function runInNewTab() {
    try {
      localStorage.setItem("flaskide-play", JSON.stringify(readProject()));
    } catch (e) {
      window.alert("This browser is blocking site storage, so the app "
                   + "cannot be handed to a new tab. Use the preview here instead.");
      return;
    }
    window.open("/play", "flaskide-play");
  }

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

    var runTab = $("run-tab");
    if (runTab) runTab.hidden = sql;      // a SQL project has no pages

    /* The button always offers the OTHER kind, which is what makes it read
       as a switch. */
    paintSwitch();    // its label says Results in a SQL project, and a file
                      // added or deleted can be the only notes there were

    var swap = $("switch-kind");
    if (swap) {
      swap.textContent = sql ? "+ Flask app" : "+ SQL";
      /* /new, not "/": "/" became the front door, which sends a signed-in
         teacher to the dashboard -- so "+ Flask app" quietly left the
         editor altogether instead of opening a Flask project. */
      swap.href = sql ? "/new" : "/sql";
      swap.title = "Start a new " + (sql ? "Flask app" : "SQL project") +
        ". This one stays where it is.";
    }
  }

  /* --------------------------------------------------------------- share */

  /* A teacher's Share opens share-ask first, to choose between a plain link
     and a demo link; a student's goes straight to sharing. The box is
     unticked every time the dialog opens, so a demo link is always a choice
     made just now and never one left over from the last share. */
  function share(hidden) {
    var project = readProject();
    fetch(cfg.shareUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        files: project.files,
        title: project.title,
        author: project.author,
        hidden: !!hidden,
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

    /* What goes in the brackets, above the line while a call is typed
       (sighint.js): Python's own, Flask's, sqlite3's, and their own defs
       from every .py file. */
    window.FlaskIDESigHint.attach(editor, {
      flask: true,
      // files[current] is already up to date: the change handler above
      // runs before the cursor moves, which is when this is asked.
      sources: function () {
        return Object.keys(files).filter(function (n) { return /\.py$/i.test(n); })
          .map(function (n) { return files[n]; });
      },
      isPython: function () { return /\.py$/i.test(current); }
    });

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
      // The author's notes, re-rendered as they write them.
      if (mdSource && notesShown === current) {
        slidesView().show(files[current]);
      }
    });

    paintTabs();
    if ($("notes-edit")) $("notes-edit").addEventListener("click", toggleSource);

    /* PICTURES IN THE NOTES, for a teacher (pictures.js; the server refuses
       anyone else). Add picture opens the source first, so the teacher sees
       where it lands; paste and drop work only while the .md source is in
       the editor. Here there is one doc and files are swapped into it with
       setValue, so a picture still uploading when the teacher presses Done
       loses its bookmark — pictures.js then hands the markdown over rather
       than writing it into app.py. */
    if ($("notes-pic")) {
      window.FlaskIDEPictures.attach(editor, function () {
        return mdSource && notesShown === current;
      });
      $("notes-pic").addEventListener("click", function () {
        if (!notesShown) return;
        if (!mdSource) toggleSource();
        window.FlaskIDEPictures.choose(function (files) {
          if (!(mdSource && notesShown === current)) return;
          window.FlaskIDEPictures.insertInto(editor.getDoc(), files);
          editor.focus();
        });
      });
    }

    /* The syntax card, covering the preview and console — where Run's result
       would have gone. `reveal` opens the file the error is in, so an error
       in models.py is shown in models.py. */
    syntaxCard = window.FlaskIDESyntax.attach({
      host: $("preview-view"),
      editor: editor,
      reveal: function (file) {
        if (!(file in files)) return null;
        if (file !== current) openFile(file);
        return editor.getDoc();
      }
    });

    /* An assignment opens on its notes, or nobody reads them. Not for the
       author: the notes are theirs, and they came to work on the code. */
    if (!cfg.authoring && notesFiles().length) showNotes(notesFiles()[0]);
    else paintSwitch();

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
      onNote: function (text) { say("\n" + text + "\n", "dim"); },
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

    /* The handles between the panes (split.js), the same ones the class's
       live page has. The editor is told, because CodeMirror measures itself
       only on a window resize. */
    window.FlaskIDESplit.attachAll(document, {
      wide: window.matchMedia ? window.matchMedia("(min-width: 861px)") : null,
      onResize: function () { editor.refresh(); }
    });

    /* THE LOGO GOES TO THE FRONT DOOR — a student's classes, a teacher's
       dashboard. A saved project has lost nothing by leaving: it autosaves,
       and pagehide sends whatever is pending (account.js). A project with
       nowhere to save to — the blank editor, before Save — is the one case
       where a click on the logo would throw work away without a word, so
       that one asks, and only when it differs from what the page opened. */
    var homeLink = $("home-link");
    if (homeLink) {
      homeLink.addEventListener("click", function (e) {
        if (cfg.readonly || cfg.draftSlug || !changedFromStarter()) return;
        if (!window.confirm("Leave this page? What you've typed here isn't saved.")) {
          e.preventDefault();
        }
      });
    }

    if ($("run")) $("run").addEventListener("click", run);
    if ($("run-tab")) $("run-tab").addEventListener("click", runInNewTab);
    if ($("preview-back")) $("preview-back").addEventListener("click", function () {
      preview.back();
    });
    if ($("new-file")) $("new-file").addEventListener("click", newFile);
    var hideCode = $("hide-code");   // a teacher's, in the share-ask dialog
    var shareAsk = $("share-ask");
    if ($("share")) {
      $("share").addEventListener("click", function () {
        if (!shareAsk) { share(false); return; }
        if (hideCode) hideCode.checked = false;
        shareAsk.hidden = false;
        $("share-go").focus();
      });
    }
    // A signed-in student's Share, out of the way in the account menu: they
    // have Save or Turn in on the bar, and that is the one thing to press.
    if ($("share-menu")) {
      $("share-menu").addEventListener("click", function () { share(false); });
    }
    if (shareAsk) {
      $("share-go").addEventListener("click", function () {
        shareAsk.hidden = true;
        share(!!(hideCode && hideCode.checked));
      });
      $("share-cancel").addEventListener("click", function () { shareAsk.hidden = true; });
      shareAsk.addEventListener("click", function (e) {
        if (e.target === shareAsk) shareAsk.hidden = true;
      });
    }
    if ($("download")) $("download").addEventListener("click", download);
    if ($("download-menu")) $("download-menu").addEventListener("click", download);
    if ($("download-share")) $("download-share").addEventListener("click", download);
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
          refreshNotes();
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

    /* WHICH TAB IS ON THE AIR. A reload of the tab teaching must carry on
       broadcasting, so the lesson is remembered — but per TAB
       (sessionStorage), with the page it was on. It was remembered for the
       whole browser, so ANY editor the teacher opened while live — a new
       tab, the logo, New project, Student view — rejoined the lesson and
       sent the class its own file: the class watched an untitled default
       template while the teacher typed in another tab, and a Go live there
       then ended the real lesson under them. Now only that tab, on that
       page, picks the lesson back up. */
    var HOST_KEY = "flaskide-live-host";
    try { localStorage.removeItem(HOST_KEY); } catch (e) { /* the old, shared marker */ }
    var rememberLive = function (code, slug) {
      try {
        sessionStorage.setItem(HOST_KEY, JSON.stringify({ code: code, path: location.pathname,
                                                          slug: slug || "" }));
      } catch (e) { /* storage blocked: a reload will need Go live again */ }
    };
    var forgetLive = function () {
      try {
        sessionStorage.removeItem(HOST_KEY);
        sessionStorage.removeItem(FILES_KEY);
      } catch (e) {}
    };

    /* WHAT WAS ON SCREEN, for a reload mid-lesson. Go live from the class
       page teaches on /new, the editor's blank page, and clears the lesson
       out of the address bar — so a reload there came back as the default
       template, resumed the broadcast, and sent that template to the class
       over the lesson's last code. The teacher's work was gone from the
       editor AND from the server, with nothing saying so (found in PyIDE,
       mid-lesson). Now the tab keeps its files as it unloads
       (sessionStorage: this tab only, gone when it closes) and a reload puts
       them back before it goes back on the air. Written on pagehide rather
       than every push: data files can be large, and a reload is the only
       thing this is for. */
    var FILES_KEY = "flaskide-live-files";
    window.addEventListener("pagehide", function () {
      if (!liveCode) return;
      var all = readProject().files;
      try {
        sessionStorage.setItem(FILES_KEY, JSON.stringify({
          code: liveCode, path: location.pathname, files: all, active: current,
          title: ($("title") && $("title").value) || ""
        }));
      } catch (e) {
        // Too big for storage: the reload falls back on the lesson's last file.
        try { sessionStorage.removeItem(FILES_KEY); } catch (e2) {}
      }
    });
    var keptFiles = function (code) {
      try {
        var kept = JSON.parse(sessionStorage.getItem(FILES_KEY) || "null");
        return kept && kept.code === code && kept.path === location.pathname
          && kept.files && typeof kept.files === "object" ? kept : null;
      } catch (e) { return null; }
    };
    var liveSlug = function () {
      try { return (JSON.parse(sessionStorage.getItem(HOST_KEY) || "null") || {}).slug || ""; }
      catch (e) { return ""; }
    };
    var liveToResume = function () {
      try {
        var saved = JSON.parse(sessionStorage.getItem(HOST_KEY) || "null");
        return saved && saved.path === location.pathname ? saved.code : null;
      } catch (e) { return null; }
    };
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
    function notesFile() {
      var md = tabOrder().filter(window.FlaskIDENotes.isMarkdown);
      return md.length ? md[0] : null;
    }

    function liveNotes() {
      var md = notesFile();
      if (!md) return "";
      return md === current ? editor.getValue() : (files[md] || "");
    }

    /* ------------------------------------------------------------ slides
       Notes with `---` dividers are slides. The class is sent the WHOLE
       file and "3/5", the slide this teacher is on: every student can move
       through the slides on their own (notes.js, slideView), and each time
       the teacher moves, every screen jumps to the teacher's slide. Sending
       one slide at a time, as this did first, made reading ahead or going
       back to an earlier question impossible.

       `slideAt` is an index that survives editing the notes mid-lesson, and
       is clamped when slides are deleted out from under it. Two slides at
       least, or it is not slides: a file whose one `---` leaves only one
       slide with anything on it goes whole.

       There was a Show all button that sent the whole file as one page.
       With students free to move through the slides it had nothing left
       to do, and it went. */
    var slideAt = 0;
    var slideCtl = $("live-slides");
    var slideLabel = $("slide-at");

    function currentSlides() {
      var cut = window.FlaskIDENotes.slides(liveNotes());
      return cut.length >= 2 ? cut : null;
    }

    function paintSlides(cut) {
      if (!slideCtl) return;
      slideCtl.hidden = !(liveCode && cut);
      if (slideCtl.hidden) return;
      slideLabel.textContent = (slideAt + 1) + " / " + cut.length;
      $("slide-prev").disabled = slideAt <= 0;
      $("slide-next").disabled = slideAt >= cut.length - 1;
    }

    function moveSlide(by) {
      var cut = currentSlides();
      if (!liveCode || !cut) return;
      slideAt = Math.max(0, Math.min(cut.length - 1, slideAt + by));
      pushNow();                 // now, not on the next tick
    }

    if (slideCtl) {
      $("slide-prev").addEventListener("click", function () { moveSlide(-1); });
      $("slide-next").addEventListener("click", function () { moveSlide(1); });
    }

    /* The slide the class is on, shown here under the preview — or the whole
       notes when they are not slides. Fed by pushNow from the very cut and
       `slide` it sends, so it cannot disagree with the class about which
       slide that is — a copy worked out separately from slideAt could.

       Re-rendered only when they change. pushNow runs on every tick, and
       rendering markdown that often would reset the scroll under the
       teacher's hand. */
    var classView = $("class-view");
    var classNotes = $("class-notes");
    var classShownNotes = null, classShownSlide = null;

    /* `theme` is the deck's (notes.js, takeTheme). One slide on its own no
       longer has the theme: line, which sits above the first slide, and
       rendered without it this pane showed the deck plain while the class
       saw it themed. Part of what is compared, so changing only the theme
       line redraws. */
    var classShownTheme = null;
    function paintClassView(notes, slide, theme) {
      if (!classView) return;
      if (notes === classShownNotes && slide === classShownSlide
          && theme === classShownTheme) return;
      classShownTheme = theme;
      var moved = slide !== classShownSlide;
      classShownNotes = notes;
      classShownSlide = slide;
      classView.hidden = !(notes && notes.trim());
      if (classView.hidden) return;
      window.FlaskIDENotes.render(classNotes, notes,
                                 slide ? { theme: theme } : undefined).then(function () {
        if (moved) classNotes.scrollTop = 0;
      });
    }

    /* The tail of what the console says. Trimmed here as well as on the
       server, so a runaway loop does not send 200 KB every 400ms. */
    var OUTPUT_CHARS = 16000;
    function liveOutput() {
      if (!hasRun || !out) return "";
      var text = out.textContent || "";
      return text.length > OUTPUT_CHARS ? text.slice(-OUTPUT_CHARS) : text;
    }

    /* What the class sees of the teacher's Run, beside their own.

       A Flask project sends the page the preview is showing, and the path it
       is showing it for — sent again whenever either changes, so following a
       link here moves the class along too. It is a picture of the page and
       nothing more: on their side the links and forms go nowhere, because
       the app that would answer them is running in this browser.

       A SQL project has no page; its answer is the results grid, which never
       touches the console. So the grid goes instead, with just enough style
       to read as a table. Built with textContent throughout (see paintSql),
       and shown in a frame with no scripts, so a row holding markup is still
       only text.

       Wrapped in JSON so the path and the kind ride with the HTML. The
       server stores it as an opaque string. */
    var SQL_PAGE_STYLE = "<style>body{font:13px ui-monospace,Menlo,monospace;"
      + "margin:10px 12px;color:#222}.sql-result{margin-bottom:18px}"
      + ".sql-result-head{display:flex;justify-content:space-between;gap:12px;"
      + "color:#777;font-size:11.5px}.sql-stmt{white-space:pre-wrap;margin:0}"
      + "table{border-collapse:collapse;width:100%}th,td{text-align:left;"
      + "padding:4px 10px;border-bottom:1px solid #ddd;white-space:nowrap}"
      + "th{background:#f3f3f3}.sql-null{color:#999;font-style:italic}"
      + "</style>";
    function livePage() {
      if (!hasRun) return "";
      if (isSql()) {
        var grid = $("sql-results");
        var html = grid ? grid.innerHTML : "";
        return html ? JSON.stringify({ sql: true, html: SQL_PAGE_STYLE + html }) : "";
      }
      if (!preview || !preview.shown) return "";
      return JSON.stringify({ path: preview.path || "/", html: preview.shown });
    }

    function pushNow() {
      if (!liveCode) return;
      // The notes while they are on show: the editor still holds the code
      // then, but the notes are what the teacher is looking at and talking
      // to, and the class's mirror has always followed the open tab.
      var name = notesShown || current;
      var text = (name === current) ? editor.getValue() : (files[name] || "");
      var notes = liveNotes();          // whole: students cut it themselves
      var slide = "";
      var onSlide = notes;              // what "Class sees" shows
      var cut = currentSlides();
      if (cut) {
        slideAt = Math.min(slideAt, cut.length - 1);
        onSlide = cut[slideAt];
        slide = (slideAt + 1) + "/" + cut.length;
        /* With the notes tab open, the mirror shows that file too — whole,
           which would put every slide on screen at once in a pane that has
           no arrows. It gets the teacher's slide. */
        if (name === notesFile()) text = onSlide;
      }
      /* Where the caret is, so the class sees it blink in the mirror and
         the mirror scrolls to follow it. In the stamp below, so moving it
         without typing still goes out — pointing at a line is half of
         teaching from the editor. None for a notes file: the class reads
         that rendered, where a line and column point at nothing.

         A highlighted block goes as "anchor-head", and the class sees it
         in yellow: dragging across a loop to talk about it is pointing
         at more than one line. Only the main selection — a second one
         made with Ctrl-click is rare, and the class would not know which
         one the teacher meant. */
      var cursor = "";
      if (editor && !window.FlaskIDENotes.isMarkdown(name)) {
        var at = editor.getCursor("head");
        cursor = at.line + ":" + at.ch;
        if (editor.somethingSelected()) {
          var from = editor.getCursor("anchor");
          cursor = from.line + ":" + from.ch + "-" + cursor;
        }
      }
      paintSlides(cut);
      paintClassView(onSlide, slide, window.FlaskIDENotes.takeTheme(notes).name);
      var output = liveOutput();
      var page = livePage();
      var stamp = [name, text, notes, slide, output, page, cursor].join("\u0000");
      if (stamp === lastSent) return;      // nothing typed since last time
      lastSent = stamp;
      fetch("/api/live/" + encodeURIComponent(liveCode) + "/push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text, filename: name, notes: notes,
                               slide: slide, output: output, page: page,
                               cursor: cursor, seq: nextSeq() })
      }).then(function (res) {
        if (res.status === 403 || res.status === 409) { stopLive(true); return; }
        return res.json().then(function (data) {
          /* Lost the race — most likely to a snippet sent a moment later,
             which moves the same version. Without forgetting what was sent,
             the check above would call this file "already pushed" and the
             class would sit on the old one until the next keystroke. */
          if (data && data.stale) lastSent = null;
        });
      }).catch(function () {
        // A dropped push is fine: the next one carries the whole file.
      });
    }

    // ------------------------------------------------ send to students
    /* Highlight, right-click, Send to students. The class gets a card above
       their own editor with an Insert button — for THIS code only. The mirror
       still cannot be copied, because typing the lesson is the exercise; this
       is for the bits that are not (a data list, a helper the lesson uses).

       Only while live and only with something selected. Any other
       right-click is left entirely to the browser, so the menu a teacher
       knows is still there the rest of the time. */
    var sentChip = $("live-sent");
    var ctxMenu = null;

    function paintSent(out) {
      if (sentChip) sentChip.hidden = !(liveCode && out);
    }

    function sendSnippet(text, tries) {
      if (!liveCode) return;
      tries = tries || 0;
      fetch("/api/live/" + encodeURIComponent(liveCode) + "/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snippet: text, seq: nextSeq() })
      }).then(function (res) {
        if (res.status === 403 || res.status === 409) { stopLive(true); return; }
        return res.json().then(function (data) {
          if (data.error) { window.alert(data.error); return; }
          /* A push overtook it. Silently dropping it would leave the teacher
             believing the class had the code; the new stamp is higher than
             anything already sent, so one more try goes through. */
          if (data.stale) {
            if (tries < 3) sendSnippet(text, tries + 1);
            else window.alert("Could not send that. Try again.");
            return;
          }
          paintSent(!!text);
        });
      }).catch(function () {
        window.alert("Could not send that. Check your connection.");
      });
    }

    function closeCtxMenu() {
      if (ctxMenu) ctxMenu.hidden = true;
    }

    function openCtxMenu(x, y, text) {
      if (!ctxMenu) {
        ctxMenu = document.createElement("div");
        ctxMenu.className = "menu ctx-menu";
        ctxMenu.setAttribute("role", "menu");
        var item = document.createElement("button");
        item.className = "menu-item";
        item.textContent = "Send to students";
        item.addEventListener("click", function () {
          closeCtxMenu();
          sendSnippet(ctxMenu.dataset.text || "");
        });
        ctxMenu.appendChild(item);
        document.body.appendChild(ctxMenu);
        document.addEventListener("mousedown", function (e) {
          if (!ctxMenu.contains(e.target)) closeCtxMenu();
        });
        document.addEventListener("keydown", function (e) {
          if (e.key === "Escape") closeCtxMenu();
        });
        window.addEventListener("blur", closeCtxMenu);
        window.addEventListener("resize", closeCtxMenu);
      }
      ctxMenu.dataset.text = text;
      ctxMenu.hidden = false;
      // Kept on screen: opened near the right or bottom edge it would
      // otherwise hang off it, half unclickable.
      var w = ctxMenu.offsetWidth, h = ctxMenu.offsetHeight;
      ctxMenu.style.left = Math.min(x, window.innerWidth - w - 8) + "px";
      ctxMenu.style.top = Math.min(y, window.innerHeight - h - 8) + "px";
    }

    /* CodeMirror's own "contextmenu" event: preventDefault there is what
       stops both the browser's menu and CodeMirror's handling of the click.
       The selection survives a right-click in CodeMirror 5, which is what
       makes highlight-then-right-click work at all. */
    function hookSend() {
      editor.on("contextmenu", function (cm, e) {
        if (!liveCode || !cm.somethingSelected()) return;
        var text = cm.getSelection();
        if (!text.trim()) return;
        e.preventDefault();
        openCtxMenu(e.clientX, e.clientY, text);
      });
      editor.on("scroll", closeCtxMenu);
    }
    // The editor is made on DOMContentLoaded, which has not happened yet
    // when this runs; the boot listener was added first, so it is there by
    // the time this one is called.
    if (editor) hookSend();
    else document.addEventListener("DOMContentLoaded", hookSend);

    if (sentChip) {
      sentChip.addEventListener("click", function () { sendSnippet(""); });
    }

    function liveLink() {
      return location.origin + "/live/" + encodeURIComponent(liveCode);
    }

    /* The chip still reads as the code, which is what a teacher says out
       loud; clicking it copies the whole address for the class's chat. The
       label flashes "Link copied" and then goes back to the code — unless the
       lesson ended in the meantime, when paintLive has already moved on. */
    liveChip.addEventListener("click", function () {
      if (!liveCode) return;
      var link = liveLink();
      function flash(text) {
        var code = liveCode;
        liveChip.textContent = text;
        setTimeout(function () {
          if (liveCode === code) liveChip.textContent = code;
        }, 1500);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link).then(function () {
          flash("Link copied");
        }, function () { window.prompt("Copy this link for your class:", link); });
      } else {
        window.prompt("Copy this link for your class:", link);
      }
    });

    function paintLive() {
      paintTabs();           // live, the notes are a button (notesAsButtons)
      if (liveCode) {
        liveBtn.textContent = "End lesson";
        liveBtn.classList.add("btn-live-on");
        liveChip.hidden = false;
        liveChip.textContent = liveCode;
        liveChip.title = "Click to copy the class's link: " + liveLink()
          + "\n(or they go to /live and type " + liveCode + ")"
          + (liveFor ? "\nThey can turn in to: " + liveFor
                     : "\nNo assignment, so they cannot turn work in.");
      } else {
        liveBtn.textContent = "Go live";
        liveBtn.classList.remove("btn-live-on");
        liveChip.hidden = true;
        paintSent(false);
        paintSlides(null);
        paintClassView(null, "");
        closeCtxMenu();
      }
    }

    function stopLive(quietly) {
      var code = liveCode;
      liveCode = null;
      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
      lastSent = null;
      paintLive();
      forgetLive();
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
    function chooseAssignment(data) {
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
      refreshNotes();
      applyKind();
      touched();
    }

    function startLive(assignment, resume, reopen) {
      var name = notesShown || current;
      var text = (name === current) ? editor.getValue() : (files[name] || "");
      fetch("/api/live/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(assignment === undefined
          ? { body: text, filename: name, resume: resume || "",
              reopen: reopen || "",
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
            forgetLive();
            return;
          }
          liveCode = data.code;
          liveFor = data.assignment_title || "";
          lastVersion = data.version || 0;
          // Back on the slide the class is looking at, after a reload. A
          // fresh lesson has none and starts at the beginning.
          var at = /^(\d+)\//.exec(data.slide || "");
          slideAt = at ? Math.max(0, parseInt(at[1], 10) - 1) : 0;
          lastSent = null;
          rememberLive(liveCode, data.assignment);
          paintLive();
          paintSent(!!data.snippet_out);
          pushNow();
          liveTimer = setInterval(pushNow, PUSH_MS);
        })
        .catch(function () {
          if (resume) return;
          window.alert("Could not start the live lesson. Check your connection.");
        });
    }

    /* "Teach this lesson again", from the lesson's own link.

       THE LINK IS THE LESSON. A teacher who wants yesterday's lesson back
       opens the link the class already has, and its page (live.html, as
       the host) sends them here with ?teach=<code>. Go live used to offer
       "your last lesson" instead, which was whichever one happened to be
       most recent — not the one they meant — and it left the editor as it
       was, so the class's screens filled with whatever happened to be open.

       So this opens the project first: the assignment's starter, with the
       lesson's last file laid over its namesake so the teacher carries on
       from where the class saw them stop. Only then does it reopen the
       lesson, so the very first push is the lesson's own code. Arrived at
       from a link, on the editor's home page, which never keeps unsaved
       work — so replacing what is on screen costs nothing and is not asked.
       A reload never comes back here; see the address bar cleared below. */
    function teachAgain(code, slug, resuming) {
      function json(res) { return res.json(); }
      var starter = slug
        ? fetch("/api/live/assignment/" + encodeURIComponent(slug))
            .then(json).catch(function () { return null; })
        : Promise.resolve(null);
      var last = fetch("/api/live/" + encodeURIComponent(code) + "?v=-1")
        .then(json).catch(function () { return null; });
      Promise.all([starter, last]).then(function (got) {
        var s = got[0], l = got[1];
        if (s && !s.error) loadStarter(s.files);
        // The notes travel separately (see pushNow), so only code is laid
        // over: a lesson that ended on the notes tab leaves them as written.
        if (l && !l.error && l.body && l.filename
            && !/\.md$/i.test(l.filename)) {
          // Set after openFile, never before: it writes the editor's text
          // back into files[current] on the way out.
          if (!(l.filename in files)) files[l.filename] = "";
          if (l.filename !== current) openFile(l.filename);
          files[l.filename] = l.body;
          editor.setValue(l.body);
          paintTabs();
        }
        if (resuming) startLive(undefined, code);
        else startLive(undefined, "", code);
      });
    }

    /* Back from a reload mid-lesson: the tab's own files if it kept them
       (see FILES_KEY), else the lesson rebuilt as Teach again builds it —
       which only /new needs, since any other page loaded its own project. */
    function resumeLive(code) {
      var kept = keptFiles(code);
      if (kept) {
        loadStarter(kept.files);
        if (kept.active && kept.active in files && kept.active !== current) openFile(kept.active);
        if ($("title") && kept.title) $("title").value = kept.title;
        startLive(undefined, code);
      } else if (location.pathname === "/new") {
        teachAgain(code, liveSlug(), true);
      } else {
        startLive(undefined, code);
      }
    }

    liveBtn.addEventListener("click", function () {
      if (liveCode) {
        if (window.confirm("End the lesson? Your class stops seeing this editor.")) {
          stopLive(false);
        }
      } else {
        fetch("/api/live/assignments")
          .then(function (res) { return res.json(); })
          .catch(function () { return {}; })
          .then(function (data) {
            var slug = chooseAssignment(data);
            if (slug === null) return;      // they cancelled the chooser
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
    var teach = null, teachFor = "";
    try {
      var q = new URLSearchParams(location.search);
      teach = q.get("teach");
      teachFor = q.get("a") || "";
    } catch (e) { /* no URLSearchParams: an old browser, not a teacher's */ }

    if (teach) {
      // Off the address bar at once, so a reload resumes the broadcast the
      // ordinary way instead of loading the starter over the lesson again.
      try { history.replaceState(null, "", location.pathname); } catch (e) {}
      teachAgain(teach, teachFor);
    } else {
      try {
        // Resuming after a reload: no assignment argument at all, so the
        // server keeps whatever the session already had. The code is sent so
        // the server can refuse anything but that same lesson — see live_start.
        var resumeCode = liveToResume();
        /* NOT YET: this runs before DOMContentLoaded, and the editor is made
           there (boot, above). Resumed at once, the first editor.getValue()
           threw, the catch below took it for blocked storage, and a teacher
           who reloaded mid-lesson was silently off the air — the button said
           Go live, the class sat on the last push. The boot listener was
           added first, so by the time this one runs the editor is there. */
        if (resumeCode) {
          if (editor) resumeLive(resumeCode);
          else document.addEventListener("DOMContentLoaded", function () { resumeLive(resumeCode); });
        }
      } catch (e) { /* storage blocked: press Go live again */ }
    }

    // ------------------------------------------------- notes, popped out
    /* Pop out: the notes as big slides in a tab of their own
       (templates/notes_present.html, static/present.js), for the projector
       while this tab stays on the teacher's laptop.

       THIS TAB STAYS IN CHARGE. Everything the class is sent still goes
       out from pushNow here; the pop-out has no lesson code and never
       talks to the server. It asks this tab to move ("go"), and this tab
       tells it what to show ("state") — the notes, the slide, whether it
       is live. When live, a move there is a move of slideAt, the very one
       the ◀ ▶ under "Class sees" make, so the class follows exactly as if
       those had been pressed. When not live it moves this page's own
       notes, which is only presenting.

       A BroadcastChannel, named by an id made when the button is pressed,
       so two editors open on two lessons each drive only their own. Same
       browser only: it is a channel between tabs, which is also why the
       pop-out says so the moment this tab goes quiet (closed, reloaded,
       crashed) rather than freezing on a slide that looks live. */
    var popChan = null, popId = null, popSent = null;
    // This page's own notes viewer (the one the pop-out moves when not
    // live). A function, because FlaskIDE makes its viewer on first use.
    function popNotes() { return slidesView(); }

    function popState() {
      var cut = currentSlides();
      var live = !!(liveCode && cut);
      return { type: "state", notes: liveNotes(), live: !!liveCode,
               slide: live ? Math.min(slideAt, cut.length - 1)
                           : (popNotes() ? popNotes().at() : 0),
               title: ($("title") && $("title").value) || document.title };
    }

    /* Sent when anything in it changed. Checked twice a second rather than
       hooked into every way the notes or the slide can change (typing in
       the .md, either set of arrows, a push, Teach again): a hook missed
       would be a projector quietly showing the wrong slide. */
    function tellPopout(force) {
      if (!popChan) return;
      var state = popState();
      var stamp = JSON.stringify(state);
      if (!force && stamp === popSent) return;
      popSent = stamp;
      popChan.postMessage(state);
    }

    function popoutGo(i) {
      var cut = currentSlides();
      if (liveCode && cut) {
        slideAt = Math.max(0, Math.min(cut.length - 1, i));
        pushNow();                     // the class moves now, not next tick
      } else if (popNotes()) {
        popNotes().go(i);
      }
      tellPopout(true);
    }

    function openPopout() {
      if (!popChan) {
        popId = Math.random().toString(36).slice(2, 10);
        popChan = new BroadcastChannel("flaskide-notes-" + popId);
        popChan.onmessage = function (e) {
          var d = e.data || {};
          if (d.type === "go" && typeof d.slide === "number") popoutGo(d.slide);
          else if (d.type === "hello") tellPopout(true);
        };
        setInterval(function () { tellPopout(false); }, 500);
        window.addEventListener("pagehide", function () {
          popChan.postMessage({ type: "bye" });
        });
      }
      // The same name each time, so pressing it again brings that tab
      // forward instead of opening another.
      window.open("/notes/present?ch=" + popId, "flaskide-notes-" + popId);
    }

    // No BroadcastChannel (Safari before 15.4): no button, rather than a
    // pop-out that would never hear from this tab. The click is listened
    // for on the document, so a button that is not on the page yet when
    // this runs still works when it is.
    function hidePopoutButtons() {
      if ("BroadcastChannel" in window) return;
      document.querySelectorAll(".js-popout").forEach(function (b) { b.hidden = true; });
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", hidePopoutButtons);
    } else {
      hidePopoutButtons();
    }
    document.addEventListener("click", function (e) {
      var b = e.target && e.target.closest && e.target.closest(".js-popout");
      if (b && "BroadcastChannel" in window) openPopout();
    });

    // ---------------------------------------------------- answers, counted
    /* While live, each question card in the teacher's notes and in "Class
       sees" shows how many of the students here have answered it: "18 / 22
       answered". The server counts (/api/live/<code>/answers, which says
       what "here" means); this asks every few seconds while there is a
       question in the notes, and puts the count on the card for it.

       The teacher's cards are their own copy, answer key and all, with no
       question id in them, so a card is found by its prompt — with the
       blanks emptied, as the class's copy has them.

       The cards are rebuilt whenever the notes are drawn again (a keystroke
       in the .md, the class moving on), which takes the count off them. A
       MutationObserver puts it back from the last answer at once rather
       than at the next ask. paintCounts only writes what differs, or the
       observer would see its own writes and never stop. */
    var counts = null;
    var ANSWERS_MS = 3000;
    // Where the cards are. A function, because FlaskIDE's notes pane is
    // made after this runs.
    function countRoots() { return [classNotes, $("notes-body")]; }

    function samePrompt(t) { return String(t || "").replace(/\[\[[^\[\]\n]*\]\]/g, "[[]]").trim(); }

    function countText(hit) {
      if (!hit) return "";
      return counts.here === null || counts.here === undefined
        ? hit.answered + " answered"
        : hit.answered + " / " + counts.here + " answered";
    }

    function paintCounts() {
      countRoots().forEach(function (root) {
        if (!root) return;
        root.querySelectorAll(".quiz").forEach(function (box) {
          var hit = null;
          if (counts && box.quizPrompt !== undefined) {
            var want = samePrompt(box.quizPrompt);
            hit = counts.questions.filter(function (q) { return q.prompt === want; })[0] || null;
          }
          var badge = box.querySelector(".quiz-count");
          if (!hit) {
            if (badge) badge.remove();
            return;
          }
          if (!badge) {
            badge = document.createElement("span");
            badge.className = "quiz-count";
            var head = box.querySelector(".quiz-head");
            (head || box).appendChild(badge);
          }
          var text = countText(hit);
          if (badge.textContent !== text) badge.textContent = text;
          var all = counts.here > 0 && hit.answered >= counts.here;
          if (badge.classList.contains("all-in") !== all) badge.classList.toggle("all-in", all);
        });
      });
    }

    function askCounts() {
      watchCards();
      // Nothing to count: not live, or no question in the notes.
      if (!liveCode || !/^ {0,3}(`{3,}|~{3,})\s*quiz\s*$/m.test(liveNotes())) {
        if (counts) { counts = null; paintCounts(); }
        return;
      }
      fetch("/api/live/" + encodeURIComponent(liveCode) + "/answers")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.questions) { counts = d; paintCounts(); }
        })
        .catch(function () { /* the next ask will do */ });
    }
    var recount = "MutationObserver" in window
      ? new MutationObserver(function () { if (counts) paintCounts(); }) : null;
    var watched = [];
    function watchCards() {
      if (!recount) return;
      countRoots().forEach(function (root) {
        if (!root || watched.indexOf(root) >= 0) return;
        watched.push(root);
        recount.observe(root, { childList: true, subtree: true });
      });
    }
    watchCards();
    setInterval(askCounts, ANSWERS_MS);
  } else {
    /* No Go live button: signed out, or not a teacher. Whatever lesson this
       browser remembers is not one this person can resume, so forget it
       here rather than let it wait for the next teacher to sign in. */
    try {
      sessionStorage.removeItem("flaskide-live-host");
      sessionStorage.removeItem("flaskide-live-files");
      localStorage.removeItem("flaskide-live-host");      // the old, shared marker
    } catch (e) {}
  }
})();
