/* Don't lose a signed-out student's work.
 *
 * THE BUG THIS EXISTS FOR
 *
 * A student opens an assignment link, works for ten minutes, realises they
 * are not signed in, and clicks Sign in. Google takes the tab away and
 * brings it back, the page reloads with a fresh copy of the starter, and
 * every line they wrote is gone. It happened in all three editors and
 * nothing anywhere even tried to prevent it: localStorage was used for the
 * theme and the font size and nothing else.
 *
 * Signing in is only the commonest way to lose it. A refresh, a crashed
 * tab, a closed laptop and a flat battery all did the same thing, because
 * there was nowhere for the work to be.
 *
 * WHAT THIS DOES
 *
 * While nobody is signed in, the project is kept in this browser after every
 * pause in typing. On the next load — signed in or not — it is offered back.
 *
 * WHO IT COVERS, AND WHY NOT EVERYONE
 *
 * Signed-out only. A signed-in student already autosaves to the server every
 * few seconds, and a second copy would be a second answer to "what is this
 * project", with no rule for which wins. The local copy exists exactly while
 * there is nowhere else for the work to go, and stops the moment there is.
 *
 * THE KEY IS THE ASSIGNMENT, NOT THE PAGE
 *
 * The work is typed at /a/<assignment> and comes back at /p/<draft> — two
 * different addresses, because signing in is what creates the draft. Keying
 * by assignment is what lets the second page find what the first one saved.
 *
 * EVERY READ AND WRITE IS WRAPPED. localStorage throws outright in a private
 * window and wherever site data is blocked, which on a school laptop is a
 * Tuesday. Losing the safety net is a shame; an editor that will not open
 * because the safety net failed is a far worse bug than the one this fixes.
 */
window.IDERescue = (function () {
  "use strict";

  /* Older than this and it is not a rescue, it is an ambush: a student who
     abandoned something last week should not have it reappear over today's
     work. A lesson is an hour; a day is generous. */
  var MAX_AGE_MS = 24 * 60 * 60 * 1000;

  function keyFor(app, cfg) {
    var what = cfg.assignmentSlug || cfg.draftSlug || cfg.shareSlug || "new";
    return app + ":rescue:" + what;
  }

  function read(key) {
    try {
      var raw = window.localStorage.getItem(key);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (!data || typeof data !== "object" || !data.at) return null;
      if (Date.now() - data.at > MAX_AGE_MS) {
        try { window.localStorage.removeItem(key); } catch (e) {}
        return null;
      }
      return data;
    } catch (e) {
      return null;            // blocked, private, or corrupt: no rescue
    }
  }

  /* opts:
   *   app        "pyide" | "webide" | "flaskide"
   *   cfg        the page's own config object
   *   readAll    () -> {name: text}   the project as it stands
   *   writeAll   ({name: text}) -> void
   *   sameAs     (a, b) -> bool       optional; deep-equal by default
   *   onRestored () -> void           mark the project edited so it saves
   *   ask        (message) -> bool    optional; window.confirm by default
   */
  function attach(opts) {
    var cfg = opts.cfg || {};
    var key = keyFor(opts.app, cfg);
    var ask = opts.ask || function (m) { return window.confirm(m); };

    function same(a, b) {
      try {
        return JSON.stringify(a) === JSON.stringify(b);
      } catch (e) {
        return false;
      }
    }

    function drop() {
      try { window.localStorage.removeItem(key); } catch (e) {}
    }

    // ---------------------------------------------------- putting it back
    var stash = read(key);
    if (stash && stash.files) {
      var now = opts.readAll();
      if (same(now, stash.files)) {
        // Already exactly this — nothing to restore, and nothing to ask.
        drop();
      } else if (!cfg.signedIn) {
        /* Still signed out, so this page is the starter and the stash is
           their own work from a moment ago. Nothing can be lost by putting
           it back, so it goes back without a word. */
        opts.writeAll(stash.files);
        if (opts.onRestored) opts.onRestored();
        drop();
      } else if (cfg.draftFresh) {
        /* Signed in, and the saved copy has not been touched — almost always
           because it was created seconds ago by the click that signed them
           in. Restoring is the whole point and there is nothing to weigh up,
           so this is silent too: the student never learns anything went
           wrong, which is the best outcome available. */
        opts.writeAll(stash.files);
        if (opts.onRestored) opts.onRestored();
        drop();
      } else if (ask("You have work on this from before you signed in.\n\n"
                     + "Put it back? What is saved now will be replaced.")) {
        /* The only case where restoring could destroy something: they had
           already done real work on this assignment. Never silent. */
        opts.writeAll(stash.files);
        if (opts.onRestored) opts.onRestored();
        drop();
      } else {
        drop();               // they chose their saved copy; stop offering
      }
    }

    // ------------------------------------------------------- keeping it
    if (cfg.signedIn) {
      /* Their work has somewhere real to go. Leaving a stale local copy
         behind would mean the next signed-out visit to this assignment
         offered work from a different session. */
      drop();
      return { noteEdit: function () {} };
    }

    var timer = null;
    function noteEdit() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        try {
          window.localStorage.setItem(key, JSON.stringify({
            at: Date.now(),
            files: opts.readAll()
          }));
        } catch (e) {
          /* Full, blocked or private. Nothing to tell them: their work is
             on the screen in front of them and still runs. */
        }
      }, 600);
    }

    return { noteEdit: noteEdit, forget: drop, key: key };
  }

  return { attach: attach, keyFor: keyFor };
})();
