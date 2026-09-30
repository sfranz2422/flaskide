/* The live lesson page.
 *
 * Two editors, stacked. The upper one mirrors whatever the teacher is typing
 * in their own PyIDE tab; the lower one is the student's, and they type the
 * lesson out themselves.
 *
 * THE ONE RULE THIS FILE EXISTS TO KEEP
 *
 *   Nothing that arrives from the network is ever written into the student's
 *   editor. Not on a poll, not on a reconnect, not when the lesson ends.
 *   `mirror` is the only CodeMirror this file ever calls setValue on, and
 *   `mine` is the only one the student types in. A class losing their own
 *   work because the teacher pressed a key is the failure that would stop
 *   anyone using this a second time, so it is arranged to be impossible
 *   rather than carefully avoided.
 *
 *   There is deliberately no button that copies the teacher's code down.
 *   Typing it is the exercise.
 *
 * WHY POLLING AND NOT A WEBSOCKET
 *
 *   FlaskIDE runs on `gunicorn --workers 2`. A socket lives inside one worker,
 *   so broadcasting across both would need a message broker — another Render
 *   service, another bill. A row in the Postgres that is already there costs
 *   nothing new, and the poll below asks "has the version changed?" and is
 *   answered 304 almost every time.
 */
(function () {
  "use strict";

  var L = window.FLASKIDE_LIVE || {};
  if (!L.joined || L.isHost) {
    hostControls();
    return;
  }

  var $ = function (id) { return document.getElementById(id); };

  var outputEl = $("output");
  var runBtn = $("run");
  var runLabel = $("run-label");
  var stopBtn = $("stop");
  var stateChip = $("live-state");
  var savedNote = $("mine-saved");

  var DRAFT_KEY = "flaskide-live-" + L.code;

  // ------------------------------------------------------------ the editors

  function isDark() {
    var set = document.documentElement.getAttribute("data-theme");
    if (set === "dark") return true;
    if (set === "light") return false;
    return window.matchMedia
      && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function cmTheme() { return isDark() ? "material-darker" : "default"; }

  /* Read-only, and `readOnly: "nocursor"` rather than plain true: with a
     cursor the mirror can be focused and looks typeable, and a student who
     clicks in and starts typing finds nothing happens and assumes the page
     is broken. */
  var mirror = CodeMirror.fromTextArea($("mirror"), {
    mode: "python",
    theme: cmTheme(),
    lineNumbers: true,
    readOnly: "nocursor",
    lineWrapping: false
  });

  /* And if a selection is made anyway, it cannot be taken.
   *
   * The stylesheet stops the ordinary drag. This is the second half, because
   * user-select is a rendering hint and not a rule: a browser extension, a
   * "select all" from the browser's own menu, or find-on-page can still leave
   * text selected inside the mirror, and then Ctrl+C would lift the lesson.
   * Cancelling the event is what actually refuses.
   *
   * Only over the mirror. The student's own editor is theirs to copy from,
   * and this listener is attached to the mirror's element, not the document,
   * so there is no way for it to reach the wrong one. */
  var mirrorEl = mirror.getWrapperElement();
  ["copy", "cut"].forEach(function (kind) {
    mirrorEl.addEventListener(kind, function (e) {
      e.preventDefault();
      note("Type it out — that is the exercise");
    });
  });

  var mine = CodeMirror.fromTextArea($("mine"), {
    mode: "python",
    theme: cmTheme(),
    lineNumbers: true,
    indentUnit: 4,
    tabSize: 4,
    indentWithTabs: false,
    matchBrackets: true,
    autoCloseBrackets: true,
    /* The same keys as the main editor. This editor was once configured on
       its own with Tab unbound, which in CodeMirror means a literal tab
       character — next to auto-indent's spaces, that is a TabError on a
       line that looks perfectly aligned. */
    extraKeys: {
      Tab: window.FlaskIDETabStops.indentToTabStop,
      Backspace: window.FlaskIDETabStops.backspaceToTabStop,
      "Shift-Tab": function (cm) { cm.indentSelection("subtract"); },
      "Ctrl-/": "toggleComment",
      "Cmd-/": "toggleComment",
      "Ctrl-Enter": function () { run(); },
      "Cmd-Enter": function () { run(); }
    }
  });

  /* Completion of the student's own names, as in the editor. Their own code
     is the only source — never the teacher's pane, which would be the copy
     button by another route — and nothing is offered in a SQL lesson. The
     check is a function because isSql() is defined further down and reads
     the lesson's filename at the moment of typing. */
  window.FlaskIDEComplete.attach(mine, function () {
    return !isSql();
  }, function () {
    return [mine.getValue()];
  });

  /* The student's own work, in their browser only. There is no account
     needed to follow a lesson, so there is nowhere on the server this could
     go — and a refresh in the middle of a lesson must not cost them the
     twenty lines they have typed. Every read and write is wrapped, because
     localStorage throws outright in a private window and on a locked-down
     school laptop. */
  /* Nothing kept here, and the lesson is for an assignment: start from what
     the handout link would have opened — their own draft of it, or its
     starter (the server decides which; see live_page). What they typed in
     this browser always wins over both, so a reload never puts the starter
     back over twenty minutes of typing. `null` rather than falsy: an editor
     they emptied on purpose stays empty. */
  var kept = null;
  try {
    kept = window.localStorage.getItem(DRAFT_KEY);
  } catch (e) { /* storage blocked: fall back to the starting point */ }
  var start = kept !== null ? kept : (L.starter || "");
  if (start) mine.setValue(start);
  mine.clearHistory();

  var saveTimer = null;
  mine.on("change", function () {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try {
        window.localStorage.setItem(DRAFT_KEY, mine.getValue());
        note("Saved on this computer");
      } catch (e) {
        note("Could not save here — keep this tab open");
      }
      autosave();
    }, 500);
  });

  /* ------------------------------------------------- into their projects
   *
   * Signed in, the copy they type here is an ordinary PyIDE project: press
   * Save once and it autosaves from then on, exactly as the editor does. It
   * turns up in My projects, opens at /p/<slug>, and can be turned in.
   *
   * The browser copy above stays either way. It is the only thing a
   * signed-out student has, and for a signed-in one it is what survives the
   * network being down for the ten minutes the school's wifi is having a
   * moment. The two never disagree about anything important, because both
   * are written from the same editor a fraction of a second apart.
   *
   * EVERYTHING BELOW SENDS `mine`. The mirror is not theirs and must never
   * end up in their projects with their name on it.
   */
  var saveBtn = $("live-save");
  var saveState = $("live-save-state");
  var openLink = $("live-open");
  var turnInBtn = $("live-turn-in");
  var SLUG_KEY = DRAFT_KEY + "-slug";
  var draftSlug = null;
  var pendingSave = false;
  /* Whether the lesson has an assignment behind it. Trusted from the save's
     own reply rather than assumed from the page, so a lesson whose
     assignment was closed between loading the page and pressing Save does
     not leave a Turn in button that cannot work. */
  var canTurnIn = false;

  try {
    draftSlug = window.localStorage.getItem(SLUG_KEY) || null;
  } catch (e) { /* they will press Save and get a fresh one */ }

  function savedNow(text) {
    if (!saveState) return;
    saveState.hidden = false;
    saveState.textContent = text;
    if (saveBtn) saveBtn.hidden = true;
    if (openLink && draftSlug) {
      openLink.hidden = false;
      openLink.href = "/p/" + encodeURIComponent(draftSlug);
    }
    if (turnInBtn) turnInBtn.hidden = !(draftSlug && canTurnIn);
  }

  if (draftSlug) {
    // Reopened mid-lesson with a copy already saved. The page knows whether
    // the lesson has an assignment, so Turn in can be offered straight away
    // rather than waiting for the next keystroke to trigger an autosave.
    canTurnIn = !!L.assignment;
    savedNow(L.submittedAt ? "Turned in " + L.submittedAt : "Saved");
  }

  /* Handing it in. The same endpoint the editor uses, against the same
     draft, so what the teacher sees on the dashboard is identical whichever
     way the student got there. */
  function turnIn() {
    if (!draftSlug || !canTurnIn) return;
    if (!window.confirm("Turn this in to " + (L.assignmentTitle || "your teacher")
                        + "? You can keep working and turn it in again.")) {
      return;
    }
    turnInBtn.disabled = true;
    /* SAVE FIRST, THEN HAND IN WHAT WAS SAVED.
       
       A WebIDE project is its files, and turning in replaces them with what
       is posted. This pane edits one file, so posting just that would drop
       any other file the assignment shipped — at the exact moment the work
       is handed in, and without a word. Keeping first merges the edit into
       the draft and hands back the whole map; that map is what goes in. */
    keep().then(function (saved) {
      if (!saved) {
        turnInBtn.disabled = false;
        window.alert("Could not save before turning in. Try again.");
        return;
      }
      return fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft: draftSlug, files: saved.files || {} })
      }).then(function (res) { return res.json(); })
        .then(function (data) {
          turnInBtn.disabled = false;
          if (data.error) { window.alert(data.error); return; }
          turnInBtn.textContent = "Turn in again";
          savedNow("Turned in" + (data.submitted_at ? " " + data.submitted_at : ""));
        });
    }).catch(function () {
      turnInBtn.disabled = false;
      window.alert("Could not turn it in. Check your connection and try again.");
    });
  }

  /* One place that writes to the lesson's draft, used by Save, by autosave
     and by Turn in — so the three cannot disagree about what a project is. */
  function keep() {
    return fetch("/api/live/" + encodeURIComponent(L.code) + "/keep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: mine.getValue() })
    }).then(function (res) { return res.json(); })
      .then(function (data) { return data && !data.error ? data : null; });
  }

  if (turnInBtn) turnInBtn.addEventListener("click", turnIn);

  function startDraft() {
    if (!L.signedIn || pendingSave) return;
    var text = mine.getValue();
    if (!text.trim()) { note("Type something first"); return; }
    pendingSave = true;
    /* /api/live/<code>/keep, NOT /api/draft.
       
       /api/draft makes a free-standing project with no assignment on it, and
       a draft with no assignment can never be turned in — which is what made
       handing work in from a live lesson impossible. This route puts the
       work in the assignment's own draft when the lesson has one, so it is
       the same row the handout link would have made and Turn in appears. */
    fetch("/api/live/" + encodeURIComponent(L.code) + "/keep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: text,                       // theirs, never the mirror's
        files: {}
      })
    }).then(function (res) { return res.json(); })
      .then(function (data) {
        pendingSave = false;
        if (data.error) { window.alert(data.error); return; }
        draftSlug = data.slug;
        canTurnIn = !!data.can_turn_in;
        try { window.localStorage.setItem(SLUG_KEY, draftSlug); } catch (e) {}
        savedNow("Saved");
      })
      .catch(function () {
        pendingSave = false;
        window.alert("Could not save. Check your connection and try again.");
      });
  }

  function autosave() {
    if (!draftSlug || !L.signedIn) return;
    fetch("/api/draft/" + encodeURIComponent(draftSlug), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: mine.getValue(),            // theirs, never the mirror's
        files: {},
        title: L.title || "Live lesson"
      })
    }).then(function (res) {
      if (res.status === 404) {
        /* The project was deleted from another tab, or from My projects.
           Forgetting the slug turns the next Save into a fresh one rather
           than leaving this page autosaving into nothing for the rest of
           the lesson and telling the student it was saved. */
        draftSlug = null;
        try { window.localStorage.removeItem(SLUG_KEY); } catch (e) {}
        if (saveBtn) saveBtn.hidden = false;
        if (saveState) saveState.hidden = true;
        if (openLink) openLink.hidden = true;
        return null;
      }
      return res.json();
    }).then(function (data) {
      if (data && data.saved_at) savedNow("Saved " + data.saved_at);
    }).catch(function () {
      if (saveState) saveState.textContent = "Not saved — still in this browser";
    });
  }

  if (saveBtn) saveBtn.addEventListener("click", startDraft);

  var noteTimer = null;
  function note(text) {
    if (!savedNote) return;
    savedNote.textContent = text;
    if (noteTimer) clearTimeout(noteTimer);
    noteTimer = setTimeout(function () { savedNote.textContent = ""; }, 2500);
  }

  // -------------------------------------------------------------- the mirror

  var seen = -1;
  /* What the notes pane was last rendered from. Compared before re-rendering
     because every poll hands over the whole file, and re-parsing markdown
     once a second would throw away a link the moment anyone moved to click
     it — the element under the cursor is replaced. */
  var lastNotes = null;

  var mirrorWrap = $("mirror-wrap");
  var mirrorNotes = $("mirror-notes");

  function showMirror(data) {
    /* A .md file is class notes, not code. Rendering it is what makes a link
       the teacher puts up something the class can actually click — raw
       markdown in a code pane is just `[click here](http://…)` in grey.
       notes.js sanitises the HTML and points every link at a new tab. */
    var asNotes = data.filename
      && window.FlaskIDENotes && window.FlaskIDENotes.isMarkdown(data.filename);

    if (asNotes) {
      mirrorWrap.hidden = true;
      mirrorNotes.hidden = false;
      if (typeof data.body === "string" && data.body !== lastNotes) {
        lastNotes = data.body;
        window.FlaskIDENotes.render(mirrorNotes, data.body);
      }
    } else {
      mirrorNotes.hidden = true;
      var wasHidden = mirrorWrap.hidden;
      mirrorWrap.hidden = false;
      // The ONLY setValue on the mirror, and there is no setValue on `mine`
      // anywhere below this line.
      if (typeof data.body === "string" && data.body !== mirror.getValue()) {
        var scroll = mirror.getScrollInfo();
        mirror.setValue(data.body);
        // Keep the reader where they were. Without this every keystroke from
        // the teacher throws a student who has scrolled back to look at line 4
        // straight back to the top, which makes the mirror unreadable.
        mirror.scrollTo(scroll.left, scroll.top);
      }
      /* CodeMirror measures itself when it is built. Built or updated while
         its container is display:none it measures zero, and comes back from
         the notes pane as an empty box that only fills in when something
         forces a redraw. Switching a tab in front of a class is exactly when
         that would happen, so refresh on the way back. */
      if (wasHidden) mirror.refresh();
    }

    if (data.filename) {
      var name = document.getElementById("mirror-name");
      if (name) name.textContent = data.filename;
    }
    seen = data.version;
    showNotes(data);
  }

  /* The project's notes, in their own pane under the console. Re-rendered
     only when they change, for the same reason as the mirror's notes above:
     every poll carries them whole, and re-rendering once a second would
     replace a link under the cursor just as someone clicked it. */
  var notesView = $("live-notes-view");
  var notesBody = $("live-notes");
  var shownNotes = null;

  function showNotes(data) {
    if (!notesView || typeof data.notes !== "string") return;
    if (data.notes === shownNotes) return;
    shownNotes = data.notes;
    notesView.hidden = !data.notes.trim();
    if (!notesView.hidden) window.FlaskIDENotes.render(notesBody, data.notes);
  }

  function setState(text, kind) {
    if (!stateChip) return;
    stateChip.textContent = text;
    stateChip.className = "chip live-chip" + (kind ? " live-" + kind : "");
  }

  if (typeof L.body === "string") {
    showMirror({ body: L.body, version: L.version, filename: L.filename,
                 notes: L.notes });
  }

  var POLL_MS = 1000;
  var misses = 0;

  function poll() {
    fetch("/api/live/" + encodeURIComponent(L.code) + "?v=" + seen,
          { cache: "no-store" })
      .then(function (res) {
        if (res.status === 304) {         // the usual answer: nothing new
          misses = 0;
          setState("Live", "on");
          return null;
        }
        if (res.status === 404) {
          setState("Lesson not found", "off");
          throw new Error("gone");
        }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        misses = 0;
        if (!data) return;
        if (data.ended) {
          showMirror(data);
          setState("Lesson ended", "off");
          // Stop asking. The row is not going to change again, and thirty
          // browsers politely polling a finished lesson until home time is
          // exactly the kind of traffic nobody notices they are paying for.
          throw new Error("ended");
        }
        showMirror(data);
        setState("Live", "on");
      })
      .catch(function (err) {
        if (err && (err.message === "ended" || err.message === "gone")) return;
        // A dropped poll is normal on school wifi and says nothing about the
        // lesson. Only a run of them is worth telling anyone about, and the
        // next success clears it.
        misses = misses + 1;
        if (misses >= 3) setState("Reconnecting…", "wait");
      })
      .finally(function () {
        if (stateChip && stateChip.textContent === "Lesson ended") return;
        if (stateChip && stateChip.textContent === "Lesson not found") return;
        setTimeout(poll, POLL_MS);
      });
  }

  poll();

  // ------------------------------------------------------------- their Run
  //
  // FlaskIDE runs a real Flask app in Pyodide and answers requests through
  // its test client, so "running" means booting Python, loading the app, and
  // asking it for "/". The preview is that reply, which is why it has an
  // address bar: the page on screen is one route's answer.
  //
  // A project here can also be SQL rather than Flask. Which one this is is
  // decided by the file the lesson is editing, not by a setting, so a SQL
  // lesson and a Flask lesson need nothing switched by hand.

  function write(text, cls) {
    var span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text;
    outputEl.appendChild(span);
    outputEl.scrollTop = outputEl.scrollHeight;
  }

  function clearOutput() { outputEl.textContent = ""; }

  var runtime = window.FlaskIDERuntime;
  var preview = null;
  var running = false;

  function isSql() { return /\.sql$/i.test(L.filename || ""); }
  function entryName() { return isSql() ? "query.sql" : "app.py"; }

  function setBusy(on) {
    running = on;
    runBtn.hidden = on;
    stopBtn.hidden = true;        // there is nothing to interrupt: see below
    runBtn.disabled = on;
  }

  async function run() {
    if (running) return;
    setBusy(true);
    clearOutput();
    var project = {};
    project[entryName()] = mine.getValue();   // theirs, never the mirror's
    try {
      if (isSql()) {
        var out = await runtime.runSql(project, function (note) {
          if (note) write(note + "\n", "dim");
        });
        if (!out.ok) {
          write("\n" + out.error + "\n", "err");
        } else {
          (out.tables || []).forEach(function (tbl) {
            write("\n" + (tbl.sql || "") + "\n", "dim");
            write((tbl.columns || []).join(" | ") + "\n");
            (tbl.rows || []).forEach(function (row) {
              write(row.join(" | ") + "\n");
            });
          });
        }
        return;
      }

      var res = await runtime.run(project, function (note) {
        if (note) write(note + "\n", "dim");
      });
      if (!res.ok) {
        write("\n" + res.error + "\n", "err");
        return;
      }
      if (!res.routes.length) {
        write("Your app has no routes yet.\n", "dim");
        return;
      }
      write("Running. Routes:\n", "dim");
      res.routes.forEach(function (r) {
        write("  " + r.methods.join(",") + "  " + r.path + "\n");
      });
      await preview.go("/");
    } catch (err) {
      write("\n" + (err && err.message ? err.message : String(err)) + "\n", "err");
    } finally {
      setBusy(false);
    }
  }

  preview = new window.FlaskIDEPreview({
    frame: $("preview"),
    bar: $("preview-path"),
    onStatus: function (code, path) {
      var el = $("preview-status");
      if (!el) return;
      el.textContent = code ? String(code) : "";
      el.className = "status-code" +
        (code >= 500 ? " bad" : code >= 400 ? " warn" : code ? " ok" : "");
      el.title = path || "";
    }
  });

  runBtn.disabled = false;
  runLabel.textContent = "Run";
  runBtn.addEventListener("click", run);
  /* No Stop. A Flask request runs to completion inside Pyodide on this
     thread; there is nothing to interrupt from here, and a button that
     cannot do its job is worse than no button. The editor has none either. */
  if (stopBtn) stopBtn.hidden = true;
  $("clear").addEventListener("click", clearOutput);
  var backBtn = $("preview-back");
  if (backBtn) backBtn.addEventListener("click", function () { preview.back(); });

  // ----------------------------------------------------------- host's page

  function hostControls() {
    var stop = document.getElementById("live-stop");
    if (!stop) return;
    stop.addEventListener("click", function () {
      if (!window.confirm("End the lesson? Your class stops seeing your editor.")) {
        return;
      }
      fetch("/api/live/" + encodeURIComponent(L.code) + "/stop", { method: "POST" })
        .then(function () { stop.disabled = true; stop.textContent = "Ended"; });
    });
  }
})();
