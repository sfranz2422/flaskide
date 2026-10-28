/* Check my work, in the notes — the same file in PyIDE, WebIDE and FlaskIDE.
 *
 * A ```tests block in the notes is drawn as a card (autograde.js's
 * renderBlocks hands its tests here): each test a line, ○ until it's
 * checked, then ✓ or ✗ with why. Where the page can check code — the
 * student's editor, the class's page in a live lesson — the card has its own
 * ✔ Check my work, and the results land in the card, next to the step they
 * are about, without opening the console. That's how GameIDE's Notes tab
 * does it, and students no longer go looking for their results.
 * It is the only Check my work there is: the button at the top of the
 * editor and the class's page came out, so students check beside the step.
 *
 * Elsewhere (a lesson's page, a class page's preview) there is no runner, so
 * the card is the list of what will be checked, as it always was.
 *
 * The page registers its runner with setRunner(fn): fn() runs every test in
 * the notes and resolves {results: [{label, ok, detail}]} (or null when it
 * couldn't). Every test is run, not just one card's — the result kept for
 * the teacher is the whole check, as before — and each card shows its own
 * lines from it, by label: a test's label is the test, so two cards with
 * the same line show the same answer.
 *
 * A card whose every line passed has data-passed; after each check every
 * card sends an "ide-checks" event (it bubbles) — notes.js's slideView
 * listens for it, to open the next slide when the notes say `locked: yes`.
 */
window.IDENotesChecks = window.IDENotesChecks || (function () {
  "use strict";

  var runner = null;      // the page's: () => Promise<{results}>, or null
  var latest = null;      // label -> {ok, detail}, from the last check
  var busy = false;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  /* The card for one block's tests: [{label, points}], under `heading`
     (each app says what is checked: your code, your page). */
  function card(tests, heading) {
    var box = el("div", "tests-card");
    box.setAttribute("data-checks", "");
    var head = el("div", "tests-head", heading || "✔ Tests your code will be checked against");
    box.appendChild(head);
    var list = el("ul", "tests-lines");
    tests.forEach(function (t) {
      var li = el("li", "test-line");
      li.setAttribute("data-label", t.label);
      li.appendChild(el("span", "tests-mark", "○"));
      var words = el("span", "tests-text");
      words.appendChild(el("span", "tests-label", t.label));
      if (t.points !== 1) words.appendChild(el("span", "dim small", "  (" + t.points + " points)"));
      words.appendChild(el("span", "tests-why"));
      li.appendChild(words);
      list.appendChild(li);
    });
    box.appendChild(list);
    var foot = el("div", "tests-foot");
    var btn = el("button", "btn btn-check tests-run", "✔ Check my work");
    btn.type = "button";
    btn.addEventListener("click", function () { check(); });
    foot.appendChild(btn);
    foot.appendChild(el("span", "tests-sum dim small"));
    box.appendChild(foot);
    // notes.js shows this while the slide is locked (`locked: yes`).
    box.appendChild(el("p", "tests-lock small", "🔒 Pass every check here to go on to the next slide."));
    paint(box);
    return box;
  }

  /* One card, from the latest results: its lines, its button, its total. */
  function paint(box) {
    var lines = box.querySelectorAll(".test-line"), passing = 0, checked = 0;
    Array.prototype.forEach.call(lines, function (li) {
      var r = latest && latest[li.getAttribute("data-label")];
      li.classList.toggle("pass", !!(r && r.ok));
      li.classList.toggle("fail", !!(r && !r.ok));
      li.querySelector(".tests-mark").textContent = busy ? "…" : r ? (r.ok ? "✓" : "✗") : "○";
      li.querySelector(".tests-why").textContent = r && !r.ok && r.detail ? r.detail : "";
      if (r) checked++;
      if (r && r.ok) passing++;
    });
    var btn = box.querySelector(".tests-run");
    btn.hidden = !runner;
    btn.disabled = busy;
    btn.textContent = busy ? "Checking…" : "✔ Check my work";
    box.querySelector(".tests-sum").textContent = !runner ? "" : busy ? "" :
      checked ? passing + " of " + lines.length + " passing" : lines.length + " to pass";
    if (lines.length && passing === lines.length) box.setAttribute("data-passed", "");
    else box.removeAttribute("data-passed");
  }

  function paintAll(announce) {
    Array.prototype.forEach.call(document.querySelectorAll(".tests-card[data-checks]"), function (box) {
      paint(box);
      if (announce) {
        var ev;
        try { ev = new CustomEvent("ide-checks", { bubbles: true }); }
        catch (e) { ev = document.createEvent("Event"); ev.initEvent("ide-checks", true, false); }
        box.dispatchEvent(ev);
      }
    });
  }

  /* Runs the page's check and shows it in every card. Resolves what the
     runner did, or null when there's no runner or one is going already. */
  function check() {
    if (!runner || busy) return Promise.resolve(null);
    busy = true;
    paintAll(false);
    return Promise.resolve().then(runner).then(function (got) {
      if (got && got.results) {
        latest = {};
        got.results.forEach(function (r) { latest[r.label] = { ok: !!r.ok, detail: r.detail || "" }; });
      }
      return got;
    }, function (e) {
      // Nothing to show in the cards; the page's own runner says what went wrong.
      return null;
    }).then(function (got) {
      busy = false;
      paintAll(true);
      return got;
    });
  }

  function setRunner(fn) {
    runner = typeof fn === "function" ? fn : null;
    paintAll(false);
  }

  /* New notes, or another student's (a shared Chromebook): forget the last check. */
  function forget() {
    latest = null;
    paintAll(false);
  }

  return { card: card, check: check, setRunner: setRunner, forget: forget,
           results: function () { return latest; } };
})();
