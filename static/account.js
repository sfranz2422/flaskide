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
      if (inFlight) { dirtyAgain = true; return; }
      var payload = read();
      var body = JSON.stringify(payload);
      if (body === lastSent) { show("Saved"); return; }

      inFlight = true;
      show("Saving…", "busy");
      fetch("/api/draft/" + encodeURIComponent(cfg.draftSlug), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body
      }).then(function (res) {
        return res.json().then(function (data) { return { res: res, data: data }; });
      }).then(function (out) {
        inFlight = false;
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
      if (!timer && !dirtyAgain) return;
      try {
        fetch("/api/draft/" + encodeURIComponent(cfg.draftSlug), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(read()),
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
      var payload = read();
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
        if (!out.res.ok) {
          btn.textContent = label;
          say("\n" + (out.data.error || "That didn't go through.") + "\n", "err");
          return;
        }
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
  function wireUpdateAssignment(read, say) {
    var btn = $("update-assignment");
    if (!btn) return;
    btn.addEventListener("click", function () {
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
    });
  }

  // ------------------------------------------------------------- publish
  function wirePublish(read, say) {
    var btn = $("publish");
    if (!btn) return;
    btn.addEventListener("click", function () {
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

    var mine = $("my-projects");
    if (mine) {
      mine.addEventListener("click", function () {
        close();
        fetch("/api/my/projects").then(function (r) { return r.json(); })
          .then(function (data) { showProjects(data.projects || []); });
      });
    }
  }

  function showProjects(list) {
    var box = $("projects-list");
    box.textContent = "";
    if (!list.length) {
      var none = document.createElement("p");
      none.className = "dim";
      none.textContent = "Nothing saved yet. Open an assignment link from your "
                       + "teacher and your work will be kept here.";
      box.appendChild(none);
    }
    list.forEach(function (p) {
      var row = document.createElement("div");
      row.className = "project-row";

      var open = document.createElement("a");
      open.className = "project-open";
      open.href = p.url;

      var name = document.createElement("span");
      name.className = "project-name";
      name.textContent = p.title || "Untitled";
      open.appendChild(name);

      var when = document.createElement("span");
      when.className = "project-when";
      /* A teacher who opens their own assignment link gets a student-style
         copy of it, which lands here beside the project they published it
         from — same title, same day, two rows. Saying which is which is the
         whole difference between a list and a puzzle. */
      var from = "";
      if (p.assignment) {
        from = (p.assignment === (p.title || "Untitled"))
             ? "your copy of this assignment"
             : "from \u201c" + p.assignment + "\u201d";
      }
      when.textContent = (from ? from + " · " : "") + p.updated
                       + (p.submitted ? " · turned in" : "");
      open.appendChild(when);
      row.appendChild(open);

      var bin = document.createElement("button");
      bin.className = "project-x";
      bin.type = "button";
      bin.textContent = "×";
      bin.title = "Delete this project";
      bin.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        /* Say what is actually at stake. Work already turned in stays with
           the teacher, and an assignment copy can be started again from the
           link — neither is obvious, and both change the answer. */
        var warning = "Delete “" + (p.title || "Untitled") + "”?";
        if (p.submitted) {
          warning += "\n\nWhat you turned in stays with your teacher. "
                   + "This only deletes your working copy.";
        } else if (p.assignment) {
          warning += "\n\nYou can open your teacher's link again to start "
                   + "this assignment over from scratch.";
        } else {
          warning += "\n\nThis can't be undone.";
        }
        if (!window.confirm(warning)) return;

        fetch("/api/draft/" + encodeURIComponent(p.slug), { method: "DELETE" })
          .then(function (res) {
            if (!res.ok) return;
            row.remove();
            if (!box.querySelector(".project-row")) showProjects([]);
            // deleting the project you are looking at leaves you on a dead
            // address, so step back to a fresh editor
            if (cfg.draftSlug === p.slug) window.location.href = "/";
          });
      });
      row.appendChild(bin);

      box.appendChild(row);
    });
    $("projects-modal").hidden = false;
  }

  return { attach: attach };
})();
