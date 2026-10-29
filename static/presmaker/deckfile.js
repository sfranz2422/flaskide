/* PresMaker — a teacher-slides .html file, taken apart and put back.
 *
 * Two kinds of deck come in: the ones PresMaker exports (teacher.js: slides
 * in .inner, code in pre.code, traces as JSON in <script id="traces">) and
 * hand-made ones (Function_Returns_Review_Teacher_Slides.html and the decks
 * copied from it: pre.py / pre.css / pre.html, `const TRACES = {…}` in the
 * script, a <!-- N --> comment over each slide).
 *
 * Everything here is strings — no DOM — so tools/test_deckfile.mjs runs it
 * in node. The rule it keeps: a deck opened and saved with nothing changed
 * comes back byte for byte. Only what was changed is written anew.
 */
(function (root) {
  "use strict";

  // ------------------------------------------------------------ parsing
  /* {kind, head, slides: [{pre, html}], tail, traces, tracesSrc, numbered} —
     head ends after the <div class="deck"> tag; each slide's `pre` is what
     sits before it (a newline, a <!-- N --> comment); tail is the rest. */
  function parse(text) {
    var deck = /<div\b[^>]*\bclass\s*=\s*["'][^"']*\bdeck\b[^"']*["'][^>]*>/i.exec(text);
    if (!deck) throw new Error("This isn't a teacher slides file: there's no <div class=\"deck\">.");
    var from = deck.index + deck[0].length;
    var stop = text.slice(from).search(/<script\b/i);
    stop = stop < 0 ? text.length : from + stop;
    var slides = [], at = from, re = /<section\b[\s\S]*?<\/section\s*>/gi, m;
    re.lastIndex = from;
    while ((m = re.exec(text)) && m.index < stop) {
      slides.push({ pre: text.slice(at, m.index), html: m[0] });
      at = m.index + m[0].length;
    }
    if (!slides.length) throw new Error("This deck has no slides (<section> elements) in it.");
    var tail = text.slice(at);
    var kind = /<script[^>]*\bid\s*=\s*["']traces["']/i.test(tail) || /PMTeacherDeck/.test(tail) ? "pm" : "hand";
    var t = findTraces(tail, kind);
    return {
      kind: kind, head: text.slice(0, from), slides: slides, tail: tail,
      traces: t.traces, tracesSrc: t.src, numbered: slides.some(function (s) { return /<!--\s*\d+\s*-->/.test(s.pre); })
    };
  }

  /* Where the traces are written in the tail: {traces, src: {start, end,
     text}} or src null if the deck has none (then traces can't be added). */
  function findTraces(tail, kind) {
    if (kind === "pm") {
      var j = /(<script[^>]*\bid\s*=\s*["']traces["'][^>]*>)([\s\S]*?)(<\/script>)/i.exec(tail);
      if (!j) return { traces: {}, src: null };
      var start = j.index + j[1].length, body = j[2], traces = {};
      try { traces = JSON.parse(body || "{}"); } catch (e) { traces = {}; }
      return { traces: traces, src: { start: start, end: start + body.length, text: body } };
    }
    var d = /\b(?:const|let|var)\s+TRACES\s*=\s*/.exec(tail);
    if (!d) return { traces: {}, src: null };
    var open = d.index + d[0].length;
    if (tail.charAt(open) !== "{") return { traces: {}, src: null };
    var close = matchBrace(tail, open);
    if (close < 0) return { traces: {}, src: null };
    var lit = tail.slice(open, close + 1), tr = {};
    // The deck's own script, which the teacher made: read the way the deck does.
    try { tr = new Function("return (" + lit + ");")(); } catch (e) { tr = {}; }
    return { traces: tr || {}, src: { start: open, end: close + 1, text: lit } };
  }

  /* The } that closes the { at `i`, skipping strings, template strings and
     comments. -1 if it never closes. */
  function matchBrace(s, i) {
    var depth = 0;
    for (var k = i; k < s.length; k++) {
      var c = s.charAt(k);
      if (c === '"' || c === "'" || c === "`") {
        for (k++; k < s.length && s.charAt(k) !== c; k++) if (s.charAt(k) === "\\") k++;
      } else if (c === "/" && s.charAt(k + 1) === "/") {
        k = s.indexOf("\n", k); if (k < 0) return -1;
      } else if (c === "/" && s.charAt(k + 1) === "*") {
        k = s.indexOf("*/", k + 2); if (k < 0) return -1; k++;
      } else if (c === "{") depth++;
      else if (c === "}") { depth--; if (depth === 0) return k; }
    }
    return -1;
  }

  // ------------------------------------------------------------ writing
  /* The traces as the deck's script wants them. A hand deck's script reads
     `skip` as one line number; trace.py gives a list. */
  function tracesText(d) {
    if (d.kind === "pm") return JSON.stringify(d.traces).replace(/</g, "\\u003c");
    var names = Object.keys(d.traces);
    if (!names.length) return "{}";
    return "{\n" + names.map(function (n) {
      var key = /^[A-Za-z_$][\w$]*$/.test(n) ? n : JSON.stringify(n);
      return "  " + key + ":[\n" + (d.traces[n] || []).map(function (st) {
        return "    " + JSON.stringify(handStep(st));
      }).join(",\n") + "\n  ]";
    }).join(",\n") + "\n}";
  }
  function handStep(st) {
    var o = { l: st.l };
    if (Array.isArray(st.skip)) { if (st.skip.length) o.skip = st.skip[0]; }
    else if (st.skip) o.skip = st.skip;
    o.note = st.note || "";
    if (st.vars && Object.keys(st.vars).length) o.vars = st.vars;
    if (st.out) o.out = st.out;
    return o;
  }

  /* The file. `tracesChanged` false keeps the traces exactly as they were
     written (a hand deck's has comments and its own layout). */
  function serialize(d, tracesChanged) {
    var body = d.slides.map(function (s) { return s.pre + s.html; }).join("");
    var tail = d.tail;
    if (tracesChanged && d.tracesSrc) {
      tail = tail.slice(0, d.tracesSrc.start) + tracesText(d) + tail.slice(d.tracesSrc.end);
    }
    return d.head + body + tail;
  }

  /* After slides move, come or go: a hand deck's <!-- N --> comments are
     numbered again, and a new slide gets a `pre` like its neighbours'. */
  function renumber(d) {
    var model = (d.slides[1] || d.slides[0] || {}).pre || "\n";
    d.slides.forEach(function (s, i) {
      if (s.pre === undefined) s.pre = d.numbered ? "\n\n<!-- " + (i + 1) + " -->\n" : model.replace(/<!--\s*\d+\s*-->/, "");
      else if (d.numbered) s.pre = s.pre.replace(/<!--\s*\d+\s*-->/, "<!-- " + (i + 1) + " -->");
      if (d.numbered && !/<!--\s*\d+\s*-->/.test(s.pre)) s.pre = "\n\n<!-- " + (i + 1) + " -->\n";
    });
  }

  // ------------------------------------------------------------ theme
  var THEME_RE = /\n?<style id="pm-theme">[\s\S]*?<\/style>/;
  var FONTS_RE = /\n?<link [^>]*data-pm-theme-fonts[^>]*>/;
  var META_RE = /\n?<meta name="pm-theme"[^>]*>/;
  function themeOf(d) {
    var m = /<meta name="pm-theme" content="([^"]*)"/.exec(d.head);
    return m ? m[1] : "";
  }
  /* Put a theme on the deck (css: the block to add; fonts: a style sheet
     URL or ""), or take it off again (name ""). Only head changes. */
  function setTheme(d, name, css, fonts) {
    var head = d.head.replace(THEME_RE, "").replace(FONTS_RE, "").replace(META_RE, "");
    if (name) {
      var add = '\n<meta name="pm-theme" content="' + esc(name) + '">' +
        (fonts ? '\n<link rel="stylesheet" data-pm-theme-fonts href="' + esc(fonts) + '">' : "") +
        '\n<style id="pm-theme">\n' + css + "\n</style>";
      var at = head.search(/<\/head>/i);
      head = at < 0 ? head + add : head.slice(0, at).replace(/\s*$/, "") + add + "\n" + head.slice(at);
    }
    d.head = head;
  }
  /* A hand deck's colours come from its own :root names (--orange is the
     accent). Code stays on a dark panel in every theme, in its own colours. */
  function handThemeCSS(t) {
    var dark = t.dark;
    return ":root{--bg:" + t.solid + ";--panel:" + t.panel + ";--panel2:" + t.line + ";--ink:" + t.ink +
      ";--muted:" + t.muted + ";--orange:" + t.accent + ";--purple:" + t.accent2 + ";--line:" + t.line +
      ";--green:" + (dark ? "#8ee06b" : "#15803d") + ";--red:" + (dark ? "#ff6b6b" : "#b91c1c") +
      ";--yellow:" + (dark ? "#ffd866" : "#a16207") + ";--blue:" + (dark ? "#7cc8ff" : "#1d4ed8") +
      ";color-scheme:" + (dark ? "dark" : "light") + "}\n" +
      ".slide{background:" + t.bg + "}\n" +
      "h1,.picked{font-family:" + t.head + "}\n" +
      "pre,.tracer{--ink:#f3eefb;--orange:#ff8a1f;--green:#8ee06b;--purple:#c39bff;--yellow:#ffd866;--blue:#7cc8ff;--red:#ff6b6b;color:var(--ink)}";
  }

  // ------------------------------------------------------------ new slides
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  /* The language most of the deck's code is in: py, css, html or js. */
  function language(d) {
    var n = { py: 0, css: 0, html: 0, js: 0 };
    d.slides.forEach(function (s) {
      var re = d.kind === "pm" ? /<pre class="code[^"]*" data-lang="(\w+)"/g : /<pre class="(py|css|html|js)\b/g, m;
      while ((m = re.exec(s.html))) if (n[m[1]] !== undefined) n[m[1]]++;
    });
    var best = "py", top = 0;
    Object.keys(n).forEach(function (k) { if (n[k] > top) { top = n[k]; best = k; } });
    return best;
  }
  /* The new-slide kinds this deck can show: a sort needs the deck's CSS to
     have chips, a trace needs a tracer and somewhere to keep the steps. */
  function kindsFor(d) {
    // An older deck whose script has no steps can't reveal anything.
    var steps = d.kind === "pm" || /\.reveal\b/.test(d.tail);
    return KINDS.filter(function (k) {
      if (!steps) return k.id === "step" || k.id === "text";
      if (k.id === "sort") return /\.tray\b/.test(d.head);
      if (k.id === "trace") return /\.tracer\b/.test(d.head) && !!d.tracesSrc;
      return true;
    });
  }
  var SAMPLE = {
    py: { code: 'def double(n):\n    return n * 2\n\nprint(double(4))', out: "8",
          bug: 'def double(n):\n    n * 2\n\nprint(double(4))', bugOut: "None", bugLine: 2, fix: 'def double(n):\n    return n * 2' },
    css: { code: "h1 {\n    color: orange;\n}", out: "", bug: "h1 {\n    color: orang;\n}", bugOut: "", bugLine: 2, fix: "h1 {\n    color: orange;\n}" },
    html: { code: '<label for="age">Age</label>\n<input id="age" type="number" name="age">', out: "",
            bug: '<label for="age">Age</label>\n<input id="ages" name="age">', bugOut: "", bugLine: 2, fix: '<input id="age" name="age">' },
    js: { code: 'function double(n) {\n    return n * 2;\n}\nconsole.log(double(4));', out: "8",
          bug: 'function double(n) {\n    n * 2;\n}\nconsole.log(double(4));', bugOut: "undefined", bugLine: 2, fix: "    return n * 2;" }
  };
  var KINDS = [
    { id: "step", label: "Step: code and its output" },
    { id: "predict", label: "Predict, then reveal" },
    { id: "bug", label: "Spot the bug" },
    { id: "pick", label: "Pick and check (multiple choice)" },
    { id: "sort", label: "Sort them into groups" },
    { id: "trace", label: "Step-through trace (Python)" },
    { id: "text", label: "Words only" }
  ];

  /* A new slide's HTML, written the way the deck's own slides are. `name`
     is the trace name for kind "trace". */
  function template(d, kind, name) {
    var lang = language(d), x = SAMPLE[lang], pm = d.kind === "pm";
    function code(src, extra) {
      extra = extra || {};
      var cls = pm ? "code" + (extra.cls ? " " + extra.cls : "") : lang + (extra.cls ? " " + extra.cls : "");
      return '<pre class="' + cls + '"' + (pm ? ' data-lang="' + lang + '"' : "") + (extra.attrs || "") + ">" + esc(src) + "</pre>";
    }
    function out(text, hidden) { return text ? '<pre class="out' + (hidden ? " reveal" : "") + '">' + esc(text) + "</pre>" : ""; }
    var body;
    if (kind === "step") {
      body = '  <h2><span class="num">1</span>A New Step</h2>\n  <p>Say what this code does.</p>\n  ' + code(x.code) + "\n  " +
        (x.out ? out(x.out, true) : '<div class="callout reveal">What it shows.</div>');
    } else if (kind === "predict") {
      body = '  <h2>🤔 Predict</h2>\n  <p>What will this print? <span class="ask">Call it out.</span></p>\n  ' + code(x.code) + "\n  " +
        '<div class="callout">It prints <span class="ans stage" data-a="' + esc(x.out || "the answer") + '"></span></div>';
    } else if (kind === "bug") {
      body = '  <h2>🐛 Spot the Bug</h2>\n  <p>This doesn\'t work. <span class="ask">Which line is wrong? Call out the number.</span></p>\n' +
        '  <div class="cols">\n    <div>\n      ' + code(x.bug, { cls: "stage", attrs: ' data-bug="' + x.bugLine + '"' }) +
        (x.bugOut ? "\n      " + out(x.bugOut) : "") + "\n    </div>\n" +
        '    <div class="reveal">\n      <span class="label">✓ Fixed</span>\n      ' + code(x.fix) +
        '\n      <div class="callout good">Why it was wrong, in a sentence.</div>\n    </div>\n  </div>';
    } else if (kind === "pick") {
      body = '  <h2>Quick Check</h2>\n  <p>The question. <span class="ask">Pick a letter.</span></p>\n  <ol class="opts stage">\n' +
        ["right", "wrong", "wrong", "wrong"].map(function (rw, n) {
          return '    <li class="' + rw + '"><span class="letter">' + "ABCD".charAt(n) + "</span><span>" +
            (rw === "right" ? "The right answer" : "A wrong answer") + '</span><span class="verdict">' + (rw === "right" ? "✓ why" : "✗") + "</span></li>";
        }).join("\n") + "\n  </ol>";
    } else if (kind === "sort") {
      body = pm
        ? '  <h2>Sort Them</h2>\n  <p>Which group does each one go in?</p>\n  <div class="tray"><span class="chip">one</span><span class="chip">two</span><span class="chip">three</span><span class="chip">four</span></div>\n' +
          '  <div class="groups reveal">\n    <div class="group"><h3>Group A</h3><span class="chip">one</span><span class="chip">three</span></div>\n' +
          '    <div class="group"><h3>Group B</h3><span class="chip">two</span><span class="chip">four</span></div>\n  </div>'
        : '  <h2>Sort Them</h2>\n  <p>Which group does each one go in?</p>\n  <div class="tray">\n    <span class="chip">one</span><span class="chip">two</span><span class="chip">three</span><span class="chip">four</span>\n  </div>\n' +
          '  <div class="cols reveal">\n    <div class="yes"><h3>✓ Group A</h3><span class="chip">one</span><span class="chip">three</span></div>\n' +
          '    <div class="no"><h3>✗ Group B</h3><span class="chip">two</span><span class="chip">four</span></div>\n  </div>';
    } else if (kind === "trace") {
      var py = SAMPLE.py.code;
      body = '  <h2>Step Through It</h2>\n  <p><span class="ask">Before each step: which line runs next?</span></p>\n' +
        '  <div class="cols wide-left">\n    ' +
        (pm ? '<pre class="code" data-lang="py" data-trace="' + esc(name) + '">' : '<pre class="py" data-trace="' + esc(name) + '">') + esc(py) + "</pre>\n    " +
        (pm ? '<div class="tracer" data-for="' + esc(name) + '"></div>' : '<div class="tracer" id="panel-' + esc(name) + '"></div>') + "\n  </div>";
    } else {
      body = "  <h2>A Heading</h2>\n  <ul>\n    <li>One point</li>\n    <li>Another point</li>\n  </ul>";
    }
    var cls = pm ? "slide " + (kind === "text" || kind === "step" || kind === "trace" ? "step" : "quiz") : "slide";
    return pm ? '<section class="' + cls + '"><div class="inner">\n' + body + "\n</div></section>"
              : '<section class="' + cls + '">\n' + body + "\n</section>";
  }

  /* A trace name not used yet: trace1, trace2, … */
  function freshTraceName(d, base) {
    base = (base || "trace").replace(/[^\w]/g, "") || "trace";
    var used = d.traces || {};
    var all = d.slides.map(function (s) { return s.html; }).join("\n");
    for (var k = 1; ; k++) {
      var n = base + k;
      if (!used[n] && all.indexOf('data-trace="' + n + '"') < 0) return n;
    }
  }

  /* Trace names no slide uses any more. */
  function unusedTraces(d) {
    var all = d.slides.map(function (s) { return s.html; }).join("\n");
    return Object.keys(d.traces).filter(function (n) { return all.indexOf('data-trace="' + n + '"') < 0; });
  }

  /* A slide's title for the slide list: its first heading's words. */
  function titleOf(html) {
    var m = /<h[12]\b[^>]*>([\s\S]*?)<\/h[12]>/i.exec(html);
    var t = m ? m[1].replace(/<span class="num">[\s\S]*?<\/span>/, "").replace(/<[^>]+>/g, "") : "";
    t = t.replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
    return t.replace(/\s+/g, " ").trim() || "(no heading)";
  }
  /* What's on a slide, for the list: bug, trace, how many steps. */
  function badges(html) {
    var b = [];
    if (/data-bug=/.test(html)) b.push("🐛");
    if (/data-trace=/.test(html)) b.push("▶");
    var steps = (html.match(/class="[^"]*\b(reveal|stage)\b/g) || []).length;
    if (steps) b.push(steps + (steps === 1 ? " step" : " steps"));
    return b;
  }

  /* Is this text a teacher deck? */
  function isDeck(text, path) {
    if (path && !/\.html?$/i.test(path)) return false;
    return /<div\b[^>]*\bclass\s*=\s*["'][^"']*\bdeck\b/i.test(text) && /<section\b[^>]*\bslide\b/i.test(text);
  }

  var api = { parse: parse, serialize: serialize, renumber: renumber, tracesText: tracesText, handStep: handStep,
              matchBrace: matchBrace, themeOf: themeOf, setTheme: setTheme, handThemeCSS: handThemeCSS,
              language: language, template: template, KINDS: KINDS, kindsFor: kindsFor, freshTraceName: freshTraceName,
              unusedTraces: unusedTraces, titleOf: titleOf, badges: badges, isDeck: isDeck, esc: esc };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PMDeckFile = api;
})(this);
