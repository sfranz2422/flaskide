/* PresMaker — the editor, the preview, and the file you're working on.
 *
 * The preview shows a slide the size it will be projected and exported —
 * 960 × 540, scaled to the pane — through pages.js, so a slide that runs
 * out of room shows that here first. The strip under it is every slide,
 * small; the editor and the preview follow each other.
 *
 * Whether the notes are slides is decided by the notes, as in the IDEs:
 * two or more slides cut by `---` lines are slides, anything else is a
 * document. The Format menu only adds or takes away the `---` lines.
 */
(function () {
  "use strict";

  var C = window.PMCompose, Notes = window.PyIDENotes, B = window.PMBridge;
  var D = window.PMDialogs, T = window.PMThemes, X = window.PMExport, P = window.PMPages;
  var DE = window.PMDeckEdit;          // teacher slides (.html) opened to change them
  var h = D.h;
  function $(id) { return document.getElementById(id); }

  var TEMPLATES = {
    slides: "# Title of the lesson\n\nWhat today is about, in a line.\n\n---\n\n## The first idea\n\n" +
            "- One point\n- Another point\n\n~~~python\nprint(\"Hello\")\n~~~\n\n---\n\n## Check your understanding\n\n" +
            "Use **+ Question** to put a question here.\n",
    doc: "# Title\n\nA document is notes with no `---` lines: it is shown whole, not as slides. " +
         "Questions and tests work the same.\n\n## A section\n\nWrite here.\n"
  };

  // ------------------------------------------------------------- state
  var file = { path: "", name: "Untitled.md", saved: "" };
  var cm = CodeMirror($("editor"), {
    value: "", mode: { name: "markdown", fencedCodeBlockHighlighting: true },
    lineWrapping: true, lineNumbers: true, tabSize: 4, indentUnit: 4, indentWithTabs: false,
    extraKeys: {
      "Enter": "newlineAndIndentContinueMarkdownList",
      "Tab": function (cm) { cm.execCommand(cm.somethingSelected() ? "indentMore" : "insertSoftTab"); },
      "Shift-Tab": "indentLess"
    }
  });

  function text() { return DE.active() ? DE.text() : cm.getValue(); }
  function dirty() { return text() !== file.saved; }

  var lastState = null;
  function tellState() {
    var s = JSON.stringify([dirty(), file.name, file.path]);
    if (s === lastState) return;
    lastState = s;
    B.call("state", { dirty: dirty(), name: file.name, path: file.path });
  }

  function load(t, path, name) {
    // Teacher slides are changed in their own editor, as the page they are.
    if (DE.isDeck(t, path)) {
      try { DE.open(t, path); } catch (e) { alert("Couldn't open it: " + (e.message || e)); return; }
      file = { path: path || "", name: name || (path ? path.split("/").pop() : "Teacher_Slides.html"), saved: t };
      document.body.classList.add("is-deck");
      lastState = null;
      tellState();
      return;
    }
    if (DE.active()) DE.close();
    document.body.classList.remove("is-deck");
    file = { path: path || "", name: name || (path ? path.split("/").pop() : "Untitled.md"), saved: t };
    cm.setValue(t);
    cm.refresh();
    cm.clearHistory();
    cm.setCursor(0, 0);
    at = 0;
    tellState();
    redraw(true);
    cm.focus();
  }

  // ----------------------------------------------------------- preview
  var stage = $("stage"), strip = $("strip");
  var at = 0;                      // the slide in the preview
  var shown = { slides: [], theme: "", body: "", isSlides: false };
  var follow = $("follow");

  function knownThemes() { return Notes.THEMES; }

  function analyse() {
    var md = text();
    var picked = Notes.takeTheme(md), head = Notes.takeHeader(md);
    var cut = Notes.slides(md);
    return { md: md, theme: picked.name, body: picked.body, slides: cut.length >= 2 ? cut : [], isSlides: cut.length >= 2,
             written: C.themeOf(md), animate: head.animate, speed: head.speed || "normal" };
  }

  /* A page (a slide's box) scaled to fit `box`, centred. */
  function scaleInto(box, page, w, hgt, pad) {
    var bw = box.clientWidth - pad * 2, bh = box.clientHeight - pad * 2;
    var k = Math.max(0.05, Math.min(bw / w, bh / hgt));
    page.style.transform = "scale(" + k + ")";
    page.parentNode.style.width = (w * k) + "px";
    page.parentNode.style.height = (hgt * k) + "px";
    return k;
  }

  function slideBox(theme) {
    var page = h("div", { class: "pm-page" });
    var slide = h("div", { class: "notes-body prose pm-slide" + (theme ? "" : " pm-plain") });
    page.appendChild(slide);
    return { page: page, slide: slide, frame: h("div", { class: "pm-frame" }, [page]) };
  }

  function finish(slide) {
    X.fixImages(slide, file.path);
    P.markTitle(slide);
    var imgs = slide.querySelectorAll("img");
    Array.prototype.forEach.call(imgs, function (img) {
      if (!img.complete) img.addEventListener("load", function () { P.fit(slide); }, { once: true });
    });
    return P.fit(slide);
  }

  var mainSeq = 0;
  function drawMain() {
    var a = shown, n = ++mainSeq;
    if (!a.isSlides) return drawDocument(n);
    at = Math.max(0, Math.min(at, a.slides.length - 1));
    var box = slideBox(a.theme);
    var drawn = a.animate ? X.renderParts(box.slide, a.slides[at], a.theme) : Notes.render(box.slide, a.slides[at], { theme: a.theme });
    return drawn.then(function () {
      if (n !== mainSeq) return;
      stage.textContent = "";
      stage.classList.remove("pm-doc");
      stage.appendChild(box.frame);
      finish(box.slide);
      previewSlide = box.slide;
      previewPlay = null;
      paintPreviewPlay();
      scaleInto(stage, box.page, X.SLIDE.w, X.SLIDE.h, 18);
      $("p-pos").textContent = (at + 1) + " / " + a.slides.length;
      $("p-prev").disabled = at <= 0;
      $("p-next").disabled = at >= a.slides.length - 1;
      markStrip();
      health();
    });
  }

  /* ▶ Play in the preview: the slide on screen played as it will be
     presented, a part a press. It's shown whole otherwise — this is where
     it's written — and whole again the moment it's redrawn. */
  var previewSlide = null, previewPlay = null;
  function paintPreviewPlay() {
    var b = $("p-play");
    b.hidden = !(shown.isSlides && shown.animate);
    if (b.hidden) return;
    var p = previewPlay;
    b.textContent = !p ? "▶ Play" : p.busy() ? "⏭ Skip" : p.more() ? "▶ Play more" : "↺ Replay";
    b.title = !p ? "Play this slide as it will be presented, a part at a time" : p.busy() ? "Show the part playing now"
      : p.more() ? "Play the next part" : "Play this slide again";
  }
  $("p-play").addEventListener("click", function () {
    if (!previewSlide) return;
    if (!previewPlay || !previewPlay.more()) {
      previewPlay = P.player(previewSlide, shown.animate, shown.speed, 0, paintPreviewPlay);
    }
    previewPlay.step();
  });

  /* A document is drawn as the sheets it will print on, the same cut
     pages.js makes for the PDF. Where the reader was is kept: redrawing
     on every keystroke would otherwise jump back to the top. */
  function drawDocument(n) {
    var a = shown;
    var flow = h("div", { class: "notes-body prose pm-flow" + (a.theme ? "" : " pm-plain") });
    var bench = $("workbench");
    var sheets = h("div", { class: "pm-sheets" });
    // Sheet size before cutting: pages are cut by measuring, and a page
    // measured at the slide default (960 × 540) ends a third of the way down.
    sheets.style.setProperty("--pm-w", X.SHEET.w + "px");
    sheets.style.setProperty("--pm-h", X.SHEET.h + "px");
    bench.appendChild(sheets);
    sheets.appendChild(flow);
    return Notes.render(flow, a.body, { theme: a.theme }).then(function () {
      if (n !== mainSeq) { sheets.remove(); return; }
      X.fixImages(flow, file.path);
      P.paginate(flow, sheets);
      var top = stage.scrollTop;
      stage.textContent = "";
      stage.classList.add("pm-doc");
      var k = Math.min(1.6, (stage.clientWidth - 40) / X.SHEET.w);
      Array.prototype.forEach.call(sheets.querySelectorAll(".pm-page"), function (p, i) {
        p.style.setProperty("--pm-w", X.SHEET.w + "px");     // it's leaving .pm-sheets
        p.style.setProperty("--pm-h", X.SHEET.h + "px");
        p.style.transform = "scale(" + k + ")";
        var frame = h("div", { class: "pm-frame pm-sheet-frame", "data-page": "Page " + (i + 1) });
        frame.style.width = X.SHEET.w * k + "px";
        frame.style.height = X.SHEET.h * k + "px";
        frame.appendChild(p);
        stage.appendChild(frame);
      });
      sheets.remove();
      stage.scrollTop = top;
      health();
    });
  }

  /* The strip: every slide small. Each is drawn once and kept until its
     text or the theme changes, so typing on slide 3 of 40 draws one. */
  var thumbs = [];           // [{key, frame, slide}]
  function drawStrip() {
    var a = shown;
    strip.hidden = !a.isSlides;
    if (!a.isSlides) { strip.textContent = ""; thumbs = []; return Promise.resolve(); }
    var jobs = [];
    var next = a.slides.map(function (s, i) {
      var key = a.theme + "\n" + s;
      var old = thumbs[i] && thumbs[i].key === key ? thumbs[i] : null;
      if (old) return old;
      var box = slideBox(a.theme);
      var t = { key: key, frame: h("button", { class: "pm-thumb", type: "button", title: "Slide " + (i + 1) }, [box.frame]),
                slide: box.slide, page: box.page };
      t.frame.addEventListener("click", function () { goSlide(next.indexOf(t), true); });
      jobs.push(Notes.render(box.slide, s, { theme: a.theme }).then(function () { t.drawn = true; }));
      return t;
    });
    thumbs = next;
    strip.textContent = "";
    thumbs.forEach(function (t, i) {
      t.frame.dataset.n = i + 1;
      t.frame.title = "Slide " + (i + 1);
      strip.appendChild(t.frame);
      t.page.style.transform = "scale(" + (150 / X.SLIDE.w) + ")";
      t.page.parentNode.style.width = "150px";
      t.page.parentNode.style.height = (150 * X.SLIDE.h / X.SLIDE.w) + "px";
    });
    return Promise.all(jobs).then(function () {
      thumbs.forEach(function (t) {
        if (t.fitted !== t.key) { finish(t.slide); t.fitted = t.key; }
      });
      markStrip();
      health();
    });
  }

  function markStrip() {
    thumbs.forEach(function (t, i) { t.frame.classList.toggle("pm-on", i === at); });
    var on = thumbs[at];
    if (on && on.frame.scrollIntoView) on.frame.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  var redrawTimer = null;
  function redraw(now) {
    clearTimeout(redrawTimer);
    if (DE.active()) return;
    redrawTimer = setTimeout(function () {
      shown = analyse();
      $("slide-nav").hidden = !shown.isSlides;
      $("follow").parentNode.hidden = !shown.isSlides;
      $("b-slide").hidden = !shown.isSlides && text().trim() !== "";
      drawMain();
      drawStrip();
      bar();
      marks();
      animateMenu();
    }, now ? 0 : 160);
  }

  function goSlide(i, moveCursor) {
    if (!shown.isSlides) return;
    at = Math.max(0, Math.min(shown.slides.length - 1, i));
    drawMain();
    if (moveCursor) {
      var line = C.slideStart(text(), at, knownThemes());
      cm.setCursor(line, 0);
      cm.scrollIntoView({ line: line, ch: 0 }, 80);
      cm.focus();
    }
  }

  cm.on("cursorActivity", function () {
    if (!shown.isSlides || !follow.checked) return;
    var where = C.slideAt(text(), cm.getCursor().line, knownThemes());
    if (where.count && where.index !== at) { at = where.index; drawMain(); }
  });
  $("p-prev").addEventListener("click", function () { goSlide(at - 1, follow.checked); });
  $("p-next").addEventListener("click", function () { goSlide(at + 1, follow.checked); });

  // Double-click a question in the preview: open it in the question form.
  stage.addEventListener("dblclick", function (e) {
    var card = e.target.closest(".quiz, .tests-card");
    if (!card) return;
    var kind = card.classList.contains("quiz") ? "quiz" : "tests";
    var cards = Array.prototype.slice.call(stage.querySelectorAll(kind === "quiz" ? ".quiz" : ".tests-card"));
    var nth = cards.indexOf(card);
    var md = text(), blocks = C.fences(md).filter(function (b) { return b.info === kind; });
    if (shown.isSlides) {
      blocks = blocks.filter(function (b) { return C.slideAt(md, b.start, knownThemes()).index === at; });
    }
    var b = blocks[nth];
    if (!b) return;
    cm.setCursor(b.start + 1, 0);
    command(kind === "quiz" ? "question" : "tests");
  });

  new ResizeObserver(function () { redraw(true); }).observe(stage);

  // ------------------------------------------------- marks in the editor
  /* Each `---` that starts a slide is labelled in the editor, and every
     question and tests block is tinted, so the shape of a deck is visible
     in its source. Worked out with the same fence rules as slides(). */
  var marked = [];
  function marks() {
    cm.operation(function () {
      marked.forEach(function (m) { cm.removeLineClass(m[0], "wrap", m[1]); });
      marked = [];
      var md = text(), lines = md.split("\n"), fence = null;
      if (shown.isSlides) {
        lines.forEach(function (ln, i) {
          var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
          if (f) {
            if (fence === null) fence = f[1];
            else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
          } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) {
            var hd = cm.addLineClass(i, "wrap", "pm-cut");
            marked.push([hd, "pm-cut"]);
          }
        });
      }
      C.fences(md).forEach(function (b) {
        if (b.info !== "quiz" && b.info !== "tests") return;
        for (var i = b.start; i <= b.end && i < lines.length; i++) {
          var cls = "pm-block pm-block-" + b.info + (i === b.start ? " pm-block-first" : "") + (i === b.end ? " pm-block-last" : "");
          marked.push([cm.addLineClass(i, "wrap", cls), cls]);
        }
      });
    });
  }

  // ---------------------------------------------------- the status bar
  function bar() {
    var a = shown, md = a.md;
    var qs = C.fences(md).filter(function (b) { return b.info === "quiz"; }).map(function (b) {
      return Notes.parseQuiz(C.blockAt(md, b.start).body);
    });
    var ts = window.PyIDETests.parse(md);
    var pts = qs.reduce(function (s, q) { return s + (q.points || 0); }, 0);
    var tpts = ts.tests.reduce(function (s, t) { return s + t.points; }, 0);
    var bits = [a.isSlides ? a.slides.length + " slides" : "Document"];
    bits.push(qs.length + (qs.length === 1 ? " question" : " questions") + (qs.length ? " (" + pts + " pts)" : ""));
    bits.push(ts.tests.length + (ts.tests.length === 1 ? " test" : " tests") + (ts.tests.length ? " (" + tpts + " pts)" : ""));
    $("status").textContent = bits.join(" · ");
    $("format").value = a.isSlides ? "slides" : "doc";
    themeMenu(a.written);
    var warn = [];
    if (ts.errors.length) warn.push(ts.errors[0]);
    if (a.written && !Notes.THEMES.length) { /* never */ }
    if (a.written && T.all().indexOf(a.written) < 0) {
      warn.push("“theme: " + a.written + "” isn't a theme — it will show on the slide as text.");
    } else if (a.written && !T.isBuiltin(a.written)) {
      warn.push("“" + a.written + "” is your own theme: the IDEs show it once it's added there (Themes… → Copy for the IDEs).");
    }
    if (C.lockedOf(md) && !ts.tests.length) {
      warn.push("Lock slides holds nothing yet: no slide has tests. Add them with + Tests.");
    }
    if (!a.isSlides && /(^|\n) {0,3}-{3,}\s*(\n|$)/.test(a.body)) {
      warn.push("A --- line in a document makes it slides in the IDEs once there's a second slide.");
    }
    warnings.base = warn;
    showNotice();
  }

  var warnings = { base: [], fit: [] };
  function health() {
    var long = [], over = [];
    thumbs.forEach(function (t, i) {
      if (t.slide.classList.contains("pm-overfull")) over.push(i + 1);
      else if (t.slide.classList.contains("pm-shrunk")) long.push(i + 1);
    });
    var w = [];
    if (over.length) w.push("Slide " + over.join(", ") + (over.length > 1 ? " don't" : " doesn't") + " fit even with smaller text — split it with a ---.");
    if (long.length) w.push("Slide " + long.join(", ") + ": smaller text, to fit the screen.");
    warnings.fit = w;
    showNotice();
  }

  var flash = null;
  function showNotice() {
    var n = $("notice");
    n.textContent = "";
    if (flash) { n.appendChild(flash); return; }
    var all = warnings.base.concat(warnings.fit);
    n.className = all.length ? "pm-warn" : "";
    n.textContent = all.join("  ·  ");
    n.title = all.join("\n");
  }

  /* A message for a few seconds, with buttons if given (Show in Finder). */
  function say(message, buttons) {
    flash = h("span", { class: "pm-flash" }, [message].concat((buttons || []).map(function (b) {
      return h("button", { class: "linkbtn", type: "button", text: b[0], onclick: b[1] });
    })));
    showNotice();
    clearTimeout(say.timer);
    say.timer = setTimeout(function () { flash = null; showNotice(); }, buttons ? 12000 : 5000);
  }

  // -------------------------------------------------------- the theme menu
  var themeSel = $("theme"), themeDrawn = null;
  function themeMenu(current) {
    var key = current + "|" + T.all().join(",");
    if (key === themeDrawn) return;
    themeDrawn = key;
    themeSel.textContent = "";
    themeSel.appendChild(h("option", { value: "", text: "None" }));
    var g1 = h("optgroup", { label: "Built in" });
    T.builtin().forEach(function (n) { g1.appendChild(h("option", { value: n, text: n })); });
    themeSel.appendChild(g1);
    var mine = T.made();
    if (mine.length) {
      var g2 = h("optgroup", { label: "Yours (PresMaker)" });
      mine.forEach(function (t) { g2.appendChild(h("option", { value: t.name, text: t.name + " ★" })); });
      themeSel.appendChild(g2);
    }
    if (current && T.all().indexOf(current) < 0) {
      themeSel.appendChild(h("option", { value: current, text: current + " (unknown)" }));
    }
    themeSel.value = current;
  }
  themeSel.addEventListener("change", function () { useTheme(themeSel.value); });

  /* Sets the deck's theme line, as one edit (so ⌘Z takes it back). */
  function useTheme(name) {
    var md = text(), next = C.setTheme(md, name);
    if (next === md) return;
    // Only the top of the file changes: replace just that much.
    var a = 0;
    while (a < md.length && a < next.length && md.charAt(a) === next.charAt(a)) a++;
    var b = 0;
    while (b < md.length - a && b < next.length - a && md.charAt(md.length - 1 - b) === next.charAt(next.length - 1 - b)) b++;
    cm.replaceRange(next.slice(a, next.length - b), cm.posFromIndex(a), cm.posFromIndex(md.length - b), "+theme");
    themeDrawn = null;
  }
  T.onChange(function () { themeDrawn = null; thumbs = []; redraw(true); if (DE.active()) DE.themes(); });

  // ------------------------------------------------- playing (animate:)
  /* The Animate menu writes the `animate:` line (compose.js setAnimate),
     the speed only when it isn't normal — what the IDEs read. */
  var animSel = $("animate"), speedSel = $("speed");
  function animateMenu() {
    animSel.value = shown.animate || "";
    speedSel.value = shown.speed || "normal";
    speedSel.hidden = !shown.animate;
    lockedBox.checked = C.lockedOf(shown.md);
  }
  /* Puts new notes in place of the old as one edit (⌘Z takes it back),
     touching only the part that changed — the header lines at the top. */
  function replaceText(next, origin) {
    var md = text();
    if (next === md) return false;
    var a = 0;
    while (a < md.length && a < next.length && md.charAt(a) === next.charAt(a)) a++;
    var b = 0;
    while (b < md.length - a && b < next.length - a && md.charAt(md.length - 1 - b) === next.charAt(next.length - 1 - b)) b++;
    cm.replaceRange(next.slice(a, next.length - b), cm.posFromIndex(a), cm.posFromIndex(md.length - b), origin);
    return true;
  }
  /* Lock slides: the `locked: yes` line (compose.js setLocked). It does
     nothing here — PresMaker has no code to check — but in the IDEs a slide
     with tests holds students until they all pass. */
  var lockedBox = $("locked");
  lockedBox.addEventListener("change", function () {
    if (replaceText(C.setLocked(text(), lockedBox.checked), "+locked") && lockedBox.checked) {
      say("In the IDEs, each slide with tests now waits until they all pass. Add tests with + Tests.");
    }
  });

  function useAnimate() {
    var how = animSel.value, sp = speedSel.value;
    var md = text(), next = C.setAnimate(md, how ? how + (sp && sp !== "normal" ? " " + sp : "") : "");
    if (next === md) return;
    var a = 0;
    while (a < md.length && a < next.length && md.charAt(a) === next.charAt(a)) a++;
    var b = 0;
    while (b < md.length - a && b < next.length - a && md.charAt(md.length - 1 - b) === next.charAt(next.length - 1 - b)) b++;
    cm.replaceRange(next.slice(a, next.length - b), cm.posFromIndex(a), cm.posFromIndex(md.length - b), "+animate");
    if (how) say("Each slide now plays a part at a time when presented. Divide a slide with + Part (…); ^ pauses; Pop makes a box.");
  }
  animSel.addEventListener("change", useAnimate);
  speedSel.addEventListener("change", useAnimate);

  // ------------------------------------------------- inserting (Insert ▾)
  function lineInsert(lines, selectFrom, selectLen) {
    var cur = cm.getCursor(), line = cm.getLine(cur.line);
    var pos = line.trim() ? { line: cur.line, ch: line.length } : { line: cur.line, ch: 0 };
    var before = cur.line > 0 ? cm.getLine(cur.line - 1) : "";
    var lead = line.trim() ? "\n\n" : before.trim() ? "\n" : "";
    cm.replaceRange(lead + lines + "\n", pos);
    var start = pos.line + (lead.match(/\n/g) || []).length;
    if (selectFrom !== undefined) {
      cm.setSelection({ line: start + selectFrom, ch: 0 }, { line: start + selectFrom, ch: selectLen });
    } else {
      cm.setCursor({ line: start + lines.split("\n").length, ch: 0 });
    }
    cm.focus();
  }
  function insertPart() { lineInsert("...\n"); }
  function insertPause() {
    var cur = cm.getCursor(), line = cm.getLine(cur.line);
    var left = line.slice(0, cur.ch), right = line.slice(cur.ch);
    cm.replaceRange((left && !/\s$/.test(left) ? " " : "") + "^" + (right && !/^\s/.test(right) ? " " : ""), cur);
    cm.focus();
  }
  function insertPop() {
    if (cm.somethingSelected()) {
      var from = cm.getCursor("from"), to = cm.getCursor("to");
      var last = to.ch === 0 && to.line > from.line ? to.line - 1 : to.line;
      cm.operation(function () {
        cm.replaceRange("\n:::", { line: last, ch: cm.getLine(last).length });
        cm.replaceRange(":::pop\n", { line: from.line, ch: 0 });
      });
      cm.focus();
      return;
    }
    lineInsert(":::pop\nWhat should stand out.\n:::", 1, "What should stand out.".length);
  }
  var SNIPPETS = {
    cards: "```cards\nloop -> code that runs more than once\nvariable -> a name for a value\n```",
    checklist: "- [ ] Read the notes\n- [ ] Try the example\n- [ ] Turn it in",
    "run-code": "```python run\nfor i in range(3):\n    print(\"Hello\", i)\n```",
    "predict-code": "```python predict\nfor i in range(3):\n    print(i * 2)\n```"
  };

  // ------------------------------------------------------- the format
  $("format").addEventListener("change", function () {
    var want = $("format").value;
    if (want === "slides" && !shown.isSlides) {
      newSlide();
      say("Slides start at each --- line. Add more with + Slide (⌘↩).");
    } else if (want === "doc" && shown.isSlides) {
      var md = text(), lines = md.split("\n"), fence = null, cuts = [];
      lines.forEach(function (ln, i) {
        var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
        if (f) {
          if (fence === null) fence = f[1];
          else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
        } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) cuts.push(i);
      });
      $("format").value = "slides";
      D.choice("Make it a document?", "That takes out the " + cuts.length + " --- lines between the slides, so the notes are shown whole. Everything else stays. (⌘Z puts them back.)", [
        { label: "Cancel" },
        { label: "Make it a document", primary: true, action: function () {
          cm.operation(function () {
            for (var k = cuts.length - 1; k >= 0; k--) {
              var i = cuts[k];
              cm.replaceRange("", { line: i, ch: 0 }, i + 1 < cm.lineCount() ? { line: i + 1, ch: 0 } : { line: i, ch: lines[i].length });
            }
          });
        } }
      ]);
    }
  });

  function newSlide() {
    var cur = cm.getCursor(), line = cm.getLine(cur.line);
    var insert = (line.trim() ? "\n" : "") + "\n---\n\n";
    var pos = line.trim() ? { line: cur.line, ch: line.length } : cur;
    cm.replaceRange(insert, pos);
    cm.setCursor({ line: pos.line + (line.trim() ? 4 : 3), ch: 0 });
    cm.focus();
  }

  /* A block (question or tests) put in on lines of its own, with a blank
     line either side — or in place of the block it came from. */
  function putBlock(block, existing) {
    if (existing) {
      var endLine = existing.end, endCh = cm.getLine(endLine).length;
      cm.replaceRange(block, { line: existing.start, ch: 0 }, { line: endLine, ch: endCh });
      cm.setCursor({ line: existing.start, ch: 0 });
    } else {
      var cur = cm.getCursor(), line = cm.getLine(cur.line);
      var before = cur.line > 0 ? cm.getLine(cur.line - 1) : "";
      var pos, insert;
      if (line.trim()) {
        pos = { line: cur.line, ch: line.length };
        insert = "\n\n" + block + "\n";
      } else {
        pos = { line: cur.line, ch: 0 };
        insert = (before.trim() ? "\n" : "") + block + "\n";
      }
      cm.replaceRange(insert, pos);
    }
    cm.focus();
  }

  // ------------------------------------------------------------ files
  function save(as) {
    if (DE.active()) DE.flush();
    var t = text();
    return B.call("save", { text: t, path: as ? "" : file.path, suggested: file.name,
                            ext: DE.active() ? "html" : "md" }).then(function (r) {
      if (!r) return false;
      if (r.path) file.path = r.path;
      file.name = r.name || file.name;
      file.saved = t;
      lastState = null;
      tellState();
      B.call("recovery.clear");
      say("Saved " + file.name);
      return true;
    }).catch(function (e) { alert("Couldn't save: " + (e.message || e)); return false; });
  }

  function guarded(then) {
    if (DE.active()) DE.flush();
    if (!dirty()) return then();
    D.unsaved(function (saveFirst) {
      if (!saveFirst) { B.call("recovery.clear"); then(); return; }
      save(false).then(function (ok) { if (ok) then(); });
    });
  }

  function openFile() {
    guarded(function () {
      B.call("open").then(function (r) { if (r) { load(r.text, r.path, r.name); B.call("recovery.clear"); } })
        .catch(function (e) { alert("Couldn't open it: " + (e.message || e)); });
    });
  }

  // Unsaved work is copied out every few seconds, so a crash or a closed
  // laptop lid doesn't lose a lesson; it's offered back on the next start.
  var recoverTimer = null;
  function keepSafe() {
    clearTimeout(recoverTimer);
    recoverTimer = setTimeout(function () {
      if (dirty()) B.call("recovery.save", { text: text(), path: file.path, name: file.name });
    }, 2500);
  }
  cm.on("changes", function () {
    if (DE.active()) return;
    tellState();
    redraw(false);
    keepSafe();
  });
  DE.init({
    onChange: function () { tellState(); keepSafe(); },
    status: function (t) { $("status").textContent = t; },
    command: function (name) { command(name); }
  });

  // ---------------------------------------------------------- export
  function baseName() { return file.name.replace(/\.(md|markdown|txt|html?)$/i, ""); }

  function counts() {
    var md = text();
    var bl = C.fences(md);
    return { questions: bl.filter(function (b) { return b.info === "quiz"; }).length,
             tests: window.PyIDETests.parse(md).tests.length,
             slides: shown.isSlides, count: shown.slides.length,
             examples: shown.isSlides ? window.PMTeacher.examples(md) : [] };
  }

  function suffix(o) {
    if (o.questions && o.answers) return " (answer key)";
    if (!o.questions && !o.tests) return " (display)";
    if (!o.questions) return " (no questions)";
    if (!o.tests) return " (no tests)";
    return "";
  }

  function doExport(o, out) {
    if (o.format === "teacher") return teacherExport(o, out);
    var name = baseName() + suffix(o);
    var info = counts();
    if (!info.questions) o.questions = true;   // nothing to leave out
    if (!info.tests) o.tests = true;
    if (o.format === "md") {
      var md = C.strip(text(), { questions: !o.questions, tests: !o.tests });
      return B.call("export", { text: md, ext: "md", suggested: name + ".md", out: out }).then(done);
    }
    say("Exporting…");
    return X.build(text(), { questions: o.questions, tests: o.tests, answers: o.answers,
                             mode: o.format === "pdf" ? "pdf" : "viewer", inline: o.format === "html",
                             path: file.path, title: baseName() })
      .then(function (r) {
        if (o.format === "pdf") {
          return B.call("pdf", { html: r.html, width: r.width, height: r.height, suggested: name + ".pdf", out: out });
        }
        return B.call("export", { text: r.html, ext: "html", suggested: name + ".html", out: out });
      }).then(done).catch(function (e) {
        flash = null;
        alert("The export didn't work: " + (e.message || e));
        throw e;
      });
    function done(r) {
      if (!r || !r.path) { flash = null; showNotice(); return r; }
      say("Exported " + r.path.split("/").pop() + " ", [
        ["Open", function () { B.call("openFile", { path: r.path }); }],
        ["Show in Finder", function () { B.call("reveal", { path: r.path }); }]
      ]);
      return r;
    }
  }

  /* Teacher slides: the lesson made into a deck for the projector
     (teacher.js). Named as the lessons repo names them. */
  function teacherExport(o, out) {
    say("Making teacher slides…");
    return window.PMTeacher.build(text(), { traces: o.traces || [], title: baseName(), path: file.path })
      .then(function (r) {
        var sent = B.call("export", { text: r.html, ext: "html", suggested: baseName() + "_Teacher_Slides.html", out: out });
        return sent.then(function (saved) {
          if (saved && saved.path && r.problems.length && !window.PM_CLI) alert("The teacher slides were made, but:\n\n" + r.problems.join("\n"));
          return saved;
        });
      }).then(function (r) {
        if (!r || !r.path) { flash = null; showNotice(); return r; }
        say("Exported " + r.path.split("/").pop() + " ", [
          ["Open", function () { B.call("openFile", { path: r.path }); }],
          ["Show in Finder", function () { B.call("reveal", { path: r.path }); }]
        ]);
        return r;
      }).catch(function (e) {
        flash = null;
        alert("The teacher slides didn't work: " + (e.message || e));
        throw e;
      });
  }

  // --------------------------------------------------------- presenting
  var presenting = false, pAt = 0, pPlay = null, pFresh = true;
  var pres = $("present"), pStage = $("present-stage");
  function present() {
    shown = analyse();
    presenting = true;
    pAt = shown.isSlides ? at : 0;
    pFresh = true;
    pres.hidden = false;
    pres.classList.toggle("pm-doc", !shown.isSlides);
    B.call("fullscreen", { on: true });
    drawPresent();
  }
  function drawPresent() {
    var a = shown;
    if (!a.isSlides) {
      var flow = h("div", { class: "notes-body prose pm-present-doc" + (a.theme ? "" : " pm-plain") });
      return Notes.render(flow, a.body, { theme: a.theme }).then(function () {
        X.fixImages(flow, file.path);
        pStage.textContent = "";
        pStage.appendChild(flow);
        $("pr-pos").textContent = "";
      });
    }
    var box = slideBox(a.theme);
    var drawn = a.animate ? X.renderParts(box.slide, a.slides[pAt], a.theme) : Notes.render(box.slide, a.slides[pAt], { theme: a.theme });
    return drawn.then(function () {
      pStage.textContent = "";
      pStage.appendChild(box.frame);
      finish(box.slide);
      scaleInto(pStage, box.page, X.SLIDE.w, X.SLIDE.h, 0);
      // Played notes: a slide arrived at going forward starts unplayed;
      // going back to one, it's shown whole.
      pPlay = a.animate ? P.player(box.slide, a.animate, a.speed, pFresh ? 0 : 1e9, presentPos) : null;
      presentPos();
    });
  }
  function presentPos() {
    var p = pPlay;
    $("pr-pos").textContent = (pAt + 1) + " / " + shown.slides.length +
      (p && p.count > 1 && p.more() ? " · part " + Math.min(p.shown() + (p.busy() ? 0 : 1), p.count) + " of " + p.count : "");
  }
  function presentGo(i) {
    if (!shown.isSlides) return;
    var n = Math.max(0, Math.min(shown.slides.length - 1, i));
    if (n !== pAt) { pFresh = n > pAt; pAt = n; drawPresent(); }
  }
  // Forward: the next part of a played slide first (or the rest of the one
  // playing, at once), then the next slide.
  function presentForward() {
    if (pPlay && pPlay.step()) return;
    presentGo(pAt + 1);
  }
  function stopPresenting() {
    if (!presenting) return;
    presenting = false;
    pres.hidden = true;
    B.call("fullscreen", { on: false });
    if (shown.isSlides) goSlide(pAt, true);
  }
  document.addEventListener("keydown", function (e) {
    if (!presenting) return;
    if (e.key === "Escape") { e.preventDefault(); stopPresenting(); }
    else if (shown.isSlides && /^(ArrowRight|ArrowDown|PageDown| |Enter)$/.test(e.key)) { e.preventDefault(); presentForward(); }
    else if (shown.isSlides && /^(ArrowLeft|ArrowUp|PageUp|Backspace)$/.test(e.key)) { e.preventDefault(); presentGo(pAt - 1); }
    else if (e.key === "Home") presentGo(0);
    else if (e.key === "End") presentGo(shown.slides.length - 1);
  }, true);
  pStage.addEventListener("click", function (e) {
    if (e.target.closest("button, a, input, select, .quiz")) return;
    if (e.clientX < window.innerWidth / 3) presentGo(pAt - 1); else presentForward();
  });
  $("pr-prev").addEventListener("click", function () { presentGo(pAt - 1); });
  $("pr-next").addEventListener("click", presentForward);
  $("pr-exit").addEventListener("click", stopPresenting);
  window.addEventListener("resize", function () { if (presenting) { pFresh = false; drawPresent(); } });

  // ---------------------------------------------------------- commands
  function blockHere(kind) {
    var b = C.blockAt(text(), cm.getCursor().line);
    return b && b.info === kind ? b : null;
  }

  function command(name) {
    if (D.isOpen() && name !== "save") return;
    if (DE.active()) {
      switch (name) {
        case "slide": return DE.insert("step");
        case "present": return DE.present();
        case "themes": return D.themes({ theme: function () { return window.PMDeckFile.themeOf(DE._state().d); }, use: DE.useTheme });
        case "question": case "tests": case "part": case "pause": case "pop": case "cards": case "checklist":
        case "run-code": case "predict-code": case "export": case "export-pdf": case "follow":
          return say("That's for markdown lessons. In teacher slides, use + Slide, click the words, or the HTML panel.");
      }
    }
    switch (name) {
      case "new-slides": return guarded(function () { load(TEMPLATES.slides); B.call("recovery.clear"); });
      case "new-doc": return guarded(function () { load(TEMPLATES.doc); B.call("recovery.clear"); });
      case "open": return openFile();
      case "save": return save(false);
      case "save-as": return save(true);
      case "slide": return newSlide();
      case "question": {
        var q = blockHere("quiz");
        return D.question(q, shown.theme, function (md) { putBlock(md, q); });
      }
      case "tests": {
        var t = blockHere("tests");
        return D.tests(t, shown.theme, function (md) { putBlock(md, t); });
      }
      case "themes":
        return D.themes({ theme: function () { return C.themeOf(text()); }, use: useTheme });
      case "export": return D.exportForm(counts(), function (o) { doExport(o); });
      case "export-pdf": return doExport({ format: "pdf", questions: true, tests: true, answers: false });
      case "present": return present();
      case "follow": follow.checked = true; return goSlide(C.slideAt(text(), cm.getCursor().line, knownThemes()).index);
      case "help": return D.help();
      case "part": return insertPart();
      case "pause": return insertPause();
      case "pop": return insertPop();
      case "cards": case "checklist": case "run-code": case "predict-code": return putBlock(SNIPPETS[name]);
    }
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-cmd]"), function (b) {
    b.addEventListener("click", function () {
      var menu = b.closest(".pm-menu-list");
      if (menu) menu.hidden = true;
      command(b.dataset.cmd);
    });
  });
  ["b-new", "b-insert"].forEach(function (id) {
    $(id).addEventListener("click", function (e) {
      e.stopPropagation();
      var list = $(id).nextElementSibling;
      Array.prototype.forEach.call(document.querySelectorAll(".pm-menu-list"), function (m) { if (m !== list) m.hidden = true; });
      list.hidden = !list.hidden;
    });
  });
  document.addEventListener("click", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".pm-menu-list"), function (m) { m.hidden = true; });
  });

  // In a plain browser there's no menu bar to give ⌘S and friends.
  // The menu's other keys too (⇧⌘K and the rest), by e.code so ⇧ and ⌥
  // don't change which key it is.
  if (!B.native) {
    document.addEventListener("keydown", function (e) {
      if (!(e.metaKey || e.ctrlKey)) return;
      var k = e.key.toLowerCase();
      var map = { s: e.shiftKey && !B.server ? "save-as" : "save", o: "open", e: "export" };
      var shifted = { KeyK: "question", KeyT: "tests", KeyY: "themes", KeyL: "follow", Period: "part", Digit6: "pause" };
      var cmd = e.altKey && e.code === "KeyP" ? "present" : e.shiftKey ? shifted[e.code] : map[k];
      if (cmd) { e.preventDefault(); command(cmd); }
      else if (k === "enter" && !D.isOpen()) { e.preventDefault(); command("slide"); }
    });
  }

  // ------------------------------------------------------ the splitter
  (function () {
    var split = $("split"), main = $("main");
    var saved = null;
    try { saved = parseFloat(localStorage.getItem("pm-split")); } catch (e) { /* none */ }
    if (saved > 15 && saved < 85) main.style.setProperty("--pm-left", saved + "%");
    split.addEventListener("mousedown", function (e) {
      e.preventDefault();
      document.body.classList.add("is-resizing-x");
      function move(ev) {
        var r = main.getBoundingClientRect();
        var pct = Math.max(20, Math.min(80, (ev.clientX - r.left) / r.width * 100));
        main.style.setProperty("--pm-left", pct + "%");
        cm.refresh();
      }
      function up() {
        document.body.classList.remove("is-resizing-x");
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        try { localStorage.setItem("pm-split", parseFloat(main.style.getPropertyValue("--pm-left"))); } catch (e) { /* none */ }
      }
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  })();

  // ------------------------------------------------------- for the app
  window.PM = {
    command: command,
    /* The editor, for a page that serves this one (an IDE's tutorial
       library attaches its picture uploads to it: paste, drop, Add picture). */
    editor: function () { return cm; },
    /* Whether the markdown has changes not saved yet. */
    dirty: function () { return dirty(); },
    openText: function (path, t) { guarded(function () { load(t, path); B.call("recovery.clear"); }); },
    forgetRecovery: function () { return B.call("recovery.clear"); },
    /* `PresMaker --export in.md out.pdf`: the export the menu makes, with
       no window, for tools/test_export.sh. */
    cliExport: function (t, path, opts, out) {
      load(t, path);
      shown = analyse();
      var o = { format: opts.format === "htm" ? "html" : opts.format, questions: opts.questions,
                tests: opts.tests, answers: opts.answers, traces: opts.traces || [] };
      return doExport(o, out).catch(function (e) {
        return B.call("cliFail", { error: String(e && e.message || e) });
      });
    }
  };

  // ----------------------------------------------------------- start
  /* Unsaved work from last time first (offered, never forced), else the
     file that was open, else a new slideshow. */
  T.load().then(function () {
    if (window.PM_CLI) return;            // an export from the command line: no start-up
    return B.call("recovery.load").then(function (r) {
      if (r && r.text) {
        load(TEMPLATES.slides);
        D.choice("Unsaved work from last time", "PresMaker closed with changes to " + (r.name || "a deck") +
                 " that weren't saved. Put them back?", [
          { label: "Throw away", action: function () { B.call("recovery.clear"); startWithLast(); } },
          { label: "Put them back", primary: true, action: function () {
            load(r.text, "", r.name);
            file.path = r.path || "";
            file.saved = "\u0000";             // still unsaved: nothing on disk matches
            lastState = null; tellState();
          } }
        ]);
        return;
      }
      return startWithLast();
    });
  }).catch(function () { load(TEMPLATES.slides); });

  function startWithLast() {
    return B.call("lastFile").then(function (r) {
      if (r && r.text !== undefined) load(r.text, r.path, r.name); else load(TEMPLATES.slides);
    }).catch(function () { load(TEMPLATES.slides); });
  }
})();
