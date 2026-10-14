/* FlaskIDE — handles for resizing panes. Ported from PyIDE's split.js.
 *
 * A handle is an element with class "resizer" between two panes. Dragging it
 * sizes the pane BEFORE it; the pane after it (and whatever follows) takes
 * the rest, through the flex rules already in style.css. That is the whole
 * model, and it is deliberately that small: one number per handle, nothing
 * to keep in step when a pane appears or goes away.
 *
 * data-size="next" sizes the pane AFTER it instead, for a pane that sits at
 * the end of a column below one that fills — the editor's "Class sees",
 * under an output and an instructions pane that take turns being shown, so
 * the pane before the handle is not always the same one.
 *
 * data-pane="<id>" names the pane outright, for one that is not next to
 * its handle. The editor's console is a <pre> under its own "Console" head:
 * the handle goes above the head, where the line between preview and
 * console is, and sizes the <pre> under it. Sizing the pane before it
 * instead was no use there — that is the preview frame in a Flask app and
 * the results grid in a SQL one, whichever is shown.
 *
 * A sized pane gets the class "is-sized", for rules that only make sense
 * once a pane has a size of its own.
 *
 *     <div class="resizer resizer-y" data-split="notes" ...></div>
 *
 * resizer-x drags sideways and sets a width; resizer-y drags up and down and
 * sets a height. data-split names the size in this browser's storage, so a
 * student who made the notes bigger finds them that size in the next lesson.
 * Double-click puts the pane back to the page's own size.
 *
 * WHY THIS EXISTS. Every fixed split of these pages was wrong for
 * somebody. The live page's right-hand column holds the student's page, the
 * console and the notes: a Chromebook left the notes a few lines, a lesson
 * on a long template wanted the preview tall, a SQL lesson wanted the
 * console. No split suits every lesson, so the students choose.
 *
 * WHAT IS STORED is a size in pixels, in localStorage, per viewer. If the
 * storage is blocked the handles still work; the size just isn't remembered.
 * A stored size larger than the window has room for is not a problem: the
 * pane is given `flex-shrink: 1`, so it gives way rather than pushing the
 * rest off the screen.
 *
 * ONLY WHILE THE PANES ARE SIDE BY SIDE. Below the page's stacking width
 * (the 860px media query in style.css) the panes are a column the page scrolls through,
 * and a width dragged on a laptop would be a height there. So sizes are
 * taken off while narrow and put back when wide again.
 */
window.FlaskIDESplit = (function () {
  "use strict";

  var PREFIX = "flaskide-split:";
  var MIN = 60;            // no pane is dragged smaller than this
  var REST = 80;           // and the panes after it keep at least this

  function load(key) {
    try {
      var n = parseInt(localStorage.getItem(PREFIX + key), 10);
      return n > 0 ? n : null;
    } catch (e) { return null; }
  }

  function save(key, px) {
    try {
      if (px == null) localStorage.removeItem(PREFIX + key);
      else localStorage.setItem(PREFIX + key, String(Math.round(px)));
    } catch (e) { /* blocked: sized for this visit only */ }
  }

  function sizesNext(handle) { return handle.dataset.size === "next"; }

  /* The pane a handle sizes: the one it names, or the element before it,
     or after it. */
  function paneOf(handle) {
    if (handle.dataset.pane) return document.getElementById(handle.dataset.pane);
    return sizesNext(handle) ? handle.nextElementSibling : handle.previousElementSibling;
  }

  function apply(pane, px) {
    if (!pane) return;
    pane.style.flex = px == null ? "" : "0 1 " + Math.round(px) + "px";
    pane.classList.toggle("is-sized", px != null);
  }

  /* opts.wide: a MediaQueryList, true while panes sit side by side.
     opts.onResize: called (once a frame at most) while a size changes, for
     the things that cannot notice by themselves — CodeMirror measures
     itself on a window resize and at no other time. */
  function attachAll(root, opts) {
    opts = opts || {};
    var handles = Array.prototype.slice.call(root.querySelectorAll(".resizer[data-split]"));
    var wide = opts.wide || { matches: true };
    var queued = false;

    function resized() {
      if (!opts.onResize || queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; opts.onResize(); });
    }

    function applyAll() {
      handles.forEach(function (h) {
        apply(paneOf(h), wide.matches ? load(h.dataset.split) : null);
      });
      resized();
    }

    handles.forEach(function (handle) {
      var vertical = handle.classList.contains("resizer-y");
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", vertical ? "horizontal" : "vertical");
      handle.tabIndex = 0;
      if (!handle.title) {
        handle.title = "Drag to resize. Double-click to put it back.";
      }

      /* The room there is to share: the pane, plus everything after it in
         the same row or column, less what those must keep. */
      function limits(pane) {
        var parent = pane.parentNode.getBoundingClientRect();
        var start = pane.getBoundingClientRect();
        var total = sizesNext(handle)
          ? (vertical ? start.bottom - parent.top : start.right - parent.left)
          : (vertical ? parent.bottom - start.top : parent.right - start.left);
        return { min: MIN, max: Math.max(MIN, total - REST - (vertical
          ? handle.offsetHeight : handle.offsetWidth)) };
      }

      function setSize(pane, px) {
        var lim = limits(pane);
        px = Math.max(lim.min, Math.min(lim.max, px));
        apply(pane, px);
        resized();
        return px;
      }

      handle.addEventListener("pointerdown", function (e) {
        if (e.button !== 0 || !wide.matches) return;
        var pane = paneOf(handle);
        if (!pane) return;
        e.preventDefault();               // no text selection while dragging
        var rect = pane.getBoundingClientRect();
        var from = vertical ? e.clientY : e.clientX;
        var size = vertical ? rect.height : rect.width;
        var sign = sizesNext(handle) ? -1 : 1;  // dragging up grows the pane below
        var last = size;
        handle.setPointerCapture(e.pointerId);
        handle.classList.add("is-dragging");
        document.body.classList.add(vertical ? "is-resizing-y" : "is-resizing-x");

        function move(ev) {
          var at = vertical ? ev.clientY : ev.clientX;
          last = setSize(pane, size + sign * (at - from));
        }
        function up() {
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          handle.removeEventListener("pointercancel", up);
          handle.classList.remove("is-dragging");
          document.body.classList.remove("is-resizing-y", "is-resizing-x");
          save(handle.dataset.split, last);
        }
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
        handle.addEventListener("pointercancel", up);
      });

      handle.addEventListener("dblclick", function () {
        apply(paneOf(handle), null);
        save(handle.dataset.split, null);
        resized();
      });

      // Arrow keys, for anyone not using a mouse: 20px a press.
      handle.addEventListener("keydown", function (e) {
        var step = { ArrowUp: -20, ArrowLeft: -20, ArrowDown: 20, ArrowRight: 20 }[e.key];
        if (!step || !wide.matches) return;
        if (vertical !== (e.key === "ArrowUp" || e.key === "ArrowDown")) return;
        e.preventDefault();
        var pane = paneOf(handle);
        var rect = pane.getBoundingClientRect();
        if (sizesNext(handle)) step = -step;
        save(handle.dataset.split,
             setSize(pane, (vertical ? rect.height : rect.width) + step));
      });
    });

    applyAll();
    if (wide.addEventListener) wide.addEventListener("change", applyAll);
    else if (wide.addListener) wide.addListener(applyAll);
  }

  return { attachAll: attachAll };
})();
