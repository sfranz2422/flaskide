/* Videos in class descriptions: a YouTube link on a line of its own becomes
 * a player, on the class pages only (class_student.html, class_teacher.html).
 *
 * WHY NOT LET THE TEACHER PASTE YOUTUBE'S <iframe>. The description goes
 * through the same sanitiser as every student's notes (notes.js), which
 * takes out every iframe — rightly: a student's project shared on to a
 * classmate must not be able to frame any page it likes. So the player is
 * built here instead, after sanitising, from nothing but the video's id
 * (eleven letters, checked), at youtube-nocookie.com. The page never trusts
 * a single character of markup from the description to do it.
 *
 * Only a link alone in its paragraph: a link in the middle of a sentence is
 * a link, and stays one. Identical in all three editors; it names none.
 */
window.ClassEmbeds = (function () {
  "use strict";

  // youtube.com/watch?v=ID, /shorts/ID, /embed/ID, /live/ID, youtu.be/ID —
  // and nothing that merely contains "youtube": the host is matched whole.
  var YOUTUBE = new RegExp(
    "^https?://(?:(?:www|m)\\.)?(?:youtube\\.com/(?:watch\\?(?:[^#]*&)?v=|shorts/|embed/|live/)" +
    "|youtu\\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])");

  function videoId(href) {
    var m = YOUTUBE.exec(String(href || ""));
    return m ? m[1] : null;
  }

  // Seconds to start at, from ?t=90 or ?t=1m30s, so a link to the middle of
  // a video plays from there.
  function startAt(href) {
    var m = /[?&#]t=(?:(\d+)h)?(?:(\d+)m)?(\d+)s?(?:&|$)/.exec(String(href || ""));
    if (!m) return 0;
    return (+(m[1] || 0)) * 3600 + (+(m[2] || 0)) * 60 + (+m[3]);
  }

  function player(id, start, title) {
    var box = document.createElement("div");
    box.className = "video-embed";
    var frame = document.createElement("iframe");
    frame.src = "https://www.youtube-nocookie.com/embed/" + id + (start ? "?start=" + start : "");
    frame.title = title || "YouTube video";
    frame.loading = "lazy";
    frame.allow = "accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen";
    frame.setAttribute("allowfullscreen", "");
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    box.appendChild(frame);
    return box;
  }

  function embedVideos(root) {
    Array.prototype.forEach.call(root.querySelectorAll("p"), function (p) {
      var parts = Array.prototype.filter.call(p.childNodes, function (n) {
        return !(n.nodeType === 3 && !n.textContent.trim()) && n.nodeName !== "BR";
      });
      if (parts.length !== 1 || parts[0].nodeName !== "A") return;
      var a = parts[0], id = videoId(a.getAttribute("href"));
      if (!id) return;
      var text = a.textContent.trim();
      p.replaceWith(player(id, startAt(a.getAttribute("href")),
                           text && text !== a.getAttribute("href") ? text : ""));
    });
    return root;
  }

  return { videoId: videoId, startAt: startAt, embedVideos: embedVideos };
})();
