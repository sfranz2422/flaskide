/* PresMaker — teacher slides (.html) opened to change them.
 *
 * The slide is the deck itself, running in a frame — its own CSS, its own
 * script — so what you change is what the class will see. Text on it can be
 * typed over; the HTML panel under it changes anything else. The list on the
 * left moves, copies and deletes slides; Insert adds new ones written the
 * way the deck's own are (deckfile.js template()).
 *
 * The deck's script redraws what it shows (highlighting, traces, answers
 * that fill in), so what's typed isn't read back off the page as is. Every
 * element of the slides is numbered (data-pm-n) in a copy kept here — the
 * source — and the frame is drawn from that copy. A typed edit finds its
 * element in the source by its number and changes only that, with the
 * deck's own marks (shown, now, …) taken off. The numbers never reach the
 * file: an unchanged slide is saved as it was read, byte for byte.
 */
(function () {
  "use strict";

  var F = window.PMDeckFile, D = window.PMDialogs, B = window.PMBridge, h = D.h;
  // Classes the decks' scripts put on while they run.
  var RUNTIME = ["shown", "now", "skip", "isbug", "on", "active", "spin", "bump", "fitting", "stack"];
  var W = 1366, H = 768;                 // the frame is a projector this size, scaled to the pane

  var d = null, path = "", cur = 0, tracesChanged = false, N = 0;
  var hooks = {}, undos = [], redos = [], lastTag = "", lastTime = 0;
  var frame, stage, list, htmlBox, cm = null, traceBar, stepInfo, presentBox, presentFrame;
  var showAll = true;

  function $(id) { return document.getElementById(id); }

  // ------------------------------------------------------------- source
  function tplOf(s) {
    if (!s.tpl) {
      s.tpl = document.createElement("template");
      s.tpl.innerHTML = s.html;
      s.tbody = /<tbody/i.test(s.html);
      stamp(s.tpl.content);
    }
    return s.tpl;
  }
  function stamp(root) {
    Array.prototype.forEach.call(root.querySelectorAll("*"), function (e) {
      if (!e.hasAttribute("data-pm-n")) e.setAttribute("data-pm-n", String(++N));
    });
  }
  /* A slide's HTML without the numbers — or the <tbody> the browser puts
     in every table, if the deck didn't write one. */
  function plain(s) {
    var box = document.createElement("div");
    box.appendChild(s.tpl.content.cloneNode(true));
    Array.prototype.forEach.call(box.querySelectorAll("[data-pm-n]"), function (e) { e.removeAttribute("data-pm-n"); });
    if (!s.tbody) {
      Array.prototype.forEach.call(box.querySelectorAll("tbody"), function (tb) {
        while (tb.firstChild) tb.parentNode.insertBefore(tb.firstChild, tb);
        tb.remove();
      });
    }
    return box.innerHTML;
  }
  function sectionOf(s) { return tplOf(s).content.querySelector("section"); }

  function text() { return d ? F.serialize(d, tracesChanged) : ""; }

  /* The page for the frame: numbered slides (editing) or the file as it
     will be saved (presenting), and a line that keeps the deck's script
     from writing #N into the frame's address. */
  function frameDoc(present) {
    var copy = { kind: d.kind, head: d.head, tail: d.tail, traces: d.traces, tracesSrc: d.tracesSrc,
                 slides: d.slides.map(function (s) { return { pre: s.pre, html: present ? s.html : tplOf(s).innerHTML }; }) };
    var t = F.serialize(copy, tracesChanged);
    var guard = "<script>try{history.replaceState=function(){};}catch(e){}</script>";
    var at = t.search(/<head[^>]*>/i);
    if (at >= 0) { var end = t.indexOf(">", at) + 1; t = t.slice(0, end) + guard + t.slice(end); }
    else t = guard + t;
    if (!present) {
      var css = "<style>.nav,.hint,.bar,#bar,.score,.overlay{display:none!important}" +
        "[data-pm-edit]{outline:2px dashed transparent;outline-offset:4px;border-radius:4px;cursor:text}" +
        "[data-pm-edit]:hover{outline-color:rgba(124,200,255,.65)}" +
        "[data-pm-edit]:focus{outline:2px solid #7cc8ff}" +
        ".ans[data-a]{cursor:pointer}</style>";
      var b = t.search(/<\/body>/i);
      t = b < 0 ? t + css : t.slice(0, b) + css + t.slice(b);
    }
    return t;
  }

  // ------------------------------------------------------------- frame
  function deckCall(w, fn, args) {
    try {
      if (w.PMTeacherDeck && w.PMTeacherDeck[fn]) return w.PMTeacherDeck[fn].apply(null, args);
      if (typeof w[fn] === "function") return w[fn].apply(null, args);
    } catch (e) { /* the deck's own script failed: the slide still shows */ }
  }
  function frameSlides() {
    var doc = frame.contentDocument;
    return doc ? doc.querySelectorAll(".deck > section, section.slide") : [];
  }

  var loading = false;
  function reload() {
    consistent();
    loading = true;
    frame.srcdoc = frameDoc(false);
  }
  function onFrameLoad() {
    if (!d || !loading) return;
    loading = false;
    var w = frame.contentWindow;
    // The deck's keys (N, S, C, arrows…) would fire while you type.
    ["keydown", "keyup", "keypress"].forEach(function (type) {
      w.addEventListener(type, function (e) { e.stopPropagation(); if (type === "keydown") frameKey(e); }, true);
    });
    ["touchstart", "touchend"].forEach(function (type) {
      w.addEventListener(type, function (e) { e.stopPropagation(); }, true);
    });
    var doc = frame.contentDocument;
    doc.addEventListener("input", function (e) { later(editableOf(e.target)); });
    doc.addEventListener("focusout", function (e) { var el = editableOf(e.target); if (el) commit(el); });
    doc.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest(".ans[data-a]");
      if (a) { e.preventDefault(); editAnswer(a); }
    });
    showSlide();
  }
  function editableOf(t) { return t && t.closest ? t.closest("[data-pm-edit]") : null; }

  function frameKey(e) {
    var t = editableOf(e.target);
    if (e.metaKey || e.ctrlKey) {
      var k = e.key.toLowerCase();
      if (!B.native && (k === "s" || k === "o")) { e.preventDefault(); if (t) commit(t); hooks.command(k === "s" ? (e.shiftKey ? "save-as" : "save") : "open"); }
      if (k === "enter" && cm) { e.preventDefault(); }
      return;
    }
    if (!t) return;
    if (e.key === "Escape") { t.blur(); return; }
    if (t.getAttribute("contenteditable") === "true" && e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) frame.contentDocument.execCommand("insertLineBreak");
    }
    if (t.tagName === "PRE" && (e.key === "Tab" || e.key === "Enter")) {
      // a newline in the words themselves, not a new block the browser makes up
      e.preventDefault();
      frame.contentDocument.execCommand("insertText", false, e.key === "Tab" ? "    " : "\n");
    }
  }

  /* Show the slide being worked on, every step of it shown, and make its
     words typeable. */
  function showSlide() {
    var w = frame.contentWindow;
    if (!w) return;
    deckCall(w, "show", [cur, showAll]);
    var el = frameSlides()[cur];
    if (el) {
      unitsOf(sectionOf(d.slides[cur])).forEach(function (n) {
        var live = el.querySelector('[data-pm-n="' + n + '"]');
        if (!live) return;
        live.setAttribute("data-pm-edit", "");
        if (live.tagName === "PRE") { live.setAttribute("contenteditable", "plaintext-only"); live.spellcheck = false; }
        else live.setAttribute("contenteditable", "true");
      });
    }
    paintSteps();
  }

  /* The elements a click can type in: code (pre), and the outermost
     elements that hold words of their own and no blocks — a heading, a
     paragraph, a list item, one cell, a callout, one option's words. */
  function unitsOf(section) {
    var out = [];
    if (!section) return out;
    var BLOCK = "div,p,ul,ol,li,table,pre,section,h1,h2,h3,h4,blockquote";
    function walk(el) {
      if (el.matches("script,style,iframe,svg,template,.tracer")) return;
      if (el.tagName === "PRE") {
        if (!el.hasAttribute("data-blanks")) out.push(el.getAttribute("data-pm-n"));
        return;
      }
      var words = Array.prototype.some.call(el.childNodes, function (c) { return c.nodeType === 3 && c.nodeValue.trim(); });
      if (words && !el.querySelector(BLOCK)) { out.push(el.getAttribute("data-pm-n")); return; }
      Array.prototype.forEach.call(el.children, walk);
    }
    Array.prototype.forEach.call(section.children, walk);
    return out;
  }

  // ------------------------------------------------------------- typing
  var timers = {};
  function later(el) {
    if (!el) return;
    var n = el.getAttribute("data-pm-n");
    clearTimeout(timers[n]);
    timers[n] = setTimeout(function () { commit(el); }, 400);
  }
  /* Code's words: a line a .ln (what the deck wrapped each line in). */
  function codeText(pre) {
    var t = "";
    Array.prototype.forEach.call(pre.childNodes, function (c) {
      if (c.nodeType === 1 && c.classList.contains("ln")) t += (t && t.slice(-1) !== "\n" ? "\n" : "") + c.textContent;
      else t += c.textContent;
    });
    return t.replace(/\n$/, "");
  }
  function clean(root) {
    [root].concat(Array.prototype.slice.call(root.querySelectorAll("*"))).forEach(function (e) {
      e.removeAttribute("contenteditable");
      e.removeAttribute("spellcheck");
      e.removeAttribute("data-pm-edit");
      RUNTIME.forEach(function (c) { e.classList.remove(c); });
      if (e.getAttribute("class") === "") e.removeAttribute("class");
    });
  }
  function commit(live) {
    if (!d || !live) return;
    var n = live.getAttribute("data-pm-n");
    clearTimeout(timers[n]);
    var s = d.slides[cur], src = tplOf(s).content.querySelector('[data-pm-n="' + n + '"]');
    if (!src) return;
    if (live.tagName === "PRE") {
      var t = live.querySelector(".ln") ? codeText(live) : live.textContent;
      if (t === src.textContent) return;
      snapshot("type" + n);
      src.textContent = t;
    } else {
      var c = live.cloneNode(true);
      clean(c);
      if (c.innerHTML === src.innerHTML) return;
      snapshot("type" + n);
      src.innerHTML = c.innerHTML;
    }
    s.html = plain(s);
    changed();
  }

  function editAnswer(live) {
    var n = live.getAttribute("data-pm-n");
    var src = tplOf(d.slides[cur]).content.querySelector('[data-pm-n="' + n + '"]');
    if (!src) return;
    var input = h("input", { class: "field", type: "text", value: src.getAttribute("data-a") || "" });
    D.open({
      title: "The answer that fills in",
      body: h("div", {}, [h("p", { class: "pm-hint", text: "Shown in place of the ? when you press → on this step." }), input]),
      buttons: [{ spacer: true }, { label: "Cancel" }, { label: "Change it", primary: true, action: function () {
        if (input.value === src.getAttribute("data-a")) return;
        snapshot();
        src.setAttribute("data-a", input.value);
        live.setAttribute("data-a", input.value);
        d.slides[cur].html = plain(d.slides[cur]);
        changed();
      } }]
    });
  }

  // ------------------------------------------------------------- undo
  function state() {
    return { slides: d.slides.map(function (s) { return { pre: s.pre, html: s.html }; }), traces: JSON.stringify(d.traces),
             head: d.head, tracesChanged: tracesChanged, cur: cur };
  }
  /* Before a change. Typing in one place is one step, not one per letter. */
  function snapshot(tag) {
    var now = Date.now();
    if (tag && tag === lastTag && now - lastTime < 2000) { lastTime = now; return; }
    lastTag = tag || ""; lastTime = now;
    undos.push(state());
    if (undos.length > 200) undos.shift();
    redos = [];
  }
  function restore(st) {
    d.slides = st.slides.map(function (s) { return { pre: s.pre, html: s.html }; });
    d.traces = JSON.parse(st.traces);
    d.head = st.head;
    tracesChanged = st.tracesChanged;
    cur = Math.min(st.cur, d.slides.length - 1);
    lastTag = "";
    changed();
    reload();
  }
  function undo() { if (undos.length) { redos.push(state()); restore(undos.pop()); } }
  function redo() { if (redos.length) { undos.push(state()); restore(redos.pop()); } }

  // ------------------------------------------------------------- after a change
  function changed() {
    paintList();
    paintSide();
    if (hooks.onChange) hooks.onChange();
  }

  /* Every trace a slide names has steps (a hand deck's script stops at one
     that doesn't), and steps no slide uses go. */
  function consistent() {
    if (!d.tracesSrc) return;
    d.slides.forEach(function (s) {
      var re = /data-trace="([^"]+)"/g, m;
      while ((m = re.exec(s.html))) {
        if (!d.traces[m[1]] || !d.traces[m[1]].length) {
          d.traces[m[1]] = [{ l: 1, note: "Press <b>Run it again</b> in PresMaker to make this trace.", vars: {}, out: "", skip: [] }];
          tracesChanged = true;
        }
      }
    });
    F.unusedTraces(d).forEach(function (n) { delete d.traces[n]; tracesChanged = true; });
  }

  // ------------------------------------------------------------- the list
  var dragFrom = -1;
  function paintList() {
    list.textContent = "";
    d.slides.forEach(function (s, i) {
      var item = h("button", { class: "pm-dl-item" + (i === cur ? " pm-on" : ""), type: "button", draggable: "true",
                               title: "Slide " + (i + 1) + " — drag to move it" }, [
        h("span", { class: "pm-dl-n", text: String(i + 1) }),
        h("span", { class: "pm-dl-t", text: F.titleOf(s.html) }),
        h("span", { class: "pm-dl-b", text: F.badges(s.html).join(" · ") })
      ]);
      item.addEventListener("click", function () { go(i); });
      item.addEventListener("dragstart", function (e) { dragFrom = i; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); });
      item.addEventListener("dragover", function (e) {
        e.preventDefault();
        var r = item.getBoundingClientRect(), below = e.clientY > r.top + r.height / 2;
        item.classList.toggle("pm-drop-above", !below);
        item.classList.toggle("pm-drop-below", below);
      });
      item.addEventListener("dragleave", function () { item.classList.remove("pm-drop-above", "pm-drop-below"); });
      item.addEventListener("drop", function (e) {
        e.preventDefault();
        var below = item.classList.contains("pm-drop-below");
        item.classList.remove("pm-drop-above", "pm-drop-below");
        if (dragFrom < 0) return;
        var to = i + (below ? 1 : 0);
        if (dragFrom < to) to--;
        move(dragFrom, to);
        dragFrom = -1;
      });
      list.appendChild(item);
    });
    var on = list.children[cur];
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest" });
    $("dl-up").disabled = cur <= 0;
    $("dl-down").disabled = cur >= d.slides.length - 1;
    $("dl-del").disabled = d.slides.length <= 1;
    $("d-undo").disabled = !undos.length;
    $("d-redo").disabled = !redos.length;
    status();
  }
  function status() {
    if (hooks.status) {
      hooks.status("Teacher slides · " + d.slides.length + " slides · " +
        (d.kind === "pm" ? "made by PresMaker" : "made by hand") + " · click words on the slide to change them");
    }
  }

  function go(i) {
    cur = Math.max(0, Math.min(d.slides.length - 1, i));
    showAll = true;
    showSlide();
    paintList();
    paintSide();
  }
  function move(from, to) {
    if (from === to || to < 0 || to >= d.slides.length) return;
    snapshot();
    var s = d.slides.splice(from, 1)[0];
    d.slides.splice(to, 0, s);
    F.renumber(d);
    cur = to;
    changed();
    reload();
  }
  function remove() {
    if (d.slides.length <= 1) return;
    snapshot();
    d.slides.splice(cur, 1);
    F.renumber(d);
    cur = Math.min(cur, d.slides.length - 1);
    changed();
    reload();
  }
  function duplicate() {
    snapshot();
    var html = d.slides[cur].html;
    // A copied trace gets its own name: two slides can't share one panel.
    var re = /data-trace="([^"]+)"/g, m, names = [];
    while ((m = re.exec(html))) if (names.indexOf(m[1]) < 0) names.push(m[1]);
    names.forEach(function (old) {
      var n = F.freshTraceName(d, old.replace(/\d+$/, ""));
      html = html.split('data-trace="' + old + '"').join('data-trace="' + n + '"')
                 .split('id="panel-' + old + '"').join('id="panel-' + n + '"')
                 .split('data-for="' + old + '"').join('data-for="' + n + '"');
      d.traces[n] = JSON.parse(JSON.stringify(d.traces[old] || []));
      tracesChanged = true;
    });
    d.slides.splice(cur + 1, 0, { pre: undefined, html: html });
    F.renumber(d);
    cur++;
    changed();
    reload();
  }
  function insert(kind) {
    snapshot();
    var name = kind === "trace" ? F.freshTraceName(d) : "";
    var html = F.template(d, kind, name);
    // Number a new step after the last numbered step before it.
    var last = 0;
    d.slides.slice(0, cur + 1).forEach(function (s) {
      var re = /<span class="num">(\d+)<\/span>/g, m;
      while ((m = re.exec(s.html))) last = +m[1];
    });
    html = html.replace('<span class="num">1</span>', '<span class="num">' + (last + 1) + "</span>");
    d.slides.splice(cur + 1, 0, { pre: undefined, html: html });
    F.renumber(d);
    cur++;
    if (name) {
      d.traces[name] = [];
      tracesChanged = true;
    }
    changed();
    if (name) runTrace(name, true); else reload();
  }

  // ------------------------------------------------------------- side: steps, traces, HTML
  function paintSteps() {
    var el = frameSlides()[cur], n = el && el.steps ? el.steps.length : 0;
    stepInfo.textContent = n ? (el.shownSteps || 0) + " of " + n + " steps shown" : "No steps on this slide";
    $("d-step-back").disabled = !n || !el.shownSteps;
    $("d-step-fwd").disabled = !n || el.shownSteps >= n;
  }
  function step(by) {
    var w = frame.contentWindow, el = frameSlides()[cur];
    if (!el || !el.steps) return;
    var n = Math.max(0, Math.min(el.steps.length, (el.shownSteps || 0) + by));
    deckCall(w, "render", [el, n]);
    showAll = n === el.steps.length;
    paintSteps();
  }

  function paintSide() {
    // HTML panel: the slide as written (not while it's being typed in)
    if (cm && !cm.hasFocus()) {
      var v = d.slides[cur].html;
      if (cm.getValue() !== v) { cm.setValue(v); cm.clearHistory(); }
    }
    $("dh-apply").disabled = true;
    // Traces on this slide, and a way to make one
    traceBar.textContent = "";
    var html = d.slides[cur].html, re = /data-trace="([^"]+)"/g, m, any = false;
    while ((m = re.exec(html))) {
      any = true;
      var name = m[1], steps = (d.traces[name] || []).length;
      traceBar.appendChild(h("div", { class: "pm-trace-row" }, [
        h("span", { class: "pm-trace-name", text: "▶ Trace “" + name + "”: " + steps + (steps === 1 ? " step" : " steps") }),
        h("button", { class: "btn pm-small", type: "button", text: "Run it again", title: "Run the code on this slide in Python and make the steps from it",
                      onclick: runTrace.bind(null, name, false) }),
        h("button", { class: "btn pm-small", type: "button", text: "Edit steps…", onclick: editSteps.bind(null, name) })
      ]));
    }
    if (!any && traceable()) {
      traceBar.appendChild(h("div", { class: "pm-trace-row" }, [
        h("span", { class: "pm-hint", text: "This slide's Python can be stepped through, a line a press." }),
        h("button", { class: "btn pm-small", type: "button", text: "Make it a trace", onclick: makeTrace })
      ]));
    }
    traceBar.hidden = !traceBar.children.length;
  }

  function isPython(pre) {
    return pre.classList.contains("py") || (pre.classList.contains("code") && pre.getAttribute("data-lang") === "py");
  }
  /* The first Python on this slide that could become a trace. */
  function traceable() {
    if (!F.kindsFor(d).some(function (k) { return k.id === "trace"; })) return null;
    var sec = sectionOf(d.slides[cur]);
    return sec && Array.prototype.filter.call(sec.querySelectorAll("pre"), function (p) {
      return isPython(p) && !p.hasAttribute("data-trace") && !p.hasAttribute("data-bug") && !p.hasAttribute("data-blanks") && !p.classList.contains("stage");
    })[0] || null;
  }
  function makeTrace() {
    var pre = traceable();
    if (!pre) return;
    snapshot();
    var s = d.slides[cur], name = F.freshTraceName(d);
    var doc = pre.ownerDocument, wrap = doc.createElement("div");
    wrap.className = "cols wide-left";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    pre.setAttribute("data-trace", name);
    var panel = doc.createElement("div");
    panel.className = "tracer";
    if (d.kind === "pm") panel.setAttribute("data-for", name); else panel.id = "panel-" + name;
    wrap.appendChild(panel);
    stamp(s.tpl.content);
    s.html = plain(s);
    d.traces[name] = [];
    tracesChanged = true;
    changed();
    runTrace(name, true);
  }

  /* The Python a trace's code runs after: every earlier slide's code that
     defines a function (students type it all into one main.py). */
  function prefixFor(name) {
    var out = [];
    for (var i = 0; i < d.slides.length; i++) {
      var sec = sectionOf(d.slides[i]), stop = false;
      Array.prototype.forEach.call(sec ? sec.querySelectorAll("pre") : [], function (p) {
        if (stop) return;
        if (p.getAttribute("data-trace") === name) { stop = true; return; }
        if (isPython(p) && !p.hasAttribute("data-bug") && !p.hasAttribute("data-blanks") && /^def /m.test(p.textContent)) out.push(p.textContent);
      });
      if (stop) break;
    }
    return out.join("\n\n");
  }
  function runTrace(name, fresh) {
    var pre = null;
    d.slides.some(function (s) { pre = sectionOf(s).querySelector('pre[data-trace="' + name + '"]'); return !!pre; });
    if (!pre) return reload();
    if (!B.native) {
      if (!fresh) alert("Traces are made by running the code in Python, which only the PresMaker app can do.");
      return reload();
    }
    hooks.status && hooks.status("Running the code in Python…");
    B.call("python", { job: JSON.stringify({ mode: "trace", code: pre.textContent, prefix: prefixFor(name) }) }).then(function (t) {
      var r = JSON.parse(t);
      if (!r.steps || !r.steps.length) throw new Error(r.error || "nothing ran");
      if (r.error) {
        var last = r.steps[r.steps.length - 1];
        r.steps.push({ l: last.l, note: "Python stops: <code>" + F.esc(r.error) + "</code>", vars: last.vars, out: last.out, skip: [] });
      }
      if (!fresh) snapshot();
      d.traces[name] = r.steps;
      tracesChanged = true;
      changed();
      reload();
    }).catch(function (e) {
      alert("Couldn't trace it: " + (e.message || e));
      reload();
    });
  }
  function editSteps(name) {
    var steps = d.traces[name] || [];
    var area = h("textarea", { class: "field pm-area pm-steps-area", spellcheck: "false" });
    area.value = "[\n" + steps.map(function (s) { return "  " + JSON.stringify(s); }).join(",\n") + "\n]";
    var err = h("p", { class: "pm-hint" });
    D.open({
      title: "Steps of the trace “" + name + "”", wide: true,
      body: h("div", { class: "pm-steps" }, [
        h("p", { class: "pm-hint", text: "One step a line: l is the line that's running, note what you say about it (HTML), " +
          "vars the variables after it, out everything printed so far, skip lines that will never run." }),
        area, err]),
      buttons: [{ spacer: true }, { label: "Cancel" }, { label: "Save steps", primary: true, action: function () {
        var v;
        try {
          v = JSON.parse(area.value);
          if (!Array.isArray(v) || !v.every(function (s) { return s && typeof s.l === "number"; })) throw new Error("every step needs a line number, l");
        } catch (e) { err.textContent = "That isn't right yet: " + (e.message || e); return false; }
        snapshot();
        d.traces[name] = v;
        tracesChanged = true;
        changed();
        reload();
      } }]
    });
  }

  function applyHTML() {
    var v = cm.getValue(), t = document.createElement("template");
    t.innerHTML = v;
    var kids = Array.prototype.filter.call(t.content.childNodes, function (c) { return c.nodeType === 1 || (c.nodeType === 3 && c.nodeValue.trim()); });
    if (kids.length !== 1 || kids[0].tagName !== "SECTION") {
      alert("A slide is one <section> … </section>, with everything on it inside.");
      return;
    }
    snapshot();
    d.slides[cur].html = v.trim();
    d.slides[cur].tpl = null;
    $("dh-apply").disabled = true;
    changed();
    reload();
  }

  // ------------------------------------------------------------- theme
  function themeMenu() {
    var sel = $("d-theme"), T = window.PMThemes, now = F.themeOf(d);
    sel.textContent = "";
    sel.appendChild(h("option", { value: "", text: "As it was made" }));
    var g1 = h("optgroup", { label: "Built in" });
    T.builtin().forEach(function (n) { g1.appendChild(h("option", { value: n, text: n })); });
    sel.appendChild(g1);
    var mine = T.made();
    if (mine.length) {
      var g2 = h("optgroup", { label: "Yours (PresMaker)" });
      mine.forEach(function (t) { g2.appendChild(h("option", { value: t.name, text: t.name + " ★" })); });
      sel.appendChild(g2);
    }
    sel.value = now;
  }
  function useTheme(name) {
    snapshot();
    if (!name) F.setTheme(d, "");
    else {
      var t = window.PMTeacher.themeVars(name);
      F.setTheme(d, name, d.kind === "pm" ? window.PMTeacher.rootCSS(t) : F.handThemeCSS(t), window.PMThemes.exportHead(name).fonts);
    }
    changed();
    reload();
  }

  // ------------------------------------------------------------- present
  function present() {
    if (!d) return;
    presentBox.hidden = false;
    presentFrame.onload = function () {
      var w = presentFrame.contentWindow;
      w.addEventListener("keydown", function (e) {
        // Esc closes the deck's own picker first; with none open, it ends the show.
        if (e.key === "Escape" && !presentFrame.contentDocument.querySelector(".overlay.on")) stopPresenting();
      }, true);
      deckCall(w, "show", [cur, false]);
      w.focus();
    };
    presentFrame.srcdoc = frameDoc(true);
    B.call("fullscreen", { on: true });
  }
  function stopPresenting() {
    if (presentBox.hidden) return;
    presentBox.hidden = true;
    presentFrame.srcdoc = "";
    B.call("fullscreen", { on: false });
  }

  // ------------------------------------------------------------- layout
  function fitFrame() {
    if (!stage || !frame) return;
    var k = Math.max(0.1, Math.min((stage.clientWidth - 24) / W, (stage.clientHeight - 24) / H));
    frame.style.transform = "scale(" + k + ")";
    frame.parentNode.style.width = W * k + "px";
    frame.parentNode.style.height = H * k + "px";
  }

  function setup() {
    frame = $("deck-frame"); stage = $("deck-stage"); list = $("deck-list"); htmlBox = $("deck-html");
    traceBar = $("deck-traces"); stepInfo = $("d-steps"); presentBox = $("deck-present"); presentFrame = $("deck-present-frame");
    frame.style.width = W + "px";
    frame.style.height = H + "px";
    frame.addEventListener("load", onFrameLoad);
    new ResizeObserver(fitFrame).observe(stage);
    cm = CodeMirror(htmlBox, {
      value: "", mode: "htmlmixed", lineWrapping: true, lineNumbers: true, tabSize: 2, indentUnit: 2,
      extraKeys: { "Cmd-Enter": applyHTML, "Ctrl-Enter": applyHTML }
    });
    cm.on("changes", function () { $("dh-apply").disabled = !d || cm.getValue() === d.slides[cur].html; });
    $("dh-apply").addEventListener("click", applyHTML);
    $("dh-toggle").addEventListener("click", function () {
      var on = document.body.classList.toggle("pm-deck-html-off");
      $("dh-toggle").textContent = on ? "HTML ▸" : "HTML ▾";
      fitFrame();
      if (!on) cm.refresh();
    });
    $("dl-up").addEventListener("click", function () { move(cur, cur - 1); });
    $("dl-down").addEventListener("click", function () { move(cur, cur + 1); });
    $("dl-dup").addEventListener("click", duplicate);
    $("dl-del").addEventListener("click", remove);
    $("d-undo").addEventListener("click", undo);
    $("d-redo").addEventListener("click", redo);
    $("d-step-back").addEventListener("click", function () { step(-1); });
    $("d-step-fwd").addEventListener("click", function () { step(1); });
    $("d-step-all").addEventListener("click", function () { showAll = true; showSlide(); });
    $("d-prev").addEventListener("click", function () { go(cur - 1); });
    $("d-next").addEventListener("click", function () { go(cur + 1); });
    $("d-theme").addEventListener("change", function () { useTheme($("d-theme").value); });
    $("deck-present-done").addEventListener("click", stopPresenting);
    $("b-dinsert").addEventListener("click", function (e) {
      e.stopPropagation();
      var menu = $("d-insert-list");
      if (menu.hidden) paintInsert();
      Array.prototype.forEach.call(document.querySelectorAll(".pm-menu-list"), function (m) { if (m !== menu) m.hidden = true; });
      menu.hidden = !menu.hidden;
    });
    // ⌘Z / ⇧⌘Z over the list or the bar (the frame and the HTML panel have their own)
    document.addEventListener("keydown", function (e) {
      if (!d || !(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "z") return;
      if (D.isOpen() || (cm && cm.hasFocus()) || /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "")) return;
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
    });
  }
  function paintInsert() {
    var menu = $("d-insert-list");
    menu.textContent = "";
    F.kindsFor(d).forEach(function (k) {
      menu.appendChild(h("button", { type: "button", text: k.label, onclick: function () { menu.hidden = true; insert(k.id); } }));
    });
  }

  // ------------------------------------------------------------- for app.js
  window.PMDeckEdit = {
    isDeck: F.isDeck,
    init: function (o) { hooks = o; setup(); },
    /* Open a deck's text. Throws (with a reason) if it isn't one. */
    open: function (t, p) {
      var parsed = F.parse(t);
      d = parsed; path = p || ""; cur = 0; tracesChanged = false; undos = []; redos = []; lastTag = "";
      themeMenu();
      changed();
      fitFrame();
      reload();
    },
    close: function () { d = null; frame.srcdoc = ""; stopPresenting(); },
    active: function () { return !!d; },
    text: text,
    /* Anything still being typed goes in first. */
    flush: function () {
      var doc = frame.contentDocument, el = doc && doc.activeElement && editableOf(doc.activeElement);
      if (el) commit(el);
      if (cm && d && cm.getValue() !== d.slides[cur].html && !$("dh-apply").disabled) applyHTML();
    },
    present: present,
    stopPresenting: stopPresenting,
    insert: insert,
    undo: undo,
    redo: redo,
    themes: themeMenu,
    useTheme: function (n) { useTheme(n); themeMenu(); },
    // for the tests
    _state: function () { return { d: d, cur: cur, tracesChanged: tracesChanged }; },
    go: go
  };
})();
