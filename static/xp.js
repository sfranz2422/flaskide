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
/* Loaded twice on some pages — by the page, and by _idle.html for the XP
   popup — so the second load keeps the first's object, and its popup queue. */
window.PyIDEXP = window.PyIDEXP || (function () {
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
  function show(text, loss) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "xp-toast";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    toastEl.classList.toggle("is-loss", !!loss);     // a penalty, in red
    toastEl.classList.remove("show");
    void toastEl.offsetWidth;          // restart the animation on a second toast
    toastEl.classList.add("show");
  }

  /* One at a time, each for as long as its animation (style.css, 3.2s):
     a teacher rewarding three behaviours at once would otherwise show only
     the last. */
  var queue = [], showing = false;
  function say(text, loss) {
    queue.push({ text: text, loss: loss });
    if (!showing) next();
  }
  function next() {
    var item = queue.shift();
    showing = item !== undefined;
    if (!showing) return;
    show(item.text, item.loss);
    setTimeout(next, 3400);
  }

  /* XP the page itself earned — a run, an answer. An answer's reply counts
     the quest reward it completed, so a "bonus" in the news just after
     is the same XP and isn't said twice (watch). */
  var quietBonusUntil = 0;
  function toast(text) {
    quietBonusUntil = Date.now() + 15000;
    say(text);
  }

  /* XP that reached the student from elsewhere — the teacher's rewards and
     penalties, a random event, tests their Check all passed — popped up on
     whatever page they're on (/api/me/xp/news says what's left out, and
     why). Started by _idle.html, so every page a signed-in student works on
     has it and a teacher's never does. Asks every 20 seconds while the tab
     is in front, and as it comes back; a hidden tab asks nothing, so two
     tabs don't both say it.

     Where to count from is kept in this browser, with whose it is: on a
     shared Chromebook the next student starts from their own latest, not
     from the last student's. Blocked storage keeps it for this page only,
     which still says what arrives while it's open. */
  var NEWS_KEY = "xp-news";
  var newsHere = null, watching = false;
  function newsMark(set) {
    if (set) {
      newsHere = set;
      try { localStorage.setItem(NEWS_KEY, JSON.stringify(set)); } catch (e) {}
      return set;
    }
    try { return JSON.parse(localStorage.getItem(NEWS_KEY) || "null") || newsHere; } catch (e) { return newsHere; }
  }
  /* A random event in one of their classes, as every student in it sees it:
     "🎲 Glowing code review · Ana, Ben +10 XP" — first names only, "You"
     for themselves, put first. Every classmate gets it, not only whoever the
     event gave XP to; the rest used to see nothing at all. */
  function eventText(ev) {
    var hits = ev.hits || [];
    var names = function (list) {
      var n = list.map(function (h) { return h.me ? "You" : h.name; });
      return n.length > 4 ? n.slice(0, 3).join(", ") + " and " + (n.length - 3) + " more" : n.join(", ");
    };
    var signed = function (x) { return (x > 0 ? "+" : "−") + Math.abs(x) + " XP"; };
    var said;
    if (!hits.length) said = "nobody had XP to lose";
    else if (hits.every(function (h) { return h.xp === hits[0].xp; })) said = names(hits) + " " + signed(hits[0].xp);
    else said = hits.map(function (h) { return names([h]) + " " + signed(h.xp); }).join(", ");
    return (ev.icon ? ev.icon + " " : "") + ev.title + " · " + said;
  }

  function news() {
    var mark = newsMark();
    var after = mark && typeof mark.after === "number" ? mark.after : null;
    var evAfter = mark && typeof mark.events === "number" ? mark.events : null;
    var q = [];
    if (after !== null) q.push("after=" + after);
    if (evAfter !== null) q.push("events_after=" + evAfter);
    fetch("/api/me/xp/news" + (q.length ? "?" + q.join("&") : ""), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.user) return;
        if (after !== null && mark.user === d.user) {
          (d.awards || []).forEach(function (a) {
            if (a.kind === "bonus" && Date.now() < quietBonusUntil) return;
            say((a.xp > 0 ? "+" + a.xp : "−" + Math.abs(a.xp)) + " XP" +
                (a.reason ? " · " + a.reason : ""), a.xp < 0);
          });
          if (evAfter !== null) {
            (d.events || []).forEach(function (ev) { say(eventText(ev), ev.mine < 0); });
          }
        }
        newsMark({ user: d.user, after: d.latest,
                   events: typeof d.events_latest === "number" ? d.events_latest : undefined });
      })
      .catch(function () {});
  }
  function watch() {
    if (watching) return;
    watching = true;
    news();
    setInterval(function () { if (!document.hidden) news(); }, 20000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) news(); });
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
  /* The editor's light/dark button goes theme -> light -> dark -> theme.
     Leaving the theme is saved to the account, or the next page would put
     it straight back — and the theme left is remembered in this browser, so
     the third click can bring it back. The button once just cleared it, and
     a student who pressed it to see what it did lost their theme until they
     found it again on their home page. */
  var LAST_KEY = "editor-theme-last";

  function clearTheme() {
    var t = namedTheme();
    if (t) { try { localStorage.setItem(LAST_KEY, t); } catch (e) {} }
    try {
      fetch("/api/me/theme", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ theme: "" }) }).catch(function () {});
    } catch (e) {}
  }

  function lastTheme() {
    var t = "";
    try { t = localStorage.getItem(LAST_KEY) || ""; } catch (e) {}
    return /^[a-z]{2,20}$/.test(t) && t !== "light" && t !== "dark" ? t : "";
  }

  /* The theme clearTheme left, back on: on the account, then on <html>.
     Resolves its name, or "" when there is none or it is no longer theirs
     (the server says — a level theme goes with the level), and then it is
     forgotten so the button stops offering it. */
  function restoreTheme() {
    var t = lastTheme();
    if (!t) return Promise.resolve("");
    return fetch("/api/me/theme", { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ theme: t }) })
      .then(function (r) {
        if (!r.ok) {
          try { localStorage.removeItem(LAST_KEY); } catch (e) {}
          return "";
        }
        document.documentElement.setAttribute("data-theme", t);
        return t;
      })
      .catch(function () { return ""; });
  }

  return { ran: ran, hash: hash, toast: toast, watch: watch, namedTheme: namedTheme, clearTheme: clearTheme,
           lastTheme: lastTheme, restoreTheme: restoreTheme };
})();
