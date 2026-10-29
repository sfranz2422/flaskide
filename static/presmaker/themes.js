/* PresMaker — slide themes: the IDEs' own, and the ones made here.
 *
 * A theme in the IDEs is a name in notes.js's THEMES plus a block of CSS
 * variables in style.css (see the comment above THEMES there). A made theme
 * is the same two things: compose.js writes its CSS in the built-ins' shape,
 * this file puts the CSS in the page and the name into THEMES — the very
 * array notes.js checks, which it hands out as PyIDENotes.THEMES — so the
 * unchanged notes.js themes a deck with it like any other.
 *
 * Made themes live in ~/Library/Application Support/PresMaker/themes.json.
 * They exist only here until they are copied into the IDEs (themeForIDEs);
 * until then the IDEs show the line `theme: name` on the slide as text,
 * which is notes.js telling you about a typo — the status bar says so.
 */
window.PMThemes = (function () {
  "use strict";

  var C = window.PMCompose, Notes = window.PyIDENotes;
  var BUILTIN = Notes.THEMES.slice();         // before any made one is added
  // notes.js's themeFonts() address, for an exported page that has no notes.js.
  var BUILTIN_FONTS = "https://fonts.googleapis.com/css2?family=Caveat:wght@600;700" +
    "&family=Patrick+Hand&family=Press+Start+2P&family=Creepster" +
    "&family=Mountains+of+Christmas:wght@700&display=swap";
  var FONT_THEMES = ["chalkboard", "arcade", "notebook", "halloween", "christmas"];

  var made = [];
  var changed = [];

  function install() {
    document.getElementById("made-themes").textContent = made.map(C.themeCSS).join("\n");
    // In place: notes.js holds this same array.
    Notes.THEMES.length = 0;
    BUILTIN.concat(made.map(function (t) { return t.name; })).forEach(function (n) { Notes.THEMES.push(n); });
    var url = C.fontsURL(made.map(function (t) { return t.font; }));
    var link = document.getElementById("made-fonts");
    if (url) {
      if (!link) {
        link = document.createElement("link");
        link.id = "made-fonts";
        link.rel = "stylesheet";
        document.head.appendChild(link);
      }
      if (link.href !== url) link.href = url;
    }
    changed.forEach(function (fn) { fn(); });
  }

  function load() {
    return window.PMBridge.call("themes.load").then(function (json) {
      try { made = JSON.parse(json || "[]").filter(function (t) { return t && t.name && !C.themeNameProblem(t.name, BUILTIN); }); }
      catch (e) { made = []; }
      install();
    });
  }

  function save() {
    install();
    return window.PMBridge.call("themes.save", { json: JSON.stringify(made, null, 2) });
  }

  function get(name) {
    for (var i = 0; i < made.length; i++) if (made[i].name === name) return made[i];
    return null;
  }

  /* Puts `theme` in place of the one called `was` (or adds it). */
  function put(theme, was) {
    var at = -1;
    made.forEach(function (t, i) { if (t.name === (was || theme.name)) at = i; });
    if (at >= 0) made[at] = theme; else made.push(theme);
    made.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
    return save();
  }

  function remove(name) {
    made = made.filter(function (t) { return t.name !== name; });
    return save();
  }

  // ------------------------------------------- starting from a built-in
  var canvas = null;
  function toHex(value) {
    canvas = canvas || document.createElement("canvas").getContext("2d");
    canvas.fillStyle = "#000000";
    canvas.fillStyle = String(value || "").trim() || "#000000";
    var s = canvas.fillStyle;                // "#rrggbb", or rgba(...) if see-through
    if (s.charAt(0) === "#") return s;
    var m = s.match(/[\d.]+/g) || [0, 0, 0];
    return "#" + m.slice(0, 3).map(function (x) {
      var n = Math.round(Number(x)); return (n < 16 ? "0" : "") + n.toString(16);
    }).join("");
  }

  /* A built-in theme's values, as a made theme's form fields — read from
     the page as it draws the theme, not copied out of style.css by hand,
     so it stays right when a theme there changes. Its background is kept
     whole under Advanced: gradients and star fields don't fit two colour
     pickers. */
  function fromBuiltin(name) {
    var box = document.createElement("div");
    box.className = "notes-body prose slide-themed slide-theme-" + name;
    var h = document.createElement("h1");
    box.appendChild(h);
    document.getElementById("workbench").appendChild(box);
    var cs = getComputedStyle(box);
    function v(k) { return cs.getPropertyValue(k).trim(); }
    var family = getComputedStyle(h).fontFamily.split(",")[0].replace(/["']/g, "").trim();
    var font = C.FONTS.filter(function (f) { return f.id && f.id === family; })[0];
    var t = {
      name: "", scheme: v("color-scheme").indexOf("light") >= 0 ? "light" : "dark",
      bgType: "solid", bg1: toHex(v("--nav-bg")), bg2: toHex(v("--nav-bg")), bg3: "", angle: 160,
      pattern: "none", bgCSS: v("--theme-bg"),
      nav: toHex(v("--nav-bg")), text: toHex(v("--text")), muted: toHex(v("--muted")),
      heading: toHex(v("--heading")), heading2: toHex(v("--heading-2") || v("--heading")),
      accent: toHex(v("--accent")), strong: toHex(v("--strong") || v("--text")),
      font: font ? font.id : ""
    };
    box.remove();
    return t;
  }

  function blank(scheme) {
    return scheme === "light"
      ? { name: "", scheme: "light", bgType: "gradient", bg1: "#fdfbf6", bg2: "#efe7da", bg3: "", angle: 165,
          pattern: "none", bgCSS: "", nav: "#efe7da", text: "#23201c", muted: "#6b645a",
          heading: "#1d4ed8", heading2: "#b45309", accent: "#c2410c", strong: "#111111", font: "" }
      : { name: "", scheme: "dark", bgType: "gradient", bg1: "#14213d", bg2: "#1f3a5f", bg3: "", angle: 160,
          pattern: "none", bgCSS: "", nav: "#14213d", text: "#eef2ff", muted: "#a5b0cc",
          heading: "#fca311", heading2: "#8ecae6", accent: "#8ecae6", strong: "#ffffff", font: "" };
  }

  /* What an exported page needs in its <head> for this theme: the made
     theme's CSS (built-ins are in style.css already) and its font. */
  function exportHead(name) {
    var t = get(name), out = { css: "", fonts: "" };
    if (t) {
      out.css = C.themeCSS(t);
      out.fonts = C.fontsURL([t.font]);
    } else if (FONT_THEMES.indexOf(name) >= 0) {
      out.fonts = BUILTIN_FONTS;
    }
    return out;
  }

  return {
    load: load, get: get, put: put, remove: remove,
    made: function () { return made.slice(); },
    builtin: function () { return BUILTIN.slice(); },
    isBuiltin: function (n) { return BUILTIN.indexOf(n) >= 0; },
    all: function () { return Notes.THEMES.slice(); },
    fromBuiltin: fromBuiltin, blank: blank, exportHead: exportHead,
    onChange: function (fn) { changed.push(fn); }
  };
})();
