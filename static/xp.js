/* A program ran without an error: tell the server, which may pay XP for it.
 *
 * The server decides everything — whether the student has worked long
 * enough since the last run that paid, whether the code has changed — and
 * mostly answers "not yet", which shows nothing. All this sends is a hash of
 * the project's code files, never the code: the server needs to know the code
 * CHANGED, not what it says, and sending a program in a POST is exactly
 * what Render's firewall blocks (see the memory on saves).
 *
 * Fire and forget. A run must never wait on this or fail because of it, so
 * every error is swallowed — the cost of losing one is a run's XP.
 *
 * Same file in all three editors, like xp.py; each says what a run that
 * worked is (app.js) and which files are its code.
 */
window.PyIDEXP = (function () {
  "use strict";

  // FNV-1a, twice with different starting points, for 64 bits: enough that
  // two different programs never look the same to the "has it changed"
  // check. Not security — the student can send any hash they like, and the
  // time limit is what makes that pointless (xp.py).
  function fnv(text, seed) {
    var h = seed >>> 0;
    for (var i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return ("0000000" + h.toString(16)).slice(-8);
  }

  /* `code` says which files are the program, so editing the notes or a data
     file isn't "changed code": .py in PyIDE, the page's files in WebIDE,
     Python and templates in FlaskIDE. */
  function hash(files, code) {
    var names = Object.keys(files || {}).filter(function (n) {
      return (code || /\.py$/i).test(n);
    }).sort();
    var text = names.map(function (n) { return n + "\u0000" + files[n]; }).join("\u0001");
    return fnv(text, 2166136261) + fnv(text, 33554467);
  }

  var toastEl = null;
  function toast(text) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "xp-toast";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    toastEl.classList.remove("show");
    void toastEl.offsetWidth;          // restart the animation on a second toast
    toastEl.classList.add("show");
  }

  /* `files`: every file in the project, name → text; `code`, a pattern for
     the ones that are code (hash). Only for a signed-in page that is the
     student's own work — not a view-only link, not a teacher's game played
     on their canvas. */
  function ran(files, code) {
    try {
      fetch("/api/xp/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: hash(files, code) })
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.awarded > 0) toast("+" + d.awarded + " XP · it ran");
        })
        .catch(function () {});
    } catch (e) {}
  }

  /* The student's editor theme, when they chose one (a page's <head> put
     it on <html> from the account): its id, or "" for ordinary light/dark.
     The editors use it for CodeMirror's colours (.cm-s-pyide-<id>). */
  function namedTheme() {
    var t = document.documentElement.getAttribute("data-theme") || "";
    return /^[a-z]{2,20}$/.test(t) && t !== "light" && t !== "dark" ? t : "";
  }
  /* Back to ordinary light/dark from the editor's button: saved to the
     account, or the next page would put the theme straight back. */
  function clearTheme() {
    try {
      fetch("/api/me/theme", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ theme: "" }) }).catch(function () {});
    } catch (e) {}
  }

  return { ran: ran, hash: hash, toast: toast, namedTheme: namedTheme, clearTheme: clearTheme };
})();
