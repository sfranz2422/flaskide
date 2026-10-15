/* The editor's notes, popped out into a tab of their own, for the projector.
 *
 * Holds no lesson of its own. The editor tab that opened it is in charge,
 * and sends it what to show ("state": the notes, the slide, whether it is
 * live) over a BroadcastChannel named in this page's address. Moving here
 * asks the editor to move ("go"); when it is live the editor moves the
 * class, exactly as its own ◀ ▶ would. See "notes, popped out" in app.js.
 *
 * WHY IT SAYS WHEN THE EDITOR IS GONE. A channel between tabs carries
 * nothing once the other tab has closed or reloaded, and this page would go
 * on showing a slide that looked live while the class had stopped
 * following. So it asks every two seconds, and covers itself with a notice
 * when nothing has answered for six — or at once, when the editor says
 * goodbye as it unloads.
 */
(function () {
  "use strict";

  var cfg = window.PRESENT;
  var N = window[cfg.ns + "Notes"];
  function $(id) { return document.getElementById(id); }

  var id = new URLSearchParams(location.search).get("ch") || "";
  var body = $("present-body"), stateChip = $("present-state"), lost = $("present-lost");
  var view = N.slideView(body);
  var notes = null, live = false, heard = 0;
  /* The slide asked for and not yet confirmed. An answer already on its way
     when the clicker was pressed still carries the slide before, and without
     this the screen would flick back to it for a moment, then on again: on
     a projector, in front of the class, on every quick double press. */
  var asked = null, askedAt = 0;

  if (!id || !("BroadcastChannel" in window)) {
    lost.hidden = false;
    return;
  }
  var chan = new BroadcastChannel(cfg.channel + id);

  function paintState() {
    stateChip.classList.toggle("live-chip", live);
    stateChip.classList.toggle("live-on", live);     // green, as the editor's chip
    stateChip.textContent = live ? "Live: the class follows these slides"
                                 : "Not live: only you see this";
  }

  chan.onmessage = function (e) {
    var d = e.data || {};
    if (d.type === "bye") { lost.hidden = false; return; }
    if (d.type !== "state") return;
    heard = Date.now();
    lost.hidden = true;
    live = !!d.live;
    paintState();
    $("present-title").textContent = d.title || "Notes";
    document.title = (d.title || "Notes") + " — notes";
    if (asked !== null) {
      if (d.slide !== asked && Date.now() - askedAt < 1500) return;
      asked = null;
    }
    var text = d.notes || "";
    if (!text.trim()) text = "*No notes in this project yet.*";
    // show() redraws only when what is on screen changed, so this is cheap
    // twice a second; given the slide, it lands where the editor is.
    if (text !== notes || d.slide !== view.at()) {
      notes = text;
      view.show(text, d.slide);
    }
  };

  function go(i) {
    asked = i;
    askedAt = Date.now();
    chan.postMessage({ type: "go", slide: i });
  }
  // The arrows under the slides: they move this view at once, and the
  // editor's answer agrees with it.
  view.onMove(go);

  // A presentation clicker sends PageDown / PageUp; a keyboard, the arrows.
  document.addEventListener("keydown", function (e) {
    var was = view.at(), to;
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") to = was + 1;
    else if (e.key === "ArrowLeft" || e.key === "PageUp") to = was - 1;
    else return;
    e.preventDefault();
    view.go(to);
    if (view.at() !== was) go(view.at());
  });

  $("present-full").addEventListener("click", function () {
    var el = document.documentElement;
    if (document.fullscreenElement) document.exitFullscreen();
    else if (el.requestFullscreen) el.requestFullscreen();
  });

  chan.postMessage({ type: "hello" });
  setInterval(function () {
    chan.postMessage({ type: "hello" });
    if (heard && Date.now() - heard > 6000) lost.hidden = false;
  }, 2000);
  // Never heard at all (the editor was closed before this opened).
  setTimeout(function () { if (!heard) lost.hidden = false; }, 6000);
})();
