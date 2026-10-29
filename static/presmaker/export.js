/* PresMaker — exports: a PDF, a presentation as one .html file, or the
 * markdown without its questions and/or tests.
 *
 * Every export is drawn by notes.js, the same as the preview: the notes are
 * cut with slides(), each slide rendered with render() into the hidden
 * workbench, and the HTML that comes out is put in a page of its own with
 * style.css and pages.js. A PDF is that page drawn by the app; the .html is
 * that page with everything inside it, so it opens anywhere, offline.
 *
 * What a display copy leaves out is taken out of the MARKDOWN (compose.js,
 * strip) before anything is drawn, not hidden afterwards: a hidden question
 * would still be in the file, and a slide that held only a question should
 * go, not stay as a blank page.
 */
window.PMExport = (function () {
  "use strict";

  var C = window.PMCompose, Notes = window.PyIDENotes;
  var SLIDE = { w: 960, h: 540 }, SHEET = { w: 612, h: 792 };
  /* A picture a teacher put in notes in an IDE is written /img/<slug>
     (pictures.js) — an address on PyIDE's server, which serves it to
     anyone (CLAUDE.md, "Students' own photos"). Here there is no server,
     so it is fetched from PyIDE's. */
  var IMG_SERVER = "https://pyide-mdfd.onrender.com";

  function dirOf(path) { return path ? path.replace(/[^/]*$/, "") : ""; }

  /* Pictures beside the deck: `![](pics/loop.png)` means next to the .md,
     as it would in any markdown viewer. The page itself lives inside the
     app, so a relative address would otherwise look there and find
     nothing — silently, as a broken-picture box. */
  function fixImages(root, path) {
    // Served by an IDE (bridge.js, PM_SERVER): its pictures are on this very
    // site, at the addresses the markdown already has.
    if (window.PMBridge && window.PMBridge.server) return;
    Array.prototype.forEach.call(root.querySelectorAll("img[src]"), function (img) {
      var src = img.getAttribute("src");
      if (/^\/img\//.test(src)) img.setAttribute("src", IMG_SERVER + src);
      else if (/^[a-z][a-z0-9+.-]*:/i.test(src)) return;
      else if (src.charAt(0) === "/") img.setAttribute("src", "file://" + src);
      else if (path) img.setAttribute("src", "file://" + encodeURI(dirOf(path)) + src);
    });
  }

  /* A question card made for the teacher's screen (notes.js draws a
     question that still has its key as a preview, with Show answer) turned
     into one for paper: no buttons, no notes to the teacher, and the answer
     printed or not. Show answer is pressed rather than copied, so the key
     shown is exactly the one notes.js would show. */
  function forPaper(root, answers) {
    Array.prototype.forEach.call(root.querySelectorAll(".quiz"), function (q) {
      var show = q.querySelector(".quiz-show");
      if (answers && show) show.click();
      q.classList.remove("quiz-preview");
      var bar = q.querySelector(".quiz-long-bar");
      if (bar) bar.remove();
      var foot = q.querySelector(".quiz-foot");
      if (!foot) return;
      var key = answers && foot.querySelector(".quiz-key");
      if (key) {
        foot.textContent = "";
        foot.appendChild(key);
      } else {
        foot.remove();
      }
    });
    Array.prototype.forEach.call(root.querySelectorAll("input, select"), function (i) {
      i.disabled = true;
      i.removeAttribute("name");
    });
  }

  function absolute(file) { return new URL(file, location.href).href; }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* Pictures on the disk, put inside the .html: a file sent to someone
     else has no folder beside it. */
  function inlineImages(root) {
    var imgs = Array.prototype.slice.call(root.querySelectorAll("img[src^='file://']"));
    return Promise.all(imgs.map(function (img) {
      var path = decodeURI(img.getAttribute("src").slice(7));
      var ext = (path.match(/\.([a-z0-9]+)$/i) || [, "png"])[1].toLowerCase();
      var type = { jpg: "jpeg", svg: "svg+xml" }[ext] || ext;
      return window.PMBridge.call("resource", { path: path, base64: true }).then(function (b64) {
        img.setAttribute("src", "data:image/" + type + ";base64," + b64);
      }).catch(function () { /* left pointing at the disk; shows on this Mac only */ });
    }));
  }

  /* opts: {questions, tests, answers: bool; mode: "pdf" | "viewer";
            inline: bool (everything inside the file); path; title} */
  function build(md, opts) {
    var text = C.strip(md, { questions: !opts.questions, tests: !opts.tests });
    var picked = Notes.takeTheme(text), theme = picked.name;
    var cut = Notes.slides(text), slides = cut.length >= 2;
    // Played a part at a time in the .html; a PDF is paper, shown whole.
    var header = Notes.takeHeader(text);
    var played = slides && opts.mode === "viewer" && header.animate;
    var size = slides ? SLIDE : SHEET;
    var bench = document.getElementById("workbench");
    bench.textContent = "";
    var plain = theme ? "" : " pm-plain";

    var boxes = (slides ? cut : [picked.body]).map(function () {
      var div = document.createElement("div");
      div.className = "notes-body prose " + (slides ? "pm-slide" : "pm-flow") + plain;
      bench.appendChild(div);
      return div;
    });
    return Promise.all(boxes.map(function (div, i) {
      return played ? renderParts(div, cut[i], theme) : Notes.render(div, slides ? cut[i] : picked.body, { theme: theme });
    })).then(function () {
      boxes.forEach(function (div) {
        fixImages(div, opts.path);
        forPaper(div, opts.answers && opts.questions);
      });
      return opts.inline ? inlineImages(bench) : null;
    }).then(function () {
      return head(opts, theme);
    }).then(function (headHTML) {
      var paged = !slides && opts.mode === "pdf";
      var body = boxes.map(function (div) {
        return slides ? '<section class="pm-page">' + div.outerHTML + "</section>" : div.outerHTML;
      }).join("\n");
      var chrome = slides && opts.mode === "viewer"
        ? '<div class="pm-chrome"><button class="pm-prev" title="Previous (←)">◀</button>' +
          '<span class="pm-count"></span><button class="pm-next" title="Next (→)">▶</button></div>'
        : "";
      bench.textContent = "";
      var html = "<!doctype html>\n<html lang=\"en\" class=\"pm-export-root\" data-theme=\"light\">\n<head>\n" +
        "<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
        "<title>" + esc(opts.title || "Presentation") + "</title>\n" + headHTML.styles + "</head>\n" +
        "<body class=\"pm-export pm-kind-" + (slides ? "slides" : "doc") + (paged ? " pm-paged" : "") +
        "\" data-mode=\"" + opts.mode + "\" data-width=\"" + size.w + "\" data-height=\"" + size.h +
        (played ? "\" data-animate=\"" + header.animate + "\" data-speed=\"" + header.speed : "") +
        "\" style=\"--pm-w: " + size.w + "px; --pm-h: " + size.h + "px\">\n" +
        "<div class=\"pm-pages\">\n" + body + "\n</div>\n" + chrome + "\n" + headHTML.script + "\n</body>\n</html>\n";
      return { html: html, width: size.w, height: size.h, slides: slides, count: slides ? cut.length : 0 };
    });
  }

  /* A slide drawn as its parts (`...` divides them), each in a .pm-part
     wrapper, for the player in pages.js. The slide itself carries the theme. */
  function renderParts(slide, md, theme) {
    return Notes.render(slide, "", { theme: theme }).then(function () {
      slide.textContent = "";
      return Promise.all(Notes.sections(md).map(function (sec) {
        var part = document.createElement("div");
        part.className = "pm-part";
        slide.appendChild(part);
        return Notes.render(part, sec, { theme: "" });
      }));
    });
  }

  function head(opts, theme) {
    var files = ["pyide/style.css", "pages.css"];
    var made = window.PMThemes.exportHead(theme);
    var fonts = made.fonts ? '<link rel="stylesheet" href="' + esc(made.fonts) + '">\n' : "";
    var extra = made.css ? "<style>\n" + made.css + "</style>\n" : "";
    if (!opts.inline) {
      return Promise.resolve({
        styles: files.map(function (f) { return '<link rel="stylesheet" href="' + esc(absolute(f)) + '">\n'; }).join("") +
                fonts + extra,
        script: '<script src="' + esc(absolute("pages.js")) + '"></script>'
      });
    }
    return Promise.all(files.concat(["pages.js"]).map(function (f) {
      return window.PMBridge.call("resource", { path: f });
    })).then(function (got) {
      return {
        styles: got.slice(0, files.length).map(function (css) { return "<style>\n" + css + "\n</style>\n"; }).join("") +
                fonts + extra,
        // A "</script>" inside the script would end it early.
        script: "<script>\n" + got[files.length].replace(/<\/script/gi, "<\\/script") + "\n</script>"
      };
    });
  }

  return { build: build, fixImages: fixImages, forPaper: forPaper, inlineImages: inlineImages, renderParts: renderParts, SLIDE: SLIDE, SHEET: SHEET };
})();
