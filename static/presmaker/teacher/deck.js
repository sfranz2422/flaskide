/* PresMaker — teacher slides, the projected page (written into the .html by
 * teacher.js, after the slides). Everything is in this one script, so the
 * file opens anywhere, offline:
 *
 *   → / space / PageDown (a clicker) shows the slide's next step — a hidden
 *   output, an answer, a bug, the next line of a trace — and only then moves
 *   to the next slide. ← / PageUp takes a step back.
 *   N picks a student (no repeats until everyone has had a turn), S shows a
 *   team scoreboard (1–4 add a point, Shift takes one away), C sets up the
 *   class list and teams, F is full screen.
 *
 * A slide's steps are its .reveal and .stage elements and the lines of its
 * traces, in page order. Each slide is shrunk (CSS zoom) until it fits at
 * every one of its steps, so nothing jumps and nothing runs off the screen.
 */
(function () {
  "use strict";

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function $(id) { return document.getElementById(id); }

  // ------------------------------------------------------- highlighting
  // One line at a time, so every line can be wrapped (traces, bugs).
  var RULES = {
    py: [/(#.*$)|(f?"[^"]*"|f?'[^']*')|\b(True|False|None|def|return|for|while|in|if|elif|else|import|from|as|and|or|not|is|class|with|lambda|pass|break|continue|try|except|finally|raise|global|yield)\b|\b(print|len|type|range|int|str|float|input|list|dict|tuple|set|upper|lower|round|sum|min|max|sorted|abs|enumerate|zip|open|append)\b|(\b\d+(?:\.\d+)?\b)|([{}\[\]()])/g,
         ["hc", "hs", "hk", "hb", "hn", "hp"]],
    js: [/(\/\/.*$)|("[^"]*"|'[^']*'|`[^`]*`)|\b(const|let|var|function|return|if|else|for|while|of|in|new|class|this|true|false|null|undefined|await|async|break|continue)\b|\b(console|document|window|log|addEventListener|querySelector|querySelectorAll|getElementById|textContent|innerHTML|value)\b|(\b\d+(?:\.\d+)?\b)|([{}\[\]()])/g,
         ["hc", "hs", "hk", "hb", "hn", "hp"]],
    css: [/(\/\*.*?\*\/)|("[^"]*"|'[^']*')|([\w-]+)(?=\s*:[^:]*;|\s*:\s*$)|(#[0-9a-fA-F]{3,8}\b|\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|deg)?)|(@[\w-]+)|([{}();])/g,
          ["hc", "hs", "ha", "hn", "hk", "hp"]]
  };
  function hlRule(line, rule) {
    var re = rule[0], cls = rule[1], out = "", last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(line))) {
      if (!m[0]) { re.lastIndex++; continue; }
      out += esc(line.slice(last, m.index));
      for (var g = 1; g < m.length; g++) {
        if (m[g] !== undefined) {
          var t = esc(m[0]);
          // f-strings: the {…} parts in the bracket colour
          if (cls[g - 1] === "hs" && m[0].charAt(0) === "f")
            t = t.replace(/\{([^}]*)\}/g, '</span><span class="hp">{</span>$1<span class="hp">}</span><span class="hs">');
          out += '<span class="' + cls[g - 1] + '">' + t + "</span>";
          break;
        }
      }
      last = re.lastIndex;
    }
    return out + esc(line.slice(last));
  }
  function hlHTML(line) {
    return esc(line).replace(/&lt;!--.*?--&gt;/g, function (c) { return '<span class="hc">' + c + "</span>"; })
      .replace(/(&lt;\/?)([\w-]+)((?:[^&]|&(?!gt;))*?)(\/?&gt;)/g, function (_, open, tag, attrs, close) {
        attrs = attrs.replace(/([\w-:]+)(=)("[^"]*"|'[^']*')/g, '<span class="ha">$1</span>$2<span class="hs">$3</span>');
        return '<span class="hp">' + open + '</span><span class="ht">' + tag + "</span>" + attrs + '<span class="hp">' + close + "</span>";
      });
  }
  function highlight(pre) {
    var lang = pre.dataset.lang, blanks = pre.dataset.blanks ? JSON.parse(pre.dataset.blanks) : [];
    var lines = pre.textContent.replace(/\n$/, "").split("\n").map(function (l) {
      var h = lang === "html" ? hlHTML(l) : RULES[lang] ? hlRule(l, RULES[lang]) : esc(l);
      // a blank of a fill-in-the-blank question: a ? that fills in
      return h.replace(/\u0001(\d+)\u0002/g, function (_, k) {
        return '<span class="ans stage" data-a="' + esc(blanks[+k] || "").replace(/"/g, "&quot;") + '"></span>';
      });
    });
    pre.innerHTML = lines.map(function (l) { return '<span class="ln">' + l + "</span>"; }).join("");
    if (pre.dataset.bug) {
      var ln = pre.querySelectorAll(".ln")[pre.dataset.bug - 1];
      if (ln) ln.classList.add("isbug");
    }
  }
  Array.prototype.forEach.call(document.querySelectorAll("pre.code"), highlight);

  // -------------------------------------------------------------- traces
  var TRACES = {};
  try { TRACES = JSON.parse($("traces").textContent); } catch (e) { /* none */ }
  function setTrace(pre, i) {             // i = -1: not started
    var steps = TRACES[pre.dataset.trace] || [];
    var panel = document.querySelector('.tracer[data-for="' + pre.dataset.trace + '"]');
    var lines = pre.querySelectorAll(".ln");
    Array.prototype.forEach.call(lines, function (l) { l.classList.remove("now", "skip"); });
    for (var k = 0; k <= i; k++) {
      (steps[k].skip || []).forEach(function (n) { if (lines[n - 1]) lines[n - 1].classList.add("skip"); });
    }
    var st = steps[i];
    if (st && lines[st.l - 1]) lines[st.l - 1].classList.add("now");
    var vars = st && st.vars && Object.keys(st.vars).length
      ? Object.keys(st.vars).map(function (k) { return "<span><b>" + esc(k) + "</b> = <i>" + esc(st.vars[k]) + "</i></span>"; }).join("")
      : '<span class="none">no variables right now</span>';
    panel.innerHTML = '<div class="tnote' + (st ? "" : " idle") + '">' +
      (st ? "<b>Line " + st.l + ":</b> " + st.note : "Press → to run it one line at a time.") + "</div>" +
      '<span class="label">variables</span><div class="tvars">' + vars + "</div>" +
      '<pre class="out">' + esc(st ? st.out : "") + "</pre>";
  }

  // --------------------------------------------------------------- steps
  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  slides.forEach(function (s) {
    s.steps = [];
    Array.prototype.forEach.call(s.querySelectorAll(".reveal, .stage, pre[data-trace]"), function (el) {
      if (el.dataset.trace) (TRACES[el.dataset.trace] || []).forEach(function (_, k) { s.steps.push({ trace: el, k: k }); });
      else s.steps.push({ el: el });
    });
    s.shownSteps = 0;
  });
  function render(s, n) {
    Array.prototype.forEach.call(s.querySelectorAll(".reveal, .stage"), function (el) { el.classList.remove("shown"); });
    Array.prototype.forEach.call(s.querySelectorAll("pre[data-trace]"), function (p) { setTrace(p, -1); });
    s.steps.slice(0, n).forEach(function (st) { if (st.trace) setTrace(st.trace, st.k); else st.el.classList.add("shown"); });
    s.shownSteps = n;
  }

  // ----------------------------------------------------------------- fit
  function sizeFrames(s) {
    Array.prototype.forEach.call(s.querySelectorAll(".preview iframe"), function (f) {
      try {
        var d = f.contentDocument;
        // the body's own height: the page's is never less than the frame
        if (d && d.body) f.style.height = Math.min(Math.max(Math.ceil(d.body.getBoundingClientRect().height) + 24, 50), window.innerHeight * 0.45) + "px";
      } catch (e) { /* not ours to measure */ }
    });
  }
  function overflows(s, inner) {
    var cs = getComputedStyle(s);
    var room = s.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    if (inner.getBoundingClientRect().height > room + 1) return true;
    return Array.prototype.some.call(inner.querySelectorAll("pre, .cols, table, .opts li"), function (e) {
      return e.scrollWidth > e.clientWidth + 1;
    });
  }
  function fit(s) {
    var inner = s.querySelector(".inner");
    if (!inner) return;
    inner.style.zoom = 1;
    if (window.innerWidth <= 760) return;              // phones scroll instead
    s.classList.add("fitting");
    // HTML code too wide to sit beside its preview goes above it instead
    Array.prototype.forEach.call(inner.querySelectorAll(".html-row"), function (row) {
      row.classList.remove("stack");
      var code = row.querySelector("pre");
      if (code && code.scrollWidth > code.clientWidth + 1) row.classList.add("stack");
    });
    var keep = s.shownSteps, states = [s.steps.length];
    // a trace's panel changes height as it runs: fit every step of it
    if (s.querySelector("pre[data-trace]")) for (var k = 0; k < s.steps.length; k++) states.push(k);
    var z = 1;
    states.forEach(function (n) {
      render(s, n);
      inner.style.zoom = z;
      while (z > 0.5 && overflows(s, inner)) { z -= 0.04; inner.style.zoom = z; }
    });
    render(s, keep);
    s.classList.remove("fitting");
  }

  // ---------------------------------------------------------- navigation
  var i = 0;
  var start = parseInt(location.hash.slice(1), 10);
  if (start >= 1 && start <= slides.length) i = start - 1;
  function show(n, all) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) { s.classList.toggle("active", k === i); });
    var s = slides[i];
    sizeFrames(s);
    render(s, all ? s.steps.length : 0);
    fit(s);
    updateNav();
    try { history.replaceState(null, "", "#" + (i + 1)); } catch (e) { /* file: in some browsers */ }
  }
  function updateNav() {
    var s = slides[i], left = s.steps.length - s.shownSteps;
    $("count").textContent = (i + 1) + " / " + slides.length;
    $("steps").textContent = s.steps.length ? (left ? "▸ " + left + " left" : "✓") : "";
    $("bar").style.width = ((i + 1) / slides.length * 100) + "%";
  }
  function next() { var s = slides[i]; if (s.shownSteps < s.steps.length) { render(s, s.shownSteps + 1); updateNav(); } else show(i + 1); }
  function prev() { var s = slides[i]; if (s.shownSteps > 0) { render(s, s.shownSteps - 1); updateNav(); } else if (i > 0) show(i - 1, true); }

  // ------------------------------------------- the page's own controls
  document.body.insertAdjacentHTML("beforeend",
    '<div class="bar" id="bar"></div>' +
    '<div class="hint">→ next · N pick a name · S scoreboard (1–4 add, Shift subtracts) · C class setup · F full screen</div>' +
    '<div class="nav"><span class="steps" id="steps"></span>' +
    '<button id="pick" aria-label="Pick a random name" title="Pick a name (N)">🎲</button>' +
    '<button id="prev" aria-label="Previous">‹</button><span id="count"></span>' +
    '<button id="next" aria-label="Next">›</button></div>' +
    '<div class="score" id="score"></div>' +
    '<div class="overlay" id="picker"><div class="box"><div class="picked" id="picked"></div><p id="pickInfo"></p>' +
    "<p>N or space: pick again · Esc: close</p></div></div>" +
    '<div class="overlay" id="setup"><div class="box setup"><h3>Class setup</h3>' +
    '<label for="roster">Class list: one name per line</label><textarea id="roster" placeholder="Ava&#10;Leo&#10;Sam"></textarea>' +
    '<label for="teams">Teams: separate with commas (up to 4)</label><input id="teams" placeholder="Team 1, Team 2">' +
    "<p>Saved in this browser only, so you type it once.</p>" +
    '<div class="row"><button id="resetScores">Reset scores</button><button id="closeSetup">Cancel</button>' +
    '<button id="saveSetup" class="main">Save</button></div></div></div>');

  // Saved per browser. The class list is shared by every teacher deck;
  // the scores belong to this deck.
  var KEY = "pm-teacher-";
  var DECK = KEY + (document.body.dataset.key || "deck") + "-";
  function load(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window */ } }
  var roster = load(KEY + "roster", []), teams = load(KEY + "teams", ["Team 1", "Team 2"]);
  var scores = load(DECK + "scores", [0, 0]), scoreOn = load(DECK + "scoreOn", false);

  function drawScore(bump) {
    var box = $("score");
    box.classList.toggle("on", scoreOn);
    box.innerHTML = teams.map(function (t, k) {
      return '<div class="team' + (k === bump ? " bump" : "") + '"><div class="tn">' + esc(t) + '</div><div class="ts">' + (scores[k] || 0) + "</div>" +
        '<button data-t="' + k + '" data-d="-1" aria-label="Take a point from ' + esc(t) + '">−</button>' +
        '<button data-t="' + k + '" data-d="1" aria-label="Give a point to ' + esc(t) + '">+</button>' +
        '<div class="tk">key ' + (k + 1) + "</div></div>";
    }).join("");
  }
  function addPoint(t, d) {
    if (t >= teams.length) return;
    scores[t] = Math.max(0, (scores[t] || 0) + d);
    save(DECK + "scores", scores);
    drawScore(d > 0 ? t : -1);
  }
  $("score").addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) addPoint(+b.dataset.t, +b.dataset.d);
  });

  var bag = [], spinTimer = null;
  function pick() {
    var out = $("picked"), info = $("pickInfo");
    $("picker").classList.add("on");
    if (!roster.length) { out.classList.remove("spin"); out.textContent = "No class list"; info.textContent = "Press C to add your students' names."; return; }
    if (!bag.length) bag = roster.slice();
    var chosen = bag.splice(Math.floor(Math.random() * bag.length), 1)[0];
    clearInterval(spinTimer);
    out.classList.add("spin");
    info.textContent = "";
    var ticks = 0;
    spinTimer = setInterval(function () {
      out.textContent = roster[Math.floor(Math.random() * roster.length)];
      if (++ticks > 14) {
        clearInterval(spinTimer);
        out.classList.remove("spin");
        out.textContent = chosen;
        info.textContent = bag.length ? bag.length + " left before anyone repeats" : "Everyone's had a turn. The next pick starts over.";
      }
    }, 70);
  }

  function openSetup() {
    $("roster").value = roster.join("\n");
    $("teams").value = teams.join(", ");
    $("setup").classList.add("on");
    $("roster").focus();
  }
  function closeOverlays() {
    Array.prototype.forEach.call(document.querySelectorAll(".overlay"), function (o) { o.classList.remove("on"); });
    clearInterval(spinTimer);
  }
  $("saveSetup").onclick = function () {
    roster = $("roster").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
    var t = $("teams").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 4);
    if (t.length) { teams = t; scores = teams.map(function (_, k) { return scores[k] || 0; }); }
    bag = [];
    save(KEY + "roster", roster); save(KEY + "teams", teams); save(DECK + "scores", scores);
    drawScore();
    closeOverlays();
  };
  $("resetScores").onclick = function () { scores = teams.map(function () { return 0; }); save(DECK + "scores", scores); drawScore(); };
  $("closeSetup").onclick = closeOverlays;
  $("picker").addEventListener("click", function (e) { if (e.target.id === "picker") closeOverlays(); });

  $("next").onclick = next;
  $("prev").onclick = prev;
  $("pick").onclick = pick;
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeOverlays(); return; }
    if ($("setup").classList.contains("on")) return;          // typing names
    if ($("picker").classList.contains("on")) {
      if (e.key === "n" || e.key === "N" || e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } else closeOverlays();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var digit = /^Digit([1-4])$/.exec(e.code);
    if (digit && scoreOn) { addPoint(+digit[1] - 1, e.shiftKey ? -1 : 1); return; }
    if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].indexOf(e.key) >= 0) { e.preventDefault(); next(); }
    else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].indexOf(e.key) >= 0) { e.preventDefault(); prev(); }
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(slides.length - 1);
    else if (e.key === "n" || e.key === "N") pick();
    else if (e.key === "s" || e.key === "S") { scoreOn = !scoreOn; save(DECK + "scoreOn", scoreOn); drawScore(); }
    else if (e.key === "c" || e.key === "C") { e.preventDefault(); openSetup(); }
    else if (e.key === "f" || e.key === "F") {
      if (!document.fullscreenElement) { if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen(); }
      else document.exitFullscreen();
    }
  });
  var tx = null;
  document.addEventListener("touchstart", function (e) { tx = e.touches[0].clientX; }, { passive: true });
  document.addEventListener("touchend", function (e) {
    if (tx === null) return;
    var dx = e.changedTouches[0].clientX - tx;
    if (Math.abs(dx) > 50) (dx < 0 ? next : prev)();
    tx = null;
  });
  var resizing = null;
  window.addEventListener("resize", function () { clearTimeout(resizing); resizing = setTimeout(function () { fit(slides[i]); }, 150); });
  Array.prototype.forEach.call(document.querySelectorAll(".preview iframe"), function (f) {
    f.addEventListener("load", function () {
      var s = f.closest(".slide");
      if (s && s.classList.contains("active")) { sizeFrames(s); fit(s); }
    });
  });
  // Web fonts change every size: fit again once they're in.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { fit(slides[i]); });

  drawScore();
  show(i);
  window.PMTeacherDeck = { show: show, next: next, prev: prev, slides: slides, render: render, fit: fit };
})();
