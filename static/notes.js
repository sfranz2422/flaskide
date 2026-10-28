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

  /* A TEACHER'S OWN WORDS on a class page — descriptions, which only the
     class's teacher can write (the server refuses anyone else) — are let
     have <iframe> (a YouTube player, Google Slides, a form) and inline
     style (a table coloured the way they want). Never for notes: students
     write those too, and the reasons above are about them. Scripts and
     event handlers are still taken out here; DOMPurify never lets them by. */
  var TRUSTED = {
    USE_PROFILES: { html: true },
    ADD_TAGS: ["iframe"],
    ADD_ATTR: ["allow", "allowfullscreen", "frameborder", "referrerpolicy",
               "loading", "scrolling"],
    FORBID_TAGS: SANITIZE.FORBID_TAGS
  };

  // ----------------------------------------------------------- themes
  /* A deck's look, picked by its author with one line at the very top:

         theme: chalkboard

     Markdown has no colours or themes of its own, and inline style is
     taken out of notes (SANITIZE, above) because students write notes too.
     So a theme is only a NAME from this list: it becomes a class, and every
     colour lives in style.css. Nothing a student types can reach CSS.

     Each theme sets the same variables the page's own palette does (--text,
     --accent, --line, ...), on the notes alone, so headings, code, quiz
     cards and links all follow it without a rule each. A theme is its own
     background, so it looks the same whether the page is light or dark.

     The line is taken out before the notes are cut into slides — in
     slides(), which the teacher's "3/5", the lesson editor's cursor and
     every student's viewer all go through, so none of them can count it
     differently. A name not on the list is left in, as text, so a typo
     shows on the slide instead of silently doing nothing. */
  var THEMES = ["ocean", "sunset", "forest", "chalkboard", "arcade",
                "notebook", "space",
                // The seasons, for the year's calendar.
                "halloween", "fall", "winter", "christmas", "spring", "summer"];
  // The ones whose headings use a display face (themeFonts).
  var FONT_THEMES = ["chalkboard", "arcade", "notebook", "halloween", "christmas"];
  var THEME_LINE = /^[ \t]*theme[ \t]*:[ \t]*([a-z]+)[ \t]*$/i;

  /* `animate: words` (or `animate: type`) beside the theme line: the notes
     are played a section at a time for students (slideView, below). The
     names it takes, and what each means. A speed may follow —
     `animate: words slow` — or stand alone, `animate: slow`, meaning words.

     The first speed, 70 ms a word, was far too quick to read along with:
     about 850 words a minute. "normal" is now a little faster than reading
     aloud, and "slow" is reading aloud. */
  var ANIMATE_LINE = /^[ \t]*animate[ \t]*:[ \t]*([a-z]+)(?:[ \t]+([a-z]+))?[ \t]*$/i;
  var ANIMATIONS = { words: "words", word: "words", reveal: "words", on: "words", yes: "words", "true": "words",
                     type: "type", typewriter: "type", typing: "type" };
  // ms a word, a letter, and a block (code, a question, a picture) takes to come in.
  // A pause (`^`) waits `pause` ms a caret.
  var SPEEDS = { slow: { word: 450, letter: 80, block: 700, pause: 1500 },
                 normal: { word: 250, letter: 45, block: 450, pause: 1000 },
                 fast: { word: 120, letter: 22, block: 260, pause: 600 } };

  /* `locked: yes` beside them: on a slide with tests, the next slide waits
     until every test on it passes (slideView) — where the page asks for it,
     a student's own editor. `locked: no` is a header line too, and says so. */
  var LOCKED_LINE = /^[ \t]*locked[ \t]*:[ \t]*(yes|no|on|off|true|false)[ \t]*$/i;

  /* {animate, speed} from an `animate:` line, or null when it isn't one
     notes.js knows — a typo stays on the slide as text. */
  function readAnimate(line) {
    var a = line.match(ANIMATE_LINE);
    if (!a) return null;
    var first = a[1].toLowerCase(), second = (a[2] || "").toLowerCase();
    if (SPEEDS[first] && !second) return { animate: "words", speed: first };
    if (!ANIMATIONS[first] || (second && !SPEEDS[second])) return null;
    return { animate: ANIMATIONS[first], speed: second || "normal" };
  }

  /* {theme, animate, body}: the notes' header lines — `theme:` and
     `animate:`, the first one or two lines with anything on them, in either
     order — and the notes without them. A line naming something unknown
     isn't a header line: it stays in, as text, so a typo shows on the slide
     instead of silently doing nothing. Taken out before the notes are cut
     into slides (slides()), so no count can differ between anyone. */
  function takeHeader(md) {
    var text = String(md || ""), theme = "", animate = "", speed = "", locked = null;
    for (var k = 0; k < 3; k++) {
      var m = text.match(/^\s*([^\n]*)\n?/);
      var line = m ? m[1].replace(/\r$/, "") : "";
      var t = line.match(THEME_LINE), a = readAnimate(line), l = line.match(LOCKED_LINE);
      if (t && !theme && THEMES.indexOf(t[1].toLowerCase()) >= 0) theme = t[1].toLowerCase();
      else if (a && !animate) { animate = a.animate; speed = a.speed; }
      else if (l && locked === null) locked = /^(yes|on|true)$/i.test(l[1]);
      else break;
      text = text.slice(m[0].length);
    }
    return { theme: theme, animate: animate, speed: speed, locked: !!locked, body: text };
  }

  /* {name, body}: the theme the notes ask for ("" for none), and the notes
     without their header lines (takeHeader). */
  function takeTheme(md) {
    var h = takeHeader(md);
    return { name: h.theme, body: h.body };
  }

  /* Headings in a few themes use a display face. Fetched the first time
     such a theme is shown, so notes without one never pay for it; until
     it arrives (or if it never does) the heading is in the page's own
     font, which is only plainer. */
  var fontsAsked = false;
  function themeFonts() {
    if (fontsAsked) return;
    fontsAsked = true;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://fonts.googleapis.com/css2?family=Caveat:wght@600;700" +
                "&family=Patrick+Hand&family=Press+Start+2P&family=Creepster" +
                "&family=Mountains+of+Christmas:wght@700&display=swap";
    document.head.appendChild(link);
  }

  function setTheme(node, name) {
    if (!node) return;
    node.className = node.className.replace(/(^|\s)(slide-themed|slide-theme-[a-z]+)(?=\s|$)/g, " ")
                                   .replace(/\s+/g, " ").trim();
    if (!name) return;
    node.className = (node.className + " slide-themed slide-theme-" + name).trim();
    if (FONT_THEMES.indexOf(name) >= 0) themeFonts();
  }

  /* options.theme, when given, is the deck's theme for a slide that no
     longer has the line (slideView). Without it the notes' own line
     decides, so notes shown whole are themed by the same one line. */
  function render(target, source, options) {
    var rules = options && options.trusted ? TRUSTED : SANITIZE;
    var theme = options && typeof options.theme === "string" ? options.theme : null;
    if (theme === null) {
      var picked = takeTheme(source);
      theme = picked.name;
      source = picked.body;
    }
    // A section divider (`...`) is never shown: where notes aren't played
    // a section at a time — live, the projector — it's just a seam.
    source = pauseLines(popMarks(sections(source || "").join("\n\n")));
    return ensureRenderer().then(function () {
      setTheme(target, theme);
      var dirty = window.marked.parse(runFences(source || ""), { breaks: true });
      // A checklist's boxes as placeholders: the sanitizer takes every
      // <input> out (SANITIZE), so a task list arrived as a list of bare
      // items. A span with a data- attribute survives, and enhanceTasks
      // makes it a real checkbox after, in the DOM, never through HTML.
      dirty = dirty.replace(/<input\b[^>]*type="checkbox"[^>]*>/g, function (tag) {
        return '<span class="task-box" data-done="' + (/\bchecked\b/.test(tag) ? "1" : "0") + '"></span>';
      });
      var clean = window.DOMPurify.sanitize(dirty, rules);
      target.innerHTML = clean;
      wrapPops(target);
      markPauses(target);
      hardenLinks(target);
      enhanceQuizzes(target);
      enhanceTasks(target);
      enhanceCards(target);
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
    var lines = takeTheme(String(md || "").replace(/\r\n?/g, "\n")).body.split("\n");
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

  /* A PAUSE while a section plays: `^` with a space (or the line's end) on
     each side waits about a second before the words after it come in; `^^`
     twice as long. Never shown — where notes are shown whole it's hidden,
     and it means nothing — and never read inside code, where ^ is Python's
     XOR (write `^` in backticks to show one).

     A line with only carets on it joins the end of the line before (or the
     start of the line after, under a blank line): left as a line of its
     own, markdown makes it an empty paragraph, a gap on the slide. */
  var PAUSE = /(^|\s)(\^+)(?=\s|$)/g;
  var PAUSE_LINE = /^ {0,3}(\^+)\s*$/;
  function pauseLines(md) {
    var lines = String(md || "").split("\n"), fence = null, out = [], carry = "";
    lines.forEach(function (ln) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
      } else if (fence === null) {
        var p = ln.match(PAUSE_LINE);
        if (p) {
          var before = out.length ? out[out.length - 1] : "";
          if (before.trim() && !/^ {0,3}(`{3,}|~{3,})|%%POP/.test(before)) out[out.length - 1] = before.replace(/\s+$/, "") + " " + p[1];
          else carry += p[1];
          return;
        }
        // Not onto a :::pop marker: that would stop it being one.
        if (carry && ln.trim() && ln.indexOf("%%POP") < 0) {
          var indent = ln.match(/^\s*(?:[-*+] |\d+[.)] |#{1,6} |> )?/)[0];
          ln = indent + carry + " " + ln.slice(indent.length);
          carry = "";
        }
      }
      out.push(ln);
    });
    return out.join("\n");
  }
  /* Each pause in the drawn notes as an empty span.reveal-pause (CSS hides
     it), its length in data-beats, for animateIn to wait at. */
  function markPauses(root) {
    var walk = document.createTreeWalker(root, 4), hits = [];
    for (var n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeValue.indexOf("^") >= 0 && !(n.parentNode.closest && n.parentNode.closest("code, pre, textarea, .quiz"))) hits.push(n);
    }
    hits.forEach(function (n) {
      var text = n.nodeValue, frag = document.createDocumentFragment(), last = 0, m;
      PAUSE.lastIndex = 0;
      while ((m = PAUSE.exec(text))) {
        var at = m.index + m[1].length;
        frag.appendChild(document.createTextNode(text.slice(last, at)));
        var span = el("span", "reveal-pause");
        span.setAttribute("data-beats", String(m[2].length));
        frag.appendChild(span);
        last = at + m[2].length;
      }
      if (!last) return;
      frag.appendChild(document.createTextNode(text.slice(last)));
      n.parentNode.replaceChild(frag, n);
    });
  }

  /* A slide cut into the sections it's played in: a line with only `...`
     on it ends one section and starts the next. Never inside fenced code,
     where `...` is a line of output (or Python's Ellipsis). A slide with no
     divider is one section. */
  var SECTION = /^ {0,3}\.\.\.\s*$/;
  function sections(md) {
    var out = [], cur = [], fence = null;
    String(md || "").replace(/\r\n?/g, "\n").split("\n").forEach(function (ln) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
      } else if (fence === null && SECTION.test(ln)) {
        out.push(cur.join("\n"));
        cur = [];
        return;
      }
      cur.push(ln);
    });
    out.push(cur.join("\n"));
    out = out.filter(function (x) { return x.trim(); });
    return out.length ? out : [""];
  }

  /* What the teacher wraps to make it stand out:

         :::pop
         Press ✔ Check my work on the card below.
         :::

     around anything — a sentence, a paragraph, a code block. Nothing pops
     by itself: the teacher chooses. Played a section at a time, it arrives
     whole with a little pop; shown whole, it's a highlighted box.

     The marker lines become paragraphs of a word no one writes, the
     markdown is rendered as it always is, and wrapPops then gathers what's
     between each pair into a div — so what's inside is ordinary markdown,
     code fences included. Never inside fenced code, where `:::` could be
     anything. A pop left open ends where its section does. */
  var POP_OPEN = /^ {0,3}:::\s*pop\s*$/i, POP_CLOSE = /^ {0,3}:::\s*$/;
  var POP_START = "%%POPSTART%%", POP_END = "%%POPEND%%";
  function popMarks(md) {
    var fence = null;
    return String(md).split("\n").map(function (ln) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length) fence = null;
        return ln;
      }
      if (fence !== null) return ln;
      if (POP_OPEN.test(ln)) return "\n" + POP_START + "\n";
      if (POP_CLOSE.test(ln)) return "\n" + POP_END + "\n";
      return ln;
    }).join("\n");
  }
  function wrapPops(root) {
    var marks = Array.prototype.filter.call(root.querySelectorAll("p"), function (p) {
      var t = p.textContent.trim();
      return t === POP_START || t === POP_END;
    });
    marks.forEach(function (mark) {
      if (!mark.parentNode || mark.textContent.trim() !== POP_START) return;
      var box = el("div", "pop-box");
      mark.parentNode.insertBefore(box, mark);
      var node = mark.nextSibling;
      while (node && !(node.nodeType === 1 && node.tagName === "P" && node.textContent.trim() === POP_END)) {
        var after = node.nextSibling;
        box.appendChild(node);
        node = after;
      }
      if (node) node.remove();
      mark.remove();
    });
    // A closing marker with nothing open: gone, not shown as text.
    Array.prototype.forEach.call(root.querySelectorAll("p"), function (p) {
      if (p.textContent.trim() === POP_END) p.remove();
    });
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

     slideView(body, {animate: true, key}) is a student's own reading: notes
     that say `animate:` are played a section at a time (below), and `key`
     names where their progress is kept. Without it — live, the teacher's
     preview, the projector — the same notes show whole.

     Re-renders only when what is on screen would change. A live page calls
     show() once a second; rendering that often would replace a link, or a
     question's half-typed answer, under the student's hand. */
  function slideView(body, opts) {
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

    var md = null, cut = [], at = 0, drawn = null, moved = null, theme = "";

    /* PLAYED A SECTION AT A TIME (`animate:` in the notes, and only where
       the page asks — a student reading their notes; never live, never the
       teacher's own preview). The slide starts empty with ▶ Play above it;
       each press plays the next section (`...` divides them) word by word
       or as a typewriter, and Play comes back when it's done. The next
       slide's arrow waits until every section of this one has been played.
       Slides already played show whole, and going back and forward again
       replays nothing: how far they've got (`reached`) is kept in this
       browser, per page. */
    var player = opts && opts.animate ? opts : null;
    // Whether to play now (a function: the teacher's editor stops playing
    // while they're live), and whether Skip is offered (the teacher's own
    // preview, to edit a slide without sitting through it).
    function wanted() { return !!player && (typeof player.animate === "function" ? player.animate() : !!player.animate); }
    function skippable() { return !!player && (typeof player.skip === "function" ? player.skip() : !!player.skip); }
    var playing = null;    // the section being played: {finish}
    var mode = "";                         // "words" or "type", when playing
    var speed = "";                        // "slow", "normal" or "fast"
    var reached = { slide: 0, played: 0 }; // the furthest slide, and its sections played
    var busy = false;
    var playBar = null, play = null, hint = null, skip = null, replay = null;

    /* LOCKED UNTIL ITS CHECKS PASS (`locked: yes` in the notes, and only
       where the page asks — the student's own editor; never the teacher's
       preview, never live, where the teacher moves the slides). On a slide
       with a tests card (checks_in_notes.js), the next slide's arrow waits
       until every check on it passes, as GameIDE's tutorials do. A slide
       once passed stays open — going back and forward again asks nothing,
       and neither does a reload: how far they've got (`unlocked`, the
       first slide not yet passed) is kept in this browser, per page. */
    var lockOpt = opts && opts.locked !== undefined ? opts : null;
    // A slide with a ```tests block: the only kind the lock holds.
    var TESTS_FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*tests[ \t]*$/im;
    function lockWanted() { return !!lockOpt && (typeof lockOpt.locked === "function" ? lockOpt.locked() : !!lockOpt.locked); }
    var lockOn = false;
    var unlocked = 0;
    function lockKey() { return "pyide-unlocked:" + ((opts && opts.key) || location.pathname); }
    function loadUnlocked() {
      try { return Math.max(0, Number(localStorage.getItem(lockKey())) || 0); } catch (e) { return 0; }
    }
    function saveUnlocked() {
      try { localStorage.setItem(lockKey(), String(unlocked)); } catch (e) { /* this visit only */ }
    }
    // This slide has checks not yet passed, and it's where they have to be passed.
    function checksHold() {
      return lockOn && cut.length > 0 && at >= unlocked &&
        !!body.querySelector(".tests-card[data-checks]:not([data-passed])");
    }
    /* The arrows, from everything that can hold the way on: a slide still
       playing (animate:), and checks not yet passed (locked:). */
    function arrows() {
      var hold = checksHold();
      body.classList.toggle("tests-locking", hold);
      if (!cut.length) return;
      next.disabled = at >= cut.length - 1 || unfinished() || busy || hold;
      next.title = unfinished() ? "Play the rest of this slide first" : hold ? "Pass this slide's checks first" : "Next slide";
    }
    body.addEventListener("ide-checks", function () {
      if (lockOn && cut.length && at >= unlocked && !body.querySelector(".tests-card[data-checks]:not([data-passed])")) {
        unlocked = at + 1;
        saveUnlocked();
      }
      arrows();
    });

    if (player) {
      playBar = el("div", "reveal-bar");
      playBar.hidden = true;
      play = el("button", "btn btn-primary reveal-play", "▶ Play");
      play.type = "button";
      skip = el("button", "btn reveal-skip", "⏭ Skip");
      skip.type = "button";
      skip.title = "Show the part playing now at once — or, between parts, the whole slide";
      replay = el("button", "btn reveal-replay", "↺ Replay");
      replay.type = "button";
      replay.title = "Play this slide again from the start";
      hint = el("span", "reveal-hint dim small");
      playBar.appendChild(play);
      playBar.appendChild(skip);
      playBar.appendChild(replay);
      playBar.appendChild(hint);
      body.parentNode.insertBefore(playBar, body);
      play.addEventListener("click", playNext);
      skip.addEventListener("click", skipAhead);
      replay.addEventListener("click", replaySlide);
    }
    function revealKey() { return "pyide-reveal:" + (player.key || location.pathname); }
    function loadReached() {
      try {
        var got = JSON.parse(localStorage.getItem(revealKey()) || "null");
        if (got && got.slide >= 0 && got.played >= 0) return { slide: got.slide, played: got.played };
      } catch (e) { /* none kept */ }
      return { slide: 0, played: 0 };
    }
    function saveReached() {
      try { localStorage.setItem(revealKey(), JSON.stringify(reached)); } catch (e) { /* this visit only */ }
    }
    // The pages played: the slides, or the notes whole when they have none.
    function pages() { return cut.length ? cut : [takeHeader(md).body]; }
    function sectionsHere() { return sections(pages()[at]); }
    function shownHere() {
      return at < reached.slide ? sectionsHere().length : at === reached.slide ? reached.played : 0;
    }
    // This slide still has sections to play: the way on waits.
    function unfinished() { return !!mode && at >= reached.slide && shownHere() < sectionsHere().length; }

    function paintPlayer() {
      if (!playBar) return;
      var total = sectionsHere().length, shown = shownHere();
      playBar.hidden = !mode;
      setTheme(playBar, theme);
      var more = mode && at === reached.slide && shown < total;
      play.hidden = !more;
      play.disabled = busy;
      skip.hidden = !skippable() || !(busy || more);
      replay.hidden = !skippable() || !mode || busy || !shown;
      play.textContent = shown ? "▶ Play more" : "▶ Play";
      hint.textContent = busy ? "" : more
        ? (total > 1 ? "Part " + (shown + 1) + " of " + total : "")
        : at < reached.slide || shown >= total ? (cut.length && at < cut.length - 1 ? "Done — on to the next slide ▶" : "Done") : "";
      if (cut.length) prev.disabled = at <= 0 || busy;
      arrows();
    }

    function drawPlayed() {
      var secs = sectionsHere(), shown = Math.min(shownHere(), secs.length);
      var key = "play\n" + theme + "\n" + at + "\n" + shown + "\n" + pages()[at];
      paintPlayer();
      if (key === drawn) return Promise.resolve(true);
      var turned = drawn !== null;
      drawn = key;
      setTheme(body, theme);
      body.textContent = "";
      if (!shown) body.appendChild(el("p", "reveal-start dim", "Press ▶ Play to start this slide."));
      var parts = secs.slice(0, shown).map(function (sec) {
        var part = el("div", "reveal-part");
        body.appendChild(part);
        return render(part, sec, { theme: "" });
      });
      return Promise.all(parts).then(function () {
        arrows();                         // a tests card played in, or there already
        if (turned) body.scrollTop = 0;
        return true;
      });
    }

    function playNext() {
      var secs = sectionsHere();
      if (busy || !mode || at !== reached.slide || reached.played >= secs.length) return;
      busy = true;
      var sec = secs[reached.played];
      reached.played += 1;
      saveReached();
      var start = body.querySelector(".reveal-start");
      if (start) start.remove();
      var part = el("div", "reveal-part");
      body.appendChild(part);
      drawn = "play\n" + theme + "\n" + at + "\n" + reached.played + "\n" + pages()[at];
      paintPlayer();
      playing = {};
      var ctl = playing;
      render(part, sec, { theme: "" }).then(function () {
        return animateIn(part, mode, body, ctl, speed);
      }).then(function () {
        if (playing === ctl) playing = null;
        busy = false;
        paintPlayer();
      });
    }

    /* The teacher's Skip: the part playing now, at once; between parts, the
       whole of this slide — so the next slide is open to them. */
    function skipAhead() {
      if (!mode || !skippable()) return;
      if (busy) {
        if (playing && playing.finish) playing.finish();
        return;
      }
      if (at !== reached.slide) return;
      reached.played = sectionsHere().length;
      saveReached();
      drawPlayed();
    }

    /* The teacher's preview only: this slide unplayed again, so a slide
       they've changed can be watched again. Without it a slide once played
       showed whole for good — moving the cursor back to edit it, the
       teacher could never see their change play. */
    function replaySlide() {
      if (!mode || !skippable() || busy) return;
      reached = { slide: at, played: 0 };
      saveReached();
      drawPlayed();
    }

    function draw() {
      if (mode) return drawPlayed();
      var text = cut.length ? cut[at] : takeTheme(md).body;
      setTheme(bar, theme);       // the arrows under a themed deck match it
      bar.hidden = !cut.length;
      if (cut.length) {
        pos.textContent = (at + 1) + " / " + cut.length;
        prev.disabled = at <= 0;
      }
      arrows();
      // The theme is part of what is on screen: changing only the theme
      // line must redraw, though no slide's text changed.
      var key = theme + "\n" + text;
      if (key === drawn) return Promise.resolve(true);
      var turned = drawn !== null && drawn.slice(drawn.indexOf("\n") + 1) !== text;
      drawn = key;
      return render(body, text, { theme: theme }).then(function (ok) {
        if (turned) body.scrollTop = 0;   // a new slide starts at its top
        arrows();                         // its tests card is there now
        return ok;
      });
    }

    function paintBar() {
      if (!mode) return;
      setTheme(bar, theme);
      bar.hidden = !cut.length;
      if (cut.length) {
        pos.textContent = (at + 1) + " / " + cut.length;
        prev.disabled = at <= 0 || busy;
      }
      paintPlayer();
    }

    function go(i) {
      if (!cut.length) return Promise.resolve(true);
      at = Math.max(0, Math.min(cut.length - 1, i));
      paintBar();
      return draw();
    }

    function step(by) {
      if (!cut.length || busy) return;
      if (by > 0 && (unfinished() || checksHold())) return;
      // Through, so this slide holds nothing any more — checks or none.
      if (lockOn && by > 0 && at >= unlocked) {
        unlocked = at + 1;
        saveUnlocked();
      }
      var was = at;
      // Onto the slide after the furthest one reached: it's the new furthest, unplayed.
      if (mode && by > 0 && at === reached.slide && at + 1 < cut.length) {
        reached = { slide: at + 1, played: 0 };
        saveReached();
      }
      go(at + by);
      if (at !== was && moved) moved(at);
    }
    prev.addEventListener("click", function () { step(-1); });
    next.addEventListener("click", function () { step(1); });

    return {
      show: function (text, i) {
        md = text || "";
        var head = takeHeader(md);
        theme = head.theme;
        var wasMode = mode;
        mode = wanted() ? head.animate : "";
        speed = head.speed;
        var wasLock = lockOn;
        lockOn = lockWanted() && head.locked;
        if (lockOn && !wasLock) unlocked = loadUnlocked();
        var c = slides(md);
        // One slide is not slides, as everywhere else.
        cut = c.length >= 2 ? c : [];
        if (mode) {
          if (!wasMode) {
            // Opened where they got to: the furthest slide, as far as they'd played it.
            reached = loadReached();
            reached.slide = Math.min(reached.slide, pages().length - 1);
            at = reached.slide;
          }
          reached.played = Math.min(reached.played, sections(pages()[reached.slide]).length);
        } else if (wasMode) {
          drawn = null;
        }
        if (typeof i === "number") {
          if (!mode) at = i;
          else if (skippable()) {
            // The teacher's preview following their cursor: straight to that
            // slide, unplayed if it's past the furthest they'd reached.
            at = Math.max(0, Math.min(i, pages().length - 1));
            if (at > reached.slide) {
              reached = { slide: at, played: 0 };
              saveReached();
            }
          }
        }
        at = Math.max(0, Math.min(at, cut.length - 1));
        paintBar();
        return draw();
      },
      go: go,
      /* Turns to slide i if the reader may go there: back, always; ahead,
         only as far as the lock (`locked: yes`) and the player (`animate:`)
         have let them. Check my work turns to a failing check this way
         (checks_in_notes.js), and must never skip them past a held slide.
         True when it turned. */
      reach: function (i) {
        if (!cut.length || i < 0 || i >= cut.length || i === at) return false;
        if (i > at && mode && i > reached.slide) return false;
        // Held only by a slide on the way that has checks and isn't passed:
        // one with none holds nothing, as its own arrow doesn't.
        for (var j = Math.max(at, unlocked); lockOn && j < i; j++) if (TESTS_FENCE.test(cut[j])) return false;
        go(i);
        if (moved) moved(at);
        return true;
      },
      at: function () { return at; },
      count: function () { return cut.length; },
      onMove: function (fn) { moved = fn; },
      bar: bar
    };
  }

  /* One section, played into view: word by word ("words") or letter by
     letter ("type"). A code block, a question, a table or a picture comes
     in whole, and so does what the teacher wrapped in :::pop, with its pop.
     Hidden with visibility, not display, so nothing jumps as it appears.
     Someone whose computer asks for reduced motion gets the section at
     once. Resolves when it's all in — or at once, everything shown, when
     `ctl.finish()` is called (the teacher's Skip). */
  var TEXT_BLOCKS = { P: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, UL: 1, OL: 1, BLOCKQUOTE: 1, DL: 1 };

  function animateIn(part, how, scroller, ctl, speed) {
    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) return Promise.resolve();
    var ms = SPEEDS[speed] || SPEEDS.normal;
    var WORD_MS = ms.word, CHAR_MS = ms.letter, BLOCK_MS = ms.block;
    var steps = [];   // [element, delay, after?]
    function hide(node) { node.classList.add("reveal-hidden"); }
    function splitText(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 3) {
          var bits = how === "type" ? child.nodeValue.split("") : child.nodeValue.split(/(\s+)/);
          var frag = document.createDocumentFragment();
          bits.forEach(function (bit) {
            if (!bit) return;
            if (how !== "type" && /^\s+$/.test(bit)) { frag.appendChild(document.createTextNode(bit)); return; }
            var span = el("span", "reveal-bit", bit);
            hide(span);
            frag.appendChild(span);
            steps.push([span, how === "type" ? (/\s/.test(bit) ? 0 : CHAR_MS) : WORD_MS]);
          });
          child.parentNode.replaceChild(frag, child);
        } else if (child.nodeType === 1) {
          if (child.classList.contains("reveal-pause")) {
            steps.push([child, ms.pause * (Number(child.getAttribute("data-beats")) || 1)]);
          } else if (/^(IMG|INPUT|IFRAME|SVG)$/i.test(child.tagName)) {
            hide(child);
            steps.push([child, BLOCK_MS]);
          } else {
            splitText(child);
          }
        }
      });
    }
    // The section's blocks, inside however many wrappers the rendering made.
    function blocks(node) {
      var out = [];
      Array.prototype.forEach.call(node.children, function (c) {
        if (c.classList.contains("reveal-part")) out = out.concat(blocks(c));
        else out.push(c);
      });
      return out;
    }
    blocks(part).forEach(function (block) {
      if (TEXT_BLOCKS[block.tagName]) {
        splitText(block);
      } else {
        hide(block);
        steps.push([block, BLOCK_MS, block.classList.contains("pop-box") ? "reveal-pop" : ""]);
      }
    });
    return new Promise(function (resolve) {
      var i = 0, timer = null, over = false;
      if (ctl) ctl.finish = function () {
        if (over) return;
        over = true;
        clearTimeout(timer);
        Array.prototype.forEach.call(part.querySelectorAll(".reveal-hidden"), function (n) { n.classList.remove("reveal-hidden"); });
        resolve();
      };
      function nextStep() {
        if (over) return;
        if (i >= steps.length) { over = true; return resolve(); }
        var s = steps[i++];
        timer = setTimeout(function () {
          s[0].classList.remove("reveal-hidden");
          if (s[2]) s[2].split(" ").forEach(function (c) { if (c) s[0].classList.add(c); });
          // Keep what's appearing in view, a word now and then.
          if (scroller && (i % 8 === 0 || s[1] === BLOCK_MS || s[2])) {
            var r = s[0].getBoundingClientRect(), box = scroller.getBoundingClientRect();
            if (r.bottom > box.bottom) scroller.scrollTop += r.bottom - box.bottom + 24;
          }
          nextStep();
        }, s[1]);
      }
      nextStep();
    });
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
  var LONG = /^type\s*:\s*(long|essay)\s*$/i;
  var TYPE = /^type\s*:\s*(blanks?|fill|match|matching|order|parsons|bug|sort|groups?|predict)\s*$/i;
  var PAIR = /^[-*+]\s+(.+?)\s+->\s+(.+)$/;
  var MATCHL = /^match\s*:\s*(.+)$/i;
  var OPTION = /^option\s*:\s*(.+)$/i;
  var BLANK = /\[\[([^\[\]\n]*)\]\]/g;
  var ITEM = /^[-*+] (.*)$/;
  var LINEQ = /^(?:line|item)\s*:\s?(.*)$/i;
  var GROUP = /^group\s*:\s*(.+)$/i;
  var BUGQ = /^bugs?\s*:\s*([\d,\s]+)$/i;
  var KINDS = { blank: "blank", blanks: "blank", fill: "blank", match: "match", matching: "match",
                order: "order", parsons: "order", bug: "bug", sort: "sort", group: "sort", groups: "sort",
                predict: "predict" };

  /* quiz.py's _fnv and scramble, exactly: the shuffled order of an order or
     sort question is part of its id, so the teacher's preview must shuffle
     the way the server will. FNV-1a over UTF-8, not SHA-1, because the
     browser has no synchronous SHA-1. */
  function fnv(text) {
    var bytes = new TextEncoder().encode(text), h = 0x811c9dc5;
    for (var i = 0; i < bytes.length; i++) h = Math.imul(h ^ bytes[i], 0x01000193) >>> 0;
    return h >>> 0;
  }
  function scramble(things) {
    var idx = things.map(function (_, i) { return i; });
    var keys = things.map(function (t, i) { return fnv(i + "\0" + t); });
    idx.sort(function (a, b) { return keys[a] - keys[b] || a - b; });
    var out = idx.map(function (i) { return things[i]; });
    var mixed = things.some(function (t) { return t !== things[0]; });
    if (mixed && out.every(function (t, i) { return t === things[i]; })) out = out.slice(1).concat(out.slice(0, 1));
    return out;
  }
  /* The language of the first fenced code in a prompt: the word after the fence. */
  function codeLang(prompt) {
    var m = String(prompt || "").match(/^ {0,3}(?:`{3,}|~{3,})\s*([\w+-]*)/m);
    return m ? m[1] : "";
  }
  /* The lines of the first fenced code in a prompt (quiz.py, code_lines). */
  function codeLines(prompt) {
    var inner = null, found = null, lines = String(prompt || "").split("\n");
    for (var i = 0; i < lines.length; i++) {
      var f = lines[i].match(FENCE);
      if (f) {
        if (inner === null) { inner = f[1]; found = []; continue; }
        if (f[1].charAt(0) === inner.charAt(0) && f[1].length >= inner.length) return found;
      } else if (inner !== null) found.push(lines[i]);
    }
    return found || [];
  }

  function parseQuiz(body) {
    var lines = String(body || "").replace(/\r\n?/g, "\n").split("\n");
    var q = { id: "", prompt: "", choices: [], correct: [], answers: [],
              points: 1 };
    var prompt = [], inner = null, long = false, typed = "";
    var lefts = [], rights = [], options = [];
    var ordered = [], shownItems = [], groups = [], itemGroups = [], bugs = [];
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
      // Lines and items before choices, as quiz.parse: `- [1, 2]` is code.
      var bare = ln.replace(/^\s+/, "");
      if (typed === "order" || typed === "sort") {
        if ((m = bare.match(ITEM)) && m[1].trim()) {
          if (typed === "order") ordered.push(m[1].replace(/\s+$/, ""));
          else { shownItems.push(m[1].trim()); itemGroups.push(groups.length ? groups[groups.length - 1] : ""); }
          return;
        }
        if ((m = bare.match(LINEQ)) && m[1].trim()) {
          shownItems.push(typed === "order" ? m[1].replace(/\s+$/, "") : m[1].trim());
          itemGroups.push(null);
          return;
        }
      }
      if (typed === "sort" && (m = s.match(GROUP))) { groups.push(m[1].trim()); return; }
      if (typed === "bug" && (m = s.match(BUGQ))) {
        m[1].split(/[,\s]+/).forEach(function (b) { if (b) bugs.push(b); });
        return;
      }
      if ((m = s.match(CHOICE))) {
        q.choices.push(m[2].trim());
        if (m[1] !== " ") q.correct.push(m[2].trim());
      } else if ((m = s.match(ANSWER))) {
        if (m[1].trim()) q.answers.push(m[1].trim());
      } else if ((m = s.match(POINTS))) {
        q.points = parseFloat(m[1]);
      } else if ((m = s.match(QID))) {
        q.id = m[1];
      } else if (LONG.test(s)) {
        long = true;
      } else if ((m = s.match(TYPE))) {
        typed = KINDS[m[1].toLowerCase()];
      } else if (typed === "match" && (m = s.match(PAIR))) {
        lefts.push(m[1].trim());
        rights.push(m[2].trim());
      } else if (typed === "match" && (m = s.match(MATCHL))) {
        lefts.push(m[1].trim());
      } else if (typed === "match" && (m = s.match(OPTION))) {
        options.push(m[1].trim());
      } else {
        prompt.push(ln);
      }
    });
    while (prompt.length && !prompt[0].trim()) prompt.shift();
    while (prompt.length && !prompt[prompt.length - 1].trim()) prompt.pop();
    q.prompt = prompt.join("\n");
    q.options = [];
    // A long response is marked by hand: no key, so none is kept (quiz.parse).
    if (long) {
      q.choices = []; q.correct = []; q.answers = [];
      q.kind = "long";
    } else if (typed === "blank") {
      // Each [[...]] is a blank and its key; [[]] is one already redacted.
      q.choices = []; q.correct = [];
      q.answers = [];
      q.prompt.replace(BLANK, function (_, b) {
        q.answers.push(b.split("|").map(function (a) { return a.trim(); })
                        .filter(function (a) { return a; }));
        return _;
      });
      q.kind = "blank";
    } else if (typed === "match") {
      // As quiz.parse: the right for each left, and every right and option
      // sorted, so neither order nor place gives a pair away.
      q.choices = lefts; q.correct = rights; q.answers = [];
      q.options = rights.concat(options).filter(function (o, i, all) {
        return all.indexOf(o) === i;
      }).sort();
      q.kind = "match";
    } else if (typed === "order") {
      q.answers = [];
      if (ordered.length) { q.choices = scramble(ordered); q.correct = ordered; }
      else { q.choices = shownItems.slice(); q.correct = []; }
      q.kind = "order";
    } else if (typed === "sort") {
      q.answers = groups;
      if (itemGroups.some(function (g) { return g; })) {
        var pairs = [];
        shownItems.forEach(function (it, i) { if (itemGroups[i]) pairs.push([it, itemGroups[i]]); });
        var shuffled = scramble(pairs.map(function (p) { return p[0]; }));
        q.correct = shuffled.map(function (it) {
          for (var k = 0; k < pairs.length; k++) {
            if (pairs[k][0] === it) return pairs.splice(k, 1)[0][1];
          }
          return "";
        });
        q.choices = shuffled;
      } else { q.choices = shownItems.slice(); q.correct = []; }
      q.kind = "sort";
    } else if (typed === "predict") {
      // A short answer about the question's code (quiz.parse): answer: is what it prints.
      q.choices = []; q.correct = [];
      q.kind = "predict";
    } else if (typed === "bug") {
      q.choices = []; q.answers = [];
      q.correct = bugs.map(function (b) { return b.replace(/^0+/, "") || "0"; });
      q.kind = "bug";
    } else {
      q.kind = q.choices.length ? "choice" : "text";
    }
    q.hasKey = q.kind === "blank"
      ? q.answers.some(function (a) { return a.length; })
      : q.kind === "match" ? rights.length > 0
      : q.kind === "order" || q.kind === "sort" || q.kind === "bug" ? q.correct.length > 0
      : !!(q.correct.length || q.answers.length);
    return q;
  }

  /* Where answers go, set by the page: the assignment's slug, and whether
     anyone is signed in. No assignment means nowhere to record an answer. */
  var quizCtx = { assignment: "", signedIn: false, viewOnly: false };
  var mine = null;            // promise of {qid: result}, fetched once
  var answered = {};          // qid -> {response, correct, earned, points}
  var pending = {};           // qid -> what is typed or picked, not yet sent
  var widgetCount = 0;

  function setQuizContext(ctx) {
    quizCtx = { assignment: (ctx && ctx.assignment) || "",
                signedIn: !!(ctx && ctx.signedIn),
                viewOnly: !!(ctx && ctx.viewOnly) };
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

  /* ```python run (and `predict`, and WebIDE's ```html run): the words
     after the language are lost by the markdown renderer, which keeps only
     the first, so they're joined onto it here (python-run) and the code
     comes out with class language-python-run for the runner to find. Only
     the opening fence's line changes; nothing inside any fence does. */
  function runFences(md) {
    var fence = null;
    return String(md).split("\n").map(function (ln) {
      var f = ln.match(FENCE);
      if (!f) return ln;
      if (fence === null) {
        fence = f[1];
        var w = f[2].trim().split(/\s+/);
        if (w.length === 2 && /^(python|py|html)$/i.test(w[0]) && /^(run|predict)$/i.test(w[1]))
          return ln.slice(0, ln.indexOf(f[1]) + f[1].length) + w[0].toLowerCase() + "-" + w[1].toLowerCase();
        return ln;
      }
      if (f[1].charAt(0) === fence.charAt(0) && f[1].length >= fence.length && !f[2].trim()) fence = null;
      return ln;
    }).join("\n");
  }

  // ------------------------------------------------------------ checklists
  /* `- [ ] Make the player move` in notes is a box to tick. What's ticked
     is kept in this browser, per page (the assignment, or else the page's
     address) and per item — a student's own record of how far they got,
     not something marked: nothing is sent anywhere. An item the notes
     write as `- [x]` starts ticked. Keyed by the item's words AND its
     place, so two items reading "Test it" are two boxes. */
  function taskKey(text, n) {
    return "pyide-task:" + (quizCtx.assignment || location.pathname) + ":" + fnv(text) + ":" + n;
  }
  function enhanceTasks(root) {
    var seen = {};
    Array.prototype.forEach.call(root.querySelectorAll("span.task-box"), function (spot) {
      var item = spot.closest("li") || spot.parentNode;
      var text = (item.textContent || "").trim();
      var n = seen[text] = (seen[text] || 0) + 1;
      var key = taskKey(text, n);
      var box = el("input", "task-check");
      box.type = "checkbox";
      box.setAttribute("aria-label", text || "Done");
      var stored = null;
      try { stored = localStorage.getItem(key); } catch (e) { stored = null; }
      box.checked = stored === null ? spot.dataset.done === "1" : stored === "1";
      item.classList.add("task-item");
      item.classList.toggle("is-done", box.checked);
      box.addEventListener("change", function () {
        item.classList.toggle("is-done", box.checked);
        try { localStorage.setItem(key, box.checked ? "1" : "0"); } catch (e) { /* this visit only */ }
      });
      spot.parentNode.replaceChild(box, spot);
    });
  }

  // ------------------------------------------------------------ flip cards
  /* A ```cards block: one card per line, `front -> back` (a leading `- `
     is fine). Each card shows its front; a click or a tap turns it over.
     Both sides go through the inline markdown renderer, so `code` and
     **bold** work and nothing else does. No answers are kept: a card is
     for practising, not marking. */
  function parseCards(text) {
    return String(text || "").split("\n").map(function (ln) {
      var m = ln.trim().replace(/^[-*+]\s+/, "").match(/^(.+?)\s+->\s+(.+)$/);
      return m ? { front: m[1].trim(), back: m[2].trim() } : null;
    }).filter(Boolean);
  }
  function enhanceCards(root) {
    Array.prototype.forEach.call(root.querySelectorAll("pre > code.language-cards"), function (code) {
      var cards = parseCards(code.textContent);
      if (!cards.length) return;
      var grid = el("div", "flip-cards");
      cards.forEach(function (c) {
        var card = button("flip-card", undefined, "Click to turn it over");
        var front = el("span", "flip-front");
        var back = el("span", "flip-back");
        md(front, c.front, true);
        md(back, c.back, true);
        card.appendChild(front);
        card.appendChild(back);
        card.setAttribute("aria-pressed", "false");
        card.addEventListener("click", function () {
          var on = !card.classList.contains("is-flipped");
          card.classList.toggle("is-flipped", on);
          card.setAttribute("aria-pressed", String(on));
        });
        grid.appendChild(card);
      });
      code.parentNode.parentNode.replaceChild(grid, code.parentNode);
    });
  }

  function enhanceQuizzes(root) {
    // A ```tests block, as the list of what the code will be checked on —
    // where autograde.js is loaded (the editor, the live page); elsewhere
    // it stays the code block it was, which still says the same.
    if (window.PyIDETests) {
      try { window.PyIDETests.renderBlocks(root); } catch (e) { /* left as code */ }
    }
    // ```python run blocks, where snippets.js is loaded (the editor and the
    // live page); elsewhere they stay code to read.
    if (window.IDESnippets) {
      try { window.IDESnippets.renderBlocks(root); } catch (e) { /* left as code */ }
    }
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
    // For the teacher's editor, which finds its own copy of a question by
    // this to put the class's answer count on it (app.js, "answers, counted").
    box.quizPrompt = q.prompt;
    var head = el("div", "quiz-head");
    head.appendChild(el("span", "quiz-label",
                        { long: "Long response", blank: "Fill in the blank",
                          match: "Matching", order: "Put in order", bug: "Find the bug",
                          sort: "Sort into groups", predict: "Predict the output" }[q.kind] || "Question"));
    head.appendChild(el("span", "quiz-points dim", pointsText(q.points)));
    box.appendChild(head);
    var prompt = el("div", "quiz-prompt");
    var inputs = [];
    if (q.kind === "blank") {
      // Each blank becomes a marker the markdown leaves alone, and then a
      // box in its place — inside a code block too, which is where a blank
      // in a line of code wants to be.
      var at = 0;
      md(prompt, q.prompt.replace(BLANK, function () { return "%%BLANK" + (at++) + "%%"; }));
      inputs = fillBlanks(prompt);
    } else {
      md(prompt, q.prompt);
    }
    box.appendChild(prompt);

    if (q.kind === "long") return buildLong(q, box);

    // The three that aren't boxes to type in or pick from: a widget that
    // says what's chosen (get), shows a response (set), and is locked or not.
    var custom = q.kind === "order" ? orderWidget(q)
      : q.kind === "sort" ? sortWidget(q)
      : q.kind === "bug" ? bugWidget(q, prompt) : null;

    if (q.kind === "blank") {
      // made above, in the prompt
    } else if (custom) {
      if (custom.node) box.appendChild(custom.node);
    } else if (q.kind === "match") {
      var rows = el("div", "quiz-match");
      q.choices.forEach(function (left, i) {
        var row = el("label", "quiz-match-row");
        var term = el("span", "quiz-match-left");
        md(term, left, true);
        var pick = el("select", "field quiz-match-pick");
        pick.setAttribute("aria-label", "Match for " + left);
        var none = el("option", "", "Choose…");
        none.value = "";
        pick.appendChild(none);
        q.options.forEach(function (o) {
          var opt = el("option", "", o);
          opt.value = o;
          pick.appendChild(opt);
        });
        row.appendChild(term);
        row.appendChild(pick);
        rows.appendChild(row);
        inputs.push(pick);
      });
      box.appendChild(rows);
    } else if (q.kind === "choice") {
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
    } else if (q.kind === "predict") {
      // A box with room for a few lines: output is often more than one.
      var guess = el("textarea", "field quiz-text quiz-predict");
      guess.rows = 3;
      guess.maxLength = 2000;
      guess.placeholder = "What will it print?";
      guess.setAttribute("aria-label", "What it will print");
      box.appendChild(guess);
      inputs.push(guess);
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
    // Predict: the code, run — once there's nothing left to give away.
    var runIt = q.kind === "predict" ? predictRun(q, box) : null;
    function disable() {
      inputs.forEach(function (i) { i.disabled = true; });
      if (custom) custom.enable(false);
    }

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
      md(key, q.kind === "choice" ? "Answer: " + q.correct.join(" or ")
        : q.kind === "blank" ? "Answers: " + q.answers.map(function (a) {
            return a.join(" or ");
          }).join(" · ")
        : q.kind === "match" || q.kind === "sort" ? q.choices.map(function (l, i) {
            return l + " → " + (q.correct[i] || "?");
          }).join("; ")
        : q.kind === "order" ? "In order, shown above."
        : q.kind === "bug" ? "The bug is on line " + q.correct.join(" or ") + "."
        : "Accepted: " + q.answers.join(" · "), true);
      show.addEventListener("click", function () {
        key.hidden = !key.hidden;
        show.textContent = key.hidden ? "Show answer" : "Hide answer";
        if (custom) custom.showKey(!key.hidden);
        Array.prototype.forEach.call(box.querySelectorAll(".quiz-choice"),
          function (lab, i) {
            lab.classList.toggle("quiz-is-key",
              !key.hidden && q.correct.indexOf(q.choices[i]) !== -1);
          });
      });
      foot.appendChild(show);
      foot.appendChild(key);
      if (runIt) runIt.show(true);
      // The same test quiz.parse makes before it gives a question an id.
      var usable = q.prompt.trim() && q.points > 0 && (
        q.kind === "text" ? q.answers.length
        : q.kind === "blank" ? q.answers.length && q.answers.every(function (a) { return a.length; })
        : q.kind === "match" ? q.choices.length >= 2 && q.correct.length === q.choices.length
        : q.kind === "order" ? q.correct.length >= 2 && q.correct.some(function (c) { return c !== q.correct[0]; })
        : q.kind === "sort" ? q.answers.length >= 2 && q.choices.length >= 2
            && q.correct.every(function (c) { return q.answers.indexOf(c) >= 0; })
        : q.kind === "predict" ? q.answers.length && codeLines(q.prompt).length
        : q.kind === "bug" ? codeLines(q.prompt).length >= 2 && q.correct.length
            && q.correct.every(function (c) { return /^\d+$/.test(c) && +c >= 1 && +c <= codeLines(q.prompt).length; })
        : q.choices.length >= 2 && q.correct.length);
      if (!usable) {
        foot.appendChild(el("span", "quiz-warn small",
          q.kind === "blank" ? "Not answerable yet: every [[blank]] needs an answer inside it."
          : q.kind === "match" ? "Not answerable yet: it needs two or more lines like - left -> right, each with a right."
          : q.kind === "order" ? "Not answerable yet: it needs two or more - lines, written in the right order."
          : q.kind === "sort" ? "Not answerable yet: it needs two or more group: lines, each with - items under it."
          : q.kind === "bug" ? "Not answerable yet: it needs code in a ~~~ fence and a bug: line naming one of its lines."
          : q.kind === "predict" ? "Not answerable yet: it needs code in a ~~~ fence and an answer: line with what it prints."
          : "Not answerable yet: it needs a question, two or more choices with one marked [x], or an answer: line."));
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
    // A class's view-only link: the question as students see it, unanswerable
    // — whoever is looking, signed in or not, is not one of the class.
    if (quizCtx.viewOnly) {
      disable();
      foot.appendChild(el("span", "dim small", "View only: answers aren't recorded here."));
      return box;
    }
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

    var many = q.kind === "blank" || q.kind === "match";
    if (custom) custom.onChange(function () { pending[q.id] = current(); });
    function current() {
      if (custom) return custom.get();
      if (many) return JSON.stringify(inputs.map(function (i) { return i.value.trim(); }));
      if (q.kind === "text" || q.kind === "predict") return inputs[0].value;
      var on = inputs.filter(function (i) { return i.checked; })[0];
      return on ? on.value : "";
    }
    // Typing or picking survives the notes being re-rendered under it — the
    // teacher editing the notes mid-question would otherwise wipe it.
    inputs.forEach(function (i) {
      var typed = q.kind === "text" || q.kind === "blank" || q.kind === "predict";
      i.addEventListener(typed ? "input" : "change", function () {
        pending[q.id] = current();
      });
      // Enter sends a one-line answer; a prediction's box takes new lines.
      if (typed && q.kind !== "predict") {
        i.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); send.click(); }
        });
      }
    });
    function restore(value) {
      if (custom) { custom.set(value); return; }
      if (many) {
        var got = [];
        try { got = JSON.parse(value || "[]"); } catch (e) { got = []; }
        inputs.forEach(function (i, k) { i.value = (got && got[k]) || ""; });
        return;
      }
      if (q.kind === "text" || q.kind === "predict") inputs[0].value = value || "";
      else inputs.forEach(function (i) { i.checked = i.value === value; });
    }

    box.paint = function () {
      var got = answered[q.id];
      if (!got) {
        restore(pending[q.id]);
        inputs.forEach(function (i) { i.disabled = false; });
        if (custom) custom.enable(true);
        send.disabled = false;
        return;
      }
      restore(got.response);
      disable();
      send.hidden = true;
      if (runIt) runIt.show(false);
      var partly = !got.correct && got.earned > 0;
      box.classList.toggle("quiz-right", !!got.correct);
      box.classList.toggle("quiz-partial", partly);
      box.classList.toggle("quiz-wrong", !got.correct && !partly);
      note.className = "quiz-result small";
      note.textContent = (got.correct
        ? "✓ Correct — " + pointsText(got.points)
        : partly ? "◐ Partly right — " + got.earned + " of " + pointsText(got.points)
        : "✗ Not quite — 0 of " + pointsText(got.points))
        + (got.practice ? " (your own question, so not recorded)" : "");
    };

    send.addEventListener("click", function () {
      var value = current();
      if (custom && !custom.filled()) {
        note.textContent = q.kind === "sort" ? "Put every item in a group first." : "Click the line with the bug first.";
        return;
      }
      if (many && inputs.some(function (i) { return !i.value.trim(); })) {
        note.textContent = q.kind === "blank" ? "Fill in every blank first." : "Match every item first.";
        return;
      }
      if (!value.trim()) {
        note.textContent = q.kind === "text" || q.kind === "predict" ? "Type an answer first." : "Pick an answer first.";
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
        announceTurnIn(out.d);
        announceXp(out.d);
      }).catch(function () {
        send.disabled = false;
        note.textContent = "No connection — your answer wasn't sent. Try again.";
      });
    });

    loadMine().then(function () { box.paint(); });
    return box;
  }

  // ------------------------------------------- order, sort and find the bug
  /* Each is {node, get, set, enable, filled, onChange, showKey}. get() is
     the response as the server takes it (quiz.py): the lines in the
     student's order as JSON; each item's group as JSON, "" for unsorted;
     the bug's line number. Every one works by click (or tap) as well as by
     dragging, because a Chromebook's trackpad drag is a fight and a phone
     has no drag at all. */
  function button(cls, text, title) {
    var b = el("button", cls, text);
    b.type = "button";
    if (title) b.title = title;
    return b;
  }

  function orderWidget(q) {
    var list = el("ol", "quiz-order");
    var order = q.choices.slice(), enabled = false, changed = function () {};
    function move(from, to) {
      if (to < 0 || to >= order.length || from === to) return;
      order.splice(to, 0, order.splice(from, 1)[0]);
      draw();
      changed();
    }
    function draw() {
      list.textContent = "";
      order.forEach(function (line, i) {
        var row = el("li", "quiz-order-row");
        row.draggable = enabled;
        // textContent, so a line's own indentation is kept (white-space: pre).
        row.appendChild(el("code", "quiz-order-line", line));
        var up = button("quiz-order-btn", "▲", "Move up");
        var down = button("quiz-order-btn", "▼", "Move down");
        up.disabled = !enabled || i === 0;
        down.disabled = !enabled || i === order.length - 1;
        up.addEventListener("click", function () { move(i, i - 1); });
        down.addEventListener("click", function () { move(i, i + 1); });
        row.addEventListener("dragstart", function (e) { e.dataTransfer.setData("text/plain", String(i)); });
        row.addEventListener("dragover", function (e) { if (enabled) e.preventDefault(); });
        row.addEventListener("drop", function (e) {
          e.preventDefault();
          var from = Number(e.dataTransfer.getData("text/plain"));
          if (!isNaN(from)) move(from, i);
        });
        row.appendChild(up);
        row.appendChild(down);
        list.appendChild(row);
      });
    }
    draw();
    return {
      node: list,
      get: function () { return JSON.stringify(order); },
      set: function (v) {
        var got = null;
        try { got = JSON.parse(v || "null"); } catch (e) { got = null; }
        order = Array.isArray(got) && got.length === q.choices.length ? got.slice() : q.choices.slice();
        draw();
      },
      enable: function (on) { enabled = on; draw(); },
      filled: function () { return true; },
      onChange: function (fn) { changed = fn; },
      showKey: function (on) { order = (on ? q.correct : q.choices).slice(); draw(); }
    };
  }

  function sortWidget(q) {
    var wrap = el("div", "quiz-sort");
    var placed = q.choices.map(function () { return ""; });
    var picked = -1, enabled = false, changed = function () {};
    function put(i, group) {
      placed[i] = group;
      picked = -1;
      draw();
      changed();
    }
    function draw() {
      wrap.textContent = "";
      [""].concat(q.answers).forEach(function (group) {
        // The tray, once it's empty and the question can't change, says nothing.
        if (!group && !enabled && placed.every(function (g) { return g; })) return;
        var zone = el("div", group ? "quiz-sort-group" : "quiz-sort-tray");
        zone.appendChild(el("div", "quiz-sort-head", group || "Not sorted yet"));
        var holder = el("div", "quiz-sort-items");
        q.choices.forEach(function (item, i) {
          if (placed[i] !== group) return;
          var chip = button("quiz-sort-item" + (picked === i ? " is-picked" : ""), undefined,
                            enabled ? "Click it, then click the group it belongs in" : "");
          md(chip, item, true);
          chip.disabled = !enabled;
          chip.draggable = enabled;
          chip.addEventListener("click", function (e) {
            e.stopPropagation();
            // With another item picked, a click on an item in a different
            // group puts it there: a group's box fills with items, and a
            // click aimed at the box landed on one of them and only changed
            // which was picked.
            if (picked >= 0 && picked !== i && placed[picked] !== placed[i]) return put(picked, placed[i]);
            picked = picked === i ? -1 : i;
            draw();
          });
          chip.addEventListener("dragstart", function (e) { e.dataTransfer.setData("text/plain", String(i)); });
          holder.appendChild(chip);
        });
        zone.appendChild(holder);
        zone.classList.toggle("is-target", enabled && picked >= 0);
        zone.addEventListener("click", function () { if (enabled && picked >= 0) put(picked, group); });
        zone.addEventListener("dragover", function (e) { if (enabled) e.preventDefault(); });
        zone.addEventListener("drop", function (e) {
          e.preventDefault();
          var i = Number(e.dataTransfer.getData("text/plain"));
          if (enabled && !isNaN(i)) put(i, group);
        });
        wrap.appendChild(zone);
      });
    }
    draw();
    return {
      node: wrap,
      get: function () { return JSON.stringify(placed); },
      set: function (v) {
        var got = null;
        try { got = JSON.parse(v || "null"); } catch (e) { got = null; }
        placed = Array.isArray(got) && got.length === q.choices.length
          ? got.map(function (g) { return q.answers.indexOf(g) >= 0 ? g : ""; })
          : q.choices.map(function () { return ""; });
        draw();
      },
      enable: function (on) { enabled = on; draw(); },
      filled: function () { return placed.every(function (g) { return g; }); },
      onChange: function (fn) { changed = fn; },
      showKey: function (on) {
        placed = on ? q.correct.slice() : q.choices.map(function () { return ""; });
        draw();
      }
    };
  }

  /* The question's code, already rendered in the prompt, swapped for a
     button per line: the student clicks the one that's wrong. */
  function bugWidget(q, prompt) {
    var lines = codeLines(q.prompt);
    var box = el("div", "quiz-bug");
    var chosen = "", enabled = false, keyShown = false, changed = function () {};
    function draw() {
      box.textContent = "";
      lines.forEach(function (line, i) {
        var n = String(i + 1);
        var b = button("quiz-bug-line" + (chosen === n ? " is-picked" : "")
                       + (keyShown && q.correct.indexOf(n) >= 0 ? " quiz-is-key" : ""));
        b.disabled = !enabled;
        b.setAttribute("aria-label", "Line " + n + ": " + line);
        b.appendChild(el("span", "quiz-bug-num", n));
        b.appendChild(el("code", "quiz-bug-code", line || " "));
        b.addEventListener("click", function () { chosen = n; draw(); changed(); });
        box.appendChild(b);
      });
    }
    var pre = prompt.querySelector("pre");
    if (pre) pre.parentNode.replaceChild(box, pre);
    draw();
    return {
      node: pre ? null : box,
      get: function () { return chosen; },
      set: function (v) { chosen = /^\d+$/.test(String(v || "")) ? String(v) : ""; draw(); },
      enable: function (on) { enabled = on; draw(); },
      filled: function () { return !!chosen; },
      onChange: function (fn) { changed = fn; },
      showKey: function (on) { keyShown = on; draw(); }
    };
  }

  /* A predict question's ▶ Run it: the code in the question, run where the
     page has the snippet runner (snippets.js), with what it printed under
     it. Shown to a student only once they've answered — before, it would be
     the answer — and in the teacher's preview, where it also offers the
     output as the question's answer: line, ready to paste. */
  function predictRun(q, box) {
    var wrap = el("div", "quiz-predict-run");
    wrap.hidden = true;
    var btn = el("button", "btn quiz-run", "▶ Run it");
    btn.type = "button";
    var copy = el("button", "linkbtn quiz-copy-answer", "Copy as the answer: line");
    copy.type = "button";
    copy.hidden = true;
    var said = el("span", "dim small");
    var out = el("pre", "snippet-out");
    out.hidden = true;
    wrap.appendChild(btn);
    wrap.appendChild(copy);
    wrap.appendChild(said);
    wrap.appendChild(out);
    box.insertBefore(wrap, box.querySelector(".quiz-foot"));
    var printed = "", forTeacher = false;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      said.textContent = "Running…";
      // The fence says which language: ~~~js runs as JavaScript (WebIDE), anything else as Python.
      var js = /^(js|javascript)$/i.test(codeLang(q.prompt));
      (js ? window.IDESnippets.runJs : window.IDESnippets.run)(codeLines(q.prompt).join("\n")).then(function (r) {
        btn.disabled = false;
        said.textContent = "";
        printed = r.text;
        out.hidden = false;
        out.textContent = r.text || (r.error ? "" : "(It printed nothing.)");
        if (r.error) out.appendChild(el("span", "snippet-err", (r.text ? "\n" : "") + r.error));
        copy.hidden = !forTeacher || !r.text.trim();
      });
    });
    copy.addEventListener("click", function () {
      var line = "answer: " + printed.replace(/\s+/g, " ").trim();
      var done = function () { said.textContent = "Copied — paste it into the question."; };
      if (navigator.clipboard) navigator.clipboard.writeText(line).then(done, function () { said.textContent = line; });
      else said.textContent = line;
    });
    return {
      show: function (teacher) {
        if (!window.IDESnippets || !window.IDESnippets.run) return;
        forTeacher = teacher;
        wrap.hidden = false;
        btn.title = teacher ? "Run the question's code" : "See what it really prints";
      }
    };
  }

  /* The blanks in a rendered prompt: every %%BLANKn%% marker in its text,
     code included, replaced by a box, in order. A marker the markdown
     broke up (it never should) is simply left as text, and the question
     then has fewer boxes than blanks — which the server marks as empty. */
  function fillBlanks(root) {
    var found = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var parts = node.nodeValue.split(/%%BLANK(\d+)%%/);
      if (parts.length < 2) return;
      var frag = document.createDocumentFragment();
      parts.forEach(function (part, i) {
        if (i % 2 === 0) { if (part) frag.appendChild(document.createTextNode(part)); return; }
        var box = el("input", "field quiz-blank");
        box.type = "text";
        box.maxLength = 300;
        box.setAttribute("aria-label", "Blank " + (Number(part) + 1));
        box.dataset.blank = part;
        frag.appendChild(box);
      });
      node.parentNode.replaceChild(frag, node);
    });
    Array.prototype.forEach.call(root.querySelectorAll("input.quiz-blank"), function (b) {
      found[Number(b.dataset.blank)] = b;
    });
    return found.filter(Boolean);
  }

  // --------------------------------------------------- long responses
  /* A long response: a box to write in, with a small toolbar — bold,
     italic, underline and two kinds of list — and no key. The teacher marks
     it by hand on the assignment's page; until then the student is told it
     is waiting, never right or wrong.

     What is sent is the box's HTML, cut down to those few tags and NO
     attributes (LONG_RULES). The server cuts it down again (quiz.clean_html)
     because a request need not come from this page, and both are needed for
     the same reason: the answer is drawn as markup on the teacher's screen.

     Pasting goes in as plain text. Pasted from Google Docs or Word, a
     paragraph brings a page of spans and styles that the cleaning would
     strip anyway — and until then the box would look formatted in ways the
     teacher will never see.

     What is typed is kept in this browser until it is sent, as well as in
     `pending`: a paragraph lost to a closed tab or a dead Chromebook
     battery is the failure worth guarding against here. */
  var LONG_RULES = {
    ALLOWED_TAGS: ["p", "div", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li"],
    ALLOWED_ATTR: []
  };
  var LONG_MAX = 20000;

  function cleanLong(html) {
    return window.DOMPurify ? window.DOMPurify.sanitize(html || "", LONG_RULES) : "";
  }

  function longKey(qid) { return "pyide-long:" + quizCtx.assignment + ":" + qid; }
  function longLoad(qid) {
    try { return localStorage.getItem(longKey(qid)) || ""; } catch (e) { return ""; }
  }
  function longStore(qid, html) {
    try {
      if (html) localStorage.setItem(longKey(qid), html);
      else localStorage.removeItem(longKey(qid));
    } catch (e) { /* private window: pending still holds it for this page */ }
  }

  var LONG_TOOLS = [
    ["bold", "B", "Bold"], ["italic", "I", "Italic"], ["underline", "U", "Underline"],
    ["insertUnorderedList", "• List", "Bulleted list"],
    ["insertOrderedList", "1. List", "Numbered list"]
  ];

  function buildLong(q, box) {
    box.classList.add("quiz-long");
    var bar = el("div", "quiz-long-bar");
    var area = el("div", "quiz-long-box");
    area.setAttribute("role", "textbox");
    area.setAttribute("aria-multiline", "true");
    area.setAttribute("aria-label", "Your answer");
    area.dataset.placeholder = "Write your answer here.";
    LONG_TOOLS.forEach(function (t) {
      var b = el("button", "quiz-tool quiz-tool-" + t[0], t[1]);
      b.type = "button";
      b.title = t[2];
      // mousedown, not click: a click moves focus to the button first and
      // the selection the student made is gone before the command runs.
      b.addEventListener("mousedown", function (e) {
        e.preventDefault();
        if (area.contentEditable !== "true") return;
        area.focus();
        document.execCommand(t[0], false, null);
        changed();
      });
      bar.appendChild(b);
    });
    var foot = el("div", "quiz-foot");
    box.appendChild(bar);
    box.appendChild(area);
    box.appendChild(foot);

    function editable(on) {
      area.contentEditable = on ? "true" : "false";
      box.classList.toggle("quiz-long-locked", !on);
    }
    editable(false);

    // The teacher's own copy: no id yet, and nothing to reveal.
    if (!q.id) {
      box.classList.add("quiz-preview");
      foot.appendChild(el("span", "dim small",
        "Students write their answer here. You mark it on the assignment's page."));
      if (!(q.prompt.trim() && q.points > 0)) {
        foot.appendChild(el("span", "quiz-warn small",
          "Not answerable yet: it needs a question and points above 0."));
      }
      return box;
    }
    box.dataset.qid = q.id;
    if (quizCtx.viewOnly) {
      foot.appendChild(el("span", "dim small", "View only: answers aren't recorded here."));
      return box;
    }
    if (!quizCtx.assignment) {
      foot.appendChild(el("span", "dim small",
        "Answers are only recorded on an assignment, so this one can't be answered here."));
      return box;
    }
    if (!quizCtx.signedIn) {
      var a = el("a", "", "Sign in");
      a.href = "/login?next=" + encodeURIComponent(location.pathname);
      foot.appendChild(a);
      foot.appendChild(document.createTextNode(" to answer this question."));
      foot.classList.add("small");
      return box;
    }

    var send = el("button", "btn btn-primary quiz-send", "Turn in answer");
    send.type = "button";
    send.disabled = true;
    var note = el("span", "quiz-result small dim",
                  "One try — once it's turned in it can't be changed.");
    foot.appendChild(send);
    foot.appendChild(note);

    function changed() {
      var html = area.textContent.trim() ? cleanLong(area.innerHTML) : "";
      pending[q.id] = html;
      longStore(q.id, html);
      if (html.length > LONG_MAX) note.textContent = "That's too long to turn in — make it shorter.";
    }
    area.addEventListener("input", changed);
    area.addEventListener("paste", function (e) {
      var text = (e.clipboardData || window.clipboardData).getData("text/plain");
      e.preventDefault();
      document.execCommand("insertText", false, text);
    });
    area.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && /^[biu]$/i.test(e.key)) {
        e.preventDefault();
        document.execCommand({ b: "bold", i: "italic", u: "underline" }[e.key.toLowerCase()]);
        changed();
      }
    });

    box.paint = function () {
      var got = answered[q.id];
      if (!got) {
        if (!area.innerHTML) area.innerHTML = cleanLong(pending[q.id] || longLoad(q.id));
        editable(true);
        send.disabled = false;
        return;
      }
      area.innerHTML = cleanLong(got.response);
      editable(false);
      bar.hidden = true;
      send.hidden = true;
      longStore(q.id, "");
      note.className = "quiz-result small";
      note.textContent = got.graded
        ? "Marked — " + got.earned + " of " + pointsText(got.points)
        : "✓ Turned in — your teacher will mark it.";
      box.classList.toggle("quiz-marked", !!got.graded);
    };

    send.addEventListener("click", function () {
      var value = area.textContent.trim() ? cleanLong(area.innerHTML) : "";
      if (!value) { note.textContent = "Write an answer first."; return; }
      if (value.length > LONG_MAX) { note.textContent = "That's too long to turn in — make it shorter."; return; }
      if (!confirm("Turn in this answer? You can't change it afterwards.")) return;
      send.disabled = true;
      note.textContent = "Sending…";
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
        announceTurnIn(out.d);
        announceXp(out.d);
      }).catch(function () {
        send.disabled = false;
        note.textContent = "No connection — your answer wasn't sent. It's kept here; try again.";
      });
    });

    loadMine().then(function () { box.paint(); });
    return box;
  }

  /* XP the answer earned (app.py, _quiz_xp), shown the way a run's is.
     Only where the page has xp.js; the answer never depends on it. */
  function announceXp(reply) {
    if (reply && reply.xp > 0 && window.PyIDEXP) window.PyIDEXP.toast("+" + reply.xp + " XP");
  }

  /* Answering a question turns the work in (the server's _auto_turn_in).
     Each page has its own Turn in button and status — the editor's, the
     lesson's, the live page's — so this only says it happened, and each
     page listens for "pyide:turnedin" and updates its own. */
  function announceTurnIn(reply) {
    if (!reply || !reply.turned_in_at) return;
    try {
      document.dispatchEvent(new CustomEvent("pyide:turnedin",
                                             { detail: { when: reply.turned_in_at } }));
    } catch (e) { /* an old browser: the button just says what it said */ }
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
    parseCards: parseCards,
    runFences: runFences,
    scramble: scramble,
    cleanLong: cleanLong,
    isMarkdown: isMarkdown,
    slides: slides,
    takeTheme: takeTheme,
    takeHeader: takeHeader, SPEEDS: SPEEDS, pauseLines: pauseLines,
    popMarks: popMarks,
    sections: sections,
    THEMES: THEMES,
    render: render,
    ensureRenderer: ensureRenderer,
    parseQuiz: parseQuiz,
    setQuizContext: setQuizContext,
    slideView: slideView
  };
})();
