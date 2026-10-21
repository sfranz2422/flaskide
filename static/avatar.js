/* Avatars: one picture from a fixed set (xp.py's AVATARS), shown in any
 * element with data-avatar="<id>". An empty or unknown id is a plain
 * silhouette — a student who hasn't chosen yet.
 *
 * The id is checked against a pattern before it goes into a URL. The
 * server only ever saves ids from its list, but this is where an id turns
 * into markup, so it is where the check belongs.
 *
 * Same file in all three editors, like xp.py.
 */
window.PyIDEAvatar = (function () {
  "use strict";

  var BASE = "/static/avatars/";

  var SILHOUETTE =
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
    '<rect width="100" height="100" fill="#2a3140"/>' +
    '<circle cx="50" cy="40" r="17" fill="#4a5466"/>' +
    '<path d="M16 100 Q18 66 50 64 Q82 66 84 100Z" fill="#4a5466"/></svg>';

  function url(id) {
    return /^[a-z0-9-]{1,40}$/.test(id || "") ? BASE + id + ".webp" : null;
  }

  function html(id) {
    var src = url(id);
    return src ? '<img src="' + src + '" alt="" loading="lazy" decoding="async">' : SILHOUETTE;
  }

  function draw(root) {
    var els = (root || document).querySelectorAll("[data-avatar]");
    Array.prototype.forEach.call(els, function (el) {
      el.innerHTML = html(el.getAttribute("data-avatar"));
    });
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { draw(); });
    } else {
      draw();
    }
  }

  return { url: url, html: html, draw: draw };
})();
