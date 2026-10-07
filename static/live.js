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

  // The two editors, once there are any. Declared here so the theme switch
  // below can repaint them; on the join card and the host's page they stay
  // undefined and the switch only changes the page around them.
  var mirror, mine;
  themeSwitch();

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

  /* Questions in the teacher's notes answer into the lesson's assignment.
     A lesson with none has nowhere to record them, and notes.js says so on
     each question instead of taking an answer it would lose. */
  window.FlaskIDENotes.setQuizContext({ assignment: L.assignment,
                                       signedIn: L.signedIn });

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
  mirror = CodeMirror.fromTextArea($("mirror"), {
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

  mine = CodeMirror.fromTextArea($("mine"), {
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

  /* What goes in the brackets (sighint.js), as in the editor. Their own
     defs come from THEIR tabs only, never the teacher's pane — the same
     rule as completion below, for the same reason. */
  window.FlaskIDESigHint.attach(mine, {
    flask: true,
    sources: function () {
      return Object.keys(docs).filter(function (n) { return /\.py$/i.test(n); })
        .map(function (n) { return docs[n].getValue(); });
    },
    isPython: function () { return modeFor(active) === "python"; }
  });

  /* Completion of the student's own names, as in the editor. Their own
     Python is the only source — never the teacher's pane, which would be the
     copy button by another route — and only while a .py tab is open: a word
     typed into a template or a query is not a Python name. The check is a
     function because it must read the tab open at the moment of typing. */
  window.FlaskIDEComplete.attach(mine, function () {
    return window.FlaskIDEComplete.isPy(active);
  }, function () {
    return Object.keys(docs).filter(function (n) {
      return /\.py$/i.test(n);
    }).map(function (n) { return docs[n].getValue(); });
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
  var keptBase = null;
  var BASE_KEY = DRAFT_KEY + "-base";
  try {
    kept = window.localStorage.getItem(DRAFT_KEY);
    keptBase = window.localStorage.getItem(BASE_KEY);
  } catch (e) { /* storage blocked: fall back to the starting point */ }

  /* UNLESS THEIR DRAFT HAS MOVED ON WITHOUT THIS BROWSER. The copy kept
     here remembers which version of their draft it grew from. If the draft
     has been saved since — homework at home last night, through the
     handout link — this browser's copy is the older work, and letting it
     win would put last night's work under it on screen and then, at the
     first Save, over it on the server. A reopened lesson is exactly when
     that happens: the same code, so the same key, a day later.

     A copy with no version beside it (kept before this existed, or never
     saved) still wins, as it always did. */
  var behind = kept !== null && keptBase !== null
    && typeof L.draftVersion === "number"
    && L.draftVersion > Number(keptBase);
  if (behind) {
    kept = null;
    try {
      window.localStorage.removeItem(DRAFT_KEY);
      window.localStorage.removeItem(DRAFT_KEY + "-files");
    } catch (e) { /* nothing kept to remove */ }
  }

  function noteBase(version) {
    try { window.localStorage.setItem(BASE_KEY, String(version)); }
    catch (e) { /* then the copy here simply wins, as before */ }
  }
  if (typeof L.draftVersion === "number" && (keptBase === null || behind)) {
    noteBase(L.draftVersion);
  }
  var start = kept !== null ? kept : (L.starter || "");
  if (start) mine.setValue(start);
  mine.clearHistory();

  /* ------------------------------------------------------------ their files
   *
   * The entry file and the rest of their project, each its own CodeMirror
   * document swapped into `mine`, as the editor keeps them — so switching
   * tabs keeps the caret and the undo history, and there is still only the
   * one editor a student types in. The mirror never fills any of these.
   *
   * WHICH FILE IS THE ENTRY comes from the server (L.entry), which reads it
   * off the project's own files the way the rest of FlaskIDE does: query.sql
   * present means SQL. It is never retyped here. Only a lesson with no
   * assignment has no files to ask, and the server then goes by the
   * teacher's open file, which is the rule this page always used.
   *
   * The other files are kept in this browser beside the entry, under their
   * own key, and the same rule decides where they start: what this browser
   * has wins, else the project's own files (their draft's, or the
   * assignment's). The entry's key is unchanged, so a browser that kept a
   * lesson before tabs existed still gets its typing back.
   *
   * A .md file stays out of the strip. It is the project's notes, which the
   * class already reads in the Notes pane, but it is still saved: a save
   * that left it out would delete the assignment's notes. */
  var MAIN = L.entry || "app.py";
  var NAME_OK = /^(?:(?:templates|static)\/)?[A-Za-z0-9][A-Za-z0-9 _-]{0,50}\.[A-Za-z0-9]{1,8}$/;
  var FILES_KEY = DRAFT_KEY + "-files";
  var docs = {};
  var active = MAIN;
  var tabsEl = $("mine-tabs");
  docs[MAIN] = mine.getDoc();
  mine.setOption("mode", modeFor(MAIN));

  var keptFiles = null;
  try {
    keptFiles = JSON.parse(window.localStorage.getItem(FILES_KEY) || "null");
  } catch (e) { /* blocked, or not ours to read: the project's own files */ }
  var startFiles = (keptFiles && typeof keptFiles === "object")
    ? keptFiles : (L.starterFiles || {});
  Object.keys(startFiles).forEach(function (name) {
    if (name !== MAIN && typeof startFiles[name] === "string") {
      docs[name] = CodeMirror.Doc(startFiles[name], modeFor(name));
    }
  });

  // The same modes the editor gives each kind of file (see app.js).
  function modeFor(name) {
    if (/\.sql$/i.test(name)) return "text/x-sql";
    if (/\.py$/i.test(name)) return "python";
    if (/\.css$/i.test(name)) return "css";
    if (/\.(html|htm|jinja2?)$/i.test(name)) return "htmlmixed";
    return "text/plain";
  }

  /* The entry file, whichever tab is open. NOT mine.getValue(): with a
     template showing, that is the template, and Save would put HTML into
     app.py. */
  function mainSource() { return docs[MAIN].getValue(); }

  function dataFiles() {
    var out = {};
    Object.keys(docs).forEach(function (n) {
      if (n !== MAIN) out[n] = docs[n].getValue();
    });
    return out;
  }

  /* The whole project, as the runtime and /api/draft both want it. */
  function allFiles() {
    var out = dataFiles();
    out[MAIN] = mainSource();
    return out;
  }

  function isNotes(name) {
    return window.FlaskIDENotes && window.FlaskIDENotes.isMarkdown(name);
  }

  function renderTabs() {
    if (!tabsEl) return;
    tabsEl.textContent = "";
    var names = [MAIN].concat(Object.keys(docs).filter(function (n) {
      return n !== MAIN && !isNotes(n);
    }).sort());
    names.forEach(function (name) {
      var tab = document.createElement("button");
      tab.type = "button";
      tab.className = "tab" + (name === active ? " tab-on" : "");
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(name === active));
      tab.textContent = name;
      tab.addEventListener("click", function () { switchTo(name); });
      tabsEl.appendChild(tab);
    });
  }

  function switchTo(name) {
    if (!docs[name] || name === active) return;
    active = name;
    mine.swapDoc(docs[name]);
    mine.setOption("mode", modeFor(name));
    renderTabs();
    mine.focus();
  }

  function keepInBrowser() {
    try {
      window.localStorage.setItem(DRAFT_KEY, mainSource());
      window.localStorage.setItem(FILES_KEY, JSON.stringify(dataFiles()));
      return true;
    } catch (e) {
      return false;
    }
  }

  /* A file of their own, for following a teacher who makes one mid-lesson —
     a second template, a stylesheet. Same names the editor allows, and the
     server checks again. No way to delete one here, on purpose: the server
     reads an empty map from this page as "leave the files alone" (see
     live_keep), which is only safe while nothing on this page can empty it. */
  var newFileBtn = $("mine-new-file");
  if (newFileBtn) {
    newFileBtn.addEventListener("click", function () {
      var name = window.prompt(
        "New file. A template goes in templates/ and a stylesheet in " +
        "static/ — that is where Flask looks for them.\n\n" +
        "For example: templates/about.html", "templates/");
      if (name === null) return;
      name = name.trim();
      if (!name) return;
      if (docs[name]) { switchTo(name); return; }
      if (!NAME_OK.test(name) || isNotes(name)
          || name === L.entry || name === L.sqlEntry) {
        window.alert("'" + name + "' will not work.\n\nUse letters, digits, " +
                     "dashes and underscores, end with an extension like " +
                     ".py, .html or .css, and put it either at the top level " +
                     "or in templates/ or static/.");
        return;
      }
      docs[name] = CodeMirror.Doc("", modeFor(name));
      switchTo(name);
      changed();
    });
  }

  renderTabs();

  var saveTimer = null;
  /* Every change in any tab, and a new file, which fires no editor event. */
  function changed() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      if (keepInBrowser()) {
        note("Saved on this computer");
      } else {
        note("Could not save here — keep this tab open");
      }
      autosave();
    }, 500);
  }
  mine.on("change", changed);

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

  /* TWO TABS, ONE DRAFT. Every write says which version of the draft this
     tab last saw, and which tab it is; the server refuses it if another tab
     has saved since. Without that, the Classroom link open in a forgotten
     second tab wrote its old copy over this lesson's work the moment a key
     was pressed in it. Refused, this tab stops saving and says so — the
     other tab's copy is the one to keep. See Draft.version in accounts.py.

     Unknown until the first save when the page had no draft to start from
     (a lesson with no assignment), and then nothing is claimed: the first
     reply carries the version, and the guard holds from there. */
  var TAB = Math.random().toString(36).slice(2, 14);
  /* NOT `seen`. The mirror below keeps the lesson's version in a `seen` of
     its own, and with one function around both they were the same variable:
     the first poll replaced the draft's version with the lesson's, so a
     student whose draft had last been saved anywhere else — the handout
     link, or this page yesterday — had every Save refused as "changed in
     another tab". Nothing about it showed until they pressed Save. */
  var draftSeen = typeof L.draftVersion === "number" ? L.draftVersion : null;
  var stale = false;

  function stamp(payload) {
    if (draftSeen !== null) { payload.base = draftSeen; payload.tab = TAB; }
    return payload;
  }

  function saw(data) {
    if (data && typeof data.version === "number") {
      draftSeen = data.version;
      noteBase(draftSeen);
    }
  }

  function goneStale(message) {
    if (stale) return;
    stale = true;
    if (saveState) {
      saveState.hidden = false;
      saveState.textContent = "Not saved — changed in another tab";
    }
    if (turnInBtn) turnInBtn.disabled = true;
    window.alert(message + " What you typed here is still on screen, and in "
                 + "this browser, so copy it first if you need it.");
  }

  function savedNow(text) {
    if (!saveState) return;
    saveState.hidden = false;
    saveState.textContent = text;
    if (saveBtn) saveBtn.hidden = true;
    if (openLink && draftSlug) {
      openLink.hidden = false;
      openLink.href = "/p/" + encodeURIComponent(draftSlug);
    }
    if (turnInBtn) turnInBtn.hidden = !canTurnIn;
  }

  /* A lesson for an assignment offers Turn in from the start: there is no
     Save to press first, and turnIn() makes the draft itself if the first
     keystroke has not already. */
  canTurnIn = !!L.assignment;
  if (draftSlug || L.submittedAt) {
    // Reopened mid-lesson with a copy already saved, or already turned in.
    savedNow(L.submittedAt ? "Turned in " + L.submittedAt : "Saved");
  }

  /* Handing it in. The same endpoint the editor uses, against the same
     draft, so what the teacher sees on the dashboard is identical whichever
     way the student got there. */
  function turnIn() {
    if (!canTurnIn || stale) return;
    if (!window.confirm("Turn this in to " + (L.assignmentTitle || "your teacher")
                        + "? You can keep working and turn it in again.")) {
      return;
    }
    turnInBtn.disabled = true;
    /* SAVE FIRST, THEN HAND IN WHAT WAS SAVED.
       
       A FlaskIDE project is its files, and turning in replaces them with
       what is posted. Keeping first writes every tab into the draft and
       hands back the whole map as saved; that map is what goes in, so what
       the teacher receives is exactly what the draft holds. */
    keep().then(function (saved) {
      if (!saved) {
        if (stale) return;                // goneStale has said why
        turnInBtn.disabled = false;
        window.alert("Could not save before turning in. Try again.");
        return;
      }
      // the first save of the lesson may be this one
      rememberDraft(saved.slug);
      return fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stamp({ draft: draftSlug, files: saved.files || {} }))
      }).then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.stale) { goneStale(data.error); return; }
          turnInBtn.disabled = false;
          if (data.error) { window.alert(data.error); return; }
          saw(data);
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
      body: JSON.stringify(stamp({ code: mainSource(), files: dataFiles(),
                                   entry: MAIN }))
    }).then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.stale) { goneStale(data.error); return null; }
        if (data && !data.error) { saw(data); return data; }
        return null;
      });
  }

  if (turnInBtn) turnInBtn.addEventListener("click", turnIn);

  function rememberDraft(slug) {
    if (!slug) return;
    draftSlug = slug;
    try { window.localStorage.setItem(SLUG_KEY, draftSlug); } catch (e) {}
  }

  /* The silent Save of an assignment lesson: the first keystroke makes the
     draft — the same row the handout link would have made — and autosave
     carries on from there. Without it a student's work would reach the
     server only when they pressed Turn in, and a closed laptop lid before
     that would leave nothing on the My work page. */
  var pendingKeep = false;
  function keepQuietly() {
    if (stale || pendingKeep || draftSlug || !L.signedIn || !L.assignment) return;
    if (!mainSource().trim()) return;
    pendingKeep = true;
    keep().then(function (saved) {
      pendingKeep = false;
      if (!saved) return;
      rememberDraft(saved.slug);
      savedNow(L.submittedAt ? "Turned in " + L.submittedAt : "Saved");
    }).catch(function () { pendingKeep = false; });
  }

  function startDraft() {
    if (!L.signedIn || pendingSave) return;
    var text = mainSource();
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
      body: JSON.stringify(stamp({
        code: text,                       // theirs, never the mirror's
        files: dataFiles(),
        entry: MAIN
      }))
    }).then(function (res) { return res.json(); })
      .then(function (data) {
        pendingSave = false;
        if (data.stale) { goneStale(data.error); return; }
        if (data.error) { window.alert(data.error); return; }
        saw(data);
        rememberDraft(data.slug);
        canTurnIn = !!data.can_turn_in;
        savedNow("Saved");
      })
      .catch(function () {
        pendingSave = false;
        window.alert("Could not save. Check your connection and try again.");
      });
  }

  function autosave() {
    if (stale) return;
    if (!draftSlug) { keepQuietly(); return; }
    if (!L.signedIn) return;
    fetch("/api/draft/" + encodeURIComponent(draftSlug), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stamp({
        /* Every file, entry included, because this route REPLACES the
           project with what it is sent — and refuses a map without an entry.
           It was sent `files: {}` once, when the page had one editor, and
           every autosave from the live page came back 400 and saved nothing;
           the "Saved" on screen was the last explicit Save, never updated. */
        files: allFiles(),
        title: L.title || "Live lesson"
      }))
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
      if (data && data.stale) { goneStale(data.error); return; }
      saw(data);
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
      // A template the teacher opens is coloured as HTML, a query as SQL.
      var mode = modeFor(data.filename || "");
      if (mirror.getOption("mode") !== mode) mirror.setOption("mode", mode);
      // The ONLY setValue on the mirror. `mine` is never given anything from
      // the network: its tabs are filled from the page and their browser.
      if (typeof data.body === "string" && data.body !== mirror.getValue()) {
        clearCaret();                // its line is about to be replaced
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
      showCaret(typeof data.cursor === "string" ? data.cursor : "");
    }

    if (data.filename) {
      // The notes are "instructions" on every page a student sees, never
      // "instructions.md": the class meets them as a button, not a file.
      var name = document.getElementById("mirror-name");
      if (name) name.textContent = asNotes
        ? data.filename.replace(/\.(md|markdown)$/i, "") : data.filename;
    }
    seen = data.version;
    showNotes(data);
    showTeacherOutput(data, data.initial);
    showTeacherPage(data, data.initial);
  }

  /* ------------------------------------------------ the teacher's caret
     Where the teacher is typing, drawn as a blinking caret on a tinted line,
     and followed: when it moves off screen the mirror scrolls to it. It is a
     bookmark widget, not a selection or a real cursor, so the mirror stays
     "nocursor" and still cannot be focused or copied from.

     What the teacher has highlighted comes as "anchor-head" and is painted
     yellow with markText — again a mark, not a selection, for the same
     reason. The caret sits at the head, where the drag ended, as it does in
     the teacher's own editor; the line tint is left off then, because a
     tinted line inside a yellow block reads as a second thing to look at.

     Following is the point — a class otherwise watches line 1 while the
     teacher types on line 40 — but a student who scrolls back to read
     something must not be yanked away mid-sentence. So scrolling the
     mirror by hand pauses following for a few seconds, and only that does:
     the scroll events CodeMirror fires for its own scrolling are ignored by
     listening for the wheel, a touch and the scrollbar instead. */
  var caretMark = null;
  var caretLine = null;
  var pickMark = null;
  var followAfter = 0;
  var FOLLOW_PAUSE_MS = 5000;

  ["wheel", "touchmove", "mousedown"].forEach(function (kind) {
    mirrorEl.addEventListener(kind, function () {
      followAfter = Date.now() + FOLLOW_PAUSE_MS;
    }, { passive: true });
  });

  function clearCaret() {
    if (caretMark) { caretMark.clear(); caretMark = null; }
    if (pickMark) { pickMark.clear(); pickMark = null; }
    /* A line handle from before a setValue is detached, and removing a
       class from it throws — getLineNumber is null for exactly those. */
    if (caretLine && mirror.getLineNumber(caretLine) !== null) {
      mirror.removeLineClass(caretLine, "background", "mirror-caret-line");
    }
    caretLine = null;
  }

  // "line:ch" to a position in the mirror. Clamped: the caret and the text
  // arrive together, but a student's mirror is never trusted to be the
  // exact shape the stamp assumed.
  function mirrorPos(line, ch) {
    line = Math.min(+line, mirror.lastLine());
    return { line: line, ch: Math.min(+ch, mirror.getLine(line).length) };
  }

  function showCaret(cursor) {
    clearCaret();
    var m = /^(?:(\d+):(\d+)-)?(\d+):(\d+)$/.exec(cursor);
    if (!m) return;                  // a notes file, or an older editor
    var at = mirrorPos(m[3], m[4]);
    var mark = document.createElement("span");
    mark.className = "mirror-caret";
    caretMark = mirror.setBookmark(at, { widget: mark, insertLeft: true });
    var show = at;
    if (m[1] !== undefined) {
      var other = mirrorPos(m[1], m[2]);
      var backwards = CodeMirror.cmpPos(other, at) > 0;  // dragged upwards
      var from = backwards ? at : other, to = backwards ? other : at;
      pickMark = mirror.markText(from, to, { className: "mirror-pick" });
      show = { from: from, to: to };
    } else {
      caretLine = mirror.addLineClass(at.line, "background", "mirror-caret-line");
    }
    // Only scrolls when it is off screen, so a mirror that already shows it
    // does not twitch on every keystroke.
    if (Date.now() >= followAfter) mirror.scrollIntoView(show, 60);
  }

  /* The project's notes, in their own pane under the console, as slides when
     they have `---` in them (notes.js, slideView). The teacher's editor
     sends the WHOLE file and "3/5", the slide the teacher is on.

     A student can move through the slides on their own — read ahead, go
     back to a question — and every time the teacher moves, this jumps to
     the teacher's slide: the class is brought back together by the person
     teaching, not kept there. Only a MOVE snaps. The teacher typing on the
     same slide leaves a student who has gone ahead where they are, or they
     would be pulled back on every keystroke.

     The viewer only re-renders when what is on screen changes, because
     every poll carries the notes whole, and rendering once a second would
     replace a link — or a half-typed answer — under the student's hand. */
  var notesView = $("live-notes-view");
  var notesBody = $("live-notes");
  var notesSlides = notesBody ? window.FlaskIDENotes.slideView(notesBody) : null;
  var teacherSlide = null;           // the last "3/5" the teacher sent
  var teacherAt = -1;                // and that slide, from 0

  /* "Teacher: slide 3", in the pane head, and a way back to it for a
     student who has wandered off. Hidden while they are on it. */
  var slideMark = $("live-slide");

  function paintTeacherMark() {
    if (!slideMark || !notesSlides) return;
    var away = teacherAt >= 0 && notesSlides.count() > 0
      && notesSlides.at() !== teacherAt;
    slideMark.hidden = !away;
    slideMark.textContent = away ? "Back to the teacher's slide (" + (teacherAt + 1) + ")" : "";
  }

  if (notesSlides) {
    notesSlides.onMove(paintTeacherMark);
    if (slideMark) {
      slideMark.addEventListener("click", function () {
        if (teacherAt >= 0) notesSlides.go(teacherAt);
        paintTeacherMark();
      });
    }
  }

  function showNotes(data) {
    if (!notesView || !notesSlides || typeof data.notes !== "string") return;
    var slide = typeof data.slide === "string" ? data.slide : "";
    notesView.hidden = !data.notes.trim();
    if (notesView.hidden) return;
    var jump;
    if (slide !== teacherSlide) {
      teacherSlide = slide;
      var m = slide.match(/^(\d+)\/(\d+)$/);
      teacherAt = m ? parseInt(m[1], 10) - 1 : -1;
      if (teacherAt >= 0) jump = teacherAt;
    }
    notesSlides.show(data.notes, jump);
    paintTeacherMark();
  }

  // ------------------------------------------- what the teacher's Run made
  //
  // Their console and their page, each beside the student's own and never
  // in it: the student's console is theirs, and their preview frame is what
  // their own app answers into. Nothing from the network goes in either.
  //
  // NEITHER COMES TO THE FRONT BY ITSELF. Each used to, whenever the
  // teacher pressed Run or followed a link, and every Run in a lesson took
  // thirty students away from their own app mid-thought. Now the tab
  // appears and gets a dot, and the student looks when they choose to.

  var teacherOut = $("teacher-output");
  var outMineTab = $("out-mine");
  var outTeacherTab = $("out-teacher");
  var clearBtn = $("clear");
  var shownOutput = null;

  function showOutputTab(teachers) {
    if (!teacherOut) return;
    teacherOut.hidden = !teachers;
    outputEl.hidden = teachers;
    outMineTab.classList.toggle("is-on", !teachers);
    outTeacherTab.classList.toggle("is-on", teachers);
    if (teachers) outTeacherTab.classList.remove("has-new");
    clearBtn.hidden = teachers;               // Clear is for their own
  }

  function showTeacherOutput(data, quietly) {
    if (!teacherOut || typeof data.output !== "string") return;
    if (data.output === shownOutput) return;
    shownOutput = data.output;
    teacherOut.textContent = data.output;
    teacherOut.scrollTop = teacherOut.scrollHeight;
    if (!data.output) return;
    outTeacherTab.hidden = false;
    if (quietly || !teacherOut.hidden) return;
    outTeacherTab.classList.add("has-new");
  }

  var teacherFrame = $("teacher-page");
  var teacherWrap = $("teacher-page-wrap");
  var pageMineTab = $("page-mine");
  var pageTeacherTab = $("page-teacher");
  var pageLabel = pageTeacherTab ? pageTeacherTab.textContent : "";
  var shownPage = null;

  function showPageTab(teachers) {
    if (!teacherWrap) return;
    teacherWrap.hidden = !teachers;
    $("preview-mine").hidden = teachers;
    var bar = $("preview-bar");
    if (bar) bar.hidden = teachers;           // it drives their app, not this
    var status = $("preview-status");
    if (status) status.style.visibility = teachers ? "hidden" : "";
    pageMineTab.classList.toggle("is-on", !teachers);
    pageTeacherTab.classList.toggle("is-on", teachers);
    if (teachers) pageTeacherTab.classList.remove("has-new");
  }

  /* `page` is JSON from the teacher's editor: {path, html} for a Flask page,
     {sql: true, html} for a results grid. srcdoc is assigned only when it
     changes, because every assignment rebuilds the frame and flashes white
     — once a second, for a whole lesson, on thirty screens. */
  function showTeacherPage(data, quietly) {
    if (!teacherFrame || typeof data.page !== "string") return;
    if (data.page === shownPage) return;
    shownPage = data.page;
    var got = {};
    try { got = data.page ? JSON.parse(data.page) : {}; } catch (e) { got = {}; }
    var html = typeof got.html === "string" ? got.html : "";
    if (!html) return;
    pageTeacherTab.textContent = got.sql
      ? pageLabel.replace(/page$/, "results")
      : pageLabel + (got.path ? " — " + got.path : "");
    /* Links open "in a new tab", which the sandbox refuses as a popup: a
       click does nothing, rather than navigating the frame to an error
       page for a path only the teacher's app can answer. */
    teacherFrame.srcdoc = '<base target="_blank">' + html;
    pageTeacherTab.hidden = false;
    if (quietly || !teacherWrap.hidden) return;
    pageTeacherTab.classList.add("has-new");
  }

  if (teacherOut) {
    outMineTab.addEventListener("click", function () {
      showOutputTab(false); openConsole(true);
    });
    outTeacherTab.addEventListener("click", function () {
      showOutputTab(true); openConsole(true);
    });
  }

  /* The console starts folded to its head, leaving the column to the page
     and the notes; the head's arrow opens it. An error opens it too — a
     mistake written into a folded pane is a mistake nobody sees, and the
     page simply looks broken. So does Run in a SQL lesson,
     where the console is the only place the results go. Not remembered between visits: folded is
     the state every lesson should start in. */
  var outputView = $("output-view");
  var foldBtn = $("out-fold");

  function openConsole(open) {
    if (!outputView) return;
    outputView.classList.toggle("is-folded", !open);
    if (foldBtn) {
      foldBtn.textContent = open ? "▾" : "▸";
      foldBtn.title = open ? "Fold the console away" : "Show the console";
      foldBtn.setAttribute("aria-expanded", String(open));
    }
  }

  if (foldBtn) {
    foldBtn.addEventListener("click", function () {
      openConsole(outputView.classList.contains("is-folded"));
    });
  }
  openConsole(false);

  if (teacherWrap) {
    pageMineTab.addEventListener("click", function () { showPageTab(false); });
    pageTeacherTab.addEventListener("click", function () { showPageTab(true); });
  }

  function setState(text, kind) {
    if (!stateChip) return;
    stateChip.textContent = text;
    stateChip.className = "chip live-chip" + (kind ? " live-" + kind : "");
  }

  if (typeof L.body === "string") {
    showMirror({ body: L.body, version: L.version, filename: L.filename,
                 notes: L.notes, slide: L.slide, output: L.output,
                 cursor: L.cursor,
                 page: L.page,
                 // joining mid-lesson: offer the teacher's output and page,
                 // but leave the student looking at their own until they change
                 initial: true });
  }

  var POLL_MS = 1000;
  /* A lesson made ahead from the assignment page, whose link was posted
     before it began. Its page keeps checking — not every second, since a
     tab opened the night before would ask all night — and the lesson
     appears within a few seconds of the teacher starting it. */
  var WAITING_MS = 15000;
  var waiting = false;
  var misses = 0;


  function poll() {
    fetch("/api/live/" + encodeURIComponent(L.code) + "?v=" + seen,
          { cache: "no-store" })
      .then(function (res) {
        if (res.status === 304) {         // the usual answer: nothing new
          misses = 0;
          waiting = false;                // only a lesson on the air says 304
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
        if (data.ended && data.waiting) {
          waiting = true;
          setState("Not started yet", "wait");
          return;
        }
        waiting = false;
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
        setTimeout(poll, waiting ? WAITING_MS : POLL_MS);
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
  // decided by the student's own entry file (see MAIN), not by a setting, so
  // a SQL lesson and a Flask lesson need nothing switched by hand.

  /* The syntax card, covering their own console (opened first, in run) —
     never the teacher's. `reveal` opens the tab the error is in. */
  var syntaxCard = window.FlaskIDESyntax.attach({
    host: $("output-view"),
    editor: mine,
    reveal: function (file) {
      if (!docs[file]) return null;
      switchTo(file);
      return docs[file];
    }
  });

  function write(text, cls) {
    var span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text;
    outputEl.appendChild(span);
    outputEl.scrollTop = outputEl.scrollHeight;
    if (cls === "err") openConsole(true);
  }

  function clearOutput() { outputEl.textContent = ""; }

  var runtime = window.FlaskIDERuntime;
  var preview = null;
  var running = false;

  function isSql() { return MAIN === L.sqlEntry; }

  function setBusy(on) {
    running = on;
    runBtn.hidden = on;
    stopBtn.hidden = true;        // there is nothing to interrupt: see below
    runBtn.disabled = on;
  }

  /* Query results as text, in the console — the live page has no results
     grid. Columns are padded to line up, because "id | name" over rows of
     different widths is unreadable after the third row. */
  function writeSqlResults(results) {
    (results || []).forEach(function (r) {
      write("\n" + r.statement + "\n", "dim");
      if (!r.columns) {
        write(r.changed >= 0 ? r.changed + " changed\n" : "done\n", "dim");
        return;
      }
      var cells = [r.columns].concat(r.rows).map(function (row) {
        return row.map(function (v) { return v === null ? "NULL" : String(v); });
      });
      var widths = r.columns.map(function (_, i) {
        return Math.max.apply(null, cells.map(function (row) {
          return row[i].length;
        }));
      });
      cells.forEach(function (row, n) {
        write(row.map(function (v, i) {
          return v + new Array(widths[i] - v.length + 1).join(" ");
        }).join(" | ").replace(/\s+$/, "") + "\n");
        if (n === 0) {
          write(widths.map(function (w) {
            return new Array(w + 1).join("-");
          }).join("-+-") + "\n", "dim");
        }
      });
      var n = r.rows.length;
      write((n === 1 ? "1 row" : n + " rows")
            + (r.clipped ? " (only the first " + n + " shown)" : "") + "\n",
            "dim");
    });
  }

  async function run() {
    if (running) return;
    // Their Run, their console and their app.
    showOutputTab(false);
    showPageTab(false);
    if (isSql()) openConsole(true);
    setBusy(true);
    clearOutput();
    /* EVERY TAB, not the entry alone. Run once sent only the one editor, so
       an app calling render_template("index.html") failed on a template that
       was sitting in their project, and a SQL lesson had no schema.sql to
       build its database from. The database is their own schema.sql, from
       the page (see live_page) — never the teacher's copy from the network. */
    var project = allFiles();                 // theirs, never the mirror's
    try {
      if (isSql() && !project["schema.sql"]) {
        /* A lesson with no assignment has no database to give them. + File
           could add a schema.sql, but writing the lesson's database is not
           the student's job — say what is actually wrong, and whose move it is. */
        write("This lesson has no database for your query to run against.\n"
              + "Your teacher can fix it by going live with an assignment "
              + "that has a schema.sql.\n", "err");
        return;
      }
      if (isSql()) {
        var out = await runtime.runSql(project, function (note) {
          if (note) write(note + "\n", "dim");
        });
        /* `results`, NOT `tables`. `tables` is the schema's table names and
           row counts; this used to print it as if it were query results, so
           every Run showed a few blank lines and no answer. Whatever ran
           before an error is still shown, as the editor does — a typo in the
           fifth query should not hide the first four. */
        writeSqlResults(out.results);
        if (!out.ok) {
          write("\n" + out.error + "\n", "err");
          if (out.statement) {
            write("\nin this statement:\n", "dim");
            write(out.statement + "\n");
          }
        } else if (!(out.results || []).length) {
          write("query.sql has no statements in it yet — only comments.\n",
                "dim");
        }
        return;
      }

      /* Can Python read it at all? Asked before the app is loaded, so a
         missing bracket gets a plain-words card over the editor (syntax.js)
         instead of a traceback from inside Flask. Python's own message
         still goes in the console. */
      syntaxCard.clear();
      var bad = await runtime.check(project, function (note) {
        if (note) write(note + "\n", "dim");
      });
      if (bad) {
        openConsole(true);                    // the card is in it, so it must show
        write("SyntaxError in " + bad.file + " on line " + bad.line + ": " + bad.msg + "\n"
            + (bad.text.trim() ? "    " + bad.text.trim() + "\n" : ""), "err");
        syntaxCard.show(bad);
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
    },
    /* The console starts folded, and a link that opened nothing must not
       fail inside it unseen. */
    onNote: function (text, failed) {
      write("\n" + text + "\n", "dim");
      if (failed) openConsole(true);
    }
  });

  runBtn.disabled = false;
  runLabel.textContent = "Run";
  runBtn.addEventListener("click", run);

  /* ------------------------------------------------- their app in a new tab
   *
   * The editor's New tab, unchanged: their project goes to /play through
   * this browser's storage under the key play.js reads, and one named tab is
   * reused; /play boots its own Python and runs its own copy of the app. It
   * reads their editor and never writes to it. The teacher's files are not
   * what it sends — a student who wants the teacher's app in a tab has to
   * have typed it, which is the exercise. A SQL lesson has no pages, so the
   * button stays hidden there, as in the editor. */
  function runInNewTab() {
    try {
      localStorage.setItem("flaskide-play", JSON.stringify({
        files: allFiles(),
        title: L.title || "Untitled"
      }));
    } catch (e) {
      window.alert("This browser is blocking site storage, so the app "
                   + "cannot be handed to a new tab. Use the preview here instead.");
      return;
    }
    window.open("/play", "flaskide-play");
  }

  var runTabBtn = $("run-tab");
  if (runTabBtn) {
    runTabBtn.hidden = isSql();
    runTabBtn.addEventListener("click", runInNewTab);
  }
  /* No Stop. A Flask request runs to completion inside Pyodide on this
     thread; there is nothing to interrupt from here, and a button that
     cannot do its job is worse than no button. The editor has none either. */
  if (stopBtn) stopBtn.hidden = true;
  $("clear").addEventListener("click", clearOutput);
  var backBtn = $("preview-back");
  if (backBtn) backBtn.addEventListener("click", function () { preview.back(); });

  // ----------------------------------------------------------------- theme
  /* The editor's light/dark button, on the same localStorage key, so a choice
     made in either place holds in both. The <head> script has already set
     data-theme before the first paint; this only keeps the glyph, the two
     CodeMirrors and the computer's own setting in step with it. */
  function themeSwitch() {
    var THEME_KEY = "flaskide-theme";
    var btn = document.getElementById("theme");
    var glyph = document.getElementById("theme-glyph");
    if (!btn) return;

    function current() { return isDark() ? "dark" : "light"; }

    function apply(name, remember) {
      document.documentElement.setAttribute("data-theme", name);
      // CodeMirror carries its own colours, so it needs telling separately
      var cm = name === "light" ? "default" : "material-darker";
      [mirror, mine].forEach(function (ed) {
        if (ed) { ed.setOption("theme", cm); ed.refresh(); }
      });
      glyph.textContent = name === "light" ? "☾" : "☀";
      btn.title = name === "light"
        ? "Switch to dark (easier on the eyes up close)"
        : "Switch to light (easier to read on a projector)";
      btn.setAttribute("aria-label", btn.title);
      if (remember) {
        try { localStorage.setItem(THEME_KEY, name); } catch (e) { /* blocked */ }
      }
    }

    apply(current(), false);
    btn.addEventListener("click", function () {
      apply(current() === "light" ? "dark" : "light", true);
    });

    // Follow the computer's setting as it changes, until a choice is made.
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: light)");
      var onSystemChange = function () {
        var saved = null;
        try { saved = localStorage.getItem(THEME_KEY); } catch (e) { /* blocked */ }
        if (saved !== "light" && saved !== "dark") {
          apply(mq.matches ? "light" : "dark", false);
        }
      };
      if (mq.addEventListener) mq.addEventListener("change", onSystemChange);
      else if (mq.addListener) mq.addListener(onSystemChange);
    }
  }

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
