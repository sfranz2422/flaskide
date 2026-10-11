/* PICTURES IN A TEACHER'S MARKDOWN — class descriptions (_describe.html),
 * a lesson's notes (lesson_teacher.js) and an assignment's notes in the
 * editor (app.js). The picture goes to /api/image, which only a teacher may
 * use, and its address comes back to go in as ![name](/img/...).
 *
 * The markdown keeps an address, never the picture itself: notes go out
 * whole on every live push and are copied into every snapshot, so a picture
 * pasted in as a data: URL would be sent to the class once a second.
 */
window.FlaskIDEPictures = (function () {
  "use strict";

  var ACCEPT = "image/png, image/jpeg, image/gif, image/webp";

  /* A big photo is shrunk here, before it is sent: a phone's 4000-pixel
     picture is several MB to show at the width of a card. 1600 across is
     plenty, and a JPEG of that is a few hundred KB. A GIF is left alone, or
     it would stop moving; the server refuses anything over 4 MB. */
  var SHRINK_OVER = 1500000, MAX_SIDE = 1600;

  function shrink(file) {
    if (file.type === "image/gif" || file.size <= SHRINK_OVER || !window.createImageBitmap) {
      return Promise.resolve(file);
    }
    return createImageBitmap(file).then(function (bmp) {
      var scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      var type = file.type === "image/png" ? "image/png" : "image/jpeg";
      return new Promise(function (resolve) {
        canvas.toBlob(function (blob) { resolve(blob || file); }, type, 0.85);
      });
    }).catch(function () { return file; });
  }

  /* Resolves to the picture's address; rejects with words to show. */
  function upload(file) {
    return shrink(file).then(function (blob) {
      var form = new FormData();
      form.append("image", blob, file.name || "picture");
      return fetch("/api/image", { method: "POST", body: form });
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; },
                           function () { return { ok: false, d: {} }; });
    }, function () {
      throw new Error("That picture didn't upload — check your connection.");
    }).then(function (out) {
      if (!out.ok) throw new Error(out.d.error || "That picture didn't upload.");
      return out.d.url;
    });
  }

  // ![holiday](/img/abc) for holiday.jpg; a pasted screenshot has no
  // useful name, and "image" says nothing a student needs.
  function markdown(file, url) {
    var alt = (file.name || "").replace(/\.[^.]+$/, "");
    if (/^image$/i.test(alt)) alt = "";
    return "![" + alt.replace(/[\[\]]/g, "") + "](" + url + ")";
  }

  function pictureFiles(list) {
    return Array.prototype.filter.call(list || [], function (f) {
      return /^image\/(png|jpeg|gif|webp)$/.test(f.type);
    });
  }

  /* Uploads each picture and writes its markdown into a CodeMirror 5 doc
     where the cursor was WHEN IT STARTED. A bookmark, because the teacher
     carries on typing during the upload, and inserting at the cursor as it
     is by then put the picture in the middle of whatever came next. On a
     line of its own, which is how marked shows it as a picture block. */
  function insertInto(doc, files, at) {
    files.forEach(function (file) {
      var mark = doc.setBookmark(at || doc.getCursor(), { insertLeft: false });
      upload(file).then(function (url) {
        var pos = mark.find();
        mark.clear();
        /* Gone: the doc was reloaded under it (FlaskIDE's editor swaps files
           with setValue, which clears every bookmark). The cursor is then in
           some other file — app.py, main.py — so the picture is handed over
           instead of being written into code where nobody asked for it. */
        if (!pos) {
          window.prompt("The notes were closed while the picture uploaded. " +
                        "Paste this where you want it:", markdown(file, url));
          return;
        }
        var line = doc.getLine(pos.line);
        var before = pos.ch > 0 ? "\n" : "";
        var after = pos.ch < line.length ? "\n" : "";
        doc.replaceRange(before + markdown(file, url) + after, pos);
      }, function (e) {
        mark.clear();
        alert(e.message);
      });
    });
  }

  /* Paste and drag-and-drop of pictures into a CodeMirror 5 editor, while
     wanted() says so — the editor's single CodeMirror holds code too, and a
     picture dropped on main.py must be left to the browser as before.
     Anything that isn't a picture (text, a .py file) is never touched. */
  function attach(cm, wanted) {
    cm.on("paste", function (cm, e) {
      if (wanted && !wanted()) return;
      var files = pictureFiles(e.clipboardData && e.clipboardData.files);
      if (!files.length) return;
      e.preventDefault();
      insertInto(cm.getDoc(), files);
    });
    cm.on("drop", function (cm, e) {
      if (wanted && !wanted()) return;
      var files = pictureFiles(e.dataTransfer && e.dataTransfer.files);
      if (!files.length) return;
      e.preventDefault();
      var at = cm.coordsChar({ left: e.clientX, top: e.clientY });
      insertInto(cm.getDoc(), files, at);
    });
  }

  /* A file picker for an Add picture button. */
  function choose(onFiles) {
    var input = document.createElement("input");
    input.type = "file";
    input.accept = ACCEPT;
    input.multiple = true;
    input.addEventListener("change", function () {
      var files = pictureFiles(input.files);
      if (files.length) onFiles(files);
    });
    input.click();
  }

  return { ACCEPT: ACCEPT, upload: upload, markdown: markdown,
           insertInto: insertInto, attach: attach, choose: choose };
})();
