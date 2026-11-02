/* The teacher's slides on a student's screen: the student's side. Covers the
 * page while the teacher is showing and is gone when they stop, with the work
 * underneath untouched. There is no button here on purpose: the student only
 * watches, and what they are sent is one slide (deck_show.js says why).
 *
 * THE FRAME'S SANDBOX IS THE GUARD, AND IT IS allow-same-origin WITHOUT
 * allow-scripts. Nothing in it can run, even if something got past
 * deck_show.js, whose clean-up happens in the teacher's browser and so proves
 * nothing here. Same-origin lets THIS script change the frame in place: reloading
 * it per slide flashes white and restarts every animation at each reveal.
 */
(function () {
  "use strict";
  var code = document.currentScript.getAttribute("data-code");
  var SHOWING_MS = 1000;
  var IDLE_MS = 2500;       // beside the live poll all lesson, so slower until it's needed

  var seq = 0, cover = null, frame = null, ready = false, current = null, waiting = null;
  var quieted = [];

  /* The student's cursor must not stay in the editor behind the slide, where
     they would type without seeing it. */
  function quiet() {
    quieted = [];
    Array.prototype.forEach.call(document.body.children, function (el) {
      if (el !== cover && !el.inert) { el.inert = true; quieted.push(el); }
    });
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  }

  function page(f) {
    return "<!doctype html><html" + f.html_attrs + "><head><meta charset=\"utf-8\">" + f.head +
           "</head><body" + f.body_attrs + ">" + f.body + "</body></html>";
  }

  function sameAttrs(from, to) {
    Array.prototype.slice.call(to.attributes).forEach(function (a) {
      if (a.name.toLowerCase() === "src" && from.getAttribute(a.name) === a.value) return;
      from.setAttribute(a.name, a.value);
    });
    Array.prototype.slice.call(from.attributes).forEach(function (a) {
      if (!to.hasAttribute(a.name)) from.removeAttribute(a.name);
    });
  }

  /* Only what changed, so a reveal doesn't restart the slide's animations or
     send a student who has scrolled back to the top. */
  function morph(from, to, doc) {
    var a = from.childNodes, b = to.childNodes;
    for (var i = 0; i < b.length; i++) {
      var old = a[i], now = b[i];
      if (!old) from.appendChild(doc.importNode(now, true));
      else if (old.nodeType !== now.nodeType || old.nodeName !== now.nodeName) {
        from.replaceChild(doc.importNode(now, true), old);
      } else if (now.nodeType === 1) {
        sameAttrs(old, now);
        morph(old, now, doc);
      } else if (old.nodeValue !== now.nodeValue) old.nodeValue = now.nodeValue;
    }
    while (a.length > b.length) from.removeChild(from.lastChild);
  }

  function open(f) {
    cover = document.createElement("div");
    cover.id = "deck-view";
    cover.setAttribute("style", "position:fixed;inset:0;z-index:2147483647;background:#000");
    frame = document.createElement("iframe");
    frame.title = "Your teacher's slides";
    frame.setAttribute("sandbox", "allow-same-origin");
    frame.setAttribute("style", "width:100%;height:100%;border:0;display:block");
    frame.addEventListener("load", function () {
      ready = true;
      if (waiting) { var w = waiting; waiting = null; draw(w); }
    });
    cover.appendChild(frame);
    document.body.appendChild(cover);
    quiet();
    ready = false;
    frame.srcdoc = page(f);
    current = f;
  }

  function draw(f) {
    if (!cover) { open(f); return; }
    if (!ready) { waiting = f; return; }
    if (f.head !== current.head) {
      ready = false;
      frame.srcdoc = page(f);
    } else {
      var doc = frame.contentDocument;
      var parsed = new DOMParser().parseFromString(page(f), "text/html");
      sameAttrs(doc.documentElement, parsed.documentElement);
      sameAttrs(doc.body, parsed.body);
      morph(doc.body, parsed.body, doc);
    }
    current = f;
  }

  function close() {
    if (!cover) return;
    cover.remove();
    cover = frame = current = waiting = null;
    ready = false;
    quieted.forEach(function (el) { el.inert = false; });
    quieted = [];
  }

  function poll() {
    fetch("/api/live/" + encodeURIComponent(code) + "/deck?d=" + seq, { cache: "no-store" })
      .then(function (r) { return r.status === 200 ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        if (d.showing) { seq = d.seq; draw(d.frame); }
        else { seq = 0; close(); }
      })
      .catch(function () {})     // school wifi drops polls; the next one catches up
      .finally(function () { setTimeout(poll, cover ? SHOWING_MS : IDLE_MS); });
  }
  poll();
})();
