/* Keep the teacher's place on a page that reloads itself after a button.
 *
 * Hide, Show, Rename, Archive, an approval, a random event — they all end in
 * location.reload(), and these pages are no-store, so the browser builds them
 * afresh and lands at the top. A teacher hiding the tenth assignment of a
 * long list had to scroll back down after every click; the same went for
 * Back from an assignment's page. So the position is kept as the page goes,
 * per page, and put back only on a reload or a Back/Forward: a link that
 * opens the page anew still starts at the top, as it should.
 *
 * WHAT SCROLLS IS NOT THE WINDOW. On a laptop these pages are fixed to the
 * screen (html and body are overflow: hidden) and the content scrolls inside
 * .sheet; only at phone width does the window scroll instead. The first
 * version of this saved window.scrollY, which on a laptop is always 0, and
 * so faithfully put the teacher back at the top every time — the bug it was
 * written to fix, unchanged, with nothing to say why. So both are saved (the
 * larger is the one that moved) and both are set.
 *
 * It is put back twice because pictures in descriptions load after this
 * runs and push the rows down; without the second go the page settles a few
 * rows short, silently.
 *
 * Same file in all three editors.
 */
window.KeepPlace = function (key, scroller) {
  "use strict";
  var box = scroller || document.querySelector(".sheet");

  function where() {
    return Math.max(window.scrollY || 0, box ? box.scrollTop : 0);
  }
  function go(y) {
    window.scrollTo(0, y);
    if (box) box.scrollTop = y;
  }

  var nav = window.performance && performance.getEntriesByType &&
            performance.getEntriesByType("navigation")[0];
  var returning = !!nav && (nav.type === "reload" || nav.type === "back_forward");
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem(key, String(where())); } catch (e) {}
  });
  if (!returning) return;
  var y = 0;
  try { y = Number(sessionStorage.getItem(key)) || 0; } catch (e) {}
  if (!y) return;
  go(y);
  window.addEventListener("load", function () { go(y); });
};
