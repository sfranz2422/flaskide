/* PresMaker — pages: one slide, or one sheet of a document, at a fixed size.
 *
 * The same code lays out the editor's preview, the PDF and the exported
 * .html, so the three can't disagree about where a slide runs out of room.
 *
 *   fit(slide)      shrinks a slide's text until it fits its page; returns
 *                   true if it had to. A projector has no scroll bar, and a
 *                   PDF page cut off at the bottom loses the end of the
 *                   slide with no sign anything was there.
 *   paginate(flow)  cuts a document into sheets, moving whole blocks, and
 *                   splitting a list or a code block that won't fit on one.
 *
 * On an export page (body.pm-export) it runs itself: the PDF is told
 * "ready" with the page count (Sources/main.swift draws them one by one with
 * show(i)); the .html becomes a viewer with arrows.
 */
window.PMPages = (function () {
  "use strict";

  var SMALLEST = 11;    // px; below this a slide is better split in two

  function overflows(el) { return el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1; }

  function fit(slide) {
    slide.style.fontSize = "";
    var size = parseFloat(getComputedStyle(slide).fontSize) || 20;
    var start = size;
    // Halving search is no faster in practice: a slide rarely needs more than
    // a few steps, and stepping keeps sizes to whole half-pixels.
    while (overflows(slide) && size > SMALLEST) {
      size -= size > 16 ? 1 : 0.5;
      slide.style.fontSize = size + "px";
    }
    slide.classList.toggle("pm-shrunk", size < start);
    slide.classList.toggle("pm-overfull", overflows(slide));
    return size < start;
  }

  /* A title slide — a big heading and a line or two — sits in the middle of
     its page; everything else starts at the top, where a reader looks. */
  function markTitle(slide) {
    // Through the played parts' wrappers (.pm-part, display: contents).
    var kids = [];
    Array.prototype.forEach.call(slide.children, function (k) {
      if (k.classList.contains("pm-part")) kids = kids.concat(Array.prototype.slice.call(k.children));
      else kids.push(k);
    });
    var title = kids.length && kids.length <= 3 && /^H1$/.test(kids[0].tagName) &&
      Array.prototype.every.call(kids, function (k) { return /^(H1|H2|H3|P)$/.test(k.tagName) && !k.querySelector("img"); });
    slide.classList.toggle("pm-title", !!title);
  }

  // ------------------------------------------------- played slides
  /* `animate:` notes, presented: each slide's parts (`...` divides them) are
     .pm-part wrappers, drawn and fitted whole, then hidden; each press
     plays the next one in, word by word or letter by letter, at the notes'
     speed, waiting at each `^` pause. Hidden with visibility, so the slide
     is laid out once and nothing moves as it plays.

     The same as notes.js's animateIn in the IDEs — copied, not shared,
     because the exported .html carries this file and not notes.js.
     tools/test_compose.mjs holds SPEEDS to notes.js's. */
  var SPEEDS = { slow: { word: 450, letter: 80, block: 700, pause: 1500 },
                 normal: { word: 250, letter: 45, block: 450, pause: 1000 },
                 fast: { word: 120, letter: 22, block: 260, pause: 600 } };
  var TEXT_BLOCKS = { P: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, UL: 1, OL: 1, BLOCKQUOTE: 1, DL: 1 };

  function animateIn(part, how, speed, ctl) {
    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) return Promise.resolve();
    var ms = SPEEDS[speed] || SPEEDS.normal, steps = [];
    function hide(n) { n.classList.add("reveal-hidden"); }
    function splitText(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 3) {
          var bits = how === "type" ? child.nodeValue.split("") : child.nodeValue.split(/(\s+)/);
          var frag = document.createDocumentFragment();
          bits.forEach(function (bit) {
            if (!bit) return;
            if (how !== "type" && /^\s+$/.test(bit)) { frag.appendChild(document.createTextNode(bit)); return; }
            var span = document.createElement("span");
            span.className = "reveal-bit";
            span.textContent = bit;
            hide(span);
            frag.appendChild(span);
            steps.push([span, how === "type" ? (/\s/.test(bit) ? 0 : ms.letter) : ms.word]);
          });
          child.parentNode.replaceChild(frag, child);
        } else if (child.nodeType === 1) {
          if (child.classList.contains("reveal-pause")) {
            steps.push([child, ms.pause * (Number(child.getAttribute("data-beats")) || 1)]);
          } else if (/^(IMG|INPUT|IFRAME|SVG)$/i.test(child.tagName)) {
            hide(child);
            steps.push([child, ms.block]);
          } else {
            splitText(child);
          }
        }
      });
    }
    Array.prototype.forEach.call(part.children, function (block) {
      if (TEXT_BLOCKS[block.tagName]) splitText(block);
      else {
        hide(block);
        steps.push([block, ms.block, block.classList.contains("pop-box") ? "reveal-pop" : ""]);
      }
    });
    return new Promise(function (resolve) {
      var i = 0, over = false, timer = null;
      ctl.finish = function () {
        if (over) return;
        over = true;
        clearTimeout(timer);
        Array.prototype.forEach.call(part.querySelectorAll(".reveal-hidden"), function (n) { n.classList.remove("reveal-hidden"); });
        resolve();
      };
      function next() {
        if (over) return;
        if (i >= steps.length) { over = true; return resolve(); }
        var s = steps[i++];
        timer = setTimeout(function () {
          s[0].classList.remove("reveal-hidden");
          if (s[2]) s[0].classList.add(s[2]);
          next();
        }, s[1]);
      }
      next();
    });
  }

  /* A slide's player. how: "words" | "type"; speed: "slow" | "normal" |
     "fast". played: how many parts start shown (all of them, going back
     to a slide; none, arriving at it). onChange is told whenever what it
     can do changes. */
  function player(slide, how, speed, played, onChange) {
    var parts = Array.prototype.slice.call(slide.querySelectorAll(":scope > .pm-part"));
    var shown = Math.max(0, Math.min(parts.length, played)), busy = false, ctl = {};
    parts.forEach(function (p, i) { p.classList.toggle("pm-waiting", i >= shown); });
    function tell() { if (onChange) onChange(api); }
    var api = {
      count: parts.length,
      shown: function () { return shown; },
      busy: function () { return busy; },
      more: function () { return busy || shown < parts.length; },
      /* The next press: finishes a part playing, else plays the next one.
         False when there was nothing left to do — the caller moves on. */
      step: function () {
        if (busy) { ctl.finish(); return true; }
        if (shown >= parts.length) return false;
        var part = parts[shown++];
        part.classList.remove("pm-waiting");
        busy = true;
        ctl = {};
        tell();
        animateIn(part, how, speed, ctl).then(function () { busy = false; tell(); });
        return true;
      },
      showAll: function () {
        if (busy) ctl.finish();
        shown = parts.length;
        parts.forEach(function (p) { p.classList.remove("pm-waiting"); });
        tell();
      }
    };
    tell();
    return api;
  }

  // ------------------------------------------------------- documents
  function newSheet(flow, sheets) {
    var page = document.createElement("section");
    page.className = "pm-page pm-sheet";
    var body = document.createElement("div");
    body.className = flow.className.replace(/\bpm-flow\b/, "").trim() + " pm-sheet-body";
    page.appendChild(body);
    sheets.appendChild(page);
    return body;
  }

  /* Splits `el` (a list or a code block) so that as much as fits stays on
     `body` and the rest is returned to start the next sheet; null if it
     can't be split. */
  function split(el, body) {
    var rest;
    if (/^(UL|OL)$/.test(el.tagName) && el.children.length > 1) {
      rest = el.cloneNode(false);
      while (overflows(body) && el.children.length > 1) {
        rest.insertBefore(el.lastElementChild, rest.firstChild);
      }
      // The numbers carry on over the page break: 6, not 1.
      if (el.tagName === "OL") rest.start = (el.start || 1) + el.children.length;
      return rest.children.length ? rest : null;
    }
    if (el.tagName === "PRE" && el.textContent.split("\n").length > 4) {
      var code = el.querySelector("code") || el;
      var lines = code.textContent.replace(/\n$/, "").split("\n"), keep = lines.length;
      while (overflows(body) && keep > 2) {
        keep--;
        code.textContent = lines.slice(0, keep).join("\n");
      }
      if (keep >= lines.length) return null;
      rest = el.cloneNode(true);
      (rest.querySelector("code") || rest).textContent = lines.slice(keep).join("\n");
      return rest;
    }
    return null;
  }

  function paginate(flow, sheets) {
    var items = Array.prototype.slice.call(flow.children);
    var body = newSheet(flow, sheets);
    while (items.length) {
      var el = items.shift();
      body.appendChild(el);
      if (!overflows(body)) continue;
      var rest = split(el, body);
      if (rest) {
        items.unshift(rest);
      } else if (body.children.length > 1) {
        body.removeChild(el);
        items.unshift(el);
      }
      // A heading left at the foot of a sheet goes over with what it heads.
      var last = body.lastElementChild;
      if (last && /^H[1-6]$/.test(last.tagName) && body.children.length > 1 && last !== el) {
        body.removeChild(last);
        items.unshift(last);
      }
      body = newSheet(flow, sheets);
    }
    if (!body.children.length && sheets.children.length > 1) sheets.removeChild(body.parentNode);
    flow.parentNode && flow.parentNode.removeChild(flow);
  }

  // ------------------------------------------------- export pages
  function pages() { return document.querySelectorAll(".pm-pages > .pm-page"); }

  function show(i) {
    Array.prototype.forEach.call(pages(), function (p, k) { p.classList.toggle("pm-on", k === i); });
    return i;
  }

  /* The theme's heading face, before anything is measured or drawn.
     document.fonts.ready alone isn't enough: it resolves at once if the
     Google Fonts sheet hasn't arrived yet, since nothing is loading — and
     the PDF then had chalkboard's headings in the plain face, at random. So
     the sheets first, then a layout (which is what asks for the faces),
     then the faces. */
  function fontsLoaded() {
    var links = Array.prototype.slice.call(document.querySelectorAll("link[rel=stylesheet]"));
    var sheets = Promise.all(links.map(function (l) {
      if (l.sheet) return null;
      return new Promise(function (r) { l.addEventListener("load", r); l.addEventListener("error", r); });
    }));
    var ready = sheets.then(function () {
      void document.body.offsetHeight;
      return document.fonts && document.fonts.ready;
    });
    // A font that never arrives (no internet) must not stop the export: the
    // headings come out in the page's own face, which is only plainer.
    return Promise.race([ready, new Promise(function (r) { setTimeout(r, 8000); })]);
  }

  function imagesLoaded() {
    var imgs = Array.prototype.slice.call(document.images);
    return Promise.all(imgs.map(function (img) {
      if (img.complete) return null;
      return new Promise(function (r) { img.onload = img.onerror = r; setTimeout(r, 8000); });
    }));
  }

  /* Every page shown while measuring: a page that is display:none (the
     PDF shows one at a time) measures 0 high, so nothing would ever seem
     too long, and no slide would shrink. */
  function layOut() {
    document.body.classList.add("pm-laying");
    var flow = document.querySelector(".pm-flow");
    var sheets = document.querySelector(".pm-pages");
    if (flow && document.body.classList.contains("pm-paged")) paginate(flow, sheets);
    var shrunk = [];
    Array.prototype.forEach.call(document.querySelectorAll(".pm-slide"), function (s, i) {
      markTitle(s);
      if (fit(s)) shrunk.push(i + 1);
    });
    document.body.classList.remove("pm-laying");
    return shrunk;
  }

  // The .html viewer: one slide at a time, as big as the window allows.
  function viewer() {
    var all = pages(), at = 0, play = null;
    var how = document.body.dataset.animate || "", speed = document.body.dataset.speed || "normal";
    if (!document.body.classList.contains("pm-kind-slides")) return;
    var w = Number(document.body.dataset.width), h = Number(document.body.dataset.height);
    var count = document.querySelector(".pm-count");
    function scale() {
      var k = Math.min(window.innerWidth / w, (window.innerHeight - 40) / h);
      document.documentElement.style.setProperty("--pm-scale", String(k));
    }
    function go(i) {
      var was = at;
      at = Math.max(0, Math.min(all.length - 1, i));
      show(at);
      // Played notes: a slide arrived at going forward starts unplayed;
      // going back, or opening at a slide, it's shown whole.
      if (play) play.showAll();
      play = null;
      var slide = all[at].querySelector(".pm-slide");
      if (how && slide && slide.querySelector(":scope > .pm-part")) {
        play = player(slide, how, speed, at > was || (at === 0 && was === 0 && first) ? 0 : 1e9, paint);
      }
      first = false;
      paint();
      try { history.replaceState(null, "", "#" + (at + 1)); } catch (e) { /* file:// in some browsers */ }
    }
    var first = true;
    function paint() {
      if (count) count.textContent = (at + 1) + " / " + all.length +
        (play && play.count > 1 && play.more() ? " · part " + Math.min(play.shown() + (play.busy() ? 0 : 1), play.count) + " of " + play.count : "");
    }
    // Forward: the next part of a played slide first, then the next slide.
    function forward() { if (!(play && play.step())) go(at + 1); }
    window.addEventListener("resize", scale);
    document.addEventListener("keydown", function (e) {
      if (/^(ArrowRight|ArrowDown|PageDown| )$/.test(e.key)) { e.preventDefault(); forward(); }
      else if (/^(ArrowLeft|ArrowUp|PageUp)$/.test(e.key)) { e.preventDefault(); go(at - 1); }
      else if (e.key === "Home") go(0);
      else if (e.key === "End") go(all.length - 1);
    });
    var prev = document.querySelector(".pm-prev"), next = document.querySelector(".pm-next");
    if (prev) prev.addEventListener("click", function () { go(at - 1); });
    if (next) next.addEventListener("click", forward);
    scale();
    go((parseInt(location.hash.slice(1), 10) || 1) - 1);
  }

  function run() {
    var b = document.body;
    if (!b || !b.classList.contains("pm-export")) return;
    // Every page shown while the fonts load, not just while measuring: a
    // face is only fetched once text on screen uses it, so with the pages
    // hidden the wait ended at once, slide 1 was drawn in the plain face,
    // and every slide was fitted to the wrong font's size.
    b.classList.add("pm-laying");
    Promise.all([fontsLoaded(), imagesLoaded()]).then(function () {
      var shrunk = layOut();
      var post = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pages;
      if (b.dataset.mode === "pdf") {
        show(0);
        if (post) post.postMessage({ count: pages().length, shrunk: shrunk });
      } else {
        viewer();
      }
    }).catch(function (e) {
      var post = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pages;
      if (post) post.postMessage({ error: String(e && e.message || e) });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();

  /* A PDF page's background, as a picture. createPDF draws a gradient that
     fades to transparent as solid, and drops whatever was under it — so
     chalkboard, space, notebook and most of the seasons came out as a
     black page with a blob on it, with no error anywhere. The app takes a
     snapshot of the page with its content hidden (bgOnly), and this puts
     that snapshot back as the page's only background; createPDF then draws
     the text over it as text, still sharp and still selectable. */
  function target(i) {
    var p = pages()[i];
    return p && p.querySelector(".pm-slide, .pm-sheet-body");
  }
  function needsPicture(i) {
    var t = target(i);
    return !!t && getComputedStyle(t).backgroundImage !== "none";
  }
  function bgOnly(on) { document.body.classList.toggle("pm-bg-only", !!on); }
  function setPicture(i, url) {
    var img = new Image();
    img.src = url;
    var ready = img.decode ? img.decode() : Promise.resolve();
    return ready.catch(function () {}).then(function () {
      var t = target(i);
      t.style.setProperty("background", 'url("' + url + '") 0 0 / 100% 100% no-repeat', "important");
      bgOnly(false);
      return true;
    });
  }

  return { fit: fit, markTitle: markTitle, paginate: paginate, show: show, player: player, SPEEDS: SPEEDS,
           needsPicture: needsPicture, bgOnly: bgOnly, setPicture: setPicture };
})();
