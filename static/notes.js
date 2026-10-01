/* FlaskIDE — rendered markdown notes.
 *
 * A .md file in a project is class notes: it renders in the right pane rather
 * than opening as text. The markdown source is only editable while authoring a
 * new project, so a student opening a shared link (or forking it) sees the
 * notes but cannot edit them or trip over a tab full of raw markdown.
 *
 * Everything a student could author gets sanitized before it reaches the page.
 * This is the only place in the app where stored content becomes HTML rather
 * than text, so it is the only place injection is possible.
 */

window.FlaskIDENotes = (function () {
  "use strict";

  var MARKED = "https://cdnjs.cloudflare.com/ajax/libs/marked/15.0.7/marked.min.js";
  var PURIFY = "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.2.4/purify.min.js";

  var loading = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("could not load " + src)); };
      document.head.appendChild(s);
    });
  }

  /* Fetched the first time notes are shown, not at page load — a project
     without notes never pays for them. */
  function ensureRenderer() {
    if (window.marked && window.DOMPurify) return Promise.resolve();
    if (!loading) {
      loading = Promise.all([loadScript(MARKED), loadScript(PURIFY)])
        .catch(function (e) { loading = null; throw e; });
    }
    return loading;
  }

  function isMarkdown(name) {
    return /\.(md|markdown)$/i.test(name);
  }

  /* Links open in a new tab so a student never loses their work by navigating
     away, and rel=noopener keeps the opened page from touching this one. */
  function hardenLinks(root) {
    var links = root.querySelectorAll("a[href]");
    Array.prototype.forEach.call(links, function (a) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
  }

  /* DOMPurify's html profile already drops <script>, event handlers such as
     onerror, javascript: hrefs, <iframe>, <object> and <meta>. Two things it
     permits that class notes have no use for, and that a student could misuse
     in a project they share on to a classmate:

       forms  — a convincing fake "school login" posting to another site
       style  — position:fixed can cover the whole editor

     Everything notes actually need (headings, lists, tables, code, links,
     images with width) is unaffected. Drop FORBID_ATTR to allow inline CSS. */
  var SANITIZE = {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["form", "input", "button", "textarea", "select", "option",
                  "label", "fieldset"],
    FORBID_ATTR: ["style"]
  };

  function render(target, source) {
    return ensureRenderer().then(function () {
      var dirty = window.marked.parse(source || "", { breaks: true });
      var clean = window.DOMPurify.sanitize(dirty, SANITIZE);
      target.innerHTML = clean;
      hardenLinks(target);
      return true;
    }).catch(function (e) {
      target.textContent =
        "The notes could not be displayed (" + e.message + ").";
      return false;
    });
  }

  /* Notes cut into slides for a live lesson: a `---` line on its own ends
     one slide and starts the next, and nothing else does. Headings are just
     headings — a slide can hold a `##` and a `###` under it, or have none.

     It cut at every `## ` heading once, and only trimmed the `---` rules
     off the edges. Notes written as a deck, with a `---` between slides,
     then ended slides in the wrong places: a slide whose own heading was a
     `###` was glued onto the slide before it, and a slide holding two `##`
     sections was cut in half. The `---` is what the author drew; it is the
     only thing that decides.

     Every `---` counts, including one straight under a line of text, which
     an ordinary markdown viewer would read as underlining that line into a
     heading. In notes written as slides it is a divider far more often than
     a heading, and a slide that runs past the line drawn under it is the
     bug this was rewritten for.

     Fenced code is skipped over, because `---` is also a line of output.
     Without that a slide whose example printed a divider would be cut in
     half in front of the class with no sign of why.

     Returns [] for notes with no `---` at all — one slide is not slides, and
     the caller then sends the notes whole, as it always did. */
  function slides(md) {
    var lines = String(md || "").replace(/\r\n?/g, "\n").split("\n");
    var out = [], cur = [], fence = null, cuts = 0;
    lines.forEach(function (ln) {
      var f = ln.match(/^ {0,3}(`{3,}|~{3,})/);
      if (f) {
        if (fence === null) fence = f[1];
        else if (f[1].charAt(0) === fence.charAt(0)
                 && f[1].length >= fence.length) fence = null;
      } else if (fence === null && /^ {0,3}-{3,}\s*$/.test(ln)) {
        out.push(cur);
        cur = [];
        cuts++;
        return;                               // the rule itself is not shown
      }
      cur.push(ln);
    });
    out.push(cur);
    if (!cuts) return [];

    return out.map(function (s) {
      while (s.length && !s[0].trim()) s.shift();
      while (s.length && !s[s.length - 1].trim()) s.pop();
      return s.join("\n");
    }).filter(function (s) { return s.trim(); });
  }

  return {
    isMarkdown: isMarkdown,
    slides: slides,
    render: render,
    ensureRenderer: ensureRenderer
  };
})();
