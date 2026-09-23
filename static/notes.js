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

  return {
    isMarkdown: isMarkdown,
    render: render,
    ensureRenderer: ensureRenderer
  };
})();
