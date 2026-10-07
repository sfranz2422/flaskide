/* The teacher's lesson page (lesson_teacher.html; "Lessons" in app.py).
 *
 * Write: the markdown, and beside it the slides as students get them, which
 * follow the cursor to the slide it is on. Saving is by the button or
 * Ctrl+S, never as they type: what is saved is what students get, and a
 * half-written slide should not reach them.
 *
 * Present: the slides full screen. Go live and every move here — ◀ ▶ or the
 * arrow keys — goes to the class, whose pages jump to this slide (lesson.js).
 * The class is sent the notes as they are in the editor, saved or not, so a
 * typo fixed mid-lesson reaches them; the server takes the answer keys out
 * of what it passes on, and keeps them for marking, as for any live push.
 */
(function () {
  "use strict";

  var T = window.LESSON_T || {};
  var N = window[(T.ns || "FlaskIDE") + "Notes"];
  var $ = function (id) { return document.getElementById(id); };

  // No assignment here: the teacher's own copy, key and all, shows each
  // question as a preview with its answer behind a button (notes.js).
  N.setQuizContext({ assignment: "", signedIn: true });

  function isDark() {
    var set = document.documentElement.getAttribute("data-theme");
    if (set) return set === "dark";
    return !(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
  }

  var editor = CodeMirror.fromTextArea($("lesson-src"), {
    mode: "markdown", lineWrapping: true, lineNumbers: false,
    theme: isDark() ? "material-darker" : "default", indentUnit: 4,
    extraKeys: { "Ctrl-S": save, "Cmd-S": save }
  });
  var preview = N.slideView($("lesson-preview"));
  var present = N.slideView($("lesson-present-body"));

  // ------------------------------------------------------------ theme
  (function () {
    var btn = $("theme"), glyph = $("theme-glyph");
    function apply(name, remember) {
      document.documentElement.setAttribute("data-theme", name);
      editor.setOption("theme", name === "light" ? "default" : "material-darker");
      glyph.textContent = name === "light" ? "☾" : "☀";
      if (remember) { try { localStorage.setItem(T.themeKey, name); } catch (e) {} }
    }
    apply(isDark() ? "dark" : "light", false);
    btn.addEventListener("click", function () { apply(isDark() ? "light" : "dark", true); });
  })();

  // ---------------------------------------------------------- writing
  /* Which slide the cursor is on: the slides of everything up to it, with a
     marker so the slide it is in is never empty and dropped. */
  function cursorSlide() {
    var cur = editor.getCursor();
    var before = editor.getRange({ line: 0, ch: 0 }, { line: cur.line, ch: 0 });
    var cut = N.slides(before + "⁣cursor");
    return Math.max(0, cut.length - 1);
  }

  var drawTimer = null;
  function redraw() {
    clearTimeout(drawTimer);
    drawTimer = setTimeout(function () {
      preview.show(editor.getValue(), cursorSlide());
    }, 150);
  }
  preview.show(editor.getValue(), 0);

  var saved = editor.getValue(), savedTitle = $("lesson-title").value;
  var state = $("lesson-saved");
  function dirty() { return editor.getValue() !== saved || $("lesson-title").value !== savedTitle; }
  function paintSaved() { state.textContent = dirty() ? "Not saved" : "Saved"; }

  editor.on("change", function () { paintSaved(); redraw(); pushSoon(); });
  editor.on("cursorActivity", redraw);
  $("lesson-title").addEventListener("input", paintSaved);

  function save() {
    var notes = editor.getValue(), title = $("lesson-title").value;
    state.textContent = "Saving…";
    fetch(T.saveUrl, { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify({ notes: notes, title: title }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (out) {
        if (!out.ok) { state.textContent = out.d.error || "Not saved"; return; }
        saved = notes;
        savedTitle = title;
        paintSaved();
      })
      .catch(function () { state.textContent = "Not saved — check your connection"; });
  }
  $("lesson-save").addEventListener("click", save);
  document.addEventListener("keydown", function (e) {
    // Outside the editor only: inside it, its own Ctrl-S has already saved.
    if (e.defaultPrevented) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  // --------------------------------------------------------- presenting
  var mode = "write";
  function setMode(next) {
    mode = next;
    $("lesson-write").hidden = next !== "write";
    $("lesson-present").hidden = next !== "present";
    document.querySelectorAll(".lesson-mode [data-mode]").forEach(function (b) {
      b.classList.toggle("is-on", b.dataset.mode === next);
    });
    if (next === "present") present.show(editor.getValue());
    else editor.refresh();
  }
  document.querySelectorAll(".lesson-mode [data-mode]").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.dataset.mode); });
  });
  present.onMove(function () { pushNow(); });
  document.addEventListener("keydown", function (e) {
    if (mode !== "present") return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "")) return;
    var was = present.at();
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") present.go(was + 1);
    else if (e.key === "ArrowLeft" || e.key === "PageUp") present.go(was - 1);
    else return;
    e.preventDefault();
    if (present.at() !== was) pushNow();
  });

  // --------------------------------------------------------------- live
  var live = null, lastSeq = 0, pushTimer = null;
  var liveBtn = $("go-live"), liveChip = $("live-code");

  function nextSeq() { lastSeq = Math.max(Date.now(), lastSeq + 1); return lastSeq; }

  function slideStamp() {
    present.show(editor.getValue());
    return present.count() ? (present.at() + 1) + "/" + present.count() : "";
  }

  function pushNow() {
    if (!live) return;
    fetch("/api/live/" + encodeURIComponent(live) + "/push", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: "", filename: "lesson.md", notes: editor.getValue(),
                             slide: slideStamp(), seq: nextSeq() })
    }).then(function (r) {
      if (r.status === 403 || r.status === 409) paintLive(null);
    }).catch(function () { /* the next move sends everything again */ });
  }
  function pushSoon() {
    if (!live) return;
    clearTimeout(pushTimer);
    pushTimer = setTimeout(pushNow, 600);
  }

  function paintLive(code) {
    live = code;
    liveBtn.textContent = code ? "End lesson" : "Go live";
    liveBtn.classList.toggle("btn-live-on", !!code);
    liveChip.hidden = !code;
  }

  function start(how) {
    var body = { body: "", filename: "lesson.md" };
    body[how] = T.liveCode;
    return fetch("/api/live/start", { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.code && d.resumed !== false) {
          paintLive(d.code);
          var at = /^(\d+)\//.exec(d.slide || "");
          if (at) present.show(editor.getValue(), parseInt(at[1], 10) - 1);
          setMode("present");
          pushNow();
        }
      });
  }

  liveBtn.addEventListener("click", function () {
    if (!live) { start("reopen"); return; }
    if (!window.confirm("End the lesson? Your class's screens stop following you.")) return;
    var code = live;
    paintLive(null);
    fetch("/api/live/" + encodeURIComponent(code) + "/stop", { method: "POST" });
  });
  liveChip.addEventListener("click", function () {
    var done = function () {
      liveChip.textContent = "Copied";
      setTimeout(function () { liveChip.textContent = T.liveCode; }, 1200);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(T.liveUrl).then(done, function () {
      window.prompt("Copy this link for your class:", T.liveUrl);
    });
    else window.prompt("Copy this link for your class:", T.liveUrl);
  });

  // Already live (a reload mid-lesson): carry on. From the dashboard's Go
  // live: start, straight into Present.
  if (T.liveOn) start("resume");
  else if (T.goLive) start("reopen");
})();
