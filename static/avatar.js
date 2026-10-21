/* Avatars, drawn from parts (xp.py's AVATAR_PARTS) as SVG.
 *
 * An avatar is stored as the name of one part of each kind — never a
 * picture, never anything a student typed — so all a page is ever sent is a
 * few ids, and this is the only thing that turns them into shapes. Every
 * element with data-avatar='{"skin":"s3",...}' is drawn when the page loads.
 *
 * Two styles: a "hero" is a head-and-shoulders portrait built from parts, in
 * the look of a fantasy character-select screen; an "icon" is one ready-made
 * picture (a sun, a dragon, a blocky hero). Both sit on the chosen
 * background.
 *
 * Every id xp.py lists must be drawable here. test_xp.py runs this file and
 * checks, because a part missing here draws as nothing at all: a student
 * unlocks a helmet at level 6, picks it, and their head is simply bare.
 *
 * Same file in all three editors, like xp.py.
 */
window.PyIDEAvatar = (function () {
  "use strict";

  // ------------------------------------------------------------ helpers

  /* A colour lighter (pct > 0) or darker (pct < 0), for shading a part in
     its own colour rather than a grey wash over it. */
  function shade(hex, pct) {
    var n = parseInt(hex.slice(1), 16);
    function f(c) {
      c = pct < 0 ? c * (1 + pct / 100) : c + (255 - c) * pct / 100;
      return Math.max(0, Math.min(255, Math.round(c)));
    }
    return "#" + ((1 << 24) + (f(n >> 16) << 16) + (f((n >> 8) & 255) << 8) +
                  f(n & 255)).toString(16).slice(1);
  }

  /* Ids inside an SVG are global to the page, and a leaderboard draws thirty
     of these: every gradient and filter is named for its own drawing. */
  function Ctx(id) { this.id = id; this.defs = []; this.made = {}; }
  Ctx.prototype.lin = function (name, a, b, horizontal) {
    var id = this.id + "-" + name;
    if (!this.made[id]) {
      this.made[id] = 1;
      this.defs.push('<linearGradient id="' + id + '" x1="0" y1="0" x2="' + (horizontal ? 1 : 0) +
                     '" y2="' + (horizontal ? 0 : 1) + '"><stop offset="0" stop-color="' + a +
                     '"/><stop offset="1" stop-color="' + b + '"/></linearGradient>');
    }
    return "url(#" + id + ")";
  };
  Ctx.prototype.rad = function (name, a, b, cx, cy, r) {
    var id = this.id + "-" + name;
    if (!this.made[id]) {
      this.made[id] = 1;
      this.defs.push('<radialGradient id="' + id + '" cx="' + (cx || 0.5) + '" cy="' + (cy || 0.5) +
                     '" r="' + (r || 0.6) + '"><stop offset="0" stop-color="' + a +
                     '"/><stop offset="1" stop-color="' + b + '"/></radialGradient>');
    }
    return "url(#" + id + ")";
  };
  /* Light that spills: magic, a glowing eye, a lava crack. */
  Ctx.prototype.glow = function (strength) {
    var id = this.id + "-glow" + (strength || 1.6);
    if (!this.made[id]) {
      this.made[id] = 1;
      this.defs.push('<filter id="' + id + '" x="-60%" y="-60%" width="220%" height="220%">' +
                     '<feGaussianBlur stdDeviation="' + (strength || 1.6) + '" result="b"/>' +
                     '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>');
    }
    return 'filter="url(#' + id + ')"';
  };
  Ctx.prototype.blur = function (strength) {
    var id = this.id + "-blur" + strength;
    if (!this.made[id]) {
      this.made[id] = 1;
      this.defs.push('<filter id="' + id + '" x="-50%" y="-50%" width="200%" height="200%">' +
                     '<feGaussianBlur stdDeviation="' + strength + '"/></filter>');
    }
    return 'filter="url(#' + id + ')"';
  };

  function p(d, fill, more) {
    return '<path d="' + d + '" fill="' + fill + '"' + (more ? " " + more : "") + "/>";
  }
  function line(d, color, width, more) {
    return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="' + width +
           '" stroke-linecap="round" stroke-linejoin="round"' + (more ? " " + more : "") + "/>";
  }
  function circle(x, y, r, fill, more) {
    return '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" fill="' + fill + '"' +
           (more ? " " + more : "") + "/>";
  }
  function ellipse(x, y, rx, ry, fill, more) {
    return '<ellipse cx="' + x + '" cy="' + y + '" rx="' + rx + '" ry="' + ry + '" fill="' +
           fill + '"' + (more ? " " + more : "") + "/>";
  }
  function starPoints(x, y, outer, inner, n) {
    var pts = [];
    for (var i = 0; i < n * 2; i++) {
      var r = i % 2 ? inner : outer, a = Math.PI / n * i - Math.PI / 2;
      pts.push((x + r * Math.cos(a)).toFixed(1) + "," + (y + r * Math.sin(a)).toFixed(1));
    }
    return pts.join(" ");
  }
  function star(x, y, outer, inner, fill, more) {
    return '<polygon points="' + starPoints(x, y, outer, inner, 5) + '" fill="' + fill + '"' +
           (more ? " " + more : "") + "/>";
  }
  /* A pixel grid: rows of characters, each a colour from `pal` ("." is
     empty). Runs of one colour are one rect, so a 16×16 sprite is a few
     dozen shapes, not 256. */
  function pixels(rows, pal, x0, y0, size) {
    var out = "";
    rows.forEach(function (row, r) {
      var c = 0;
      while (c < row.length) {
        var ch = row[c], start = c;
        while (c < row.length && row[c] === ch) c++;
        if (ch !== "." && pal[ch]) {
          out += '<rect x="' + (x0 + start * size) + '" y="' + (y0 + r * size) + '" width="' +
                 ((c - start) * size + 0.05) + '" height="' + (size + 0.05) + '" fill="' + pal[ch] + '"/>';
        }
      }
    });
    return out;
  }
  /* A tiny repeatable "random" for speckles, so the same avatar is always
     drawn the same. */
  function speckle(seed) {
    var s = seed;
    return function () { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  }

  // -------------------------------------------------------- backgrounds

  function solid(c) {
    return function (x) {
      return '<rect width="100" height="100" fill="' + x.rad("bg", shade(c, 18), shade(c, -35), 0.5, 0.35, 0.8) + '"/>';
    };
  }
  function pine(x, base, h, w, c) {
    return p("M" + x + " " + (base - h) + " L" + (x + w / 2) + " " + base + " L" + (x - w / 2) + " " + base + "Z", c);
  }
  function stars(seed, n, maxY) {
    var rnd = speckle(seed), out = "";
    for (var i = 0; i < n; i++) {
      out += circle((rnd() * 100).toFixed(1), (rnd() * maxY).toFixed(1), (0.3 + rnd() * 0.7).toFixed(2),
                    "#fff", 'opacity="' + (0.4 + rnd() * 0.6).toFixed(2) + '"');
    }
    return out;
  }

  var BACK = {
    // Cliffs, falls and a castle high up: the world in the class's picture.
    falls: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#79b2dd", "#d3ebf3") + '"/>' +
        p("M0 66 L0 30 Q6 22 12 25 L18 12 Q27 6 34 16 L36 66Z", "#6e8f87") +
        p("M62 66 L63 18 Q71 6 80 11 L87 22 Q95 17 100 23 L100 66Z", "#5d7d74") +
        // A castle on the right-hand cliff, clear of where a head goes.
        p("M66 13 L66 5 L68 5 L68 7 L70 7 L70 2 L73 2 L73 7 L76 7 L76 4 L78 4 L78 13Z", "#a7b6c0", 'opacity=".85"') +
        '<rect x="20" y="22" width="3" height="46" fill="' + x.lin("fall", "#ffffff", "#bfe3f5") + '" opacity=".9"/>' +
        '<rect x="71" y="16" width="4" height="52" fill="' + x.lin("fall", "#ffffff", "#bfe3f5") + '" opacity=".9"/>' +
        '<rect x="86" y="26" width="2" height="40" fill="#e6f5fc" opacity=".8"/>' +
        p("M0 100 L0 60 Q8 52 17 59 Q25 50 33 57 Q40 52 47 60 L47 100Z", "#3e7b46") +
        p("M55 100 L55 62 Q64 53 73 60 Q83 51 91 58 Q97 55 100 59 L100 100Z", "#346c3b") +
        p("M0 70 Q9 63 18 69 Q27 62 36 68 L36 100 L0 100Z", "#2c5e33", 'opacity=".8"') +
        ellipse(50, 74, 60, 9, "#ffffff", 'opacity=".35" ' + x.blur(3));
    },
    forest: function (x) {
      var out = '<rect width="100" height="100" fill="' + x.lin("sky", "#2c5440", "#0f2016") + '"/>' +
        '<polygon points="30,0 44,0 20,100 0,100" fill="#fff" opacity=".05"/>' +
        '<polygon points="62,0 70,0 56,100 44,100" fill="#fff" opacity=".04"/>';
      [[8, 70, 44, 18], [26, 66, 40, 16], [70, 68, 46, 18], [90, 64, 40, 16], [50, 62, 34, 14]]
        .forEach(function (t) { out += pine(t[0], t[1], t[2], t[3], "#26493a"); });
      [[0, 100, 56, 24], [18, 104, 50, 22], [84, 102, 58, 26], [100, 100, 50, 22]]
        .forEach(function (t) { out += pine(t[0], t[1], t[2], t[3], "#14291d"); });
      return out;
    },
    slate: solid("#3a4352"),
    midnight: solid("#1b2238"),
    crimson: solid("#5e1a28"),
    sky: solid("#6a9cc9"),
    castle: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#33406e", "#cf8c76") + '"/>' +
        circle(78, 26, 7, "#f6dfb8", 'opacity=".9"') +
        p("M0 100 L0 70 L10 70 L10 58 L14 58 L14 54 L18 58 L18 70 L28 70 L28 48 L31 44 L34 48 L34 70 " +
          "L66 70 L66 46 L69 42 L72 46 L72 70 L82 70 L82 56 L86 52 L90 56 L90 70 L100 70 L100 100Z", "#1d2036") +
        '<rect x="30" y="54" width="2" height="3" fill="#ffd27a"/><rect x="68" y="52" width="2" height="3" fill="#ffd27a"/>' +
        '<rect x="85" y="60" width="2" height="3" fill="#ffd27a"/>';
    },
    night: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#0a0f24", "#22315c") + '"/>' +
        stars(7, 40, 70) + circle(76, 22, 8, "#f3edd2", x.glow(2.5));
    },
    sunset: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#ffb75e", "#a53f6d") + '"/>' +
        circle(50, 70, 20, "#ffd98a", 'opacity=".85"') +
        p("M0 100 L0 72 L18 58 L30 68 L46 52 L62 70 L76 58 L100 74 L100 100Z", "#4a2648") +
        p("M0 100 L0 84 L22 74 L40 84 L60 76 L82 86 L100 80 L100 100Z", "#2e1730");
    },
    lava: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#120404", "#5c1406") + '"/>' +
        line("M0 86 L14 80 L22 88 L36 82 M64 90 L78 82 L90 88 L100 84 M30 100 L40 92 L52 96", "#ff6a1a", 1.4, x.glow(1.6)) +
        stars(3, 14, 90).replace(/#fff/g, "#ffb04a");
    },
    galaxy: function (x) {
      return '<rect width="100" height="100" fill="' + x.lin("sky", "#100a2a", "#3b1d66") + '"/>' +
        ellipse(36, 38, 40, 14, "#8a46cf", 'opacity=".45" transform="rotate(-25 36 38)" ' + x.blur(6)) +
        ellipse(70, 60, 34, 10, "#2f86c9", 'opacity=".35" transform="rotate(-25 70 60)" ' + x.blur(6)) +
        stars(11, 46, 100);
    }
  };

  // ---------------------------------------------------------- the hero

  var SKIN = { s1: "#f6d8c2", s2: "#ecbf96", s3: "#d9a273", s4: "#bd8150", s5: "#8d5a35", s6: "#5c3a22" };
  var HAIR = { black: "#1e1a18", brown: "#57381f", auburn: "#7d3418", blonde: "#d6b06a",
               red: "#a4321c", gray: "#9a9aa2", blue: "#2b5bb8", purple: "#6a3aa6",
               white: "#ecebf2", gold: "#d4a017" };

  // The shoulders every outfit fills, and the neck under them.
  var SHOULDERS = "M6 100 L8 88 Q12 72 31 68 Q41 65.5 50 66 Q59 65.5 69 68 Q88 72 92 88 L94 100Z";

  function shoulders(x, name, color, light) {
    return p(SHOULDERS, x.lin(name, light || shade(color, 12), shade(color, -30)));
  }
  function pauldrons(x, color, edge) {
    var f = x.lin("pauld", shade(color, 25), shade(color, -20));
    return p("M6 86 Q8 70 26 68 Q36 70 36 80 Q22 78 10 92Z", f, 'stroke="' + edge + '" stroke-width="1"') +
           p("M94 86 Q92 70 74 68 Q64 70 64 80 Q78 78 90 92Z", f, 'stroke="' + edge + '" stroke-width="1"');
  }
  function vNeck(fill) { return p("M43.5 66.5 L50 82 L56.5 66.5 Q50 70 43.5 66.5Z", fill); }

  var OUTFIT = {
    duelist: function (x) {
      return shoulders(x, "duel", "#8e1f2a") + vNeck("#ece6d8") +
        p("M43.5 66.5 L39 100 L45 100 L50 82Z", "#25252b") + p("M56.5 66.5 L61 100 L55 100 L50 82Z", "#25252b") +
        p("M42 66 L35 80 L40 87 L44 68Z", "#6e141e") + p("M58 66 L65 80 L60 87 L56 68Z", "#6e141e") +
        circle(46.5, 91, 0.9, "#d4af37") + circle(53.5, 91, 0.9, "#d4af37") +
        p("M40 66 Q50 61.5 60 66 L59 62.5 Q50 59 41 62.5Z", "#a3283a");
    },
    bard: function (x) {
      return shoulders(x, "bard", "#2c4f7a") + vNeck("#e8dcc4") +
        line("M26 72 L62 100", "#6b4a2b", 3) +
        p("M39.5 63 Q50 70 60.5 63 Q62 70 58 73 Q50 77 42 73 Q38 70 39.5 63Z", "#4f9a52") +
        p("M52 72 L57 94 L50 96 L47.5 74Z", "#3e8443");
    },
    scout: function (x) {
      return shoulders(x, "scout", "#7a4a2a") + vNeck("#d9c8a8") +
        p("M37 73 Q50 79 63 73 L63 86 Q50 92 37 86Z", "#5c381f", 'stroke="#3a2313" stroke-width="1"') +
        line("M37 79.5 Q50 85.5 63 79.5", "#3a2313", 0.8) +
        p("M8 86 Q10 72 27 69 Q34 71 33 79 Q20 78 12 92Z", "#8f5a33", 'stroke="#3a2313" stroke-width="1"');
    },
    hoodie: function (x) {
      return shoulders(x, "hood", "#3c4552") +
        p("M32 69 Q36 59.5 50 62.5 Q64 59.5 68 69 Q60 74 50 73.5 Q40 74 32 69Z", "#2c333d") +
        line("M46 73 L45 85 M54 73 L55 85", "#d9d9d9", 0.9);
    },
    tee: function (x) {
      return shoulders(x, "tee", "#2f3542") + line("M42 66.5 Q50 72 58 66.5", "#1f242e", 2.2);
    },
    jacket: function (x) {
      return shoulders(x, "jacket", "#2c2826") + vNeck("#3d5068") +
        p("M43.5 66.5 L38 84 L45 100 L50 82Z", "#221f1d") + p("M56.5 66.5 L62 84 L55 100 L50 82Z", "#221f1d") +
        line("M43.5 66.5 L38 84 L45 100 M56.5 66.5 L62 84 L55 100", "#4a4440", 0.8);
    },
    varsity: function (x) {
      return shoulders(x, "vars", "#7a1e2a") +
        p("M6 100 L8 88 Q12 72 31 68 L30 100Z", "#ece2cc") + p("M94 100 L92 88 Q88 72 69 68 L70 100Z", "#ece2cc") +
        line("M41 66.5 Q50 72 59 66.5", "#ece2cc", 2.6) + line("M41.5 69 Q50 74.5 58.5 69", "#7a1e2a", 1) +
        line("M50 73 L50 100", "#5c1520", 0.8);
    },
    rogue: function (x) {
      return shoulders(x, "rogue", "#2f4a35") + line("M26 70 L64 100", "#4a3220", 3.2) +
        '<rect x="42" y="84" width="4" height="3" fill="#b8a46a" transform="rotate(38 44 85)"/>' +
        p("M39.5 62.5 Q50 70 60.5 62.5 L61.5 68.5 Q50 76 38.5 68.5Z", "#22372a");
    },
    warrior: function (x) {
      return shoulders(x, "war", "#3d5a3a") +
        p("M36 72 Q50 77 64 72 L63 92 Q50 97 37 92Z", x.lin("plate", "#8a9a84", "#55634f"), 'stroke="#33402f" stroke-width="1"') +
        circle(40, 76, 0.8, "#cfd8c9") + circle(60, 76, 0.8, "#cfd8c9") +
        pauldrons(x, "#7c8c75", "#33402f");
    },
    knight: function (x) {
      return shoulders(x, "kn", "#7d8794") +
        p("M36 71 Q50 76 64 71 L63 96 Q50 100 37 96Z", x.lin("plate", "#c4ccd6", "#79828e"), 'stroke="#545c66" stroke-width="1"') +
        line("M50 75 L50 98", "#545c66", 0.8) + line("M37 74 Q50 79 63 74", "#d4af37", 1) +
        pauldrons(x, "#a6aeb9", "#545c66");
    },
    mage: function (x) {
      return shoulders(x, "mage", "#2d3c96") + line("M41 66.5 L50 86 L59 66.5", "#d4af37", 2.4) +
        star(50, 92, 3.2, 1.3, "#e8c860") +
        p("M36 68 Q38 60 44 62 L43 68Z", "#25307a") + p("M64 68 Q62 60 56 62 L57 68Z", "#25307a");
    },
    ranger: function (x) {
      return shoulders(x, "rang", "#6b4a2b") + vNeck("#d9c8a8") +
        p("M6 100 L8 86 Q12 70 32 66 Q42 64 46 70 L40 100Z", "#2f5a3a") +
        p("M94 100 L92 86 Q88 70 68 66 Q58 64 54 70 L60 100Z", "#2f5a3a") +
        circle(50, 72, 2.2, "#d4af37", 'stroke="#8a6d1f" stroke-width=".6"');
    },
    sorcerer: function (x) {
      return shoulders(x, "sorc", "#1f2a55") + line("M41 66.5 L50 84 L59 66.5", "#b9c3e0", 1.8) +
        circle(50, 90, 2.6, "#7fd4ff", x.glow(1.8)) +
        p("M34 70 Q36 58 45 61 L44 69Z", "#18214a") + p("M66 70 Q64 58 55 61 L56 69Z", "#18214a");
    },
    darkknight: function (x) {
      return shoulders(x, "dk", "#1c1c22") +
        p("M36 71 Q50 76 64 71 L63 96 Q50 100 37 96Z", x.lin("plate", "#3a3a44", "#141418"), 'stroke="#0b0b0e" stroke-width="1"') +
        line("M40 78 L50 84 L60 78 M50 84 L50 96", "#ff5a1f", 0.9, x.glow(1.2)) +
        p("M6 86 Q8 70 26 67 L22 58 L32 66 Q36 70 36 80 Q22 78 10 92Z", "#2a2a32", 'stroke="#0b0b0e" stroke-width="1"') +
        p("M94 86 Q92 70 74 67 L78 58 L68 66 Q64 70 64 80 Q78 78 90 92Z", "#2a2a32", 'stroke="#0b0b0e" stroke-width="1"');
    },
    paladin: function (x) {
      return shoulders(x, "pal", "#d9d3c2") +
        p("M36 71 Q50 76 64 71 L63 96 Q50 100 37 96Z", x.lin("plate", "#f4efe2", "#bdb39a"), 'stroke="#a8862a" stroke-width="1.2"') +
        circle(50, 85, 4, "#e2b93b", x.glow(1.2)) + star(50, 85, 6.5, 2.2, "#e2b93b", 'opacity=".6"') +
        pauldrons(x, "#e2b93b", "#8a6d1f");
    }
  };

  // Hair: a part behind the head (hanging down past it) and a part in front.
  var TOP_LIGHT = "M42 22.5 Q49 20 56 22";
  var HAIR_STYLE = {
    none: { front: function () { return ""; } },
    short: { front: function (c) {
      return p("M35.5 39 Q34 21 50 20 Q66 21 64.5 39 Q63 29 57 27.5 Q50 29.5 43 27.5 Q37 29 35.5 39Z", c); } },
    buzz: { front: function (c) {
      return p("M36 35 Q36 22 50 21.5 Q64 22 64 35 Q60 27.5 50 27 Q40 27.5 36 35Z", c, 'opacity=".85"'); } },
    swept: { front: function (c) {
      return p("M35.5 38 Q34 18 52 17.5 Q68 18 65 34 Q60 25 48 27 Q42 28.5 39 34 Q38 37 35.5 38Z", c) +
        p("M39 31 Q36.5 37 40 40 Q41 33 47 28Z", c); } },
    messy: { front: function (c) {
      return p("M35 39 Q33 22 42 19.5 Q46 15.5 52 18 Q58 15.5 61 20.5 Q67 23 65 39 Q63 31 60 31.5 " +
               "Q58 26.5 54 29.5 Q50 25.5 46 29.5 Q42 26.5 40 31.5 Q37 30.5 35 39Z", c); } },
    curly: { front: function (c) {
      var out = "";
      [[36, 36], [36.5, 29.5], [40, 24], [45.5, 20.5], [51.5, 19.5], [57.5, 21], [62, 25], [64, 31],
       [64, 37], [44, 26], [50, 25], [56, 26]].forEach(function (pt) {
        out += circle(pt[0], pt[1], 4.6, c, 'stroke="' + shade(c, -30) + '" stroke-width=".5"');
      });
      return out; } },
    long: {
      back: function (c) {
        return p("M33 38 Q32 19 50 18.5 Q68 19 67 38 L70 74 Q61 78 57 71 L56 52 L44 52 L43 71 Q39 78 30 74Z", shade(c, -12)); },
      front: function (c) {
        return p("M35.5 41 Q34 21 50 20 Q66 21 64.5 41 Q62 28 52 26.5 Q49 32 42 30.5 Q37 33 35.5 41Z", c) +
          p("M35.5 34 Q33 47 36.5 58 L38.5 57 Q37 46 38 36Z", c) + p("M64.5 34 Q67 47 63.5 58 L61.5 57 Q63 46 62 36Z", c); } },
    ponytail: {
      back: function (c) { return p("M60 23 Q75 26 73 45 Q71 60 64 66 Q68 50 63 35Z", shade(c, -12)); },
      front: function (c) {
        return p("M35.5 39 Q34 20 50 19.5 Q66 20 64.5 37 Q61 27 52 26.5 Q44 27 39 32 Q36.5 35 35.5 39Z", c); } },
    braids: {
      back: function (c) { return p("M34 38 Q33 20 50 19.5 Q67 20 66 38 L64 56 L36 56Z", shade(c, -12)); },
      front: function (c) {
        var out = p("M35.5 39 Q34 21 50 20 Q66 21 64.5 39 Q60 27 50 27.5 Q40 27 35.5 39Z", c);
        for (var i = 0; i < 6; i++) {
          out += ellipse(36.5 - i * 0.6, 50 + i * 5, 2.6, 3.1, c, 'stroke="' + shade(c, -30) + '" stroke-width=".5"');
          out += ellipse(63.5 + i * 0.6, 50 + i * 5, 2.6, 3.1, c, 'stroke="' + shade(c, -30) + '" stroke-width=".5"');
        }
        return out; } },
    spiky: { front: function (c) {
      return p("M35 39 L33 22 L40 27 L41 15 L47 23 L51 12 L55 22 L61 14 L61 25 L68 21 L65 39 " +
               "Q62 29.5 50 28.5 Q39 29.5 35 39Z", c); } },
    mohawk: { front: function (c) {
      return p("M36 36 Q36 22 50 21.5 Q64 22 64 36 Q60 28 50 27.5 Q40 28 36 36Z", c, 'opacity=".35"') +
        p("M45.5 31 L44 9 Q50 3 56 9 L54.5 31Z", c); } }
  };

  function brows(color, kind) {
    if (kind === "fierce") return line("M40 35.2 L47.6 37.6 M60 35.2 L52.4 37.6", color, 1.5);
    if (kind === "focused") return line("M40.2 36 Q44 35.6 47.6 37 M59.8 36 Q56 35.6 52.4 37", color, 1.3);
    return line("M40.2 36.6 Q44 34.8 47.6 36.2 M59.8 36.6 Q56 34.8 52.4 36.2", color, 1.2);
  }
  function eye(x, cx, iris, glowing) {
    var y = 40.6;
    var white = glowing ? shade(iris, 60) : "#f4f1ec";
    return p("M" + (cx - 3.7) + " " + y + " Q" + cx + " " + (y - 2.9) + " " + (cx + 3.7) + " " + y +
             " Q" + cx + " " + (y + 2.3) + " " + (cx - 3.7) + " " + y + "Z", white, glowing ? x.glow(1.4) : "") +
      circle(cx, y + 0.1, 1.75, iris, glowing ? x.glow(1) : "") +
      (glowing ? "" : circle(cx, y + 0.1, 0.85, "#120c09") + circle(cx + 0.6, y - 0.5, 0.45, "#fff")) +
      line("M" + (cx - 3.9) + " " + (y + 0.1) + " Q" + cx + " " + (y - 3.1) + " " + (cx + 3.9) + " " + (y + 0.1),
           "#1f1612", 0.9);
  }
  var EYES = {
    calm: function (x) { return eye(x, 44, "#5a3d2a") + eye(x, 56, "#5a3d2a"); },
    focused: function (x) { return eye(x, 44, "#3f5f7a") + eye(x, 56, "#3f5f7a"); },
    fierce: function (x) { return eye(x, 44, "#6b5a2a") + eye(x, 56, "#6b5a2a"); },
    glow: function (x) { return eye(x, 44, "#34d5ff", true) + eye(x, 56, "#34d5ff", true); },
    ember: function (x) { return eye(x, 44, "#ff6a1f", true) + eye(x, 56, "#ff6a1f", true); }
  };
  var MOUTH = {
    neutral: function () { return line("M46.5 52.2 Q50 52.9 53.5 52.2", "#6b3a32", 1.1); },
    smile: function () { return line("M46 51.6 Q50 54.4 54 51.6", "#6b3a32", 1.15); },
    smirk: function () { return line("M46.5 52.5 Q51 53.1 54.5 50.9", "#6b3a32", 1.15); },
    grin: function () {
      return p("M45.5 51 Q50 56.5 54.5 51Z", "#5c1f22") +
        p("M46.3 51.3 L53.7 51.3 Q53.3 52.6 50 52.8 Q46.7 52.6 46.3 51.3Z", "#f4f1ec");
    }
  };
  var BEARD = {
    none: function () { return ""; },
    stubble: function (x, c) {
      return p("M36.5 44 Q38 56 50 58.5 Q62 56 63.5 44 Q60 52.5 50 55 Q40 52.5 36.5 44Z", c, 'opacity=".32"') +
        p("M45.5 50.3 Q50 49 54.5 50.3 Q50 50.6 45.5 50.3Z", c, 'opacity=".4"');
    },
    goatee: function (x, c) {
      return p("M46.5 54 Q50 59.5 53.5 54 Q50 55.6 46.5 54Z", c) +
        p("M45.5 50.6 Q50 48.6 54.5 50.6 Q52 50 50 50.4 Q48 50 45.5 50.6Z", c);
    },
    full: function (x, c) {
      return p("M35.5 41 Q35 59 50 62 Q65 59 64.5 41 Q62.5 50 57.5 52.5 Q54 49.2 50 50 Q46 49.2 42.5 52.5 Q37.5 50 35.5 41Z", c);
    }
  };
  var MARKS = {
    none: function () { return ""; },
    freckles: function (x, s) {
      var out = "", d = shade(s, -30);
      [[40, 45], [42, 46.6], [44, 45.4], [56, 45.4], [58, 46.6], [60, 45]].forEach(function (pt) {
        out += circle(pt[0], pt[1], 0.45, d);
      });
      return out;
    },
    scar: function (x, s) {
      return line("M41 33.5 L45.5 46", shade(s, -35), 1) + line("M41.8 37 L43.6 36.2 M43 40.5 L44.8 39.7", shade(s, -35), 0.6);
    },
    warpaint: function () {
      return p("M39 43.5 L47.5 43 L46.5 45 L39.5 45.5Z", "#8a1c1c", 'opacity=".85"') +
        p("M61 43.5 L52.5 43 L53.5 45 L60.5 45.5Z", "#8a1c1c", 'opacity=".85"');
    },
    rune: function (x) {
      return p("M50 26.5 L52 29.5 L50 32.5 L48 29.5Z", "none", 'stroke="#7fe7ff" stroke-width=".8" ' + x.glow(1.2)) +
        circle(50, 29.5, 0.6, "#7fe7ff", x.glow(1));
    }
  };
  var GLASSES = {
    none: function () { return ""; },
    round: function () {
      return '<g fill="rgba(220,235,255,.12)" stroke="#2a2522" stroke-width="1.1">' +
        circle(44, 40.6, 4.5, "rgba(220,235,255,.12)") + circle(56, 40.6, 4.5, "rgba(220,235,255,.12)") + "</g>" +
        line("M48.5 40.4 Q50 39.6 51.5 40.4 M39.5 40 L36 39.4 M60.5 40 L64 39.4", "#2a2522", 0.9);
    },
    square: function () {
      return '<rect x="38.8" y="37.4" width="10" height="6.8" rx="1.4" fill="rgba(220,235,255,.12)" stroke="#1b1b1b" stroke-width="1.6"/>' +
        '<rect x="51.2" y="37.4" width="10" height="6.8" rx="1.4" fill="rgba(220,235,255,.12)" stroke="#1b1b1b" stroke-width="1.6"/>' +
        line("M48.8 40 L51.2 40 M38.8 39.6 L36 39 M61.2 39.6 L64 39", "#1b1b1b", 1.2);
    },
    shades: function () {
      return p("M38.5 38 L49 38 L48.2 42.5 Q44 44.5 39.5 42.5Z", "#121214") +
        p("M51 38 L61.5 38 L60.5 42.5 Q56 44.5 51.8 42.5Z", "#121214") +
        line("M49 38.6 L51 38.6 M38.5 38.6 L36 38.2 M61.5 38.6 L64 38.2", "#121214", 1.1) +
        line("M40.5 39.4 L43 39.4", "#fff", 0.5, 'opacity=".5"');
    }
  };
  var MASK = {
    none: function () { return ""; },
    cloth: function () {
      return p("M36.2 43.5 Q37 59 50 61 Q63 59 63.8 43.5 Q57 46 50 45.4 Q43 46 36.2 43.5Z", "#2b3d2f") +
        line("M40 50 Q50 53 60 50 M42 55.5 Q50 58 58 55.5", "#1d2a20", 0.7);
    },
    veil: function () {
      return p("M35.5 42.5 Q36 61 50 63 Q64 61 64.5 42.5 L60 44.5 Q50 47.5 40 44.5Z", "#1a1f3d") +
        line("M35.5 42.5 L40 44.5 Q50 47.5 60 44.5 L64.5 42.5", "#b9c3e0", 0.8);
    }
  };

  /* Hats come in two halves too: what sits behind the head (a hood's back,
     a wizard's brim behind) and what goes over the hair. `covers` hides the
     hair's top, which would otherwise poke through. */
  var HAT = {
    none: { front: function () { return ""; } },
    hood: {
      back: function (x) {
        return p("M30 46 Q29 13 50 12 Q71 13 70 46 Q71 62 63 70 L37 70 Q29 62 30 46Z", x.lin("hoodb", "#3d4a3f", "#222b24"));
      },
      front: function () {
        return p("M33 42 Q32 15 50 14 Q68 15 67 42 Q66 25 50 24 Q34 25 33 42Z", "#34403a") +
          line("M33.5 42 Q33 19 50 18.5 Q67 19 66.5 42", "#262f29", 1.2);
      },
      covers: true
    },
    bandana: { front: function () {
      return p("M34.5 31 Q50 25.5 65.5 31 L65.5 35.5 Q50 30.5 34.5 35.5Z", "#2f4a63") +
        line("M38 31.5 L40 33.5 M45 29.5 L47 31.5 M53 29.5 L55 31.5 M60 31 L62 33", "#9bb6cc", 0.6) +
        p("M65 31.5 L72 28.5 L70 33 L73 37 L65 34.5Z", "#2f4a63");
    } },
    beanie: { front: function () {
      return p("M34.3 34 Q34 15 50 14.5 Q66 15 65.7 34Z", "#3f4a5c") +
        p("M33.8 30.5 Q50 27.5 66.2 30.5 L66.5 35.5 Q50 32.5 33.5 35.5Z", "#2f3846") +
        line("M40 18 L40 30 M45 16 L45 29 M50 15.5 L50 28.5 M55 16 L55 29 M60 18 L60 30", "#4b586c", 0.6);
    }, covers: true },
    cap: { front: function () {
      return p("M35 32 Q35 16 50 15.5 Q65 16 65 32 Q50 28.5 35 32Z", "#7a2230") +
        p("M64 25 Q74 21 77 26 Q72 30 64 30Z", "#5c1823") +
        '<rect x="45" y="28.6" width="10" height="2.2" rx="1" fill="#e9e1d0"/>';
    }, covers: true },
    headphones: { front: function (x) {
      return line("M33.5 42 Q32 13 50 13 Q68 13 66.5 42", "#2a2a2e", 3) +
        '<rect x="29" y="35" width="7.5" height="13" rx="3.2" fill="#2a2a2e"/>' +
        '<rect x="63.5" y="35" width="7.5" height="13" rx="3.2" fill="#2a2a2e"/>' +
        '<rect x="30.6" y="37" width="4.3" height="9" rx="2" fill="none" stroke="#ff5050" stroke-width=".9" ' + x.glow(1) + '/>' +
        '<rect x="65.1" y="37" width="4.3" height="9" rx="2" fill="none" stroke="#ff5050" stroke-width=".9" ' + x.glow(1) + '/>';
    } },
    circlet: { front: function (x) {
      return line("M35.5 32.5 Q50 27.5 64.5 32.5", "#d4af37", 1.5) +
        p("M50 27 L52 29.6 L50 32.2 L48 29.6Z", "#5fe0ff", x.glow(1.2));
    } },
    helmet: { front: function (x, a) {
      var lit = a.eyes === "glow" ? "#34d5ff" : a.eyes === "ember" ? "#ff6a1f" : null;
      return p("M50 15 Q58 3 68 6 Q59 8 55 16Z", "#a3283a") +
        p("M32.5 46 Q31.5 15 50 14 Q68.5 15 67.5 46 L66 57 Q58 63.5 50 63.5 Q42 63.5 34 57Z",
          x.lin("helm", "#c3cad3", "#6b737e"), 'stroke="#4d545e" stroke-width="1"') +
        line("M50 15 L50 38", "#8a929d", 1) +
        p("M37 38.5 L63 38.5 L62 42.8 L38 42.8Z", "#0d0d10") +
        (lit ? circle(44, 40.6, 1.3, lit, x.glow(1.4)) + circle(56, 40.6, 1.3, lit, x.glow(1.4)) : "") +
        circle(46, 50, 0.7, "#2c3138") + circle(50, 51, 0.7, "#2c3138") + circle(54, 50, 0.7, "#2c3138");
    }, covers: true, face: true },
    wizard: {
      back: function () { return ellipse(50, 26, 23, 4.8, "#2c1f63"); },
      front: function () {
        return p("M37 26 Q46 15 49 -2 Q56 10 63 26Z", "#43319a") +
          p("M36.5 22.5 Q50 26 63.5 22.5 L64 26.5 Q50 30 36 26.5Z", "#d4af37") +
          star(51, 13, 2.8, 1.1, "#f2d36b");
      }, covers: true },
    crown: { front: function (x) {
      return p("M36 28 L36 14 L42 20.5 L50 10 L58 20.5 L64 14 L64 28Z", x.lin("crown", "#ffe07a", "#c08a12"),
               'stroke="#8a6410" stroke-width=".8"') +
        circle(50, 23, 1.7, "#d6455d") + circle(42, 24.5, 1.1, "#3fb6e0") + circle(58, 24.5, 1.1, "#3fb6e0");
    } }
  };

  // Magic in the hands, lower corners, like the heroes in a class picture.
  var EFFECT = {
    none: function () { return ""; },
    sparks: function (x) {
      return "<g " + x.glow(1.2) + ">" + star(16, 82, 2.6, 0.9, "#ffe58a") + star(24, 74, 1.6, 0.6, "#ffe58a") +
        star(84, 80, 2.4, 0.8, "#ffe58a") + star(78, 90, 1.4, 0.5, "#ffe58a") + "</g>";
    },
    fire: function (x) {
      var f = "M0 0 Q-9 -14 -1 -25 Q-1 -16 4 -14 Q4 -26 12 -32 Q10 -20 16 -14 Q20 -8 16 0Z";
      var fill = x.lin("flame", "#ffd25a", "#ff4a1a");
      return '<g ' + x.glow(1.6) + '><path transform="translate(9 100)" d="' + f + '" fill="' + fill + '"/>' +
        '<path transform="translate(91 100) scale(-1 1)" d="' + f + '" fill="' + fill + '"/>' +
        '<path transform="translate(13 100) scale(.5)" d="' + f + '" fill="#fff3b0"/>' +
        '<path transform="translate(87 100) scale(-.5 .5)" d="' + f + '" fill="#fff3b0"/></g>';
    },
    frost: function (x) {
      function shard(cx, cy, s) {
        return p("M" + cx + " " + (cy - 8 * s) + " L" + (cx + 2.5 * s) + " " + cy + " L" + cx + " " + (cy + 8 * s) +
                 " L" + (cx - 2.5 * s) + " " + cy + "Z", "#bfefff", 'opacity=".9"');
      }
      return "<g " + x.glow(1.5) + ">" + shard(14, 84, 1) + shard(20, 76, 0.6) + shard(86, 84, 1) +
        shard(80, 76, 0.6) + "</g>";
    },
    arcane: function (x) {
      return "<g " + x.glow(1.6) + ">" +
        ellipse(16, 84, 9, 3.5, "none", 'stroke="#b46cff" stroke-width="1.2" transform="rotate(-25 16 84)"') +
        ellipse(16, 84, 5, 7, "none", 'stroke="#6fd6ff" stroke-width=".9"') +
        ellipse(84, 84, 9, 3.5, "none", 'stroke="#b46cff" stroke-width="1.2" transform="rotate(25 84 84)"') +
        circle(16, 84, 2, "#e3c6ff") + circle(84, 84, 2, "#e3c6ff") + "</g>";
    },
    nature: function (x) {
      return "<g " + x.glow(1.5) + ">" +
        line("M4 100 Q10 76 24 80 Q32 84 26 92 Q20 96 18 88", "#7dff8a", 1.4) +
        line("M96 100 Q90 76 76 80 Q68 84 74 92 Q80 96 82 88", "#7dff8a", 1.4) +
        ellipse(24, 79, 2.6, 1.3, "#4fd66a", 'transform="rotate(-30 24 79)"') +
        ellipse(76, 79, 2.6, 1.3, "#4fd66a", 'transform="rotate(30 76 79)"') + "</g>";
    },
    lightning: function (x) {
      return "<g " + x.glow(1.4) + ">" +
        p("M18 66 L10 82 L16 82 L9 98 L23 78 L17 78 L24 66Z", "#ffe94a") +
        p("M82 66 L90 82 L84 82 L91 98 L77 78 L83 78 L76 66Z", "#ffe94a") + "</g>";
    }
  };

  function hero(x, a) {
    var s = SKIN[a.skin], c = HAIR[a.hair_color];
    var hair = HAIR_STYLE[a.hair], hat = HAT[a.hat];
    var browColor = a.hair === "none" ? "#3a2a20" : shade(c, c === HAIR.white || c === HAIR.blonde ? -35 : -15);
    var faceFill = x.rad("skin", shade(s, 8), shade(s, -14), 0.42, 0.35, 0.7);
    var face = a.face === "square"
      ? p("M35.5 34 Q36 20.5 50 20.5 Q64 20.5 64.5 34 L64 46 Q62 56.5 50 59 Q38 56.5 36 46Z", faceFill)
      : a.face === "round"
        ? ellipse(50, 40, 15.2, 17.6, faceFill)
        : ellipse(50, 40, 14.3, 18.2, faceFill);
    var out = "";
    if (hat.back) out += hat.back(x, a);
    if (hair.back && !(hat.covers && a.hat === "hood")) out += hair.back(c);
    // The neck, and the shadow the jaw throws on it.
    out += p("M44 50 L44 67 Q50 71 56 67 L56 50Z", s) +
      p("M44 54 Q50 60.5 56 54 L56 50 L44 50Z", shade(s, -30), 'opacity=".5"');
    out += OUTFIT[a.outfit](x);
    out += circle(35.5, 41.5, 3.4, shade(s, -6)) + circle(64.5, 41.5, 3.4, shade(s, -6)) + face;
    out += MARKS[a.marks](x, s);
    out += BEARD[a.beard](x, shade(c, -8));
    out += line("M50.6 42.2 Q49 46.8 48.7 47.5 Q50 48.5 51.6 47.8", shade(s, -30), 0.85);
    out += MOUTH[a.mouth]();
    out += EYES[a.eyes](x) + brows(browColor, a.eyes);
    if (!(hat.covers && (a.hat === "hood"))) {
      out += hair.front(c);
      if (a.hair !== "none" && a.hair !== "mohawk" && a.hair !== "buzz") {
        out += line(TOP_LIGHT, shade(c, 35), 1.1, 'opacity=".55"');
      }
    } else if (a.hair !== "none") {
      // Under a hood only a fringe shows.
      out += p("M38 33 Q44 27 50 28 Q56 27 62 33 Q56 30.5 50 31 Q44 30.5 38 33Z", c);
    }
    out += MASK[a.mask]();
    out += GLASSES[a.glasses]();
    out += hat.front(x, a);
    out += EFFECT[a.effect](x);
    return out;
  }

  // ------------------------------------------------------- the pictures

  function cube(top, left, right, cx, cy, s) {
    // Three 8×8 faces of a block, each a pixel grid bent into place.
    return '<g transform="matrix(' + s + ' ' + s / 2 + ' ' + (-s) + ' ' + s / 2 + ' ' + cx + ' ' + (cy - 8 * s) + ')">' +
      pixels(top.rows, top.pal, 0, 0, 1) + "</g>" +
      '<g transform="matrix(' + s + ' ' + s / 2 + ' 0 ' + s + ' ' + (cx - 8 * s) + ' ' + (cy - 4 * s) + ')">' +
      pixels(left.rows, left.pal, 0, 0, 1) + "</g>" +
      '<g transform="matrix(' + s + ' ' + (-s / 2) + ' 0 ' + s + ' ' + cx + ' ' + cy + ')">' +
      pixels(right.rows, right.pal, 0, 0, 1) + "</g>";
  }
  function noisy(seed, base, alt, rate, rows) {
    var rnd = speckle(seed), out = [];
    for (var r = 0; r < (rows || 8); r++) {
      var row = "";
      for (var c = 0; c < 8; c++) row += rnd() < rate ? alt : base;
      out.push(row);
    }
    return out;
  }
  function darken(pal, pct) {
    var out = {};
    Object.keys(pal).forEach(function (k) { out[k] = shade(pal[k], pct); });
    return out;
  }
  function diagonalTool(kind) {
    // A 16×16 diagonal sprite: blade or handle along c + r = 15.
    var g = [];
    for (var r = 0; r < 16; r++) g.push(Array(17).join(".").split(""));
    function set(c, r, ch) { if (c >= 0 && c < 16 && r >= 0 && r < 16) g[r][c] = ch; }
    if (kind === "sword") {
      for (r = 0; r < 10; r++) { set(15 - r, r, "L"); set(14 - r, r, "O"); set(16 - r, r, "M"); }
      [[3, 8], [4, 9], [5, 10], [6, 11], [7, 12]].forEach(function (q) { set(q[0], q[1], "G"); });
      [[4, 11], [3, 12], [2, 13]].forEach(function (q) { set(q[0], q[1], "H"); });
      set(1, 14, "G"); set(0, 15, "G");
    } else {
      for (r = 3; r < 16; r++) { set(15 - r, r, "H"); set(16 - r, r, "D"); }
      for (r = 0; r < 7; r++) { set(9 + r, r, "C"); set(8 + r, r, "B"); }
    }
    return g.map(function (row) { return row.join(""); });
  }

  var ICON = {
    sun: function (x) {
      var rays = "";
      for (var i = 0; i < 12; i++) {
        rays += '<polygon points="50,14 53,24 47,24" fill="#ffc83a" transform="rotate(' + i * 30 + ' 50 50)"/>';
      }
      return "<g " + x.glow(2) + ">" + rays + circle(50, 50, 18, x.rad("sun", "#fff3a8", "#ffb21a", 0.4, 0.4, 0.7)) + "</g>";
    },
    flower: function (x) {
      var petals = "";
      for (var i = 0; i < 8; i++) {
        petals += ellipse(50, 30, 6.5, 12, x.lin("petal", "#ff9ac0", "#e0457d"), 'transform="rotate(' + i * 45 + ' 50 44)"');
      }
      return line("M50 56 Q47 76 50 96", "#3f8a44", 3) + ellipse(41, 80, 7, 3, "#4fa055", 'transform="rotate(-30 41 80)"') +
        petals + circle(50, 44, 7, x.rad("ctr", "#ffe27a", "#e0a020"));
    },
    moon: function (x) {
      return p("M58 18 A30 30 0 1 0 82 66 A24 24 0 1 1 58 18Z", x.lin("moon", "#fff6d6", "#e2cf8a"), x.glow(2)) +
        star(80, 24, 3, 1.1, "#fff6d6") + star(70, 40, 1.8, 0.7, "#fff6d6") + star(86, 44, 1.4, 0.5, "#fff6d6");
    },
    mountain: function () {
      return circle(74, 28, 8, "#ffe7a3") +
        p("M2 90 L34 36 L52 64 L66 46 L98 90Z", "#4f5d75") +
        p("M34 36 L42 50 L37 48 L32 53 L28 46Z", "#f2f4f8") + p("M66 46 L72 55 L68 54 L64 57 L61 53Z", "#f2f4f8") +
        p("M0 100 L0 86 Q50 78 100 86 L100 100Z", "#2f5a3a");
    },
    wave: function (x) {
      return p("M6 70 Q14 40 38 38 Q60 37 64 56 Q66 66 56 66 Q48 66 50 58 Q52 50 44 51 Q32 53 30 70 Q38 70 46 76 " +
               "Q62 86 80 76 Q90 70 96 74 L96 96 L6 96Z", x.lin("wave", "#5cc8f0", "#1a5fa8")) +
        line("M14 62 Q22 46 38 44", "#e6f7ff", 2, 'opacity=".8"');
    },
    star: function (x) {
      return star(50, 52, 34, 14, x.rad("star", "#fff1a0", "#f0a81a", 0.45, 0.4, 0.7), x.glow(2) + ' stroke="#c27c0e" stroke-width="1.2"');
    },
    blocky: function () {
      var head = ["HHHHHHHH", "HHHHHHHH", "KkKkKkKk", "SSSSSSSS", "SWESSEWS", "SSSNNSSS", "SBBMMBBS", "BBBBBBBB"];
      var pal = { H: "#4a2f1c", K: "#2d2d33", k: "#77777f", S: "#c8916a", W: "#f2f2f2", E: "#3a6fd8",
                  N: "#a8714f", B: "#6b4426", M: "#8a4a3a" };
      var body = noisy(5, "g", "G", 0.35, 6).map(function (r) { return r + r.slice(0, 6); });
      return pixels(body, { g: "#55705a", G: "#3f5644" }, 15, 64, 5) +
        line("M24 64 L56 100", "#6b4426", 4) +
        pixels(["SS", "SS"], { S: "#b98260" }, 45, 56, 5) +
        pixels(head, pal, 30, 16, 5);
    },
    grass: function () {
      var top = { rows: noisy(2, "g", "G", 0.3), pal: { g: "#6cbf3a", G: "#4f9a2a" } };
      var sideRows = ["GgGgGGgG", "gGGgGgGG", "dDGddgDd"].concat(noisy(4, "d", "D", 0.3, 5));
      var side = { rows: sideRows, pal: { g: "#6cbf3a", G: "#4f9a2a", d: "#8a5a32", D: "#6b4423" } };
      return cube(top, side, { rows: sideRows, pal: darken(side.pal, -22) }, 50, 56, 4);
    },
    ore: function () {
      var rows = noisy(9, "s", "S", 0.3).map(function (r, i) {
        return [1, 4, 6].indexOf(i) >= 0 ? r.slice(0, 2) + "cC" + r.slice(4, 6) + "C" + r.slice(7) : r;
      });
      var pal = { s: "#8a8f96", S: "#6d7178", c: "#5ff0e0", C: "#2fb8c8" };
      return cube({ rows: rows, pal: darken(pal, 10) }, { rows: rows, pal: pal }, { rows: rows, pal: darken(pal, -22) }, 50, 56, 4);
    },
    pixsword: function () {
      return pixels(diagonalTool("sword"), { L: "#e6f8ff", O: "#2b4a5a", M: "#7fcde6", G: "#c49a2a", H: "#6b4426" }, 18, 18, 4);
    },
    pickaxe: function () {
      return pixels(diagonalTool("pick"), { H: "#8a5a32", D: "#5c3a1e", C: "#6ff0ff", B: "#2a9db0" }, 18, 18, 4);
    },
    sword: function (x) {
      return p("M70 16 L76 22 L40 64 L34 58Z", x.lin("blade", "#eef4fa", "#9aa7b4", true), 'stroke="#5c6670" stroke-width=".8"') +
        p("M30 54 L42 66 L39 69 L27 57Z", "#c49a2a") + p("M33 66 L24 75 L28 79 L37 70Z", "#6b4426") +
        p("M50 34 L82 40 Q84 66 62 84 Q42 70 46 42Z", x.lin("shield", "#3a5fb0", "#1f3570"), 'stroke="#d4af37" stroke-width="2.2"') +
        star(64, 58, 6, 2.4, "#d4af37");
    },
    potion: function (x) {
      return '<rect x="44" y="18" width="12" height="8" rx="2" fill="#8a5a32"/>' +
        p("M45 26 L55 26 L55 36 Q72 42 72 62 Q72 84 50 84 Q28 84 28 62 Q28 42 45 36Z", "rgba(230,240,255,.25)",
          'stroke="#dfe8f2" stroke-width="1.8"') +
        p("M30 60 Q50 54 70 60 Q70 82 50 82 Q30 82 30 60Z", "#b04aff", x.glow(2)) +
        circle(42, 68, 2, "#e6c4ff") + circle(54, 72, 1.4, "#e6c4ff") + circle(48, 62, 1, "#e6c4ff") +
        line("M36 46 Q34 52 35 58", "#fff", 1.6, 'opacity=".6"');
    },
    crystal: function (x) {
      return "<g " + x.glow(2.2) + ">" +
        p("M50 12 L70 34 L62 86 L38 86 L30 34Z", "#4fd0f0") +
        p("M50 12 L56 34 L50 86 L38 86 L30 34Z", "#8fe6ff") + p("M50 12 L56 34 L44 34Z", "#d8f7ff") +
        p("M30 34 L44 34 L38 86Z", "#2ea6cc") + "</g>";
    },
    dragon: function (x) {
      return "<g " + x.glow(2) + ">" +
        p("M18 70 Q10 40 26 22 Q24 40 34 46 Q30 24 42 10 Q44 30 50 34 Q56 30 58 10 Q70 24 66 46 Q76 40 74 22 Q90 40 82 70Z",
          x.lin("fl", "#ffd25a", "#ff4a1a"), 'opacity=".9"') + "</g>" +
        p("M30 28 Q22 12 18 4 Q30 12 38 26Z", "#5a2a10") + p("M70 28 Q78 12 82 4 Q70 12 62 26Z", "#5a2a10") +
        p("M50 22 Q67 24 69 42 Q69 56 59 64 L56 76 L44 76 L41 64 Q31 56 31 42 Q33 24 50 22Z",
          x.lin("drag", "#e2702a", "#8a2a10")) +
        p("M36 40 L46 44 L45 47 L37 45Z", "#ffe25a", x.glow(1.4)) + p("M64 40 L54 44 L55 47 L63 45Z", "#ffe25a", x.glow(1.4)) +
        line("M34 36 L46 40 M66 36 L54 40", "#5a2a10", 1.6) +
        circle(46, 66, 1.2, "#3a1406") + circle(54, 66, 1.2, "#3a1406") +
        line("M44 30 Q50 27 56 30 M42 52 Q50 56 58 52", "#a8441a", 1);
    },
    phoenix: function (x) {
      var wing = x.lin("wing", "#ffe06a", "#ff4a1a");
      return "<g " + x.glow(2.2) + ">" +
        p("M50 52 Q30 30 6 30 Q20 38 22 46 Q10 46 6 54 Q24 54 30 60 Q22 66 22 74 Q38 66 50 62Z", wing) +
        p("M50 52 Q70 30 94 30 Q80 38 78 46 Q90 46 94 54 Q76 54 70 60 Q78 66 78 74 Q62 66 50 62Z", wing) +
        p("M50 60 Q44 78 38 94 Q50 84 50 96 Q50 84 62 94 Q56 78 50 60Z", wing) +
        ellipse(50, 50, 6, 12, "#ff8a2a") + circle(50, 36, 5, "#ffb03a") +
        p("M50 36 L56 38 L50 40Z", "#5a2a10") + "</g>";
    }
  };

  // ------------------------------------------------------------ drawing

  var DEFAULT = { style: "hero", icon: "sun", skin: "s1", face: "oval", hair: "short",
                  hair_color: "black", beard: "none", eyes: "calm", mouth: "neutral",
                  marks: "none", glasses: "none", mask: "none", hat: "none",
                  outfit: "duelist", effect: "none", background: "falls" };
  var TABLES = { style: { hero: 1, icon: 1 }, icon: ICON, skin: SKIN, face: { oval: 1, square: 1, round: 1 },
                 hair: HAIR_STYLE, hair_color: HAIR, beard: BEARD, eyes: EYES, mouth: MOUTH,
                 marks: MARKS, glasses: GLASSES, mask: MASK, hat: HAT, outfit: OUTFIT,
                 effect: EFFECT, background: BACK };

  var made = 0;

  /* `view` crops to part of the picture: "face" and "head" for the
     editor's small buttons, "bust" for a leaderboard's rows. */
  var VIEWS = { face: "30 22 40 40", head: "18 0 64 64", bust: "16 10 68 68" };

  function svg(avatar, view) {
    var a = {};
    Object.keys(TABLES).forEach(function (kind) {
      var want = avatar && avatar[kind];
      a[kind] = Object.prototype.hasOwnProperty.call(TABLES[kind], want) ? want : DEFAULT[kind];
    });
    var x = new Ctx("pyide-av-" + (++made));
    var body = BACK[a.background](x) + (a.style === "icon" ? ICON[a.icon](x) : hero(x, a));
    return '<svg viewBox="' + (VIEWS[view] || "0 0 100 100") + '" xmlns="http://www.w3.org/2000/svg" ' +
      'role="img" aria-hidden="true"><defs>' + x.defs.join("") + "</defs>" + body + "</svg>";
  }

  function draw(root) {
    var els = (root || document).querySelectorAll("[data-avatar]");
    Array.prototype.forEach.call(els, function (el) {
      var a = {};
      try { a = JSON.parse(el.getAttribute("data-avatar") || "{}"); } catch (e) {}
      // data-avatar-view="bust" for small ones, where a whole portrait
      // makes the face a few pixels across.
      el.innerHTML = svg(a, el.getAttribute("data-avatar-view"));
    });
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { draw(); });
    } else {
      draw();
    }
  }

  var drawable = {};
  Object.keys(TABLES).forEach(function (kind) { drawable[kind] = Object.keys(TABLES[kind]); });

  return {
    svg: svg,
    draw: draw,
    // What this file can draw, by kind, for test_xp.py to hold against
    // xp.py's list.
    drawable: drawable
  };
})();
