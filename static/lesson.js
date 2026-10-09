/* A lesson, as a student sees it: the notes full screen, as slides, with the
 * questions in them answerable (lesson.html; "Lessons" in app.py).
 *
 * TWO WAYS IN, ONE DIFFERENCE. From the assignment link the student moves
 * through the slides at their own pace. From the live link the page asks
 * the lesson's row once a second and jumps to the teacher's slide each time
 * the teacher MOVES — the same rule the notes pane follows in a coding
 * lesson (live.js) — so a student who has read ahead is brought back by the
 * teacher moving on, not by the teacher typing.
 *
 * Nothing here holds the answer key. The notes arrive with it taken out,
 * and every answer is marked by the server (notes.js, /api/quiz).
 */
(function () {
  "use strict";

  var L = window.LESSON || {};
  var N = window[(L.ns || "FlaskIDE") + "Notes"];
  var $ = function (id) { return document.getElementById(id); };

  N.setQuizContext({ assignment: L.slug, signedIn: L.signedIn });
  var slides = N.slideView($("lesson-body"));

  // ------------------------------------------------------------ theme
  (function themeSwitch() {
    var btn = $("theme"), glyph = $("theme-glyph");
    if (!btn) return;
    function isDark() {
      var set = document.documentElement.getAttribute("data-theme");
      if (set) return set === "dark";
      return !(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
    }
    function apply(name, remember) {
      document.documentElement.setAttribute("data-theme", name);
      glyph.textContent = name === "light" ? "☾" : "☀";
      btn.title = name === "light" ? "Switch to dark" : "Switch to light (easier to read on a projector)";
      if (remember) { try { localStorage.setItem(L.themeKey, name); } catch (e) {} }
    }
    apply(isDark() ? "dark" : "light", false);
    btn.addEventListener("click", function () { apply(isDark() ? "light" : "dark", true); });
  })();

  // ---------------------------------------------------------- turn in
  var turnBtn = $("lesson-turnin"), turned = $("lesson-turned");
  // Answering a question turns the lesson in (notes.js, _auto_turn_in).
  document.addEventListener("pyide:turnedin", function (e) {
    if (!turnBtn) return;
    turned.textContent = "Turned in " + ((e.detail && e.detail.when) || "");
    turnBtn.textContent = "Turn in again";
  });
  if (turnBtn) {
    turnBtn.addEventListener("click", function () {
      turnBtn.disabled = true;
      fetch(L.turnInUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (out) {
          turnBtn.disabled = false;
          if (!out.ok) { turned.textContent = out.d.error || "Not turned in"; return; }
          turned.textContent = "Turned in " + out.d.submitted_at;
          turnBtn.textContent = "Turn in again";
        })
        .catch(function () {
          turnBtn.disabled = false;
          turned.textContent = "Not turned in — check your connection";
        });
    });
  }

  /* Whether a key is someone typing an answer, which the slide keys must
     leave alone. A long response's box is a contenteditable <div>, not an
     input: checking tag names alone, ← and → in the middle of a paragraph
     turned the slide and took the half-written answer off the screen. */
  function typing(e) {
    var t = e.target || {};
    return /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "") || !!t.isContentEditable;
  }

  // ------------------------------------------------ at their own pace
  if (!L.live) {
    slides.show(L.notes);
    // ← and → move through the slides, unless they are typing an answer.
    document.addEventListener("keydown", function (e) {
      if (typing(e)) return;
      if (e.key === "ArrowRight") slides.go(slides.at() + 1);
      if (e.key === "ArrowLeft") slides.go(slides.at() - 1);
    });
    return;
  }

  // ------------------------------------------------- following live
  var state = $("live-state"), back = $("lesson-back");
  var seen = -1, teacherSlide = null, teacherAt = -1;
  var waiting = false, misses = 0;

  function setState(text, kind) {
    state.textContent = text;
    state.className = "chip live-chip" + (kind ? " live-" + kind : "");
  }

  /* "Back to the teacher's slide", while a student is on another one. */
  function paintBack() {
    var away = teacherAt >= 0 && slides.count() > 0 && slides.at() !== teacherAt;
    back.hidden = !away;
    back.textContent = away ? "Back to the teacher's slide (" + (teacherAt + 1) + ")" : "";
  }
  slides.onMove(paintBack);
  back.addEventListener("click", function () {
    if (teacherAt >= 0) slides.go(teacherAt);
    paintBack();
  });
  document.addEventListener("keydown", function (e) {
    if (typing(e)) return;
    var was = slides.at();
    if (e.key === "ArrowRight") slides.go(was + 1);
    if (e.key === "ArrowLeft") slides.go(was - 1);
    if (slides.at() !== was) paintBack();
  });

  /* Only a MOVE snaps (see the top of this file). */
  function apply(data) {
    if (typeof data.notes !== "string") return;
    var slide = typeof data.slide === "string" ? data.slide : "";
    var jump;
    if (slide !== teacherSlide) {
      teacherSlide = slide;
      var m = slide.match(/^(\d+)\/(\d+)$/);
      teacherAt = m ? parseInt(m[1], 10) - 1 : -1;
      if (teacherAt >= 0) jump = teacherAt;
    }
    // Before the teacher has sent anything, the lesson as saved.
    slides.show(data.notes || L.notes, jump);
    paintBack();
  }

  apply({ notes: "", slide: L.slide });

  // ENDED_MS: an ended lesson keeps checking, so teaching it again brings
  // the class along without a reload (the same as live.js).
  var POLL_MS = 1000, WAITING_MS = 15000, ENDED_MS = 5000, pace = POLL_MS;
  var moving = false;      // sent on to another link; this page is done
  function poll() {
    fetch("/api/live/" + encodeURIComponent(L.live) + "?v=" + seen, { cache: "no-store" })
      .then(function (res) {
        if (res.status === 304) { misses = 0; waiting = false; pace = POLL_MS; setState("Live", "on"); return null; }
        if (res.status === 404) { setState("Lesson not found", "off"); throw new Error("gone"); }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        misses = 0;
        if (!data) return;
        // An older link for this assignment: on to its lesson (live_poll).
        if (data.moved) {
          moving = true;
          location.replace("/live/" + encodeURIComponent(data.moved));
          return;
        }
        if (data.ended && data.waiting) { waiting = true; pace = WAITING_MS; setState("Not started yet", "wait"); return; }
        waiting = false;
        seen = data.version;
        apply(data);
        if (data.ended) {
          // The slides stay and stop following, but it keeps asking.
          pace = ENDED_MS;
          setState("Lesson ended", "off");
          return;
        }
        pace = POLL_MS;
        setState("Live", "on");
      })
      .catch(function (err) {
        if (err && err.message === "gone") return;
        misses += 1;
        if (misses >= 3) setState("Reconnecting…", "wait");
      })
      .finally(function () {
        var t = state.textContent;
        if (t === "Lesson not found" || moving) return;
        setTimeout(poll, pace);
      });
  }
  poll();
})();
