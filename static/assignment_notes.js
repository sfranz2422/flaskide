/* A tutorial, edited in the library (library_edit.html; library.py saves
 * it, and writes it into every assignment linked to it). It began as the
 * assignment page's notes editor; the library is now the only place notes
 * are edited, so the name stayed and the page moved.
 *
 * THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE. What differs between them —
 * the name their notes and pictures scripts go by (PyIDENotes,
 * WebIDENotes…), where it saves, the theme's storage key — comes from
 * window.NOTES_T, set by the page. Change it in one, copy it to the others.
 *
 * Write the markdown on the left; on the right, the slides as students get
 * them, following the cursor to the slide it is on (as the lesson page does,
 * lesson_teacher.js). Saving is by the button or Ctrl+S, never as they
 * type: what is saved is what students get, and a half-written question
 * should not reach them. Pictures: Add picture, or paste or drop one.
 */
(function () {
  "use strict";

  var T = window.NOTES_T;
  if (!T) return;
  var N = window[T.ns + "Notes"], P = window[T.ns + "Pictures"];
  var $ = function (id) { return document.getElementById(id); };
  var src = $("notes-src");
  if (!src || !N || !window.CodeMirror) return;

  // No assignment here: the teacher's own copy, key and all, shows each
  // question as a preview with its answer behind a button (notes.js).
  N.setQuizContext({ assignment: "", signedIn: true });

  function isDark() {
    var set = document.documentElement.getAttribute("data-theme");
    if (set) return set === "dark";
    return !(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
  }

  var editor = window.CodeMirror.fromTextArea(src, {
    mode: "markdown", lineWrapping: true, lineNumbers: false,
    theme: isDark() ? "material-darker" : "default", indentUnit: 4,
    extraKeys: { "Ctrl-S": save, "Cmd-S": save }
  });
  // `animate:` notes play here as they will for students, with Skip to get
  // past a part, or a slide, while editing (notes.js, slideView).
  var preview = N.slideView($("notes-preview"), { animate: true, skip: true, key: "author:" + location.pathname });

  /* Which slide the cursor is on: the slides of everything up to it, with a
     marker so the slide it is in is never empty and dropped. */
  function cursorSlide() {
    var cur = editor.getCursor();
    var before = editor.getRange({ line: 0, ch: 0 }, { line: cur.line, ch: 0 });
    return Math.max(0, N.slides(before + "⁣cursor").length - 1);
  }

  var drawTimer = null;
  function redraw() {
    clearTimeout(drawTimer);
    drawTimer = setTimeout(function () { preview.show(editor.getValue(), cursorSlide()); }, 150);
  }
  preview.show(editor.getValue(), 0);

  var saved = editor.getValue();
  var state = $("notes-saved");
  function dirty() { return editor.getValue() !== saved; }
  function paintSaved() {
    state.textContent = dirty() ? "Not saved" : "Saved";
    state.classList.toggle("is-dirty", dirty());
  }

  if (P) {
    P.attach(editor);
    var pic = $("notes-pic");
    if (pic) pic.addEventListener("click", function () {
      P.choose(function (files) {
        P.insertInto(editor.getDoc(), files);
        editor.focus();
      });
    });
  }

  editor.on("change", function () { paintSaved(); redraw(); });
  editor.on("cursorActivity", redraw);

  function save() {
    var notes = editor.getValue();
    state.textContent = "Saving…";
    fetch(T.saveUrl, { method: "POST", credentials: "same-origin",
                       headers: { "Content-Type": "application/json" },
                       body: JSON.stringify({ notes: notes }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (out) {
        if (!out.ok) { state.textContent = out.d.error || "Not saved"; return; }
        saved = notes;
        paintSaved();
      })
      .catch(function () { state.textContent = "Not saved — check your connection"; });
  }
  $("notes-save").addEventListener("click", save);
  document.addEventListener("keydown", function (e) {
    // Outside the editor only: inside it, its own Ctrl-S has already saved.
    if (e.defaultPrevented) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "s" && dirty()) { e.preventDefault(); save(); }
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty()) { e.preventDefault(); e.returnValue = ""; }
  });
})();
