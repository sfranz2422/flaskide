/* FlaskIDE — rendered markdown notes.
 *
 * A .md file in a project is class notes: it renders in the right pane rather
 * than opening as text. The markdown source is only editable while authoring a
 * new project, so a student opening a shared link (or forking it) sees the
 * notes but cannot edit them or trip over a tab full of raw markdown.
 *
 * Everything a student could author gets sanitized before it reaches the page.
 * This is the only place in the app where stored content becomes HTML rather
 * than text, so it is the only place injection is possible.
 */

window.FlaskIDENotes = (function () {
  "use strict";

  var MARKED = "https://cdnjs.cloudflare.com/ajax/libs/marked/15.0.7/marked.min.js";
  var PURIFY = "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.2.4/purify.min.js";

  var loading = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("could not load " + src)); };
      document.head.appendChild(s);
    });
  }

  /* Fetched the first time notes are shown, not at page load — a project
     without notes never pays for them. */
  function ensureRenderer() {
    if (window.marked && window.DOMPurify) return Promise.resolve();
    if (!loading) {
      loading = Promise.all([loadScript(MARKED), loadScript(PURIFY)])
        .catch(function (e) { loading = null; throw e; });
    }
    return loading;
  }

  function isMarkdown(name) {
    return /\.(md|markdown)$/i.test(name);
  }

  /* Links open in a new tab so a student never loses their work by navigating
     away, and rel=noopener keeps the opened page from touching this one. */
  function hardenLinks(root) {
    var links = root.querySelectorAll("a[href]");
    Array.prototype.forEach.call(links, function (a) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
  }

  /* DOMPurify's html profile already drops <script>, event handlers such as
     onerror, javascript: hrefs, <iframe>, <object> and <meta>. Two things it
     permits that class notes have no use for, and that a student could misuse
     in a project they share on to a classmate:

       forms  — a convincing fake "school login" posting to another site
       style  — position:fixed can cover the whole editor

     Everything notes actually need (headings, lists, tables, code, links,
     images with width) is unaffected. Drop FORBID_ATTR to allow inline CSS. */
  var SANITIZE = {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["form", "input", "button", "textarea", "select", "option",
                  "label", "fieldset"],
    FORBID_ATTR: ["style"]
  };

  function render(target, source) {
    return ensureRenderer().then(function () {
      var dirty = window.marked.parse(source || "", { breaks: true });
      var clean = window.DOMPurify.sanitize(dirty, SANITIZE);
      target.innerHTML = clean;
      hardenLinks(target);
      enhanceQuizzes(target);
      return true;
    }).catch(function (e) {
      target.textContent =
        "The notes could not be displayed (" + e.message + ").";
      return false;
    });
  }

  /* Notes cut into slides for a live lesson: a `---` line on its own ends
     one slide and starts the next, and nothing else does. Headings are just
     headings — a slide can hold a `##` and a `###` under it, or have none.

     It cut at every `## ` heading once, and only trimmed the `---` rules
     off the edges. Notes written as a deck, with a `---` between slides,
     then ended slides in the wrong places: a slide whose own heading was a
     `###` was glued onto the slide before it, and a slide holding two `##`
     sections was cut in half. The `---` is what the author drew; it is the
     only thing that decides.

     Every `---` counts, including one straight under a line of text, which
     an ordinary markdown viewer would read as underlining that line into a
     heading. In notes written as slides it is a divider far more often than
     a heading, and a slide that runs past the line drawn under it is the
     bug this was rewritten for.

     Fenced code is skipped over, because `---` is also a line of output.
     Without that a slide whose example printed a divider would be cut in
     half in front of the class with no sign of why.

     Returns [] for notes with no `---` at all — one slide is not slides, and
     the caller then sends the notes whole, as it always did. */
  function slides(md) {
    var lines = String(md || "").replace(/\r\n?/g, "\n").split("\n");
    var out = [], cur = [], fence = null, cuts = 0;
    lines.forEach(function (ln) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0)
                 && f[1].length >= fence.length) fence = null;
      } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) {
        out.push(cur);
        cur = [];
        cuts++;
        return;                               // the rule itself is not shown
      }
      cur.push(ln);
    });
    out.push(cur);
    if (!cuts) return [];

    return out.map(function (s) {
      while (s.length && !s[0].trim()) s.shift();
      while (s.length && !s[s.length - 1].trim()) s.pop();
      return s.join("\n");
    }).filter(function (s) { return s.trim(); });
  }

  // ------------------------------------------------------- the slide viewer
  /* Notes are always shown as slides when they have them — in the editor,
     on a shared link and on the class's page in a live lesson — with ◀ ▶
     under them so anyone can move through at their own pace. Notes with no
     `---` (slides() returns []) are shown whole, as they always were.

     ONE VIEWER, so the three places cannot drift apart in how they cut or
     number. It owns a bar it puts straight after `body`, outside the part
     that scrolls, so the arrows stay put on a long slide.

       show(md, i) the notes, whole. Stays on the same slide number unless
                   given `i`, so the author editing a slide, or the teacher
                   typing during a lesson, does not throw the reader back to
                   the start.
       go(i)       to slide i (from 0), clamped.
       onMove(fn)  told when the READER moved, never when go() was called —
                   so the editor can tell a click from its own snapping.

     Re-renders only when what is on screen would change. A live page calls
     show() once a second; rendering that often would replace a link, or a
     question's half-typed answer, under the student's hand. */
  function slideView(body) {
    var bar = document.createElement("div");
    bar.className = "slide-nav";
    bar.hidden = true;
    var prev = el("button", "btn slide-btn", "◀");
    prev.type = "button";
    prev.title = "Previous slide";
    var pos = el("span", "slide-pos");
    pos.setAttribute("aria-live", "polite");
    var next = el("button", "btn slide-btn", "▶");
    next.type = "button";
    next.title = "Next slide";
    bar.appendChild(prev);
    bar.appendChild(pos);
    bar.appendChild(next);
    body.parentNode.insertBefore(bar, body.nextSibling);

    var md = null, cut = [], at = 0, drawn = null, moved = null;

    function draw() {
      var text = cut.length ? cut[at] : (md || "");
      bar.hidden = !cut.length;
      if (cut.length) {
        pos.textContent = (at + 1) + " / " + cut.length;
        prev.disabled = at <= 0;
        next.disabled = at >= cut.length - 1;
      }
      if (text === drawn) return Promise.resolve(true);
      var turned = drawn !== null;
      drawn = text;
      return render(body, text).then(function (ok) {
        if (turned) body.scrollTop = 0;   // a new slide starts at its top
        return ok;
      });
    }

    function go(i) {
      if (!cut.length) return Promise.resolve(true);
      at = Math.max(0, Math.min(cut.length - 1, i));
      return draw();
    }

    function step(by) {
      if (!cut.length) return;
      var was = at;
      go(at + by);
      if (at !== was && moved) moved(at);
    }
    prev.addEventListener("click", function () { step(-1); });
    next.addEventListener("click", function () { step(1); });

    return {
      show: function (text, i) {
        md = text || "";
        var c = slides(md);
        // One slide is not slides, as everywhere else.
        cut = c.length >= 2 ? c : [];
        if (typeof i === "number") at = i;
        at = Math.max(0, Math.min(at, cut.length - 1));
        return draw();
      },
      go: go,
      at: function () { return at; },
      count: function () { return cut.length; },
      onMove: function (fn) { moved = fn; },
      bar: bar
    };
  }

  // ------------------------------------------------- questions in the notes
  /* A ```quiz block is a question (quiz.py has the format, and why). By the
     time a student's page has one, the server has taken the answer key out
     and put an `id:` line in, so what arrives here can be shown but not
     marked: every answer goes to /api/quiz/answer and the server says right
     or wrong. A block that still HAS its key is the teacher's own copy — the
     editor, or the "Class sees" pane — and is shown as a preview with the
     answer behind a button, because that screen is often on the projector.

     parseQuiz must read a block exactly as quiz.parse does. test_quiz.py
     runs both on the same blocks. */
  var FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  var CHOICE = /^[-*+]\s+\[([ xX])\]\s+(.*)$/;
  var ANSWER = /^answer\s*:\s*(.*)$/i;
  var POINTS = /^points?\s*:\s*(\d{1,4}(?:\.\d{1,2})?)\s*$/i;
  var QID = /^id\s*:\s*([0-9a-f]{12})\s*$/;

  function parseQuiz(body) {
    var lines = String(body || "").replace(/\r\n?/g, "\n").split("\n");
    var q = { id: "", prompt: "", choices: [], correct: [], answers: [],
              points: 1 };
    var prompt = [], inner = null;
    lines.forEach(function (ln) {
      var s = ln.trim(), m;
      var f = ln.match(FENCE);
      if (f) {
        if (inner === null) inner = f[1];
        else if (f[1].charAt(0) === inner.charAt(0)
                 && f[1].length >= inner.length) inner = null;
        prompt.push(ln);
        return;
      }
      if (inner !== null) { prompt.push(ln); return; }
      if ((m = s.match(CHOICE))) {
        q.choices.push(m[2].trim());
        if (m[1] !== " ") q.correct.push(m[2].trim());
      } else if ((m = s.match(ANSWER))) {
        if (m[1].trim()) q.answers.push(m[1].trim());
      } else if ((m = s.match(POINTS))) {
        q.points = parseFloat(m[1]);
      } else if ((m = s.match(QID))) {
        q.id = m[1];
      } else {
        prompt.push(ln);
      }
    });
    while (prompt.length && !prompt[0].trim()) prompt.shift();
    while (prompt.length && !prompt[prompt.length - 1].trim()) prompt.pop();
    q.prompt = prompt.join("\n");
    q.kind = q.choices.length ? "choice" : "text";
    q.hasKey = !!(q.correct.length || q.answers.length);
    return q;
  }

  /* Where answers go, set by the page: the assignment's slug, and whether
     anyone is signed in. No assignment means nowhere to record an answer. */
  var quizCtx = { assignment: "", signedIn: false };
  var mine = null;            // promise of {qid: result}, fetched once
  var answered = {};          // qid -> {response, correct, earned, points}
  var pending = {};           // qid -> what is typed or picked, not yet sent
  var widgetCount = 0;

  function setQuizContext(ctx) {
    quizCtx = { assignment: (ctx && ctx.assignment) || "",
                signedIn: !!(ctx && ctx.signedIn) };
    mine = null;
    answered = {};
  }

  function loadMine() {
    if (!mine) {
      mine = fetch("/api/quiz/" + encodeURIComponent(quizCtx.assignment) + "/mine")
        .then(function (r) { return r.ok ? r.json() : { answers: {} }; })
        .then(function (d) {
          Object.keys(d.answers || {}).forEach(function (k) {
            answered[k] = d.answers[k];
          });
        })
        .catch(function () { mine = null; });
    }
    return mine;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function md(target, text, inline) {
    var html = inline ? window.marked.parseInline(text || "")
                      : window.marked.parse(text || "", { breaks: true });
    target.innerHTML = window.DOMPurify.sanitize(html, SANITIZE);
    hardenLinks(target);
  }

  function pointsText(p) { return p + (p === 1 ? " point" : " points"); }

  function enhanceQuizzes(root) {
    var codes = root.querySelectorAll("pre > code.language-quiz");
    /* One at a time, each on its own: a question that cannot be built stays
       on the page as the code block it came in, and the rest of the notes
       still show. Without this one bad question threw out of render() and
       the whole pane said "could not be displayed". */
    Array.prototype.forEach.call(codes, function (code) {
      try {
        code.parentNode.replaceWith(buildQuiz(parseQuiz(code.textContent)));
      } catch (e) { /* left as the code block it was */ }
    });
  }

  function buildQuiz(q) {
    var n = ++widgetCount;
    var box = el("div", "quiz");
    var head = el("div", "quiz-head");
    head.appendChild(el("span", "quiz-label", "Question"));
    head.appendChild(el("span", "quiz-points dim", pointsText(q.points)));
    box.appendChild(head);
    var prompt = el("div", "quiz-prompt");
    md(prompt, q.prompt);
    box.appendChild(prompt);

    var inputs = [];
    if (q.kind === "choice") {
      var list = el("div", "quiz-choices");
      q.choices.forEach(function (c) {
        var label = el("label", "quiz-choice");
        var radio = el("input");
        radio.type = "radio";
        radio.name = "quiz-" + n;
        radio.value = c;
        label.appendChild(radio);
        var span = el("span");
        md(span, c, true);
        label.appendChild(span);
        list.appendChild(label);
        inputs.push(radio);
      });
      box.appendChild(list);
    } else {
      var field = el("input", "field quiz-text");
      field.type = "text";
      field.maxLength = 2000;
      field.placeholder = "Your answer";
      field.setAttribute("aria-label", "Your answer");
      box.appendChild(field);
      inputs.push(field);
    }
    var foot = el("div", "quiz-foot");
    box.appendChild(foot);
    function disable() { inputs.forEach(function (i) { i.disabled = true; }); }

    // The teacher's own copy, key and all.
    if (q.hasKey) {
      disable();
      box.classList.add("quiz-preview");
      var show = el("button", "btn quiz-show", "Show answer");
      show.type = "button";
      var key = el("span", "quiz-key small");
      key.hidden = true;
      // Through the inline renderer, like the choices, so `3` reads as code
      // and not as a 3 between two backticks.
      md(key, q.kind === "choice"
        ? "Answer: " + q.correct.join(" or ")
        : "Accepted: " + q.answers.join(" · "), true);
      show.addEventListener("click", function () {
        key.hidden = !key.hidden;
        show.textContent = key.hidden ? "Show answer" : "Hide answer";
        Array.prototype.forEach.call(box.querySelectorAll(".quiz-choice"),
          function (lab, i) {
            lab.classList.toggle("quiz-is-key",
              !key.hidden && q.correct.indexOf(q.choices[i]) !== -1);
          });
      });
      foot.appendChild(show);
      foot.appendChild(key);
      // The same test quiz.parse makes before it gives a question an id.
      var usable = q.prompt.trim() && q.points > 0 && (q.kind === "text"
        ? q.answers.length : q.choices.length >= 2 && q.correct.length);
      if (!usable) {
        foot.appendChild(el("span", "quiz-warn small",
          "Not answerable yet: it needs a question, two or more choices with one marked [x], or an answer: line."));
      }
      return box;
    }

    if (!q.id) {
      disable();
      foot.appendChild(el("span", "dim small",
        "This question isn't ready yet — your teacher hasn't marked its answer."));
      return box;
    }
    box.dataset.qid = q.id;
    if (!quizCtx.assignment) {
      disable();
      foot.appendChild(el("span", "dim small",
        "Answers are only recorded on an assignment, so this one can't be answered here."));
      return box;
    }
    if (!quizCtx.signedIn) {
      disable();
      var a = el("a", "", "Sign in");
      a.href = "/login?next=" + encodeURIComponent(location.pathname);
      foot.appendChild(a);
      foot.appendChild(document.createTextNode(" to answer this question."));
      foot.classList.add("small");
      return box;
    }

    // A student's question. Locked until we know whether they answered it.
    var send = el("button", "btn btn-primary quiz-send", "Submit answer");
    send.type = "button";
    var note = el("span", "quiz-result small dim", "One try.");
    foot.appendChild(send);
    foot.appendChild(note);
    disable();
    send.disabled = true;

    function current() {
      if (q.kind === "text") return inputs[0].value;
      var on = inputs.filter(function (i) { return i.checked; })[0];
      return on ? on.value : "";
    }
    // Typing or picking survives the notes being re-rendered under it — the
    // teacher editing the notes mid-question would otherwise wipe it.
    inputs.forEach(function (i) {
      i.addEventListener(q.kind === "text" ? "input" : "change", function () {
        pending[q.id] = current();
      });
      if (q.kind === "text") {
        i.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); send.click(); }
        });
      }
    });
    function restore(value) {
      if (q.kind === "text") inputs[0].value = value || "";
      else inputs.forEach(function (i) { i.checked = i.value === value; });
    }

    box.paint = function () {
      var got = answered[q.id];
      if (!got) {
        restore(pending[q.id]);
        inputs.forEach(function (i) { i.disabled = false; });
        send.disabled = false;
        return;
      }
      restore(got.response);
      disable();
      send.hidden = true;
      box.classList.toggle("quiz-right", !!got.correct);
      box.classList.toggle("quiz-wrong", !got.correct);
      note.className = "quiz-result small";
      note.textContent = (got.correct
        ? "✓ Correct — " + pointsText(got.points)
        : "✗ Not quite — 0 of " + pointsText(got.points))
        + (got.practice ? " (your own question, so not recorded)" : "");
    };

    send.addEventListener("click", function () {
      var value = current();
      if (!value.trim()) {
        note.textContent = q.kind === "text" ? "Type an answer first." : "Pick an answer first.";
        return;
      }
      send.disabled = true;
      note.textContent = "Checking…";
      fetch("/api/quiz/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assignment: quizCtx.assignment,
                               question: q.id, response: value })
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, d: d }; });
      }).then(function (out) {
        if (!out.ok) {
          send.disabled = false;
          note.textContent = out.d.error || "That didn't go through. Try again.";
          return;
        }
        answered[q.id] = out.d;
        delete pending[q.id];
        paintAll(q.id);
      }).catch(function () {
        send.disabled = false;
        note.textContent = "No connection — your answer wasn't sent. Try again.";
      });
    });

    loadMine().then(function () { box.paint(); });
    return box;
  }

  /* The same question can be on the page twice — the live page shows the
     notes in their own pane and again in the mirror when the teacher opens
     the .md — and answering one must lock both. */
  function paintAll(qid) {
    Array.prototype.forEach.call(document.querySelectorAll(".quiz[data-qid]"),
      function (box) {
        if (box.dataset.qid === qid && box.paint) box.paint();
      });
  }

  return {
    isMarkdown: isMarkdown,
    slides: slides,
    render: render,
    ensureRenderer: ensureRenderer,
    parseQuiz: parseQuiz,
    setQuizContext: setQuizContext,
    slideView: slideView
  };
})();
