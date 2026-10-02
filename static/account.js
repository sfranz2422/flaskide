/* FlaskIDE — saving, turning in, and the account menu.
 *
 * All of this is dormant unless somebody is signed in. Anonymous students get
 * exactly the editor they had before: nothing here runs, nothing is sent, and
 * no button appears.
 *
 * Autosave lives in the editor rather than on a home page on purpose. Students
 * arrive from a link their teacher gave them and never see a front page, so a
 * "your recent projects" list there would never be read. The save state sits
 * in the toolbar they are already looking at, and their own work is reachable
 * from the account menu in the same bar.
 */

window.FlaskIDEAccount = (function () {
  "use strict";

  var SAVE_DELAY = 1500;     // after typing stops; long enough not to spam,
                             // short enough that a closed tab loses a sentence

  var cfg = window.FLASKIDE || {};
  var $ = function (id) { return document.getElementById(id); };

  /* ------------------------------------------------- two tabs, one draft
   * Every write to the draft says which version this tab last saw and which
   * tab it is, and the server refuses it if ANOTHER tab has saved since.
   * Without that, a forgotten second tab — the Classroom link open beside the
   * live lesson — wrote its old copy over the newer one the moment a key was
   * pressed in it. See Draft.version in accounts.py. Flask apps and SQL
   * projects both save through here, so both are covered.
   *
   * Refused, this tab stops saving for good and says so. It does not try to
   * merge or retry: the other tab's copy is the one to keep, and what was
   * typed here is still on screen to copy across by hand. */
  var TAB = Math.random().toString(36).slice(2, 14);
  var STALE_NOTE = "This was changed in another tab or window. Reload this "
                 + "page to carry on from the latest version, then turn it in.";
  var seen = typeof cfg.draftVersion === "number" ? cfg.draftVersion : null;
  var stale = false;

  function stamp(payload) {
    if (seen !== null) { payload.base = seen; payload.tab = TAB; }
    return payload;
  }

  function saw(data) {
    if (data && typeof data.version === "number") seen = data.version;
  }

  function goneStale(say, message) {
    if (stale) return;
    stale = true;
    var el = $("save-state");
    if (el) {
      el.textContent = "Not saved — changed in another tab";
      el.className = "savestate bad";
    }
    say("\n" + message + " Anything you typed here since is still on screen, "
        + "so copy it first if you need it.\n", "err");
    // The output pane can be folded away or behind the preview; this cannot.
    window.alert(message);
  }

  function attach(opts) {
    var read = opts.read;               // () -> {files, title}
    var say = opts.say;                 // (text, cls) -> write to the output pane
    var onEdit = opts.onEdit || function () {};

    if (!cfg.draftSlug) {
      // Not a saved project yet. Wire the menus and the Save button, then stop
      // — there is nothing to autosave to until they press it.
      wireAccountMenu();
      wirePublish(read, say);
      wireSave(read, say);
      wireUpdateAssignment(read, say);
      return { noteEdit: function () {} };
    }

    var stateEl = $("save-state");
    var timer = null;
    var inFlight = false;
    var dirtyAgain = false;
    var lastSent = null;

    function show(text, cls) {
      if (!stateEl) return;
      stateEl.textContent = text;
      stateEl.className = "savestate" + (cls ? " " + cls : "");
    }

    function save() {
      if (stale) return;
      if (inFlight) { dirtyAgain = true; return; }
      // Compared unstamped: the version moves on every save, so a stamped
      // body would never match the last one and nothing would be skipped.
      var body = JSON.stringify(read());
      if (body === lastSent) { show("Saved"); return; }

      inFlight = true;
      show("Saving…", "busy");
      fetch("/api/draft/" + encodeURIComponent(cfg.draftSlug), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stamp(JSON.parse(body)))
      }).then(function (res) {
        return res.json().then(function (data) { return { res: res, data: data }; });
      }).then(function (out) {
        inFlight = false;
        if (out.data && out.data.stale) { goneStale(say, out.data.error); return; }
        if (!out.res.ok) {
          /* Left visible rather than retried silently. A student whose work is
             not reaching the server needs to know before they close the tab,
             and "too large to save" will not fix itself on a retry. */
          show("Not saved", "bad");
          say("\nCouldn't save: " + (out.data.error || "the server said no") +
              "\n", "err");
          return;
        }
        lastSent = body;
        saw(out.data);
        show("Saved " + (out.data.saved_at || ""));
        if (dirtyAgain) { dirtyAgain = false; schedule(); }
      }).catch(function () {
        inFlight = false;
        show("Not saved", "bad");
      });
    }

    function schedule() {
      clearTimeout(timer);
      show("Saving…", "busy");
      timer = setTimeout(save, SAVE_DELAY);
    }

    /* A tab closing takes any pending save with it, so push one last copy on
       the way out. keepalive lets the request outlive the page. */
    window.addEventListener("pagehide", function () {
      if (stale || (!timer && !dirtyAgain)) return;
      try {
        fetch("/api/draft/" + encodeURIComponent(cfg.draftSlug), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(stamp(read())),
          keepalive: true
        });
      } catch (e) { /* nothing more we can do from here */ }
    });

    wireAccountMenu();
    wirePublish(read, say);
    wireTurnIn(read, say);
    show("Saved");

    return {
      noteEdit: function () { schedule(); onEdit(); },
      saveNow: save
    };
  }

  // ------------------------------------------------------------- turn in
  function wireTurnIn(read, say) {
    var btn = $("turn-in");
    if (!btn) return;
    btn.addEventListener("click", function () {
      if (stale) { window.alert(STALE_NOTE); return; }
      var payload = stamp(read());
      payload.draft = cfg.draftSlug;
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "Turning in…";
      fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (res) {
        return res.json().then(function (d) { return { res: res, data: d }; });
      }).then(function (out) {
        btn.disabled = false;
        if (out.data && out.data.stale) {
          btn.textContent = label;
          goneStale(say, out.data.error);
          return;
        }
        if (!out.res.ok) {
          btn.textContent = label;
          say("\n" + (out.data.error || "That didn't go through.") + "\n", "err");
          return;
        }
        saw(out.data);
        btn.textContent = "Turn in again";
        say("\nTurned in at " + out.data.submitted_at +
            (out.data.again ? " (replacing your last one)" : "") +
            ". You can keep working and turn it in again.\n", "dim");
      }).catch(function () {
        btn.disabled = false;
        btn.textContent = label;
        say("\nCouldn't reach the server to turn that in.\n", "err");
      });
    });
  }

  // ---------------------------------------------------------------- save
  /* Keeping a project the student started themselves. One press turns it into
     their own project and moves them onto its address, after which it behaves
     exactly like one opened from an assignment — the editor does not change,
     it just starts remembering. */
  function wireSave(read, say) {
    var btn = $("save-project");
    if (!btn) return;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "Saving…";
      fetch("/api/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(read())
      }).then(function (res) {
        return res.json().then(function (d) { return { res: res, data: d }; });
      }).then(function (out) {
        if (!out.res.ok) {
          btn.disabled = false;
          btn.textContent = label;
          say("\n" + (out.data.error || "Couldn't save that.") + "\n", "err");
          return;
        }
        // onto the saved copy, which autosaves from here
        window.location.href = out.data.url;
      }).catch(function () {
        btn.disabled = false;
        btn.textContent = label;
        say("\nCouldn't reach the server to save that.\n", "err");
      });
    });
  }

  // ------------------------------------------------ updating an assignment
  /* Saving over an assignment that already exists.
   *
   * Reached two ways: the Update button the server renders when you open an
   * assignment from the dashboard, and the Publish button AFTER it has
   * published once — which is why this is its own function rather than
   * living inside a click handler. Two copies of this would be two places to
   * fix the message that explains who the change reaches.
   */
  function updateAssignment(btn, read, say) {
    (function () {
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "Saving…";
      fetch("/api/assignment/" + encodeURIComponent(cfg.editingAssignment), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(read())
      }).then(function (res) {
        return res.json().then(function (d) { return { res: res, data: d }; });
      }).then(function (out) {
        btn.disabled = false;
        btn.textContent = label;
        if (!out.res.ok) {
          say("\n" + (out.data.error || "Couldn't save that.") + "\n", "err");
          return;
        }
        var n = out.data.already_started || 0;
        /* Say plainly who this reaches. A teacher fixing a typo needs to know
           it does not rewrite work already in progress — and equally that
           students already working will not see the fix. */
        say("\nAssignment updated. Students who open the link from now on get "
            + "this version."
            + (n ? " The " + n + " already working keep their own copy "
                 + "unchanged — tell them if they need the fix." : "")
            + "\n", "dim");
      }).catch(function () {
        btn.disabled = false;
        btn.textContent = label;
        say("\nCouldn't reach the server.\n", "err");
      });
    }());
  }

  function wireUpdateAssignment(read, say) {
    var btn = $("update-assignment");
    if (!btn) return;
    btn.addEventListener("click", function () { updateAssignment(btn, read, say); });
  }

  // ------------------------------------------------------------- publish
  function wirePublish(read, say) {
    var btn = $("publish");
    if (!btn) return;
    btn.addEventListener("click", function () {
      /* Publish once, then this same button keeps that assignment current.
       *
       * It used to make a brand new assignment on every press, so a teacher
       * revising a task ended up with three links and no idea which one the
       * class had. Wanting a second, separate assignment is the rarer case,
       * and it already has a better path: share the project to yourself,
       * open the copy — which arrives named "Copy of ..." — and publish that.
       */
      if (cfg.editingAssignment) {
        updateAssignment(btn, read, say);
        return;
      }

      var payload = read();
      var title = window.prompt(
        "Name this assignment — students will see it:", payload.title || "");
      if (title === null) return;
      payload.title = title.trim() || payload.title;

      btn.disabled = true;
      fetch("/api/assignment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (res) {
        return res.json().then(function (d) { return { res: res, data: d }; });
      }).then(function (out) {
        btn.disabled = false;
        if (!out.res.ok) {
          say("\n" + (out.data.error || "Couldn't publish that.") + "\n", "err");
          return;
        }
        $("modal-title").textContent = "Assignment published";
        $("modal-sub").textContent =
          "Hand this link to your class. Each student gets their own copy.";
        $("modal-note").textContent =
          "Opening it again returns a student to their own work rather than " +
          "starting them over. Turned-in work appears under Assignments.";
        $("share-url").value = out.data.url;
        $("modal").hidden = false;
        $("share-url").select();

        /* From here on this button edits what was just published. The label
           has to change with it: a button that says Publish and quietly
           updates is worse than one that made duplicates. */
        cfg.editingAssignment = out.data.slug;
        btn.textContent = "Update assignment";
        btn.title = "Save these changes to the assignment you just published.";
      }).catch(function () {
        btn.disabled = false;
        say("\nCouldn't reach the server.\n", "err");
      });
    });
  }

  // -------------------------------------------------------- account menu
  function wireAccountMenu() {
    var btn = $("account");
    var menu = $("account-menu");
    if (!btn || !menu) return;

    function close() {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      btn.setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  return { attach: attach };
})();
