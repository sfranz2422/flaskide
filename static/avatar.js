/* Avatars, drawn from parts (xp.py's AVATAR_PARTS) as SVG.
 *
 * An avatar is stored as the name of one part of each kind — never a
 * picture, never anything a student typed — so all a page is ever sent is a
 * few ids, and this is the only thing that turns them into shapes. Every
 * element with data-avatar='{"skin":"s3",...}' is drawn when the page loads.
 *
 * Every id xp.py lists must be drawable here. test_xp.py runs this file and
 * checks, because a part missing here draws as nothing at all: a student
 * unlocks a hat at level 5, picks it, and their head is simply bare.
 *
 * Same file in all three editors, like xp.py.
 */
window.PyIDEAvatar = (function () {
  "use strict";

  var SKIN = { s1: "#f9dcc4", s2: "#f1c27d", s3: "#e0ac69",
               s4: "#c68642", s5: "#8d5524", s6: "#5c3a1e" };
  var HAIR = { black: "#26221f", brown: "#6b4226", blonde: "#e6c36a",
               red: "#b5462a", gray: "#9a9a9a", blue: "#3b7ddd",
               pink: "#e86fb0", green: "#3fae5a", gold: "#d4a017" };
  var BACK = { sky: ["#a7d3f5"], mint: ["#b5ead7"], peach: ["#ffd3b6"],
               lilac: ["#d7c4f2"], night: ["#2b2d5c"],
               sunset: ["#ffb35a", "#c2417a"], galaxy: ["#1b1340", "#5b2a86"] };
  var INK = "#2a1d1a";

  // Each returns SVG. `c` is the hair colour, `s` the skin.
  var FACE = {
    round: function (s) { return '<ellipse cx="50" cy="55" rx="26" ry="27" fill="' + s + '"/>'; },
    oval: function (s) { return '<ellipse cx="50" cy="55" rx="23" ry="29" fill="' + s + '"/>'; },
    square: function (s) { return '<rect x="25" y="28" width="50" height="54" rx="13" fill="' + s + '"/>'; }
  };

  // Drawn behind the face: only hair that hangs down past it.
  var HAIR_BACK = {
    long: function (c) { return '<rect x="21" y="32" width="58" height="56" rx="20" fill="' + c + '"/>'; },
    bun: function (c) { return '<circle cx="50" cy="21" r="10" fill="' + c + '"/>'; }
  };

  var TOP = "M24 50 Q24 24 50 24 Q76 24 76 50 Q70 36 50 36 Q30 36 24 50Z";
  var HAIR_FRONT = {
    none: function () { return ""; },
    short: function (c) { return '<path d="' + TOP + '" fill="' + c + '"/>'; },
    buzz: function (c) {
      return '<path d="M26 46 Q28 28 50 28 Q72 28 74 46 Q66 37 50 37 Q34 37 26 46Z" fill="' +
             c + '" opacity=".8"/>';
    },
    long: function (c) { return '<path d="' + TOP + '" fill="' + c + '"/>'; },
    curly: function (c) {
      return [[27, 44], [32, 33], [41, 26], [50, 24], [59, 26], [68, 33], [73, 44]]
        .map(function (p) { return '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="8" fill="' + c + '"/>'; })
        .join("");
    },
    bun: function (c) { return '<path d="' + TOP + '" fill="' + c + '"/>'; },
    spiky: function (c) {
      return '<path d="M24 48 L27 25 L36 35 L42 18 L50 32 L58 18 L64 35 L73 25 L76 48 ' +
             'Q64 37 50 37 Q36 37 24 48Z" fill="' + c + '"/>';
    },
    mohawk: function (c) {
      return '<path d="M44 38 L41 12 Q50 6 59 12 L56 38Z" fill="' + c + '"/>';
    }
  };

  function eye(x, y) {
    return '<circle cx="' + x + '" cy="' + y + '" r="5" fill="#fff"/>' +
           '<circle cx="' + x + '" cy="' + (y + 0.5) + '" r="2.5" fill="' + INK + '"/>';
  }
  function arc(x, y, up) {
    return '<path d="M' + (x - 5) + ' ' + y + ' Q' + x + ' ' + (y + (up ? -6 : 4)) + ' ' +
           (x + 5) + ' ' + y + '" stroke="' + INK + '" stroke-width="2" fill="none" stroke-linecap="round"/>';
  }
  function star(x, y) {
    var pts = [];
    for (var i = 0; i < 10; i++) {
      var r = i % 2 ? 2.4 : 6, a = Math.PI / 5 * i - Math.PI / 2;
      pts.push((x + r * Math.cos(a)).toFixed(1) + "," + (y + r * Math.sin(a)).toFixed(1));
    }
    return '<polygon points="' + pts.join(" ") + '" fill="#f5c518" stroke="#b8860b" stroke-width=".6"/>';
  }
  var EYES = {
    dots: function () {
      return '<circle cx="40" cy="54" r="2.7" fill="' + INK + '"/><circle cx="60" cy="54" r="2.7" fill="' + INK + '"/>';
    },
    round: function () { return eye(40, 53) + eye(60, 53); },
    happy: function () { return arc(40, 55, true) + arc(60, 55, true); },
    sleepy: function () { return arc(40, 53, false) + arc(60, 53, false); },
    wink: function () { return eye(40, 53) + arc(60, 55, true); },
    stars: function () { return star(40, 54) + star(60, 54); }
  };

  var MOUTH = {
    smile: function () {
      return '<path d="M42 66 Q50 74 58 66" stroke="' + INK + '" stroke-width="2.2" fill="none" stroke-linecap="round"/>';
    },
    grin: function () {
      return '<path d="M40 65 Q50 79 60 65Z" fill="#7a1f2b"/><path d="M42 65.5 L58 65.5 L57 68 L43 68Z" fill="#fff"/>';
    },
    flat: function () {
      return '<path d="M43 68 L57 68" stroke="' + INK + '" stroke-width="2.2" stroke-linecap="round"/>';
    },
    open: function () { return '<ellipse cx="50" cy="69" rx="5" ry="4.5" fill="#7a1f2b"/>'; },
    tongue: function () {
      return '<path d="M40 65 Q50 79 60 65Z" fill="#7a1f2b"/>' +
             '<ellipse cx="52" cy="71" rx="4" ry="3.2" fill="#ef7c95"/>';
    }
  };

  var GLASSES = {
    none: function () { return ""; },
    round: function () {
      return '<g stroke="' + INK + '" stroke-width="1.8" fill="rgba(255,255,255,.15)">' +
             '<circle cx="40" cy="54" r="7"/><circle cx="60" cy="54" r="7"/></g>' +
             '<path d="M47 54 L53 54" stroke="' + INK + '" stroke-width="1.8"/>';
    },
    square: function () {
      return '<g stroke="' + INK + '" stroke-width="1.8" fill="rgba(255,255,255,.15)">' +
             '<rect x="32" y="48" width="15" height="11" rx="2"/><rect x="53" y="48" width="15" height="11" rx="2"/></g>' +
             '<path d="M47 53 L53 53" stroke="' + INK + '" stroke-width="1.8"/>';
    },
    shades: function () {
      return '<rect x="31" y="48" width="16" height="10" rx="4" fill="#111"/>' +
             '<rect x="53" y="48" width="16" height="10" rx="4" fill="#111"/>' +
             '<path d="M47 52 L53 52" stroke="#111" stroke-width="2"/>';
    },
    visor: function () {
      return '<rect x="27" y="47" width="46" height="12" rx="6" fill="#33d1ff" opacity=".8" stroke="#1585a8" stroke-width="1.2"/>';
    }
  };

  var HAT = {
    none: function () { return ""; },
    beanie: function () {
      return '<path d="M23 44 Q23 16 50 16 Q77 16 77 44Z" fill="#d6455d"/>' +
             '<rect x="22" y="39" width="56" height="8" rx="4" fill="#a8304a"/>' +
             '<circle cx="50" cy="14" r="5" fill="#f0f0f0"/>';
    },
    cap: function () {
      return '<path d="M25 42 Q25 18 50 18 Q75 18 75 42Z" fill="#2f6fd6"/>' +
             '<path d="M52 38 L86 42 Q87 47 76 47 L52 43Z" fill="#1f4fa0"/>' +
             '<circle cx="50" cy="19" r="2.5" fill="#1f4fa0"/>';
    },
    headphones: function () {
      return '<path d="M23 54 Q23 16 50 16 Q77 16 77 54" stroke="#333" stroke-width="5" fill="none"/>' +
             '<rect x="17" y="46" width="10" height="17" rx="4" fill="#e04848"/>' +
             '<rect x="73" y="46" width="10" height="17" rx="4" fill="#e04848"/>';
    },
    wizard: function () {
      return '<path d="M26 36 L52 0 L74 36Z" fill="#5b3fb5"/>' +
             '<rect x="22" y="32" width="56" height="7" rx="3.5" fill="#3e2a85"/>' +
             star(48, 20);
    },
    crown: function () {
      return '<path d="M29 32 L29 13 L39 23 L50 9 L61 23 L71 13 L71 32Z" fill="#f5c518" stroke="#b8860b" stroke-width="1.2"/>' +
             '<circle cx="50" cy="25" r="2.6" fill="#d6455d"/>';
    }
  };

  var DEFAULT = { skin: "s1", face: "round", hair: "short", hair_color: "brown",
                  eyes: "round", mouth: "smile", glasses: "none", hat: "none",
                  background: "sky" };

  var made = 0;

  function pick(table, id, fallback) {
    return Object.prototype.hasOwnProperty.call(table, id) ? id : fallback;
  }

  function svg(avatar) {
    var a = avatar || {};
    var s = SKIN[pick(SKIN, a.skin, DEFAULT.skin)];
    var c = HAIR[pick(HAIR, a.hair_color, DEFAULT.hair_color)];
    var hair = pick(HAIR_FRONT, a.hair, DEFAULT.hair);
    var hat = pick(HAT, a.hat, "none");
    var back = BACK[pick(BACK, a.background, DEFAULT.background)];
    // Ids inside an SVG are global to the page, and a leaderboard draws
    // thirty of these: each gets its own gradient name.
    var gid = "pyide-av-" + (++made);
    var fill = back[0];
    var defs = "";
    if (back.length > 1) {
      defs = '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1">' +
             '<stop offset="0" stop-color="' + back[0] + '"/><stop offset="1" stop-color="' + back[1] + '"/>' +
             '</linearGradient></defs>';
      fill = "url(#" + gid + ")";
    }
    var sparkle = a.background === "galaxy"
      ? '<g fill="#fff" opacity=".8"><circle cx="14" cy="18" r="1.2"/><circle cx="84" cy="12" r="1"/>' +
        '<circle cx="88" cy="40" r="1.3"/><circle cx="10" cy="46" r="1"/><circle cx="20" cy="78" r=".9"/></g>'
      : "";
    // A hat covers the top of the hair; hair that sticks up past a hat
    // would poke through it, so under a hat only the sides show.
    var front = HAIR_FRONT[hair](c);
    if (hat !== "none" && hat !== "headphones" && (hair === "mohawk" || hair === "spiky")) {
      front = HAIR_FRONT.short(c);
    }
    return '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">' +
      defs + '<rect width="100" height="100" fill="' + fill + '"/>' + sparkle +
      (HAIR_BACK[hair] ? HAIR_BACK[hair](c) : "") +
      '<path d="M30 100 Q30 80 50 80 Q70 80 70 100Z" fill="#4a6fa5"/>' +
      '<rect x="44" y="74" width="12" height="10" fill="' + s + '"/>' +
      '<circle cx="24" cy="56" r="5" fill="' + s + '"/><circle cx="76" cy="56" r="5" fill="' + s + '"/>' +
      FACE[pick(FACE, a.face, DEFAULT.face)](s) +
      EYES[pick(EYES, a.eyes, DEFAULT.eyes)]() +
      MOUTH[pick(MOUTH, a.mouth, DEFAULT.mouth)]() +
      front +
      GLASSES[pick(GLASSES, a.glasses, "none")]() +
      HAT[hat]() +
      "</svg>";
  }

  function draw(root) {
    var els = (root || document).querySelectorAll("[data-avatar]");
    Array.prototype.forEach.call(els, function (el) {
      var a = {};
      try { a = JSON.parse(el.getAttribute("data-avatar") || "{}"); } catch (e) {}
      el.innerHTML = svg(a);
    });
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { draw(); });
    } else {
      draw();
    }
  }

  return {
    svg: svg,
    draw: draw,
    // What this file can draw, by kind, for test_xp.py to hold against
    // xp.py's list.
    drawable: {
      skin: Object.keys(SKIN), face: Object.keys(FACE), hair: Object.keys(HAIR_FRONT),
      hair_color: Object.keys(HAIR), eyes: Object.keys(EYES), mouth: Object.keys(MOUTH),
      glasses: Object.keys(GLASSES), hat: Object.keys(HAT), background: Object.keys(BACK)
    }
  };
})();
