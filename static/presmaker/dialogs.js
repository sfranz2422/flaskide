/* PresMaker — the forms: a question, a block of tests, a theme, an export.
 *
 * Each form writes markdown through compose.js and shows it drawn by
 * notes.js as it is filled in, so what the preview shows is what the IDEs
 * will show — "Not answerable yet" included, which is notes.js's own check
 * that the question has a key. The form never decides a question is fine;
 * notes.js does.
 */
window.PMDialogs = (function () {
  "use strict";

  var C = window.PMCompose, Notes = window.PyIDENotes, Tests = window.PyIDETests;

  // ----------------------------------------------------------- helpers
  function h(tag, props, kids) {
    var e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === undefined || v === null || v === false) return;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), v);
      else if (k === "value" || k === "checked" || k === "disabled" || k === "selected") e[k] = v;
      else e.setAttribute(k, v === true ? "" : v);
    });
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return e;
  }

  var modal = document.getElementById("modal"), dialog = document.getElementById("dialog");
  var onKey = null, current = null;

  /* One dialog at a time. opts: {title, body, buttons: [{label, primary,
     danger, action -> false keeps it open}], wide, onClose}. Esc closes;
     ⌘↩ presses the primary button. */
  function open(opts) {
    close();
    current = opts;
    dialog.className = "pm-dialog" + (opts.wide ? " pm-wide" : "");
    dialog.textContent = "";
    dialog.appendChild(h("h2", { class: "pm-dialog-title", text: opts.title }));
    dialog.appendChild(h("div", { class: "pm-dialog-body" }, [opts.body]));
    var foot = h("div", { class: "pm-dialog-foot" });
    var primary = null;
    (opts.buttons || []).forEach(function (b) {
      if (b.spacer) { foot.appendChild(h("span", { class: "pm-spacer" })); return; }
      var btn = h("button", {
        class: "btn" + (b.primary ? " btn-primary" : "") + (b.danger ? " pm-danger" : ""),
        text: b.label, type: "button", title: b.title,
        onclick: function () {
          var r = b.action ? b.action() : undefined;
          Promise.resolve(r).then(function (keep) { if (keep !== false) close(); });
        }
      });
      if (b.primary) primary = btn;
      foot.appendChild(btn);
    });
    dialog.appendChild(foot);
    modal.hidden = false;
    onKey = function (e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && primary) { e.preventDefault(); primary.click(); }
    };
    document.addEventListener("keydown", onKey, true);
    var first = dialog.querySelector("textarea, input:not([type=checkbox]):not([type=radio]), select");
    if (first && !opts.noFocus) setTimeout(function () { first.focus(); }, 0);
  }

  function close() {
    if (!current) return;
    var was = current;
    current = null;
    modal.hidden = true;
    dialog.textContent = "";
    document.removeEventListener("keydown", onKey, true);
    if (was.onClose) was.onClose();
  }

  /* Rows that can be added to and taken away: choices, answers, pairs,
     tests. `make(item, i)` gives a row's fields; the list owns the ✕. */
  function rows(items, make, blank, addLabel, changed, min) {
    var box = h("div", { class: "pm-rows" });
    function draw() {
      box.textContent = "";
      items.forEach(function (item, i) {
        var row = h("div", { class: "pm-row" }, make(item, i));
        row.appendChild(h("button", {
          class: "pm-x", type: "button", title: "Take this out", text: "✕",
          disabled: items.length <= (min || 0),
          onclick: function () { items.splice(i, 1); draw(); changed(); }
        }));
        box.appendChild(row);
      });
      box.appendChild(h("button", {
        class: "btn pm-add", type: "button", text: "+ " + addLabel,
        onclick: function () {
          items.push(blank());
          draw(); changed();
          var all = box.querySelectorAll(".pm-row");
          var f = all.length && all[all.length - 1].querySelector("input[type=text], input:not([type]), textarea");
          if (f) f.focus();
        }
      }));
    }
    draw();
    box.redraw = draw;
    return box;
  }

  function field(label, input, hint) {
    return h("label", { class: "pm-field" }, [
      h("span", { class: "pm-field-label", text: label }), input,
      hint ? h("span", { class: "pm-hint", text: hint }) : null
    ]);
  }

  function text(value, oninput, props) {
    return h("input", Object.assign({ class: "field", type: "text", value: value || "", oninput: oninput }, props || {}));
  }

  function area(value, oninput, props) {
    return h("textarea", Object.assign({ class: "field pm-area", value: value || "", oninput: oninput, spellcheck: "true" }, props || {}));
  }

  /* A preview of a piece of markdown, drawn in the deck's theme. */
  function previewBox() {
    var box = h("div", { class: "pm-mini notes-body prose" });
    var seq = 0;
    box.show = function (md, theme) {
      var n = ++seq;
      var out = h("div", { class: "notes-body prose" + (theme ? "" : " pm-plain") });
      return Notes.render(out, md, { theme: theme || "" }).then(function () {
        if (n !== seq) return;           // a newer one is on its way
        box.className = out.className + " pm-mini";
        box.innerHTML = "";
        while (out.firstChild) box.appendChild(out.firstChild);
      });
    };
    return box;
  }

  // ------------------------------------------------------- questions
  var KINDS = [
    ["choice", "Multiple choice", "Tick the right choice. More than one ticked means any of them counts."],
    ["text", "Short answer", "Each answer you'll accept. Capitals, extra spaces and a full stop at the end don't matter."],
    ["long", "Long response", "A box to write a paragraph in. No key: you mark it on the assignment's page."],
    ["blank", "Fill in the blank", "Put each answer in [[ ]] where the blank goes — in the code too. [[True|true]] accepts either."],
    ["match", "Matching", "Each pair's right side goes in a list students pick from, with any extra wrong options."],
    ["order", "Put in order", "The lines in the RIGHT order, indentation and all. Students get them shuffled; a line out of place costs that line only."],
    ["sort", "Sort into groups", "Each group and the items that belong in it. Students get every item in a tray, shuffled; each is worth its share."],
    ["bug", "Find the bug", "The code, and the number of the line that's wrong (from 1). 2, 3 accepts either. Students click the line."],
    ["predict", "Predict the output", "The code, and what it prints. Marked like a short answer — capitals, spaces and line breaks don't count."]
  ];
  // The kinds whose code is the question itself, not an extra.
  var CODE_KINDS = { bug: true, predict: true };

  function blankForm() {
    return { kind: "choice", prompt: "", code: "", points: 1,
             choices: [{ text: "", correct: true }, { text: "" }, { text: "" }],
             answers: [""], pairs: [{ left: "", right: "" }, { left: "", right: "" }], options: [],
             lines: "", groups: [{ name: "", items: "" }, { name: "", items: "" }], bugs: "" };
  }

  /* Opens the question form. `existing` is {body} when the cursor was in a
     ```quiz block; done(markdown) gets the finished block. */
  function question(existing, theme, done) {
    var f = blankForm();
    if (existing) {
      var got = C.quizForm(Notes.parseQuiz(existing.body), existing.body);
      Object.keys(got).forEach(function (k) {
        if (Array.isArray(got[k]) && !got[k].length && Array.isArray(f[k])) return;   // keep the empty rows
        f[k] = got[k];
      });
    }
    var preview = previewBox();
    var source = h("pre", { class: "pm-source" });
    var kindBox = h("div", { class: "pm-seg" });
    var about = h("p", { class: "pm-hint pm-about" });
    var specific = h("div", { class: "pm-specific" });
    var promptBox = area(f.prompt, function () { f.prompt = promptBox.value; changed(); },
                         { rows: 3, placeholder: "The question. **Markdown** and `code` work here." });
    var codeBox = area(f.code, function () { f.code = codeBox.value; changed(); },
                       { rows: 4, class: "field pm-area pm-mono", placeholder: "Optional. Shown as a code block under the question.", spellcheck: "false" });
    // Opening a bug or predict question again: its code is in the prompt's
    // ~~~ fence (notes.js leaves it there); it goes back in the code box.
    if (existing && CODE_KINDS[f.kind]) {
      var fenced = String(f.prompt).match(/\n?^ {0,3}(~{3,}|`{3,})([^\n]*)\n([\s\S]*?)\n {0,3}\1[ \t]*$/m);
      if (fenced) {
        f.code = fenced[3];
        f.codeLang = fenced[2].trim() || "python";
        f.prompt = (f.prompt.slice(0, fenced.index) + f.prompt.slice(fenced.index + fenced[0].length)).trim();
        promptBox.value = f.prompt;
        codeBox.value = f.code;
      }
    }
    var blankBtn = h("button", { class: "btn pm-small", type: "button", text: "[[ ]] Make the selection a blank",
      title: "Select a word in the question or the code first",
      onmousedown: function (e) { e.preventDefault(); },
      onclick: function () {
        var box = document.activeElement === codeBox ? codeBox : lastFocus;
        var a = box.selectionStart, b = box.selectionEnd;
        if (a === b) return;
        box.setRangeText("[[" + box.value.slice(a, b) + "]]", a, b, "end");
        box.dispatchEvent(new Event("input"));
      } });
    var lastFocus = promptBox;
    promptBox.addEventListener("focus", function () { lastFocus = promptBox; });
    codeBox.addEventListener("focus", function () { lastFocus = codeBox; });
    var points = h("input", { class: "field pm-points", type: "number", min: "0", step: "0.5", value: String(f.points),
                              oninput: function () { f.points = points.value === "" ? 1 : Number(points.value); changed(); } });

    function block() { return C.quizBlock(f); }

    /* The preview is drawn with stand-ins for what isn't filled in yet, so
       a half-made question looks like the question it's becoming. Drawn
       as it is, notes.js shows a question without a key as a student's
       copy that "isn't ready yet", which says nothing about what to do.
       The markdown below the preview, and what goes in, has no stand-ins. */
    function standIns() {
      var g = JSON.parse(JSON.stringify(f));
      if (!String(g.prompt).trim()) g.prompt = g.kind === "blank" ? "Your sentence with a [[blank]] in it." : "*Your question*";
      if (CODE_KINDS[g.kind] && !String(g.code).trim()) g.code = "# your code";
      if (!String(g.lines).trim()) g.lines = "first line\nsecond line\nthird line";
      g.groups.forEach(function (x, i) {
        if (!x.name.trim()) x.name = "Group " + (i + 1);
        if (!x.items.trim()) x.items = "item " + (i * 2 + 1) + "\nitem " + (i * 2 + 2);
      });
      if (!C.bugLines(g.bugs).length) g.bugs = "1";
      g.choices.forEach(function (c, i) { if (!c.text.trim()) c.text = "*Choice " + (i + 1) + "*"; });
      if (!g.answers.some(function (a) { return a.trim(); })) g.answers = ["your answer"];
      g.pairs.forEach(function (p, i) {
        if (!p.left.trim()) p.left = "Left " + (i + 1);
        if (!p.right.trim()) p.right = "Match " + (i + 1);
      });
      return C.quizBlock(g);
    }

    /* What stops the question being answerable, in words — the same test
       notes.js and quiz.py make (a question without it gets no id). */
    function problems() {
      var p = [], filled = function (x) { return String(x || "").trim(); };
      if (!filled(f.prompt) && f.kind !== "blank") p.push("Write the question.");
      if (f.kind === "choice") {
        var cs = f.choices.filter(function (c) { return filled(c.text); });
        if (cs.length < 2) p.push("It needs at least two choices.");
        if (!cs.some(function (c) { return c.correct; })) p.push("Tick the right choice.");
      } else if (f.kind === "text") {
        if (!f.answers.some(filled)) p.push("Add an answer you'll accept.");
      } else if (f.kind === "blank") {
        var blanks = (String(f.prompt) + "\n" + String(f.code)).match(/\[\[[^\[\]\n]*\]\]/g) || [];
        if (!blanks.length) p.push("Put at least one [[answer]] in the question or the code.");
        if (blanks.some(function (b) { return !b.slice(2, -2).trim(); })) p.push("Every [[ ]] needs its answer inside it.");
      } else if (f.kind === "match") {
        if (f.pairs.filter(function (x) { return filled(x.left) && filled(x.right); }).length < 2)
          p.push("It needs at least two complete pairs.");
      } else if (f.kind === "order") {
        if (String(f.lines).split("\n").filter(filled).length < 2) p.push("It needs at least two lines.");
      } else if (f.kind === "sort") {
        var gs = f.groups.filter(function (x) { return filled(x.name) && filled(x.items); });
        if (gs.length < 2) p.push("It needs at least two groups, each with an item.");
      } else if (f.kind === "bug" || f.kind === "predict") {
        if (!filled(f.code)) p.push("Put the code in the code box.");
        if (f.kind === "predict" && !f.answers.some(filled)) p.push("Write what it prints.");
        if (f.kind === "bug") {
          var n = String(f.code).replace(/\s+$/, "").split("\n").length, bs = C.bugLines(f.bugs);
          if (!bs.length) p.push("Give the number of the wrong line.");
          else if (bs.some(function (b) { return Number(b) < 1 || Number(b) > n; }))
            p.push("The code has " + n + " line" + (n === 1 ? "" : "s") + ": the wrong line is one of those.");
        }
      }
      if (!(Number(f.points) > 0)) p.push("Give it more than 0 points.");
      return p;
    }
    var warn = h("div", { class: "pm-problems" });

    var timer = null;
    function changed() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        source.textContent = block();
        preview.show(standIns(), theme);
        var p = problems();
        warn.textContent = p.length ? "Not answerable yet: " + p.join(" ") : "";
        warn.hidden = !p.length;
      }, 120);
    }

    var codeField = field("Code (optional)", codeBox);
    var codeLabel = codeField.querySelector(".pm-field-label") || codeField.firstChild;
    function drawKind() {
      kindBox.textContent = "";
      KINDS.forEach(function (k) {
        kindBox.appendChild(h("button", {
          class: "pm-seg-btn" + (f.kind === k[0] ? " pm-on" : ""), type: "button", text: k[1],
          onclick: function () { f.kind = k[0]; drawKind(); changed(); }
        }));
      });
      var k = KINDS.filter(function (x) { return x[0] === f.kind; })[0];
      about.textContent = k[2];
      blankBtn.hidden = f.kind !== "blank";
      // Order and sort are made of their lines and items: no code under them.
      codeField.hidden = f.kind === "order" || f.kind === "sort";
      if (codeLabel && codeLabel.nodeType === 1) codeLabel.textContent = CODE_KINDS[f.kind] ? "Code" : "Code (optional)";
      codeBox.placeholder = f.kind === "bug" ? "The code with the mistake in it. Students click the line."
        : f.kind === "predict" ? "The code. Students say what it prints." : "Optional. Shown as a code block under the question.";
      specific.textContent = "";
      if (f.kind === "choice") {
        specific.appendChild(h("div", { class: "pm-field-label", text: "Choices — tick the right one" }));
        specific.appendChild(rows(f.choices, function (c) {
          return [
            h("input", { type: "checkbox", class: "pm-tick", checked: !!c.correct, title: "Right answer",
                         onchange: function (e) { c.correct = e.target.checked; changed(); } }),
            text(c.text, function (e) { c.text = e.target.value; changed(); }, { placeholder: "A choice" })
          ];
        }, function () { return { text: "" }; }, "Choice", changed, 2));
      } else if (f.kind === "text") {
        specific.appendChild(h("div", { class: "pm-field-label", text: "Answers you'll accept" }));
        specific.appendChild(rows(f.answers, function (a, i) {
          return [text(a, function (e) { f.answers[i] = e.target.value; changed(); }, { placeholder: "An accepted answer" })];
        }, function () { return ""; }, "Answer", changed, 1));
      } else if (f.kind === "match") {
        specific.appendChild(h("div", { class: "pm-field-label", text: "Pairs" }));
        specific.appendChild(rows(f.pairs, function (p) {
          return [
            text(p.left, function (e) { p.left = e.target.value; changed(); }, { placeholder: "Left (shown)" }),
            h("span", { class: "pm-arrow", text: "→" }),
            text(p.right, function (e) { p.right = e.target.value; changed(); }, { placeholder: "Its match" })
          ];
        }, function () { return { left: "", right: "" }; }, "Pair", changed, 2));
        specific.appendChild(h("div", { class: "pm-field-label", text: "Extra wrong options (optional)" }));
        specific.appendChild(rows(f.options, function (o, i) {
          return [text(o, function (e) { f.options[i] = e.target.value; changed(); }, { placeholder: "A wrong answer to choose from" })];
        }, function () { return ""; }, "Wrong option", changed, 0));
      } else if (f.kind === "order") {
        var linesBox = area(f.lines, function () { f.lines = linesBox.value; changed(); },
                            { rows: 6, class: "field pm-area pm-mono", spellcheck: "false",
                              placeholder: "One line each, in the right order.\nIndentation is kept." });
        specific.appendChild(field("The lines, in the right order", linesBox));
      } else if (f.kind === "sort") {
        specific.appendChild(h("div", { class: "pm-field-label", text: "Groups — a name, then its items one a line" }));
        specific.appendChild(rows(f.groups, function (g) {
          return [
            text(g.name, function (e) { g.name = e.target.value; changed(); }, { placeholder: "Group name" }),
            area(g.items, function (e) { g.items = e.target.value; changed(); },
                 { rows: 3, placeholder: "An item\nAnother item" })
          ];
        }, function () { return { name: "", items: "" }; }, "Group", changed, 2));
      } else if (f.kind === "bug") {
        specific.appendChild(field("The wrong line", text(f.bugs, function (e) { f.bugs = e.target.value; changed(); },
                                                          { placeholder: "2 — or 2, 3 to accept either" }),
                                   "Counting from 1, the first line of the code."));
      } else if (f.kind === "predict") {
        specific.appendChild(h("div", { class: "pm-field-label", text: "What it prints" }));
        specific.appendChild(rows(f.answers, function (a, i) {
          return [text(a, function (e) { f.answers[i] = e.target.value; changed(); }, { placeholder: "0 2 4" })];
        }, function () { return ""; }, "Answer", changed, 1));
        // Python is fetched the first time (snippets.js); this saves working the output out by hand.
        if (window.IDESnippets && window.IDESnippets.run) {
          var said = h("span", { class: "pm-hint" });
          specific.appendChild(h("div", { class: "pm-row" }, [
            h("button", { class: "btn pm-small", type: "button", text: "▶ Run it and use what it prints",
              onclick: function () {
                if (!String(f.code).trim()) { said.textContent = "Put the code in first."; return; }
                said.textContent = "Running… (the first run fetches Python, a few seconds)";
                window.IDESnippets.run(String(f.code)).then(function (r) {
                  var out = String((r && r.text) || "").replace(/\s+$/, "");
                  if (r && r.error) { said.textContent = "It stopped with an error: " + String(r.error).split("\n").pop(); return; }
                  f.answers = [out.split("\n").map(function (l) { return l.trim(); }).join(" ")];
                  said.textContent = "";
                  drawKind();
                  changed();
                }, function (e) { said.textContent = "Couldn't run it: " + (e && e.message || e); });
              } }),
            said
          ]));
        }
      }
    }

    drawKind();
    var form = h("div", { class: "pm-form" }, [
      kindBox, about,
      field("Question", promptBox),
      blankBtn,
      codeField,
      specific,
      field("Points", points, "Added to the student's score. Blanks and pairs each earn their share.")
    ]);
    var side = h("div", { class: "pm-side" }, [
      h("div", { class: "pm-field-label", text: "How it will look (your copy, with the answer)" }), preview, warn,
      h("details", { class: "pm-details" }, [h("summary", { text: "The markdown" }), source])
    ]);
    changed();
    open({
      title: existing ? "Change question" : "Insert a question", wide: true,
      body: h("div", { class: "pm-two" }, [form, side]),
      buttons: [
        { label: "Help with formats", action: function () { help(); return false; } },
        { spacer: true },
        { label: "Cancel" },
        { label: existing ? "Save question" : "Insert question", primary: true, action: function () { done(block()); } }
      ]
    });
  }

  // ----------------------------------------------------------- tests
  var TEST_KINDS = [
    ["output", "Output", "Runs the program, typing the inputs; what it prints must contain the answer."],
    ["call", "Function call", "Calls one of their functions and compares what it returns."],
    ["uses", "Uses", "The code uses this somewhere: for, while, if, def, return, import math, len…"],
    ["avoids", "Avoids", "The name appears nowhere in the code."],
    ["defines", "Defines", "There is a def with this name."]
  ];
  var WORDS = ["for", "while", "if", "else", "elif", "def", "return", "try", "list", "dict", "class",
               "import math", "import random", "len", "range", "input", "print", "sum", "max", "min", "sorted"];

  function fromParsed(t) {
    var r = { kind: t.kind, points: t.points, inputs: "", expect: "", exact: false, expr: "", name: "" };
    if (t.kind === "output") { r.inputs = t.inputs.join(", "); r.expect = t.expect; r.exact = t.exact; }
    else if (t.kind === "call") { r.expr = t.expr; r.expect = t.expect; }
    else r.name = t.name;
    return r;
  }
  function toTest(r) {
    return { kind: r.kind, points: r.points, exact: r.exact, expect: r.expect, expr: r.expr, name: r.name,
             inputs: String(r.inputs || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean) };
  }

  /* Tests as lines, typed in the IDE's own words (WebIDE's "has 3 li",
     FlaskIDE's "GET / -> 200"…), for an IDE whose tests the form's kinds
     don't cover (bridge.js PM_SERVER.tests == "lines"). Each line is read
     by that IDE's own autograde.js as it's typed, so a line it wouldn't
     take is said here, not found out by a student. */
  function testsAsLines(existing, theme, done, examples) {
    var box = h("textarea", { class: "field pm-mono pm-test-lines", rows: "10", spellcheck: "false",
                              placeholder: (examples || []).join("\n") });
    box.value = existing ? existing.body.replace(/\n+$/, "") : "";
    var preview = previewBox();
    var source = h("pre", { class: "pm-source" });
    var problems = h("div", { class: "pm-problems" });
    function block() { return "```tests\n" + box.value.replace(/\s+$/, "") + "\n```"; }
    var timer = null;
    function changed() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var md = block(), got = Tests.parseBlock(box.value);
        source.textContent = md;
        preview.show(md, theme);
        problems.textContent = got.errors.join("\n");
        problems.hidden = !got.errors.length;
      }, 150);
    }
    box.addEventListener("input", changed);
    var form = h("div", { class: "pm-form" }, [
      h("p", { class: "pm-hint", text: "One test a line, checked against the student's work. Students run them with Check my work; your Check all is what counts toward the grade. Add (2 points) at the end of a line for more than 1." }),
      box, problems,
      examples && examples.length ? h("div", {}, [h("div", { class: "pm-field-label", text: "For example" }),
        h("pre", { class: "pm-source", text: examples.join("\n") })]) : null
    ]);
    var side = h("div", { class: "pm-side" }, [
      h("div", { class: "pm-field-label", text: "How students will see it" }), preview,
      h("details", { class: "pm-details", open: true }, [h("summary", { text: "The markdown" }), source])
    ]);
    changed();
    open({
      title: existing ? "Change tests" : "Insert tests", wide: true,
      body: h("div", { class: "pm-two" }, [form, side]),
      buttons: [
        { spacer: true },
        { label: "Cancel" },
        { label: existing ? "Save tests" : "Insert tests", primary: true, action: function () { done(block()); } }
      ]
    });
    setTimeout(function () { box.focus(); }, 0);
  }

  function tests(existing, theme, done) {
    var server = window.PMBridge.server;
    if (server && server.tests === "lines") return testsAsLines(existing, theme, done, server.testExamples);
    var list = existing ? Tests.parseBlock(existing.body).tests.map(fromParsed) : [];
    if (!list.length) list.push({ kind: "output", points: 1, inputs: "", expect: "", exact: false, expr: "", name: "" });
    var preview = previewBox();
    var source = h("pre", { class: "pm-source" });
    var problems = h("div", { class: "pm-problems" });
    var dl = h("datalist", { id: "pm-words" }, WORDS.map(function (w) { return h("option", { value: w }); }));

    function block() { return C.testsBlock(list.map(toTest)); }
    var timer = null;
    function changed() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var md = block();
        source.textContent = md;
        preview.show(md, theme);
        var p = [];
        list.forEach(function (r, i) {
          C.testProblems(toTest(r)).forEach(function (m) { p.push("Test " + (i + 1) + ": " + m); });
          if (!C.testLine(toTest(r))) p.push("Test " + (i + 1) + " is empty and won't be written.");
        });
        problems.textContent = p.join("\n");
        problems.hidden = !p.length;
      }, 120);
    }

    var table = rows(list, function (r) {
      var kind = h("select", { class: "field pm-test-kind", onchange: function () { r.kind = kind.value; table.redraw(); changed(); } },
        TEST_KINDS.map(function (k) { return h("option", { value: k[0], text: k[1], selected: r.kind === k[0] }); }));
      var pts = h("input", { class: "field pm-points", type: "number", min: "0.5", step: "0.5", value: String(r.points || 1),
                             title: "Points", oninput: function () { r.points = Number(pts.value) || 1; changed(); } });
      var bits;
      if (r.kind === "output") {
        bits = [
          text(r.inputs, function (e) { r.inputs = e.target.value; changed(); },
               { placeholder: "typed in: 3, 4 (optional)", class: "field pm-w-in", title: "What the test types, in order, with commas between" }),
          h("span", { class: "pm-arrow", text: "→ prints" }),
          h("label", { class: "pm-inline", title: "The whole output, exactly (trimmed) — prompts included" }, [
            h("input", { type: "checkbox", checked: !!r.exact, onchange: function (e) { r.exact = e.target.checked; changed(); } }),
            "exactly"]),
          text(r.expect, function (e) { r.expect = e.target.value; changed(); }, { placeholder: "12", class: "field pm-w-out" })
        ];
      } else if (r.kind === "call") {
        bits = [
          text(r.expr, function (e) { r.expr = e.target.value; changed(); }, { placeholder: "area(3, 4)", class: "field pm-mono pm-w-in" }),
          h("span", { class: "pm-arrow", text: "==" }),
          text(r.expect, function (e) { r.expect = e.target.value; changed(); }, { placeholder: "12", class: "field pm-mono pm-w-out" })
        ];
      } else {
        bits = [text(r.name, function (e) { r.name = e.target.value; changed(); },
                     { placeholder: r.kind === "defines" ? "area" : "for", list: "pm-words", class: "field pm-mono pm-w-out" })];
      }
      return [kind].concat(bits, [pts]);
    }, function () {
      var last = list[list.length - 1] || {};
      return { kind: last.kind || "output", points: 1, inputs: "", expect: "", exact: false, expr: "", name: "" };
    }, "Test", changed, 1);

    var guide = h("ul", { class: "pm-hint pm-guide" }, TEST_KINDS.map(function (k) {
      return h("li", {}, [h("b", { text: k[1] + ": " }), k[2]]);
    }));
    var form = h("div", { class: "pm-form" }, [
      h("p", { class: "pm-hint", text: "Each line is one test, checked against the student's code. Students run them with Check my work; your Check all is what counts toward the grade. Each test is 1 point unless you change it." }),
      table, problems, guide, dl
    ]);
    var side = h("div", { class: "pm-side" }, [
      h("div", { class: "pm-field-label", text: "How students will see it" }), preview,
      h("details", { class: "pm-details", open: true }, [h("summary", { text: "The markdown" }), source])
    ]);
    changed();
    open({
      title: existing ? "Change tests" : "Insert tests", wide: true,
      body: h("div", { class: "pm-two" }, [form, side]),
      buttons: [
        { label: "Help with formats", action: function () { help("tests"); return false; } },
        { spacer: true },
        { label: "Cancel" },
        { label: existing ? "Save tests" : "Insert tests", primary: true, action: function () { done(block()); } }
      ]
    });
  }

  // ----------------------------------------------------------- themes
  // Short enough to fit the sample slide at full size: a sample shrunk to
  // fit shows the theme at a size no deck will use.
  var SAMPLE = "## Lists\nA **list** holds values in order. [A link](#)\n\n- starts at index `0`\n\n" +
    "~~~python\nnames = [\"Ada\", \"Grace\"]\n~~~\n\n" +
    "```quiz\nWhat does `names[1]` give?\n- [ ] \"Ada\"\n- [x] \"Grace\"\n```";

  /* The theme maker. `deck` is {theme: the deck's theme now, use(name)}. */
  function themes(deck) {
    var T = window.PMThemes;
    var editing = null, was = null;     // the form's theme, and its name when opened
    var listBox = h("div", { class: "pm-theme-list" });
    var formBox = h("div", { class: "pm-theme-form" });
    var page = h("div", { class: "pm-page pm-theme-page" });
    var slide = h("div", { class: "notes-body prose pm-slide" });
    page.appendChild(slide);
    var holder = h("div", { class: "pm-frame pm-theme-frame" }, [page]);
    var stage = h("div", { class: "pm-theme-stage" }, [holder, h("p", { class: "pm-hint", text: "The sample is a slide at the size it's projected, shrunk to fit here." })]);
    var sizer = new ResizeObserver(function () {
      var k = Math.max(0.2, (stage.clientWidth - 4) / 960);
      page.style.transform = "scale(" + k + ")";
      holder.style.width = 960 * k + "px";
      holder.style.height = 540 * k + "px";
    });
    sizer.observe(stage);
    var draftCSS = h("style");
    document.head.appendChild(draftCSS);
    var draftFont = h("link", { rel: "stylesheet" });
    document.head.appendChild(draftFont);
    var note = h("div", { class: "pm-hint pm-theme-note" });

    function drawList() {
      listBox.textContent = "";
      listBox.appendChild(h("div", { class: "pm-field-label", text: "Your themes" }));
      var mine = T.made();
      if (!mine.length) listBox.appendChild(h("p", { class: "pm-hint", text: "None yet. Start a new one, or copy a built-in one and change it." }));
      mine.forEach(function (t) {
        listBox.appendChild(h("button", {
          class: "pm-theme-item" + (editing && was === t.name ? " pm-on" : ""), type: "button",
          onclick: function () { edit(JSON.parse(JSON.stringify(t)), t.name); }
        }, [swatch(t.name), t.name]));
      });
      listBox.appendChild(h("div", { class: "pm-theme-new" }, [
        h("button", { class: "btn pm-small", type: "button", text: "+ New dark", onclick: function () { edit(T.blank("dark"), null); } }),
        h("button", { class: "btn pm-small", type: "button", text: "+ New light", onclick: function () { edit(T.blank("light"), null); } })
      ]));
      listBox.appendChild(h("div", { class: "pm-field-label", text: "Built in (in all three IDEs)" }));
      T.builtin().forEach(function (n) {
        listBox.appendChild(h("button", {
          class: "pm-theme-item pm-builtin", type: "button", title: "Copy " + n + " as a new theme to change",
          onclick: function () {
            var t = T.fromBuiltin(n);
            t.name = freeName("my" + n);
            edit(t, null);
          }
        }, [swatch(n), n, h("span", { class: "pm-hint", text: " copy" })]));
      });
    }

    function freeName(base) {
      var name = base.replace(/[^a-z]/g, ""), taken = T.all(), k = 0, letters = "bcdefghijk";
      var out = name;
      while (taken.indexOf(out) >= 0) out = name + letters.charAt(k++);
      return out;
    }

    function swatch(name) {
      return h("span", { class: "pm-swatch notes-body slide-themed slide-theme-" + name }, [h("i"), h("b")]);
    }

    function paint() {
      if (!editing) return;
      var t = Object.assign({}, editing, { name: "pmdraft" });
      draftCSS.textContent = C.themeCSS(t);
      var url = C.fontsURL([t.font]);
      if (url && draftFont.href !== url) draftFont.href = url;
      Notes.render(slide, SAMPLE, { theme: "pmdraft" }).then(function () { window.PMPages.fit(slide); });
      var problem = C.themeNameProblem(editing.name, T.all().filter(function (n) { return n !== was; }));
      note.textContent = problem;
      note.classList.toggle("pm-bad", !!problem);
    }

    function colour(label, key) {
      var inp = h("input", { type: "color", value: C.hex(editing[key]) ? editing[key] : "#888888",
                             oninput: function () { editing[key] = inp.value; paint(); } });
      return h("label", { class: "pm-colour" }, [inp, h("span", { text: label })]);
    }

    function edit(t, name) {
      editing = t; was = name;
      formBox.textContent = "";
      var nameBox = text(t.name, function () { t.name = nameBox.value.trim().toLowerCase(); paint(); },
                         { placeholder: "lagoon", maxlength: "24", class: "field pm-mono" });
      var scheme = h("select", { class: "field", onchange: function () { t.scheme = scheme.value; paint(); } }, [
        h("option", { value: "dark", text: "Dark (light text)", selected: t.scheme !== "light" }),
        h("option", { value: "light", text: "Light (dark text)", selected: t.scheme === "light" })
      ]);
      var bgType = h("select", { class: "field", onchange: function () { t.bgType = bgType.value; redrawBg(); paint(); } }, [
        h("option", { value: "solid", text: "One colour", selected: t.bgType !== "gradient" }),
        h("option", { value: "gradient", text: "Gradient", selected: t.bgType === "gradient" })
      ]);
      var bgRow = h("div", { class: "pm-colours" });
      function redrawBg() {
        bgRow.textContent = "";
        bgRow.appendChild(colour(t.bgType === "gradient" ? "From" : "Background", "bg1"));
        if (t.bgType === "gradient") {
          bgRow.appendChild(colour("To", "bg2"));
          var third = h("input", { type: "checkbox", checked: !!t.bg3, title: "A third colour at the end",
            onchange: function () { t.bg3 = third.checked ? (t.bg3 || t.bg2) : ""; redrawBg(); paint(); } });
          bgRow.appendChild(h("label", { class: "pm-inline" }, [third, "3rd"]));
          if (t.bg3) bgRow.appendChild(colour("Then", "bg3"));
          var angle = h("input", { type: "range", min: "0", max: "360", value: String(t.angle || 160),
                                   oninput: function () { t.angle = Number(angle.value); paint(); } });
          bgRow.appendChild(h("label", { class: "pm-inline", title: "Direction" }, ["↻", angle]));
        }
      }
      redrawBg();
      var patt = h("select", { class: "field", onchange: function () { t.pattern = patt.value; paint(); } },
        C.PATTERNS.map(function (p) { return h("option", { value: p, text: p, selected: (t.pattern || "none") === p }); }));
      var adv = area(t.bgCSS, function () { t.bgCSS = adv.value; paint(); },
                     { rows: 3, class: "field pm-area pm-mono", spellcheck: "false",
                       placeholder: "Any CSS background, e.g. linear-gradient(#123, #456). Wins over the colours above." });
      var font = h("select", { class: "field", onchange: function () { t.font = font.value; paint(); } },
        C.FONTS.map(function (f) { return h("option", { value: f.id, text: f.label, selected: (t.font || "") === f.id }); }));

      formBox.appendChild(h("div", { class: "pm-grid2" }, [
        field("Name (a–z)", nameBox), field("Kind", scheme)
      ]));
      formBox.appendChild(note);
      formBox.appendChild(h("div", { class: "pm-grid2" }, [field("Background", bgType), field("Pattern over it", patt)]));
      formBox.appendChild(bgRow);
      formBox.appendChild(h("details", { class: "pm-details", open: !!t.bgCSS }, [
        h("summary", { text: "Advanced: background as CSS" }), adv]));
      formBox.appendChild(h("div", { class: "pm-field-label", text: "Colours" }));
      formBox.appendChild(h("div", { class: "pm-colours pm-colours-grid" }, [
        colour("Text", "text"), colour("Quieter text", "muted"), colour("Headings", "heading"),
        colour("Small headings", "heading2"), colour("Links & bullets", "accent"), colour("Bold", "strong"),
        colour("Bar under slides", "nav")
      ]));
      formBox.appendChild(field("Heading font", font,
        "The first five are the faces the IDEs already load; the others need one more line there (Copy for the IDEs says which)."));
      formBox.appendChild(h("div", { class: "pm-theme-actions" }, [
        h("button", { class: "btn btn-primary", type: "button", text: "Save theme", onclick: saveIt }),
        h("button", { class: "btn", type: "button", text: "Save & use in this deck", onclick: function () {
          saveIt().then(function (ok) { if (ok) { deck.use(editing.name); close(); } });
        } }),
        h("button", { class: "btn", type: "button", text: "Copy for the IDEs",
          title: "The CSS and where it goes in PyIDE, WebIDE and FlaskIDE",
          onclick: function () {
            window.PMBridge.call("copy", { text: C.themeForIDEs(editing) }).then(function () {
              note.classList.remove("pm-bad");
              note.textContent = "Copied — the CSS, with notes at the top saying where it goes in each IDE.";
            });
          } }),
        was ? h("button", { class: "btn pm-danger", type: "button", text: "Delete", onclick: function () {
          if (!confirm("Delete the theme " + was + "? Decks that use it will show the theme line as text.")) return;
          T.remove(was).then(function () { editing = null; was = null; formBox.textContent = ""; formBox.appendChild(empty()); drawList(); });
        } }) : null
      ]));
      drawList();
      paint();
    }

    function saveIt() {
      var problem = C.themeNameProblem(editing.name, T.all().filter(function (n) { return n !== was; }));
      if (problem) { note.textContent = problem; note.classList.add("pm-bad"); return Promise.resolve(false); }
      var renamed = was && was !== editing.name;
      return T.put(JSON.parse(JSON.stringify(editing)), was).then(function () {
        if (renamed && deck.theme() === was) deck.use(editing.name);
        was = editing.name;
        note.classList.remove("pm-bad");
        note.textContent = "Saved.";
        drawList();
        return true;
      });
    }

    function empty() {
      return h("div", { class: "pm-hint pm-theme-empty" }, [
        h("p", { text: "Pick one of your themes to change it, start a new one, or copy a built-in theme." }),
        h("p", { text: "A theme made here works in PresMaker, its PDFs and its .html at once. The IDEs show it once its CSS is added there — Copy for the IDEs puts that CSS on the clipboard with notes on where it goes." })
      ]);
    }

    formBox.appendChild(empty());
    drawList();
    var mine = deck.theme() && T.get(deck.theme());
    if (mine) edit(JSON.parse(JSON.stringify(mine)), mine.name);
    open({
      title: "Slide themes", wide: true, noFocus: true,
      body: h("div", { class: "pm-themes" }, [listBox, formBox, stage]),
      buttons: [{ spacer: true }, { label: "Done" }],
      onClose: function () { draftCSS.remove(); draftFont.remove(); sizer.disconnect(); }
    });
  }

  // ----------------------------------------------------------- export
  // A PDF needs the Mac app (bridge.js "pdf"); in a browser, .html is first.
  var lastExport = { format: window.PMBridge.native ? "pdf" : "html", questions: true, tests: true, answers: false, traces: [] };

  function exportForm(info, go) {
    var o = Object.assign({}, lastExport);
    // Traces are picked per lesson: keep only the ones this lesson has.
    var ids = (info.examples || []).map(function (ex) { return ex.id; });
    o.traces = (o.traces || []).filter(function (id) { return ids.indexOf(id) >= 0; });
    if (!info.slides && o.format === "teacher") o.format = window.PMBridge.native ? "pdf" : "html";
    var radios = h("div", { class: "pm-radios" });
    var FORMATS = [
      ["pdf", "PDF", info.slides ? "One slide a page, widescreen (13.33 × 7.5 in)." : "Letter pages."],
      ["html", "Presentation (.html)", info.slides ? "One file that opens in any browser: arrow keys move through the slides. Works offline." : "One file that opens in any browser."],
      ["md", "Markdown (.md)", "The notes, for the IDEs or another editor — with what you leave out below taken out."]
    ];
    if (!window.PMBridge.native) FORMATS.shift();
    if (info.slides) FORMATS.push(["teacher", "Teacher slides (.html)",
      "For the projector while students watch: outputs hidden until you reveal them, spot-the-bug, " +
      "step-through traces, a name picker and team points. Tests and the final coding exercise are left out."]);
    var opts = h("div", { class: "pm-checks" });
    var summary = h("p", { class: "pm-hint" });
    var traceBox = h("div", { class: "pm-traces" });
    var includeBox = h("div");
    function drawTraces() {
      traceBox.textContent = "";
      var list = info.examples || [];
      traceBox.appendChild(h("div", { class: "pm-field-label", text: "Step-through traces" }));
      if (!list.length) {
        traceBox.appendChild(h("p", { class: "pm-hint", text: "This lesson has no Python examples to trace." }));
        return;
      }
      traceBox.appendChild(h("p", { class: "pm-hint", text: window.PMBridge.native
        ? "Tick 1–3 examples where the order things run matters. Each press of → then runs one line, with the variables and output beside it."
        : "Traces run your Python, so they can only be made in the PresMaker app." }));
      var rows = h("div", { class: "pm-trace-list" });
      list.forEach(function (ex) {
        var off = !window.PMBridge.native || ex.input;
        rows.appendChild(h("label", { class: "pm-inline" + (off ? " pm-off" : ""),
                                      title: ex.input ? "It asks for input(), so it can't be traced" : "" }, [
          h("input", { type: "checkbox", checked: o.traces.indexOf(ex.id) >= 0 && !off, disabled: off,
                       onchange: function (e) {
                         o.traces = o.traces.filter(function (id) { return id !== ex.id; });
                         if (e.target.checked) o.traces.push(ex.id);
                         draw();
                       } }),
          h("span", { text: "Slide " + ex.slide + ": " }),
          h("code", { text: ex.line + (ex.lines > 1 ? " …" : "") })
        ]));
      });
      traceBox.appendChild(rows);
    }
    function draw() {
      radios.textContent = "";
      FORMATS.forEach(function (f) {
        radios.appendChild(h("label", { class: "pm-radio" + (o.format === f[0] ? " pm-on" : "") }, [
          h("input", { type: "radio", name: "pm-format", value: f[0], checked: o.format === f[0],
                       onchange: function () { o.format = f[0]; draw(); } }),
          h("span", {}, [h("b", { text: f[1] }), h("br"), h("span", { class: "pm-hint", text: f[2] })])
        ]));
      });
      opts.textContent = "";
      function check(key, label, disabled, title) {
        opts.appendChild(h("label", { class: "pm-inline" + (disabled ? " pm-off" : ""), title: title }, [
          h("input", { type: "checkbox", checked: !!o[key] && !disabled, disabled: disabled,
                       onchange: function (e) { o[key] = e.target.checked; draw(); } }), label]));
      }
      check("questions", "Questions (" + info.questions + ")", !info.questions);
      check("tests", "Tests (" + info.tests + ")", !info.tests);
      check("answers", "Show the answers", o.format === "md" || !o.questions || !info.questions,
            "An answer key: each question printed with its answer");
      var teacher = o.format === "teacher";
      includeBox.hidden = teacher;
      traceBox.hidden = !teacher;
      if (teacher) {
        drawTraces();
        summary.textContent = "A deck for the projector, made from this lesson's " + info.count + " slides" +
          (o.traces.length ? ", with " + o.traces.length + " trace" + (o.traces.length > 1 ? "s" : "") : "") + ".";
        return;
      }
      var left = [];
      if (!o.questions && info.questions) left.push("no questions");
      if (!o.tests && info.tests) left.push("no tests");
      summary.textContent = (info.slides ? info.count + " slides" : "A document") +
        (left.length ? " — display only: " + left.join(", ") + "." : ".") +
        (o.format === "md" && !o.questions && !o.tests ? "" : "");
    }
    function preset(q, t, a) { o.questions = q; o.tests = t; o.answers = a; draw(); }
    draw();
    open({
      title: "Export", noFocus: true,
      body: h("div", { class: "pm-export" }, [
        radios,
        includeBox,
        traceBox,
        summary
      ]),
      buttons: [{ spacer: true }, { label: "Cancel" },
                { label: "Export…", primary: true, action: function () { lastExport = Object.assign({}, o); go(o); } }]
    });
    includeBox.appendChild(h("div", { class: "pm-field-label", text: "Include" }));
    includeBox.appendChild(opts);
    includeBox.appendChild(h("div", { class: "pm-presets" }, [
          h("span", { class: "pm-hint", text: "Quick: " }),
          h("button", { class: "btn pm-small", type: "button", text: "Display only", title: "No questions, no tests", onclick: function () { preset(false, false, false); } }),
          h("button", { class: "btn pm-small", type: "button", text: "Student copy", title: "Questions and tests, no answers", onclick: function () { preset(true, true, false); } }),
          h("button", { class: "btn pm-small", type: "button", text: "Answer key", title: "Questions with their answers", onclick: function () { preset(true, true, true); o.format = o.format === "md" ? "pdf" : o.format; draw(); } })
    ]));
  }

  // ------------------------------------------------------------- help
  var EXAMPLES = [
    ["Multiple choice", 'What does len("hello") return?\n- [ ] "hello"\n- [x] 5\n- [ ] 4\npoints: 2'],
    ["Short answer", "Which keyword repeats code while a condition stays true?\nanswer: while\nanswer: a while loop"],
    ["Long response", "Explain why a while loop needs its condition to change.\ntype: long\npoints: 5"],
    ["Fill in the blank", "type: blank\nA [[while]] loop keeps going as long as its condition is [[True|true]].\npoints: 2"],
    ["Matching", "type: match\nMatch each keyword to what it does.\n- for -> repeats once for each item\n- while -> repeats while a condition holds\noption: stops the program\npoints: 2"]
  ];
  function help(which) {
    var body = h("div", { class: "pm-help prose" });
    body.appendChild(h("p", { text: "These are the IDEs' own formats — a deck made here works as-is in PyIDE, WebIDE and FlaskIDE." }));
    body.appendChild(h("h3", { text: "Slides" }));
    body.appendChild(h("p", { text: "A line with only --- on it starts a new slide. Notes with none are a document. A theme is the first line: theme: ocean." }));
    body.appendChild(h("h3", { text: "Questions" }));
    EXAMPLES.forEach(function (ex) {
      body.appendChild(h("p", {}, [h("b", { text: ex[0] })]));
      body.appendChild(h("pre", { class: "pm-source", text: "```quiz\n" + ex[1] + "\n```" }));
    });
    body.appendChild(h("h3", { text: "Tests", id: "pm-help-tests" }));
    body.appendChild(h("pre", { class: "pm-source", text:
      "```tests\ninput 3, 4 -> prints 12              typing 3 then 4; output must contain 12\n" +
      "input 5 -> prints exactly Area? 25    …or be exactly this\nprints Hello                          no input\n" +
      "area(3, 4) == 12        (2 points)    call their function and compare\nuses for                              a for loop somewhere\n" +
      "avoids sum                            the name sum appears nowhere\ndefines area                          there is a def area\n```" }));
    var back = current;
    open({ title: "Question and test formats", body: body, wide: true, noFocus: true,
           buttons: [{ spacer: true }, { label: back ? "Back" : "Close", primary: true, action: function () {
             if (back) setTimeout(function () { reopen(back); }, 0);
           } }] });
    if (which === "tests") setTimeout(function () { var t = document.getElementById("pm-help-tests"); if (t) t.scrollIntoView(); }, 0);
  }
  // Help opened from inside a form goes back to the form as it was.
  function reopen(was) {
    current = null;
    open(was);
  }

  /* Save / Don't save / Cancel, for New and Open over unsaved work. */
  function unsaved(then) {
    open({
      title: "Save your changes first?", noFocus: true,
      body: h("p", { class: "pm-hint", text: "If you don't, what you've written since the last save is lost." }),
      buttons: [{ spacer: true },
                { label: "Cancel" },
                { label: "Don't Save", action: function () { then(false); } },
                { label: "Save", primary: true, action: function () { then(true); } }]
    });
  }

  function choice(title, message, buttons) {
    open({ title: title, noFocus: true, body: h("p", { class: "pm-hint", text: message }),
           buttons: [{ spacer: true }].concat(buttons) });
  }

  return { h: h, open: open, close: close, isOpen: function () { return !!current; },
           question: question, tests: tests, themes: themes, exportForm: exportForm,
           help: help, unsaved: unsaved, choice: choice };
})();
