/* The teacher's slides on every student's screen: the teacher's side.
 *
 * Added to the deck only when it is opened with ?show=1 (teacher_deck), so the
 * uploaded file itself is never changed and the plain link stays as it was.
 *
 * WHAT GOES OUT IS A PICTURE OF THE SLIDE, NEVER THE DECK. A deck is the
 * teacher's own scripts, and on a student's page they would run with the
 * student's sign-in; it also holds every later slide and every answer. So each
 * time the page changes, what is on screen now is written out as plain HTML:
 * no scripts, no other slides, no unrevealed answers. That is also why any deck
 * works whatever it is built with, why a student who joins late needs no
 * catching up, and why the students can't move anything: they have no slides
 * to move to.
 *
 * Unrevealed answers are removed rather than left to the deck's CSS, which only
 * hides them: `.reveal` text is masked, and `data-a` and the marks on a bug or
 * a right choice are dropped until the step is shown. Masking keeps the text's
 * length, so the slide doesn't jump when the step comes out.
 *
 * The class list stays home. The setup box is never written out, and a
 * textarea's typed value is a property that this never reads. A name the picker
 * draws does go out: it is on the slide, as it is on the projector.
 */
(function (root) {
  "use strict";

  //: Controls for the person presenting. On a student's screen they would be
  //: buttons that do nothing. `.nav` itself stays, for the slide counter.
  var TEACHER_ONLY = "#setup, .hint, #pick, #prev, #next, #score button, #score .tk, #deck-show-pill";
  var DROPPED = { script: 1, noscript: 1, template: 1, base: 1, meta: 1 };
  var EMPTY = { area: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1, input: 1, link: 1,
                param: 1, source: 1, track: 1, wbr: 1 };
  var RAW = { style: 1 };

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function has(el, name) {
    return (" " + (el.getAttribute("class") || "") + " ").indexOf(" " + name + " ") >= 0;
  }

  function attrsOf(el, secret) {
    var tag = el.tagName.toLowerCase();
    var out = "";
    var list = el.attributes;
    for (var i = 0; i < list.length; i++) {
      var name = list[i].name, value = list[i].value, low = name.toLowerCase();
      if (low.indexOf("on") === 0) continue;
      if (low === "srcdoc") continue;
      // Links lead nowhere from here: a click would take the student's view
      // off the slide, with the teacher none the wiser.
      if ((tag === "a" || tag === "area") && (low === "href" || low === "target")) continue;
      if (low === "action" || low === "formaction") continue;
      if (secret && (low === "data-a" || low === "data-bug")) continue;
      if (secret && low === "class") {
        value = value.split(/\s+/).filter(function (c) {
          return c !== "right" && c !== "wrong" && c !== "isbug";
        }).join(" ");
      }
      out += " " + name + '="' + esc(value).replace(/"/g, "&quot;") + '"';
    }
    return out;
  }

  function write(node, win, mask, secret) {
    if (node.nodeType === 3) {
      var text = node.nodeValue;
      return esc(mask ? text.replace(/\S/g, "x") : text);
    }
    if (node.nodeType !== 1) return "";
    var tag = node.tagName.toLowerCase();
    if (DROPPED[tag] || node.matches(TEACHER_ONLY)) return "";
    var seen = win.getComputedStyle(node);
    // Every other slide leaves here, along with closed overlays.
    if (seen.display === "none") return "";
    var hidesSteps = has(node, "reveal") || has(node, "stage");
    var unshown = hidesSteps && !has(node, "shown");
    var nowSecret = secret || unshown;
    var nowMask = mask || seen.visibility === "hidden" || (has(node, "reveal") && !has(node, "shown"));
    var open = "<" + tag + attrsOf(node, nowSecret) + ">";
    if (EMPTY[tag]) return open;
    var inner = "";
    for (var i = 0; i < node.childNodes.length; i++) {
      var child = node.childNodes[i];
      inner += RAW[tag] ? (child.nodeValue || "") : write(child, win, nowMask, nowSecret);
    }
    return open + inner + "</" + tag + ">";
  }

  /* What is on screen now, as strings. Only style reaches the head. */
  function snapshot(doc, win) {
    var head = "";
    var kids = doc.head.childNodes;
    for (var i = 0; i < kids.length; i++) {
      var k = kids[i];
      if (k.nodeType !== 1) continue;
      var tag = k.tagName.toLowerCase();
      if (tag === "style") head += "<style>" + (k.textContent || "") + "</style>";
      else if (tag === "link" && (k.getAttribute("rel") || "").toLowerCase() === "stylesheet") {
        head += "<link" + attrsOf(k, false) + ">";
      }
    }
    var body = "";
    var seen = doc.body.childNodes;
    for (var j = 0; j < seen.length; j++) body += write(seen[j], win, false, false);
    return { head: head, body: body,
             html_attrs: attrsOf(doc.documentElement, false),
             body_attrs: attrsOf(doc.body, false) };
  }

  /* Base64 in JSON, for the reason upload_teacher_deck gives: Render's firewall
     refuses a body that looks like a page before the app sees it, and a lesson
     on HTML is full of what it looks for. */
  function pack(text) {
    var bytes = new TextEncoder().encode(text), bin = "";
    for (var i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }

  root.PyIDEDeckShow = { snapshot: snapshot };

  var CFG = root.DECK_SHOW;
  if (!CFG || !root.document) return;       // loaded by the tests for snapshot

  var SETTLE_MS = 200;    // a name picker's spin is 14 changes in a second: send where it lands
  var MOST_MS = 1500;     // ...but an animation that never settles still goes out
  var BEAT_MS = 20000;    // see DECK_SHOW_STALE_SECONDS
  var api = "/api/live/" + encodeURIComponent(CFG.code) + "/deck";

  var showing = true;     // opening this address is the teacher asking for it
  var lastSent = "";
  var lastSeq = 0;
  var settle = null, most = null, sending = false, again = false;

  /* Always higher than the last, as a live push's is, so a stop can't be
     overtaken by a slide sent just before it. */
  function stamp() {
    lastSeq = Math.max(lastSeq + 1, Date.now());
    return lastSeq;
  }

  var pill = document.createElement("div");
  pill.id = "deck-show-pill";
  pill.setAttribute("style",
    "position:fixed;left:12px;bottom:14px;z-index:2147483647;display:flex;gap:10px;align-items:center;" +
    "padding:6px 8px 6px 12px;border-radius:999px;background:#14141c;color:#fff;font:13px system-ui,sans-serif;" +
    "box-shadow:0 2px 10px rgba(0,0,0,.45)");
  var state = document.createElement("span");
  var link = document.createElement("span");
  link.style.opacity = ".75";
  link.textContent = CFG.join;
  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("style",
    "border:0;border-radius:999px;padding:4px 12px;font:600 13px system-ui,sans-serif;cursor:pointer");
  pill.appendChild(state);
  pill.appendChild(link);
  pill.appendChild(button);

  function drawPill(problem) {
    state.textContent = problem || (showing ? "● On students' screens" : "Only you see this");
    state.style.color = problem ? "#ffb4a8" : (showing ? "#8ee06b" : "#fff");
    link.hidden = !showing;
    button.textContent = showing ? "Stop showing" : "Show to class";
  }

  function post(body, keepalive) {
    return fetch(api, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: !!keepalive,
      body: JSON.stringify(body)
    });
  }

  function send() {
    if (!showing) return;
    clearTimeout(settle); clearTimeout(most);
    settle = most = null;
    if (sending) { again = true; return; }
    var text = JSON.stringify(snapshot(document, window));
    if (text === lastSent) return;
    sending = true;
    post({ seq: stamp(), showing: true, data: pack(text) }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; },
                           function () { return { ok: false, d: {} }; });
    }).then(function (out) {
      if (out.ok) { lastSent = text; drawPill(); }
      else drawPill(out.d.error || "Students didn't get that slide");
    }).catch(function () {
      drawPill("Can't reach the server");     // the beat tries again
      lastSent = "";
    }).finally(function () {
      sending = false;
      if (again) { again = false; send(); }
    });
  }

  function changed() {
    if (!showing) return;
    clearTimeout(settle);
    settle = setTimeout(send, SETTLE_MS);
    if (most === null) most = setTimeout(send, MOST_MS);
  }

  function stop(keepalive) {
    return post({ seq: stamp(), showing: false }, keepalive).catch(function () {});
  }

  button.addEventListener("click", function () {
    showing = !showing;
    // Space is the deck's Next. Left focused here, it would press this button.
    button.blur();
    drawPill();
    lastSent = "";
    if (showing) send(); else stop();
  });

  new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var t = records[i].target;
      var el = t.nodeType === 1 ? t : t.parentNode;
      if (!el || !pill.contains(el)) { changed(); return; }
    }
  }).observe(document.documentElement, {
    subtree: true, childList: true, attributes: true, characterData: true
  });

  /* The beat is what lets students go if this tab dies without saying so. */
  setInterval(function () {
    if (!showing) return;
    if (!lastSent) { send(); return; }
    post({ seq: stamp(), beat: true }).catch(function () {});
  }, BEAT_MS);

  /* Closing the tab ends it, or the class would sit on the last slide until
     the beat ran out. A reload stops and starts again. */
  addEventListener("pagehide", function () { if (showing) stop(true); });
  addEventListener("pageshow", function (e) {
    if (e.persisted && showing) { lastSent = ""; send(); }
  });

  document.body.appendChild(pill);
  drawPill();
  send();
})(typeof window !== "undefined" ? window : globalThis);
