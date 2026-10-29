/* PresMaker — teacher slides: a student lesson turned into the deck a
 * teacher projects while the class watches and calls out answers.
 *
 * Two halves. model() reads the lesson's markdown into a list of slides and
 * needs no page — notes.js's own slides(), parseQuiz() and parseCards() do
 * the reading, so a question means here what it means in the IDEs — and
 * tools/test_teacher.mjs runs it in node. build() draws that list as one
 * .html file with web/teacher/deck.css and deck.js inside it.
 *
 * What changes on the way:
 *   - tests, "Type this" / "Check my work" instructions, checklists and the
 *     final coding exercise go: they're for students at their computers.
 *   - an example's expected output (the ```text after its code) is hidden
 *     until the teacher reveals it, so the class predicts it first.
 *   - each question becomes something to call out: multiple choice and
 *     sort are revealed with the answers marked, a bug question highlights
 *     its line, a blank or a short answer fills in, a predict question's
 *     output is hidden (the real output, when Python can be run).
 *   - the code examples the teacher picks get a step-through trace, made by
 *     running the lesson's Python (web/teacher/trace.py, through the app).
 *   - the cards become a Words to Know grid, and a Recap closes the deck.
 */
(function (root) {
  "use strict";

  var FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  var LANGS = { python: "py", py: "py", html: "html", css: "css", js: "js", javascript: "js" };
  var OUTPUT = { text: 1, output: 1, console: 1, txt: 1 };

  function lines(s) { return String(s || "").replace(/\r\n?/g, "\n").split("\n"); }

  // ------------------------------------------------------------- reading
  /* A slide as items: {type: "md", text}, {type: "fence", info, words, body},
     {type: "pop", items}. Part breaks (...) and pauses (^) are dropped — a
     teacher's deck isn't typed out — and a pop left open ends at the next
     part break, as in notes.js. */
  function items(md) {
    var ls = lines(md), out = [], stack = [out], text = [];
    function top() { return stack[stack.length - 1]; }
    function flush() {
      var t = text.join("\n");
      if (t.trim()) top().push({ type: "md", text: t });
      text = [];
    }
    for (var i = 0; i < ls.length; i++) {
      var ln = ls[i], f = FENCE.exec(ln);
      if (f) {
        flush();
        var mark = f[1], words = f[2].trim().toLowerCase().split(/\s+/).filter(Boolean), body = [];
        for (i = i + 1; i < ls.length; i++) {
          var g = FENCE.exec(ls[i]);
          if (g && g[1][0] === mark[0] && g[1].length >= mark.length && !g[2].trim()) break;
          body.push(ls[i]);
        }
        top().push({ type: "fence", info: words[0] || "", words: words, body: body.join("\n") });
        continue;
      }
      if (/^ {0,3}:::\s*pop\s*$/i.test(ln)) {
        flush();
        var pop = { type: "pop", items: [] };
        top().push(pop);
        stack.push(pop.items);
        continue;
      }
      if (/^ {0,3}:::\s*$/.test(ln) && stack.length > 1) { flush(); stack.pop(); continue; }
      if (/^ {0,3}\.\.\.\s*$/.test(ln)) { flush(); stack.length = 1; continue; }
      if (/^\s*\^+\s*$/.test(ln)) continue;
      text.push(ln);
    }
    flush();
    return out;
  }

  // Lines that are instructions for a student at a computer.
  var DROP_LINE = [
    /^\s*\**\s*expected output\s*:?\s*\**\s*:?\s*$/i,
    /^\s*[-*+] \[[ xX]\]\s/,
    /check my work/i,
    /^\s*click a card to flip it\.?\s*$/i,
    /^\s*(✏\s*)?\**\s*type (this|these)\b/i
  ];
  function cleanText(t) {
    return lines(t).filter(function (l) {
      return !DROP_LINE.some(function (r) { return r.test(l); });
    }).map(function (l) {
      return /`/.test(l) ? l : l.replace(/(^|\s)\^+(?=\s|$)/g, "$1");
    }).join("\n");
  }

  /* A pop is kept (as a callout) unless it's a typing instruction — "✏ Type
     this", "✏ Start it with:", "✔ Press Check my work" — whose code, if
     any, follows it on its own. "✏ Your turn: …" describes the task, and stays. */
  function keepPop(pop) {
    var t = pop.items.filter(function (x) { return x.type === "md"; })
      .map(function (x) { return x.text; }).join(" ").replace(/[*_`]/g, "");
    if (/check my work/i.test(t)) return false;
    return !/^\s*✏?\s*(type|replace|now add|add these|start it|change|copy)\b/i.test(t);
  }

  function firstLine(its) {
    for (var k = 0; k < its.length; k++) {
      if (its[k].type !== "md") return null;
      var ls = lines(its[k].text);
      for (var j = 0; j < ls.length; j++) if (ls[j].trim()) return { item: its[k], index: j, text: ls[j].trim() };
    }
    return null;
  }
  // The slide's heading, when it's the first thing on it; taken off the text.
  function takeHeading(its) {
    var f = firstLine(its), m = f && f.text.match(/^(#{1,3})\s+(.*?)\s*#*\s*$/);
    if (!m) return null;
    var ls = lines(f.item.text);
    ls.splice(f.index, 1);
    f.item.text = ls.join("\n");
    return { level: m[1].length, text: m[2] };
  }

  function parts(its, ctx) {
    var out = [];
    its.forEach(function (it) {
      if (it.type === "md") {
        var t = cleanText(it.text);
        if (t.trim()) out.push({ t: "md", text: t });
      } else if (it.type === "pop") {
        if (!keepPop(it)) return;
        var inner = parts(it.items, ctx);
        if (inner.length) out.push({ t: "callout", parts: inner });
      } else if (OUTPUT[it.info]) {
        // the expected output of the latest example on the slide still without one
        for (var k = out.length - 1; k >= 0; k--) {
          if (out[k].t === "code" && out[k].output === null && out[k].lang !== "html") { out[k].output = it.body; return; }
        }
        out.push({ t: "out", text: it.body });
      } else if (it.info !== "tests" && it.info !== "quiz" && it.info !== "cards") {
        var mode = it.words[1] === "run" || it.words[1] === "predict" ? it.words[1] : "";
        var part = { t: "code", lang: LANGS[it.info] || "", mode: mode, code: it.body, output: null };
        if (part.lang === "py") {
          // Students type every step into one main.py: a step's code runs
          // after the steps before it. `python run` examples stand alone.
          part.id = "ex" + (++ctx.n);
          part.prefix = mode ? "" : ctx.prefix.join("\n\n");
          if (!mode) ctx.prefix.push(it.body);
          ctx.examples.push(part);
        }
        out.push(part);
      }
    });
    return out;
  }

  /* A lesson slide with two examples is two slides here: projected, each
     example needs the room. The words after an example stay with it. */
  function hasCode(p) { return p.t === "code" || (p.parts || []).some(hasCode); }
  function splitAtCode(ps) {
    var groups = [[]], seen = false;
    ps.forEach(function (p) {
      if (hasCode(p) && seen) groups.push([]);
      if (hasCode(p)) seen = true;
      groups[groups.length - 1].push(p);
    });
    return groups;
  }

  function each(ps, fn) {
    ps.forEach(function (p) { fn(p); if (p.parts) each(p.parts, fn); });
  }

  /* {theme, title, slides: [...], examples: [python code parts]}. Slide kinds:
     title, words, step, divider, quiz, recap. */
  function model(md, Notes) {
    Notes = Notes || root.PyIDENotes;
    var head = Notes.takeHeader(md);
    var cut = Notes.slides(md);
    if (!cut.length) cut = [head.body];
    var out = { theme: head.theme, title: "", slides: [], examples: [] };
    var ctx = { n: 0, prefix: [], examples: out.examples };
    cut.forEach(function (raw, i) {
      var its = items(raw);
      var heading = takeHeading(its);
      var quizzes = [], cards = null, rest = [];
      its.forEach(function (it) {
        if (it.type === "fence" && it.info === "quiz") quizzes.push(it);
        else if (it.type === "fence" && it.info === "cards") cards = it;
        else if (!(it.type === "fence" && it.info === "tests")) rest.push(it);
      });
      var slide = null;
      if (i === 0) {
        out.title = heading ? heading.text : "";
        slide = { kind: "title", title: out.title, parts: parts(rest, ctx) };
      } else if (heading && /^✏/.test(heading.text) && /exercise|continued|check it/i.test(heading.text)) {
        return;                                  // the coding exercise is the students' work
      } else if (cards) {
        slide = { kind: "words", heading: heading ? heading.text : "Words to Know", cards: Notes.parseCards(cards.body) };
      } else {
        var first = firstLine(rest);
        var ps = parts(rest, ctx);
        if (!heading && first && /^[A-Z][A-Z0-9 '’!?-]{2,}$/.test(first.text)) {
          ps = parts(rest.map(function (it) {
            return it === first.item ? { type: "md", text: lines(it.text).slice(first.index + 1).join("\n") } : it;
          }), { n: 0, prefix: [], examples: [] });
          slide = { kind: "divider", label: first.text, parts: ps };
        } else if (heading || ps.length) {
          var step = heading && heading.text.match(/^step\s+(\d+)\s*[—–:-]\s*(.*)$/i);
          slide = { kind: "step", heading: step ? step[2] : heading ? heading.text : "",
                    num: step ? step[1] : "", parts: ps };
        }
      }
      var made = !slide ? [] : slide.kind !== "step" ? [slide] : splitAtCode(slide.parts).map(function (g, k) {
        return { kind: "step", heading: slide.heading + (k ? " (continued)" : ""), num: slide.num, parts: g, continued: k > 0 };
      });
      made.forEach(function (s) {
        out.slides.push(s);
        if (s.parts) each(s.parts, function (p) { if (p.id) p.slide = out.slides.length; });
      });
      quizzes.forEach(function (q) {
        var parsed = Notes.parseQuiz(q.body);
        if (parsed.kind !== "long") out.slides.push({ kind: "quiz", q: parsed });
      });
    });
    var titles = out.slides.filter(function (s) { return s.kind === "step" && s.num && !s.continued; }).map(function (s) { return s.heading; });
    if (titles.length >= 2) out.slides.push({ kind: "recap", items: titles, title: out.title });
    return out;
  }

  /* The examples a trace can be made of, for the export dialog. */
  function examples(md, Notes) {
    Notes = Notes || root.PyIDENotes;
    return model(md, Notes).examples.map(function (ex) {
      var first = lines(ex.code).filter(function (l) { return l.trim(); })[0] || "";
      return { id: ex.id, slide: ex.slide, line: first.trim(), lines: lines(ex.code).length,
               input: /\binput\s*\(/.test(ex.code) };
    });
  }

  // ------------------------------------------------------------- drawing
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function mdHTML(text) {
    return window.DOMPurify.sanitize(window.marked.parse(String(text), { breaks: true }));
  }
  function inlineHTML(text) {
    return window.DOMPurify.sanitize(window.marked.parseInline(String(text)));
  }
  function pre(code, lang, extra) {
    return '<pre class="code' + (extra && extra.cls ? " " + extra.cls : "") + '" data-lang="' + (lang || "") + '"' +
      (extra && extra.attrs ? " " + extra.attrs : "") + ">" + esc(code) + "</pre>";
  }
  function outPre(text, hidden) {
    return '<pre class="out' + (hidden ? " reveal" : "") + '">' + esc(String(text).replace(/\n$/, "")) + "</pre>";
  }
  // An HTML example, drawn as the browser would draw it.
  function previewFrame(code) {
    var doc = "<!doctype html><html><head><meta charset=\"utf-8\"><style>body{font-family:Arial,sans-serif;margin:12px;font-size:18px}" +
      "label{display:block;margin-top:8px}</style></head><body>" + code + "</body></html>";
    return '<div class="preview"><iframe sandbox="allow-scripts allow-same-origin" srcdoc="' + esc(doc) + '" title="The example in a browser"></iframe></div>';
  }

  function drawParts(ps, traces) {
    return ps.map(function (p) {
      if (p.t === "md") return '<div class="md">' + mdHTML(p.text) + "</div>";
      if (p.t === "callout") return '<div class="callout">' + drawParts(p.parts, traces) + "</div>";
      if (p.t === "out") return outPre(p.text, true);
      if (p.t !== "code") return "";
      if (p.id && traces[p.id]) {
        return '<div class="cols wide-left">' + pre(p.code, "py", { attrs: 'data-trace="' + p.id + '"' }) +
          '<div class="tracer" data-for="' + p.id + '"></div></div>';
      }
      if (p.lang === "html") return '<div class="cols html-row">' + pre(p.code, "html") + previewFrame(p.code) + "</div>";
      return pre(p.code, p.lang) + (p.output !== null && p.output !== undefined ? outPre(p.output, true) : "");
    }).join("\n");
  }

  /* A question's prompt: its words, and its code (~~~python …). Blanks
     ([[answer|other]]) become a ? each that fills in, in order. */
  function drawPrompt(prompt, opts) {
    var blanks = [], k = 0;
    function cutBlanks(s, inCode) {
      return s.replace(/\[\[([^\[\]\n]*)\]\]/g, function (_, b) {
        blanks.push(b.split("|")[0].trim());
        var n = k++;
        return inCode ? "\u0001" + n + "\u0002" : "%%BLANK" + n + "%%";
      });
    }
    var html = items(prompt).map(function (it) {
      if (it.type === "md") {
        var h = mdHTML(cutBlanks(it.text, false));
        return '<div class="md">' + h.replace(/%%BLANK(\d+)%%/g, function (_, n) {
          return '<span class="ans stage" data-a="' + esc(blanks[+n]) + '"></span>';
        }) + "</div>";
      }
      if (it.type !== "fence") return "";
      var start = blanks.length, code = opts && opts.blanks ? cutBlanks(it.body, true) : it.body;
      var attrs = blanks.length > start ? "data-blanks='" + esc(JSON.stringify(blanks)) + "'" : "";
      if (opts && opts.bug) return pre(code, LANGS[it.info] || "", { cls: "stage", attrs: 'data-bug="' + opts.bug + '"' });
      return pre(code, LANGS[it.info] || "", { attrs: attrs });
    }).join("\n");
    return html;
  }

  var QUIZ_TITLES = { bug: "🐛 Spot the Bug", predict: "🤔 Predict", match: "Match Them Up",
                      order: "Put It in Order", sort: "Sort Them", choice: "Quick Check", text: "Quick Check", blank: "Fill It In" };

  function drawQuiz(q, ran) {
    var h = "<h2>" + QUIZ_TITLES[q.kind] + "</h2>";
    if (q.kind === "choice") {
      h += drawPrompt(q.prompt) + '<p class="ask">Pick a letter. Then press → to check.</p><ol class="opts stage">' +
        q.choices.map(function (c, n) {
          var right = q.correct.indexOf(c) >= 0;
          return '<li class="' + (right ? "right" : "wrong") + '"><span class="letter">' + String.fromCharCode(65 + n) +
            '</span><span class="txt">' + inlineHTML(c) + '</span><span class="verdict">' + (right ? "✓" : "✗") + "</span></li>";
        }).join("") + "</ol>";
    } else if (q.kind === "text") {
      h += drawPrompt(q.prompt) + '<div class="callout">Answer: <span class="ans stage" data-a="' + esc(q.answers[0] || "") + '"></span></div>';
    } else if (q.kind === "blank") {
      h += drawPrompt(q.prompt, { blanks: true });
    } else if (q.kind === "match") {
      var extra = q.options.filter(function (o) { return q.correct.indexOf(o) < 0; });
      h += drawPrompt(q.prompt) + '<table class="match stage">' + q.choices.map(function (l, n) {
        return "<tr><td>" + inlineHTML(l) + '</td><td class="hid"><span>' + inlineHTML(q.correct[n] || "") + "</span></td></tr>";
      }).join("") + "</table>" +
        (extra.length ? '<p class="sub">Also on the list: ' + extra.map(inlineHTML).join(", ") + "</p>" : "");
    } else if (q.kind === "order") {
      var lang = LANGS[(q.prompt.match(/^ {0,3}(?:`{3,}|~{3,})\s*(\w+)/m) || [])[1]] || "py";
      h += drawPrompt(q.prompt) + '<div class="cols"><div><span class="label">Mixed up</span>' + pre(q.choices.join("\n"), lang) +
        '</div><div class="reveal"><span class="label">In order</span>' + pre(q.correct.join("\n"), lang) + "</div></div>";
    } else if (q.kind === "sort") {
      h += drawPrompt(q.prompt) + '<div class="tray">' + q.choices.map(function (c) {
        return '<span class="chip">' + inlineHTML(c) + "</span>";
      }).join("") + '</div><div class="groups reveal">' + q.answers.map(function (g) {
        return '<div class="group"><h3>' + inlineHTML(g) + "</h3>" + q.choices.filter(function (_, n) { return q.correct[n] === g; })
          .map(function (c) { return '<span class="chip">' + inlineHTML(c) + "</span>"; }).join("") + "</div>";
      }).join("") + "</div>";
    } else if (q.kind === "bug") {
      // "Click the line" is for the IDE; here the class calls it out
      h += drawPrompt(q.prompt.replace(/\s*click (on )?the (line|bug)[^.!?\n]*[.!?]?/i, ""), { bug: q.correct[0] || "" }) + '<p class="ask">Which line is wrong? Call out the number.</p>';
    } else if (q.kind === "predict") {
      var out = ran !== undefined ? ran : (q.answers[0] || "");
      h += drawPrompt(q.prompt) + outPre(out, true);
    }
    return h;
  }

  function drawSlide(s, traces, ran) {
    var body;
    if (s.kind === "title") body = "<h1>" + inlineHTML(s.title) + "</h1>" + drawParts(s.parts, traces);
    else if (s.kind === "words") {
      body = "<h2>" + inlineHTML(s.heading) + '</h2><div class="cards">' + s.cards.map(function (c) {
        return "<div class=\"card\"><b>" + inlineHTML(c.front) + "</b><span>" + inlineHTML(c.back) + "</span></div>";
      }).join("") + "</div>";
    } else if (s.kind === "divider") body = '<p class="label">' + esc(s.label) + "</p>" + drawParts(s.parts, traces);
    else if (s.kind === "step") {
      body = (s.heading ? "<h2>" + (s.num ? '<span class="num">' + esc(s.num) + "</span>" : "") + inlineHTML(s.heading) + "</h2>" : "") +
        drawParts(s.parts, traces);
    } else if (s.kind === "quiz") body = drawQuiz(s.q, ran);
    else if (s.kind === "recap") {
      body = "<h2>Recap</h2><ul>" + s.items.map(function (t) { return "<li>" + inlineHTML(t) + "</li>"; }).join("") + "</ul>" +
        '<div class="callout">Next: open <b>' + inlineHTML(s.title || "the lesson") + "</b> in the IDE and build it step by step.</div>";
    }
    return '<section class="slide ' + s.kind + '"><div class="inner">' + body + "</div></section>";
  }

  /* The lesson theme's colours, read off a slide drawn in it here — the
     IDEs' style.css (and a made theme's CSS) is already in this page. */
  var PLAIN = { bg: "radial-gradient(ellipse at 85% 10%,#2c1d44 0,transparent 55%),radial-gradient(ellipse at 10% 95%,#2a1608 0,transparent 50%),#14101c",
                solid: "#14101c", ink: "#f3eefb", muted: "#b7aacb", accent: "#ff8a1f", accent2: "#c39bff",
                panel: "#211a2e", line: "#3a2f52", dark: true, head: "Nunito, system-ui, sans-serif" };
  function themeVars(theme) {
    if (!theme) return PLAIN;
    var box = document.createElement("div");
    box.className = "notes-body prose pm-slide slide-themed slide-theme-" + theme;
    var h1 = document.createElement("h1");
    h1.textContent = "Title";
    box.appendChild(h1);
    document.getElementById("workbench").appendChild(box);
    var cs = getComputedStyle(box);
    function v(n, d) { return cs.getPropertyValue(n).trim() || d; }
    var t = {
      bg: v("--theme-bg", PLAIN.bg), solid: v("--nav-bg", PLAIN.solid), ink: v("--text", PLAIN.ink),
      muted: v("--muted", PLAIN.muted), accent: v("--heading", PLAIN.accent), accent2: v("--heading-2", PLAIN.accent2),
      panel: v("--bg-panel", PLAIN.panel), line: v("--line", PLAIN.line),
      dark: !/light/.test(cs.colorScheme || "") || /dark/.test(cs.colorScheme || ""),
      head: getComputedStyle(h1).fontFamily || PLAIN.head
    };
    box.remove();
    return t;
  }
  function rootCSS(t) {
    return ":root{--bg:" + t.bg + ";--bg-solid:" + t.solid + ";--ink:" + t.ink + ";--muted:" + t.muted +
      ";--accent:" + t.accent + ";--accent2:" + t.accent2 + ";--panel:" + t.panel + ";--line:" + t.line +
      ";--head-font:" + t.head + ";--good:" + (t.dark ? "#8ee06b" : "#15803d") + ";--bad:" + (t.dark ? "#ff6b6b" : "#b91c1c") +
      ";--ask:" + (t.dark ? "#ffd866" : "#a16207") + ";color-scheme:" + (t.dark ? "dark" : "light") + "}";
  }

  /* opts: {traces: [example ids], title, path}. Resolves to
     {html, count, problems: ["…"]}. */
  function build(md, opts) {
    var Notes = window.PyIDENotes, B = window.PMBridge, X = window.PMExport;
    var m = model(md, Notes), traces = {}, ran = {}, problems = [];
    var wanted = (opts && opts.traces) || [];
    function py(job) {
      // Only the app can run Python; opened in a browser the call answers null.
      return B.call("python", { job: JSON.stringify(job) }).then(function (t) {
        if (typeof t !== "string") throw new Error("Python can only be run in the PresMaker app");
        return JSON.parse(t);
      });
    }
    var jobs = [];
    m.examples.forEach(function (ex) {
      if (wanted.indexOf(ex.id) >= 0) {
        jobs.push(py({ mode: "trace", code: ex.code, prefix: ex.prefix }).then(function (r) {
          if (r.steps && r.steps.length) {
            traces[ex.id] = r.steps;
            if (r.error) {
              var last = r.steps[r.steps.length - 1];
              r.steps.push({ l: last.l, note: "Python stops: <code>" + esc(r.error) + "</code>", vars: last.vars, out: last.out, skip: [] });
            }
          } else problems.push("Slide " + ex.slide + ": couldn't trace it (" + (r.error || "nothing ran") + ").");
        }, function (e) { problems.push("Slide " + ex.slide + ": couldn't trace it (" + (e.message || e) + ")."); }));
      }
      // a `python run` example has no written output: run it for one
      if (ex.mode && ex.output === null) {
        jobs.push(py({ mode: "run", code: ex.code }).then(function (r) { if (!r.error) ex.output = r.out; }, function () {}));
      }
    });
    m.slides.forEach(function (s, n) {
      if (s.kind === "quiz" && s.q.kind === "predict" && /^ {0,3}(?:`{3,}|~{3,})\s*(python|py)\b/m.test(s.q.prompt)) {
        var code = items(s.q.prompt).filter(function (it) { return it.type === "fence"; })[0];
        if (code) jobs.push(py({ mode: "run", code: code.body }).then(function (r) { if (!r.error) ran[n] = r.out; }, function () {}));
      }
    });
    var t = themeVars(m.theme);
    var fonts = "https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800&family=JetBrains+Mono:wght@400;700&display=swap";
    var themeFonts = window.PMThemes ? window.PMThemes.exportHead(m.theme).fonts : "";
    return Promise.all(jobs).then(function () {
      return Promise.all(["teacher/deck.css", "teacher/deck.js"].map(function (f) { return B.call("resource", { path: f }); }));
    }).then(function (got) {
      // Pictures beside the lesson go inside the file, as in the .html export.
      var bench = document.getElementById("workbench");
      var holder = document.createElement("div");
      holder.innerHTML = m.slides.map(function (s, n) { return drawSlide(s, traces, ran[n]); }).join("\n");
      Array.prototype.forEach.call(holder.querySelectorAll("iframe"), function (f) { f.setAttribute("data-srcdoc", f.getAttribute("srcdoc")); f.removeAttribute("srcdoc"); });
      bench.appendChild(holder);
      X.fixImages(holder, opts && opts.path);
      return (X.inlineImages ? X.inlineImages(holder) : Promise.resolve()).then(function () {
        Array.prototype.forEach.call(holder.querySelectorAll("iframe"), function (f) { f.setAttribute("srcdoc", f.getAttribute("data-srcdoc")); f.removeAttribute("data-srcdoc"); });
        var slidesHTML = holder.innerHTML;
        holder.remove();
        var title = (opts && opts.title) || m.title || "Teacher slides";
        var key = String(title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "deck";
        var html = "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" +
          "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
          "<title>" + esc(title) + "</title>\n" +
          '<link rel="stylesheet" href="' + esc(fonts) + '">\n' +
          (themeFonts ? '<link rel="stylesheet" href="' + esc(themeFonts) + '">\n' : "") +
          "<style>\n" + rootCSS(t) + "\n" + got[0] + "\n</style>\n</head>\n" +
          '<body data-key="' + esc(key) + '">\n<div class="deck">\n' + slidesHTML + "\n</div>\n" +
          '<script type="application/json" id="traces">' + JSON.stringify(traces).replace(/</g, "\\u003c") + "</script>\n" +
          "<script>\n" + got[1].replace(/<\/script/gi, "<\\/script") + "\n</script>\n</body>\n</html>\n";
        return { html: html, count: m.slides.length, problems: problems };
      });
    });
  }

  var api = { items: items, model: model, examples: examples, build: build, cleanText: cleanText, keepPop: keepPop,
              themeVars: themeVars, rootCSS: rootCSS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PMTeacher = api;
})(this);
