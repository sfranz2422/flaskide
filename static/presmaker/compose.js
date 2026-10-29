/* PresMaker — the markdown it writes, and the markdown it takes apart.
 *
 * Everything here is plain text in, plain text out, with no page, so
 * tools/test_compose.mjs can run it in node against the IDEs' own readers
 * (notes.js's parseQuiz and slides(), autograde.js's parse). That is the
 * whole point of this file: a question PresMaker writes is only right if
 * PyIDE reads it back as the same question, and the only way to know that
 * is to ask PyIDE's code.
 */
(function (root) {
  "use strict";

  // The same fence notes.js and autograde.js look for.
  var FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  var THEME_LINE = /^[ \t]*theme[ \t]*:[ \t]*([a-z]+)[ \t]*$/i;
  // notes.js's: the words `animate:` takes, and how each plays, and the
  // speed that may follow (or stand alone, meaning words).
  var ANIMATE_LINE = /^[ \t]*animate[ \t]*:[ \t]*([a-z]+)(?:[ \t]+([a-z]+))?[ \t]*$/i;
  var SPEED_NAMES = { slow: 1, normal: 1, fast: 1 };
  // notes.js's `locked:` line: hold a slide with tests until they pass (in the IDEs).
  var LOCKED_LINE = /^[ \t]*locked[ \t]*:[ \t]*(yes|no|on|off|true|false)[ \t]*$/i;
  function readAnimate(line) {
    var a = line.match(ANIMATE_LINE);
    if (!a) return null;
    var first = a[1].toLowerCase(), second = (a[2] || "").toLowerCase();
    if (SPEED_NAMES[first] && !second) return { animate: "words", speed: first };
    if (!ANIMATIONS[first] || (second && !SPEED_NAMES[second])) return null;
    return { animate: ANIMATIONS[first], speed: second || "normal" };
  }
  var ANIMATIONS = { words: "words", word: "words", reveal: "words", on: "words", yes: "words", "true": "words",
                     type: "type", typewriter: "type", typing: "type" };

  function lines(md) { return String(md || "").replace(/\r\n?/g, "\n").split("\n"); }
  function oneLine(s) { return String(s || "").replace(/\s*\n\s*/g, " ").trim(); }

  /* Every top-level fenced block: {start, end, info}, line numbers from 0,
     end being the closing fence (or the last line, for one never closed —
     markdown runs an unclosed fence to the end of the document too).

     A fence closes on the same character, at least as long, with nothing
     after it. That last part is CommonMark's rule and autograde.js's, and
     it matters here: a quiz block's prompt may hold ~~~python and ~~~, and
     only a bare ``` of three or more ends the question. */
  function fences(md) {
    var ls = lines(md), out = [], i = 0;
    while (i < ls.length) {
      var f = FENCE.exec(ls[i]);
      if (!f) { i++; continue; }
      var mark = f[1], start = i, end = ls.length - 1;
      for (i = i + 1; i < ls.length; i++) {
        var g = FENCE.exec(ls[i]);
        if (g && g[1][0] === mark[0] && g[1].length >= mark.length && !g[2].trim()) { end = i; break; }
      }
      out.push({ start: start, end: end, info: f[2].trim().split(/\s+/)[0].toLowerCase() });
      i = end + 1;
    }
    return out;
  }

  /* The block around a line, if it is a ```quiz or ```tests: so the editor
     can open a question for editing when the cursor is inside one. */
  function blockAt(md, line) {
    var hit = null;
    fences(md).forEach(function (b) {
      if (line >= b.start && line <= b.end && (b.info === "quiz" || b.info === "tests")) hit = b;
    });
    if (!hit) return null;
    var ls = lines(md);
    var closed = FENCE.test(ls[hit.end]) && hit.end > hit.start;
    hit.body = ls.slice(hit.start + 1, closed ? hit.end : hit.end + 1).join("\n");
    return hit;
  }

  /* The notes without their questions and/or tests, for a display-only
     copy. Blank lines left where a block was are squeezed to one, so a
     slide that was "text, question, text" doesn't gain a hole.

     A slide that held nothing but its heading and what was taken out goes
     too, with its `---`: "Check your understanding" over an empty slide is
     a slide that only says something was removed. A slide that was only
     ever a heading (a section title) is kept — nothing was taken from it. */
  function strip(md, what) {
    what = what || {};
    var drop = {};
    if (what.questions) drop.quiz = true;
    if (what.tests) drop.tests = true;
    var ls = lines(md), cut = {};
    fences(md).forEach(function (b) {
      if (drop[b.info]) for (var i = b.start; i <= b.end; i++) cut[i] = true;
    });
    // The slides, by line, with the `---` that starts each (none for the first).
    var slides = [{ rule: -1, from: 0, lost: false }], fence = null;
    ls.forEach(function (ln, i) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
      } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) {
        slides.push({ rule: i, from: i + 1, lost: false });
      }
      if (cut[i]) slides[slides.length - 1].lost = true;
    });
    // The header lines (theme:, animate:) are on the first slide's lines but belong to the deck.
    var head = {};
    header(md).lines.forEach(function (i) { head[i] = true; });
    if (slides.length > 1) {
      slides.forEach(function (s, k) {
        var to = k + 1 < slides.length ? slides[k + 1].rule : ls.length;
        var left = [];
        for (var i = s.from; i < to; i++) if (!cut[i] && !head[i] && ls[i].trim()) left.push(ls[i]);
        var bare = left.every(function (l) { return /^ {0,3}#{1,6}\s/.test(l); });
        if (!s.lost || !bare) return;
        for (var j = s.from; j < to; j++) if (!head[j]) cut[j] = true;
        // Its own `---` goes with it; the first slide has none, so the
        // one after it goes instead.
        if (s.rule >= 0) cut[s.rule] = true;
        else if (slides[1]) cut[slides[1].rule] = true;
      });
    }
    var out = ls.filter(function (_, i) { return !cut[i]; }).join("\n");
    return out.replace(/\n{3,}/g, "\n\n");
  }

  // ------------------------------------------------------------- header
  /* The notes' header lines as notes.js's takeHeader reads them: `theme:`
     and `animate:`, the first one or two lines with anything on them, in
     either order. {theme, animate, themeLine, animateLine, lines, end}: the
     names written, the lines themselves as written, their numbers, and the
     line the rest starts on.

     `known` (the theme names notes.js has) makes a theme it doesn't know
     stop the header, as it does in the IDEs, where it stays on the slide as
     text. Without it any name counts — the editor needs to tell "no theme"
     from "a theme the IDEs don't have". */
  function header(md, known) {
    var ls = lines(md), i = 0;
    var out = { theme: "", animate: "", speed: "", locked: false,
                themeLine: "", animateLine: "", lockedLine: "", lines: [], end: 0 };
    for (var k = 0; k < 3; k++) {
      while (i < ls.length && !ls[i].trim()) i++;
      if (i >= ls.length) break;
      var t = ls[i].match(THEME_LINE), a = readAnimate(ls[i]), l = ls[i].match(LOCKED_LINE);
      if (t && !out.themeLine && (!known || known.indexOf(t[1].toLowerCase()) >= 0)) {
        out.theme = t[1].toLowerCase();
        out.themeLine = ls[i].trim();
      } else if (a && !out.animateLine) {
        out.animate = a.animate;
        out.speed = a.speed;
        out.animateLine = ls[i].trim();
      } else if (l && !out.lockedLine) {
        out.locked = /^(yes|on|true)$/i.test(l[1]);
        out.lockedLine = ls[i].trim();
      } else break;
      out.lines.push(i);
      out.end = ++i;
    }
    return out;
  }

  /* The notes with the header made of these lines, theme first; the rest
     untouched. Blank lines before the header go with it, as takeHeader
     takes them. */
  function withHeader(md, themeLine, animateLine, lockedLine) {
    var h = header(md);
    var body = h.lines.length ? lines(md).slice(h.end).join("\n") : String(md || "");
    var top = [themeLine, animateLine, lockedLine === undefined ? h.lockedLine : lockedLine].filter(function (l) { return l; });
    return top.length ? top.join("\n") + "\n" + body : body;
  }

  /* The theme line's name, known or not ("" for none). */
  function themeOf(md) { return header(md).theme; }

  /* The notes with their theme line set to `name`, or taken out for "".
     An `animate:` line stays. */
  function setTheme(md, name) {
    return withHeader(md, name ? "theme: " + name : "", header(md).animateLine);
  }

  /* How the notes play: "words", "type", or "" (shown whole). */
  function animateOf(md) { return header(md).animate; }

  /* The notes with their `animate:` line set to `how` ("words" / "type"),
     or taken out for "". The theme line stays, first. */
  function setAnimate(md, how) {
    return withHeader(md, header(md).themeLine, how ? "animate: " + how : "");
  }

  /* Whether the IDEs hold each slide with tests until they pass (`locked: yes`). */
  function lockedOf(md) { return header(md).locked; }

  /* The notes with `locked: yes`, or without the line (on false). The theme
     and animate lines stay, in front of it. */
  function setLocked(md, on) {
    var h = header(md);
    return withHeader(md, h.themeLine, h.animateLine, on ? "locked: yes" : "");
  }

  // ------------------------------------------------------------- slides
  /* Which slide line `at` (from 0) is on, counted exactly as notes.js's
     slides() counts: the header lines come off the top, each `---` outside
     fenced code ends a slide, and empty slides are dropped. A cursor on an
     empty one (two `---` in a row) shows the slide after it.

     {index, count}: count is 0 for notes that are not slides — no `---`,
     or only one slide with text, which the viewer shows whole. */
  function slideAt(md, at, known) {
    var ls = lines(md);
    var first = header(md, known).end;
    var chunk = 0, fence = null, cuts = 0, chunkOf = [], text = [""];
    for (var i = first; i < ls.length; i++) {
      var ln = ls[i], f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
      } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) {
        chunk++; cuts++; text.push("");
        chunkOf[i] = chunk;            // the rule starts the slide after it
        continue;
      }
      chunkOf[i] = chunk;
      text[chunk] += ln.trim();
    }
    var number = [], n = 0;
    text.forEach(function (t, c) { number[c] = t ? n++ : -1; });
    if (!cuts || n < 2) return { index: 0, count: 0 };
    var c = at < first ? 0 : (chunkOf[Math.min(at, ls.length - 1)] || 0);
    while (c < text.length && number[c] < 0) c++;
    if (c >= text.length) c = text.length - 1;
    while (c > 0 && number[c] < 0) c--;
    return { index: Math.max(0, number[c]), count: n };
  }

  /* The line a slide (from 0) starts on, for the preview's arrows moving
     the editor. The inverse of slideAt: the first line slideAt puts there. */
  function slideStart(md, index, known) {
    var ls = lines(md);
    for (var i = 0; i < ls.length; i++) {
      if (!ls[i].trim() || /^ {0,3}-{3,}\s*$/.test(ls[i])) continue;
      if (slideAt(md, i, known).index === index) return i;
    }
    return 0;
  }

  // ---------------------------------------------------------- questions
  /* A fence long enough that nothing inside can close it: one more than the
     longest run of the same character opening a line inside. Markdown has
     no escape for a fence, so length is the only way. */
  function fenceFor(body, ch) {
    var longest = 2;
    lines(body).forEach(function (ln) {
      var m = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (m && m[1][0] === ch) longest = Math.max(longest, m[1].length);
    });
    return new Array(longest + 2).join(ch);
  }

  function codeBlock(code, lang) {
    var c = String(code || "").replace(/\s+$/, "");
    if (!c) return "";
    var f = fenceFor(c, "~");
    return f + (lang || "python") + "\n" + c + "\n" + f;
  }

  /* One ```quiz block from what the question form holds:

       kind     choice | text | long | blank | match | order | sort | bug | predict
       prompt   the question, markdown
       code     code shown under it (a ~~~ fence; blanks allowed) — optional,
                but it IS the question for bug and predict
       choices  [{text, correct}]          (choice)
       answers  ["while", "a while loop"]  (text; predict: what it prints)
       pairs    [{left, right}]            (match)
       options  ["stops the program"]      (match: wrong answers to offer)
       lines    "the lines\nin order"      (order; indentation kept)
       groups   [{name, items: "a\nb"}]    (sort)
       bugs     "2" or "2, 3"              (bug: the wrong line, from 1)
       points   number, 1 if left out

     The order of lines follows the examples on /help/questions, which is
     what a teacher reading their own source will recognise. */
  function quizBlock(q) {
    var out = [], kind = q.kind || "choice";
    if (/^(blank|match|order|sort|bug|predict)$/.test(kind)) out.push("type: " + kind);
    var prompt = String(q.prompt || "").replace(/\s+$/, "");
    if (prompt) out.push(prompt);
    var code = kind === "order" || kind === "sort" ? "" : codeBlock(q.code, q.codeLang);
    if (code) out.push(code);
    if (kind === "choice") {
      (q.choices || []).forEach(function (c) {
        var t = oneLine(c.text);
        if (t) out.push("- [" + (c.correct ? "x" : " ") + "] " + t);
      });
    } else if (kind === "text" || kind === "predict") {
      (q.answers || []).forEach(function (a) {
        a = oneLine(a);
        if (a) out.push("answer: " + a);
      });
    } else if (kind === "long") {
      out.push("type: long");
    } else if (kind === "match") {
      (q.pairs || []).forEach(function (p) {
        var l = oneLine(p.left), r = oneLine(p.right);
        if (l && r) out.push("- " + l + " -> " + r);
      });
      (q.options || []).forEach(function (o) {
        o = oneLine(o);
        if (o) out.push("option: " + o);
      });
    } else if (kind === "order") {
      // Each line after "- ", its own indentation kept: indenting is part of the order.
      lines(q.lines).forEach(function (l) {
        l = l.replace(/\s+$/, "");
        if (l.trim()) out.push("- " + l);
      });
    } else if (kind === "sort") {
      (q.groups || []).forEach(function (g) {
        var name = oneLine(g.name);
        if (!name) return;
        out.push("group: " + name);
        lines(g.items).forEach(function (it) {
          if (it.trim()) out.push("- " + it.trim());
        });
      });
    } else if (kind === "bug") {
      var bugs = bugLines(q.bugs);
      if (bugs.length) out.push("bug: " + bugs.join(", "));
    }
    var pts = Number(q.points);
    if (isFinite(pts) && pts !== 1 && pts >= 0) out.push("points: " + pts);
    var body = out.join("\n");
    var f = fenceFor(body, "`");
    return f + "quiz\n" + body + "\n" + f;
  }

  /* A sort question's groups as written: each `group:` line and the `- `
     items under it, outside fenced code. */
  function sortGroups(body) {
    var out = [], fence = null;
    lines(body).forEach(function (ln) {
      var f = ln.match(FENCE);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length && !f[2].trim()) fence = null;
        return;
      }
      if (fence !== null) return;
      var g = ln.match(/^\s*group\s*:\s*(.+?)\s*$/i), it = ln.match(/^\s*-\s+(.*\S)\s*$/);
      if (g) out.push({ name: g[1], items: "" });
      else if (it && out.length) {
        var last = out[out.length - 1];
        last.items += (last.items ? "\n" : "") + it[1];
      }
    });
    return out;
  }

  /* The line numbers in a bug question's "2, 3", as quiz.py reads them. */
  function bugLines(s) {
    return String(s || "").split(/[,\s]+/).filter(function (b) { return /^\d+$/.test(b); })
      .map(function (b) { return b.replace(/^0+/, "") || "0"; });
  }

  /* The form's fields from a block already in the notes, so a question can
     be opened again and changed. `parsed` is notes.js's parseQuiz of the
     body — PyIDE's reading, not a second one made up here. The prompt keeps
     any code it holds; the code field starts empty. */
  function quizForm(parsed, body) {
    var p = parsed, f = { kind: p.kind, prompt: p.prompt, code: "", points: p.points,
                          choices: [], answers: [], pairs: [], options: [], lines: "", groups: [], bugs: "" };
    if (p.kind === "choice") {
      f.choices = p.choices.map(function (c) { return { text: c, correct: p.correct.indexOf(c) >= 0 }; });
    } else if (p.kind === "text" || p.kind === "predict") {
      f.answers = p.answers.slice();
    } else if (p.kind === "order") {
      f.lines = p.correct.join("\n");
    } else if (p.kind === "sort") {
      // From the block's own lines when there are any, not parseQuiz's
      // shuffle: the shuffle is worked out from the items in the order
      // written, so writing them back in another order would show
      // students a different tray.
      f.groups = body !== undefined ? sortGroups(body) : p.answers.map(function (name) {
        return { name: name, items: p.choices.filter(function (_, i) { return p.correct[i] === name; }).join("\n") };
      });
    } else if (p.kind === "bug") {
      f.bugs = p.correct.join(", ");
    } else if (p.kind === "match") {
      f.pairs = p.choices.map(function (l, i) { return { left: l, right: p.correct[i] || "" }; });
      f.options = p.options.filter(function (o) { return p.correct.indexOf(o) < 0; });
    }
    return f;
  }

  // -------------------------------------------------------------- tests
  /* One test line from the tests form, in autograde.py's words:

       {kind: "output", inputs: ["3","4"], expect: "12", exact: false}
       {kind: "call",   expr: "area(3, 4)", expect: "12"}
       {kind: "uses" | "avoids" | "defines", name: "for"}

     plus points (1 if left out). Returns "" for a test with nothing in it. */
  function testLine(t) {
    var line = "";
    if (t.kind === "output") {
      var expect = oneLine(t.expect);
      if (!expect) return "";
      var ins = (t.inputs || []).map(oneLine).filter(function (s) { return s; });
      line = (ins.length ? "input " + ins.join(", ") + " -> " : "") +
             "prints " + (t.exact ? "exactly " : "") + expect;
    } else if (t.kind === "call") {
      var expr = oneLine(t.expr), want = oneLine(t.expect);
      if (!expr || !want) return "";
      line = expr + " == " + want;
    } else {
      var name = oneLine(t.name);
      if (!name) return "";
      line = t.kind + " " + name;
    }
    var pts = Number(t.points);
    if (isFinite(pts) && pts !== 1 && pts > 0) line += "  (" + pts + (pts === 1 ? " point)" : " points)");
    return line;
  }

  function testsBlock(tests) {
    var body = (tests || []).map(testLine).filter(function (l) { return l; }).join("\n");
    return "```tests\n" + body + "\n```";
  }

  /* What can't be said in a test line, in words for the form. autograde
     splits inputs on commas and reads " == " as the comparison, so those
     are the two ways a test can quietly come out as a different test. */
  function testProblems(t) {
    var p = [];
    if (t.kind === "output") {
      (t.inputs || []).forEach(function (s) {
        if (/,/.test(s)) p.push("An input can't hold a comma — commas separate the inputs.");
      });
      if (/\(\s*\d+(\.\d+)?\s*points?\s*\)\s*$/i.test(t.expect || ""))
        p.push("What it prints can't end in (N points) — that would be read as the points.");
    }
    if (t.kind === "call" && / == /.test(t.expr || "")) p.push("The call can't contain \" == \" itself.");
    if ((t.kind === "uses" || t.kind === "avoids" || t.kind === "defines") && /\s/.test(oneLine(t.name)) &&
        !/^import\s+\S+$/i.test(oneLine(t.name)))
      p.push("Use one word (or import name).");
    return p;
  }

  // ---------------------------------------------------- the theme maker
  /* The display faces a made theme may use for its headings. The first
     five are the ones the IDEs already fetch (notes.js, themeFonts), so a
     theme using them needs no change there but its CSS. The rest work in
     PresMaker; the CSS this makes for the IDEs says so when one is used. */
  var FONTS = [
    { id: "", label: "The page's own (no display face)" },
    { id: "Caveat", label: "Caveat — chalk handwriting", spec: "Caveat:wght@600;700", ide: true, weight: 700 },
    { id: "Patrick Hand", label: "Patrick Hand — neat handwriting", spec: "Patrick+Hand", ide: true, weight: 400 },
    { id: "Press Start 2P", label: "Press Start 2P — pixel arcade", spec: "Press+Start+2P", ide: true, weight: 400, small: true },
    { id: "Creepster", label: "Creepster — spooky", spec: "Creepster", ide: true, weight: 400 },
    { id: "Mountains of Christmas", label: "Mountains of Christmas", spec: "Mountains+of+Christmas:wght@700", ide: true, weight: 700 },
    { id: "Bangers", label: "Bangers — comic book", spec: "Bangers", weight: 400 },
    { id: "Orbitron", label: "Orbitron — sci-fi", spec: "Orbitron:wght@700", weight: 700 },
    { id: "Lobster", label: "Lobster — script", spec: "Lobster", weight: 400 },
    { id: "Fredoka", label: "Fredoka — round and friendly", spec: "Fredoka:wght@600", weight: 600 },
    { id: "Merriweather", label: "Merriweather — bookish serif", spec: "Merriweather:wght@700", weight: 700 },
    { id: "Special Elite", label: "Special Elite — typewriter", spec: "Special+Elite", weight: 400 }
  ];
  function font(id) {
    for (var i = 0; i < FONTS.length; i++) if (FONTS[i].id === id) return FONTS[i];
    return FONTS[0];
  }
  function fontsURL(ids) {
    var specs = [];
    ids.forEach(function (id) {
      var f = font(id);
      if (f.spec && specs.indexOf(f.spec) < 0) specs.push(f.spec);
    });
    if (!specs.length) return "";
    return "https://fonts.googleapis.com/css2?family=" + specs.join("&family=") + "&display=swap";
  }

  var PATTERNS = ["none", "stars", "snow", "dots", "grid", "lines", "paper", "glow"];

  function hex(c) {
    var m = String(c || "").trim().match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!m) return null;
    var h = m[1].length === 3 ? m[1].replace(/./g, "$&$&") : m[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function rgba(c, a) {
    var v = hex(c) || [128, 128, 128];
    return "rgba(" + v.join(", ") + ", " + a + ")";
  }
  /* c moved toward white (by > 0) or black (by < 0), for the hover colour
     of a link: lighter on a dark theme, darker on a light one, as the
     built-in themes do it. */
  function shade(c, by) {
    var v = hex(c) || [128, 128, 128];
    var to = by > 0 ? 255 : 0, k = Math.abs(by);
    return "#" + v.map(function (x) {
      var y = Math.round(x + (to - x) * k);
      return (y < 16 ? "0" : "") + y.toString(16);
    }).join("");
  }

  function pattern(t) {
    var dark = t.scheme !== "light";
    var ink = dark ? "rgba(255, 255, 255, .85)" : rgba(t.text, 0.18);
    var faint = dark ? "rgba(255, 255, 255, .07)" : rgba(t.text, 0.07);
    switch (t.pattern) {
      // A tiled field in two sizes so the repeat doesn't read as a grid —
      // the way space and winter draw theirs.
      case "stars": return [
        "radial-gradient(2px 2px at 24px 36px, " + ink + " 50%, transparent) 0 0 / 220px 190px",
        "radial-gradient(1.5px 1.5px at 140px 22px, " + ink + " 50%, transparent) 0 0 / 220px 190px",
        "radial-gradient(1.5px 1.5px at 92px 150px, " + ink + " 50%, transparent) 0 0 / 220px 190px",
        "radial-gradient(1px 1px at 60px 80px, " + ink + " 50%, transparent) 0 0 / 170px 230px"];
      case "snow": return [
        "radial-gradient(4px 4px at 30px 40px, " + (dark ? "#fff" : "#ffffff") + " 55%, transparent) 0 0 / 200px 180px",
        "radial-gradient(3px 3px at 130px 110px, #ffffff 55%, transparent) 0 0 / 200px 180px",
        "radial-gradient(3.5px 3.5px at 80px 150px, #ffffff 55%, transparent) 0 0 / 160px 220px"];
      case "dots": return ["radial-gradient(" + faint.replace(".07", ".16") + " 1.5px, transparent 1.6px) 0 0 / 22px 22px"];
      case "grid": return [
        "linear-gradient(" + faint + " 1px, transparent 1px) 0 0 / 28px 28px",
        "linear-gradient(90deg, " + faint + " 1px, transparent 1px) 0 0 / 28px 28px"];
      case "lines": return ["linear-gradient(transparent 27px, " + faint.replace(".07", ".14") + " 27px) 0 0 / 100% 28px"];
      case "paper": return [
        "linear-gradient(90deg, transparent 34px, " + rgba(t.accent, 0.45) + " 34px, " + rgba(t.accent, 0.45) + " 36px, transparent 36px)",
        "linear-gradient(transparent 27px, " + rgba(t.heading, 0.18) + " 27px) 0 0 / 100% 28px"];
      case "glow": return [
        "radial-gradient(ellipse at 15% 0%, " + rgba(t.accent, 0.22) + ", transparent 55%)",
        "radial-gradient(ellipse at 90% 100%, " + rgba(t.heading, 0.2) + ", transparent 55%)"];
    }
    return [];
  }

  /* The CSS value of a made theme's background: its pattern over its
     colour, or what the author typed under Advanced, which wins. */
  function background(t) {
    if (t.bgCSS && t.bgCSS.trim()) return t.bgCSS.trim().replace(/;+\s*$/, "");
    var base = t.bgType === "gradient"
      ? "linear-gradient(" + (Number(t.angle) || 0) + "deg, " + t.bg1 + " 0%, " +
        (t.bg3 ? t.bg2 + " 55%, " + t.bg3 + " 100%)" : t.bg2 + " 100%)")
      : t.bg1;
    return pattern(t).concat([base]).join(",\n              ");
  }

  /* A made theme as CSS, in the shape of the built-in ones in style.css:
     the same variable names on .slide-theme-<name>, so headings, code,
     tables, question cards and links all follow without a rule each. The
     colours the form doesn't ask for (lines, panels, the box behind code)
     are see-through white on a dark theme and see-through ink on a light
     one, which is how the built-ins are made too. */
  function themeCSS(t) {
    var dark = t.scheme !== "light", n = t.name;
    var sel = ".slide-theme-" + n;
    var css = sel + " {\n" +
      "  --theme-bg: " + background(t) + ";\n" +
      "  --nav-bg: " + (t.nav || t.bg1) + ";\n" +
      "  --text: " + t.text + "; --muted: " + t.muted + "; --heading: " + t.heading +
      "; --heading-2: " + (t.heading2 || t.heading) + ";\n" +
      "  --accent: " + t.accent + "; --accent-hover: " + shade(t.accent, dark ? 0.35 : -0.25) +
      "; --strong: " + (t.strong || t.text) + ";\n" +
      (dark
        ? "  --line: rgba(255, 255, 255, .16); --bg: rgba(0, 0, 0, .3);\n" +
          "  --bg-panel: rgba(255, 255, 255, .07); --bg-head: rgba(255, 255, 255, .1);\n" +
          "  --hover-bg: rgba(255, 255, 255, .1); color-scheme: dark;\n"
        : "  --line: " + rgba(t.text, 0.16) + "; --bg: rgba(255, 255, 255, .72);\n" +
          "  --bg-panel: rgba(255, 255, 255, .55); --bg-head: rgba(255, 255, 255, .82);\n" +
          "  --hover-bg: rgba(255, 255, 255, .65); color-scheme: light;\n") +
      "}\n";
    if (t.pattern === "paper") css += ".notes-body" + sel + " { background-attachment: local; padding-left: 56px; }\n";
    var f = font(t.font);
    if (f.id) {
      css += sel + " h1, " + sel + " h2, " + sel + " h3 {\n  font-family: \"" + f.id +
             "\", var(--sans); font-weight: " + f.weight + ";\n}\n";
      css += f.small
        ? sel + " h1 { font-size: 1.25em; }\n" + sel + " h2 { font-size: 1em; }\n" + sel + " h3 { font-size: .8em; }\n"
        : sel + " h1 { font-size: 2.2em; }\n" + sel + " h2 { font-size: 1.75em; }\n" + sel + " h3 { font-size: 1.4em; }\n";
    }
    return css;
  }

  /* Everything a person needs to give a made theme to PyIDE, WebIDE and
     FlaskIDE, as one paste: the CSS, and where the name has to go. A theme
     only in style.css does nothing there — notes.js's THEMES is what turns
     the name into a class — and a name only in THEMES has no colours. */
  function themeForIDEs(t) {
    var f = font(t.font);
    var note = "/* Theme \"" + t.name + "\", made in PresMaker.\n" +
      "   1. This CSS goes at the end of the SLIDE THEMES part of static/style.css.\n" +
      "   2. \"" + t.name + "\" goes in THEMES in static/notes.js" +
      (f.id ? ", and in FONT_THEMES too (its headings use " + f.id + ")" : "") + ".\n" +
      "   3. Add it to the theme list in templates/help_questions.html (test_themes.py checks it).\n" +
      (f.id && !f.ide ? "   4. " + f.id + " isn't one of the faces themeFonts() fetches: add \"" +
        f.spec + "\" to its fonts.googleapis.com address.\n" : "") +
      "   The same in all three IDEs. */\n";
    return note + themeCSS(t);
  }

  var NAME = /^[a-z]+$/;
  function themeNameProblem(name, taken) {
    if (!name) return "Give it a name.";
    if (!NAME.test(name)) return "Only small letters a–z, no spaces or digits — that's all the theme line accepts.";
    if (taken && taken.indexOf(name) >= 0) return "There's already a theme called " + name + ".";
    return "";
  }

  var api = {
    fences: fences, blockAt: blockAt, strip: strip,
    themeOf: themeOf, setTheme: setTheme, header: header, animateOf: animateOf, setAnimate: setAnimate,
    lockedOf: lockedOf, setLocked: setLocked,
    bugLines: bugLines,
    slideAt: slideAt, slideStart: slideStart,
    quizBlock: quizBlock, quizForm: quizForm,
    testLine: testLine, testsBlock: testsBlock, testProblems: testProblems,
    FONTS: FONTS, font: font, fontsURL: fontsURL, PATTERNS: PATTERNS,
    themeCSS: themeCSS, themeForIDEs: themeForIDEs, themeNameProblem: themeNameProblem,
    hex: hex
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PMCompose = api;
})(this);
