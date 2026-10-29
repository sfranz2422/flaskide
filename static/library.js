/* The tutorial library's page (library.html; library.py's /api/library).
 *
 * THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE.
 *
 * Lists every tutorial and teacher deck, with where each is used; makes,
 * uploads (many at once — a file with the same title as one here replaces
 * it, links and all), duplicates, downloads, deletes, and links them to
 * assignments. Editing is on each tutorial's own page.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var items = [], assignments = [];

  function api(url, opts) {
    opts = opts || {};
    var init = { method: opts.method || (opts.json ? "POST" : "GET"), credentials: "same-origin" };
    if (opts.json) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.json);
    }
    return fetch(url, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || "That didn't work (" + r.status + ").");
        return d;
      });
    });
  }

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }

  function when(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function say(text, bad) {
    var r = $("lib-report");
    r.hidden = !text;
    r.textContent = "";
    if (text) r.appendChild(el("span", { "class": bad ? "error-text" : "", text: text }));
  }

  /* ---------------------------------------------------------------- the list */

  function load() {
    return api("/api/library").then(function (d) {
      items = d.items;
      assignments = d.assignments;
      draw();
    }, function (e) { say(e.message, true); });
  }

  function shown() {
    var q = $("lib-search").value.trim().toLowerCase(), kind = $("lib-kind").value, by = $("lib-sort").value;
    var list = items.filter(function (i) {
      return (!kind || i.kind === kind) && (!q || i.title.toLowerCase().indexOf(q) >= 0);
    });
    list.sort(function (a, b) {
      if (by === "title") return a.title.localeCompare(b.title);
      if (by === "uses") return b.uses.length - a.uses.length || a.title.localeCompare(b.title);
      return a.updated < b.updated ? 1 : -1;
    });
    return list;
  }

  function usedIn(item) {
    if (!item.uses.length) return el("span", { "class": "muted", text: "Not used yet" });
    var names = item.uses.map(function (u) { return (u.class ? u.class + ": " : "") + u.title + (u.archived ? " (archived)" : ""); });
    var d = el("details", { "class": "library-uses" }, [
      el("summary", { text: item.uses.length + " assignment" + (item.uses.length === 1 ? "" : "s") }),
    ]);
    var ul = el("ul");
    item.uses.forEach(function (u, i) {
      ul.appendChild(el("li", {}, [el("a", { href: u.url, text: names[i] })]));
    });
    d.appendChild(ul);
    return d;
  }

  function draw() {
    var body = $("lib-rows");
    body.textContent = "";
    var list = shown();
    if (!list.length) {
      body.appendChild(el("tr", {}, [el("td", { colspan: "4", "class": "muted",
        text: items.length ? "Nothing matches." : "No tutorials yet. Make one, or upload the ones on your computer." })]));
      return;
    }
    list.forEach(function (item) {
      var tutorial = item.kind === "tutorial";
      var title = tutorial
        ? el("a", { href: window.LIBRARY_T.editUrl + item.slug + "/edit", text: item.title, "class": "library-title" })
        : el("span", { text: item.title, "class": "library-title" });
      body.appendChild(el("tr", { "data-slug": item.slug, "data-testid": "library-row" }, [
        el("td", {}, [el("span", { "class": "library-kind " + item.kind, text: tutorial ? "Tutorial" : "Deck" }), " ", title]),
        el("td", {}, [usedIn(item)]),
        el("td", { "class": "muted small", text: when(item.updated) }),
        el("td", { "class": "library-actions" }, [
          tutorial ? el("a", { "class": "btn small", href: window.LIBRARY_T.editUrl + item.slug + "/edit", text: "Edit" }) : null,
          el("button", { "class": "btn small", type: "button", text: "Link to…", "data-testid": "library-link",
                         onclick: function () { openLink(item); } }),
          el("button", { "class": "linkbtn", type: "button", text: "Duplicate", onclick: function () { duplicate(item); } }),
          el("a", { "class": "linkbtn", href: "/api/library/" + item.slug + "/download", text: "⤓ Download" }),
          el("button", { "class": "linkbtn danger", type: "button", text: "Delete", onclick: function () { remove(item); } }),
        ]),
      ]));
    });
  }

  ["lib-search", "lib-kind", "lib-sort"].forEach(function (id) { $(id).addEventListener("input", draw); });

  /* ---------------------------------------------------------------- making, copying, deleting */

  $("lib-new").addEventListener("click", function () {
    var title = prompt("What's it called?");
    if (!title || !title.trim()) return;
    api("/api/library", { json: { title: title.trim(), body: "# " + title.trim() + "\n\n" } })
      .then(function (d) { location.href = window.LIBRARY_T.editUrl + d.slug + "/edit"; }, function (e) { say(e.message, true); });
  });

  function duplicate(item) {
    api("/api/library/" + item.slug + "/duplicate", { json: {} }).then(load, function (e) { say(e.message, true); });
  }

  function remove(item) {
    var n = item.uses.length;
    var ask = "Delete “" + item.title + "” from the library?" +
      (n ? " The " + n + " assignment" + (n === 1 ? "" : "s") + " using it keep" + (n === 1 ? "s" : "") + " the notes as they are now, as their own." : "");
    if (!confirm(ask)) return;
    api("/api/library/" + item.slug, { method: "DELETE" }).then(load, function (e) { say(e.message, true); });
  }

  /* ---------------------------------------------------------------- linking */

  var linking = null;
  function openLink(item) {
    linking = item;
    $("lib-link-title").textContent = "Link “" + item.title + "” to…";
    var box = $("lib-link-list");
    box.textContent = "";
    var byClass = {};
    assignments.forEach(function (a) {
      if (a.archived) return;
      (byClass[a.class || ""] = byClass[a.class || ""] || []).push(a);
    });
    var names = Object.keys(byClass).sort(function (a, b) { return !a ? 1 : !b ? -1 : a.localeCompare(b); });
    if (!names.length) box.appendChild(el("p", { "class": "muted", text: "You have no assignments yet." }));
    names.forEach(function (name) {
      var group = el("fieldset", {}, [el("legend", { text: name || "Not in a class" })]);
      byClass[name].forEach(function (a) {
        var mine = (item.kind === "tutorial" ? a.tutorial : a.deck) === item.id;
        var other = item.kind === "tutorial" && a.tutorial && !mine;
        var box2 = el("input", { type: "checkbox", value: a.slug });
        box2.checked = mine;
        box2.dataset.was = mine ? "1" : "";
        group.appendChild(el("label", { "class": "library-link-item" }, [
          box2, " ", a.title + (a.kind === "lesson" ? " (lesson)" : ""),
          other ? el("span", { "class": "muted small", text: " — uses another tutorial now" }) : null,
        ]));
      });
      box.appendChild(group);
    });
    $("lib-link").showModal();
  }

  $("lib-link").addEventListener("close", function () {
    if ($("lib-link").returnValue !== "save" || !linking) return;
    var link = [], unlink = [];
    $("lib-link-list").querySelectorAll("input[type=checkbox]").forEach(function (b) {
      if (b.checked && !b.dataset.was) link.push(b.value);
      if (!b.checked && b.dataset.was) unlink.push(b.value);
    });
    if (!link.length && !unlink.length) return;
    api("/api/library/" + linking.slug + "/link", { json: { link: link, unlink: unlink } })
      .then(function () { say("Linked. Students see it from now on."); return load(); }, function (e) { say(e.message, true); });
  });

  /* ---------------------------------------------------------------- uploading */

  function asBase64(file) {
    return file.arrayBuffer().then(function (buf) {
      var bytes = new Uint8Array(buf), out = "";
      for (var i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(out);
    });
  }

  function upload(files) {
    files = Array.prototype.filter.call(files, function (f) { return /\.(md|markdown|txt|html?)$/i.test(f.name); });
    if (!files.length) return say("Choose .md tutorials or .html decks.", true);
    say("Uploading " + files.length + " file" + (files.length === 1 ? "" : "s") + "…");
    Promise.all(files.map(function (f) { return asBase64(f).then(function (data) { return { name: f.name, data: data }; }); }))
      .then(function (list) { return api("/api/library/upload", { json: { files: list } }); })
      .then(function (d) {
        var r = $("lib-report");
        r.hidden = false;
        r.textContent = "";
        var counts = {};
        d.report.forEach(function (x) { counts[x.result] = (counts[x.result] || 0) + 1; });
        r.appendChild(el("p", { text: ["added", "replaced", "unchanged", "skipped"].filter(function (k) { return counts[k]; })
          .map(function (k) { return counts[k] + " " + k; }).join(", ") + "." }));
        var ul = el("ul", { "class": "small" });
        d.report.forEach(function (x) {
          ul.appendChild(el("li", { text: x.name + ": " + x.result + (x.why ? " (" + x.why + ")" : "") +
            (x.result === "replaced" && x.updated ? " — " + x.updated + " assignment" + (x.updated === 1 ? "" : "s") + " updated" : "") }));
        });
        r.appendChild(ul);
        return load();
      }, function (e) { say(e.message, true); });
  }

  $("lib-upload").addEventListener("click", function () { $("lib-files").click(); });
  $("lib-files").addEventListener("change", function () { upload($("lib-files").files); $("lib-files").value = ""; });
  var drop = $("lib-drop"), depth = 0;
  document.addEventListener("dragenter", function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, "Files") >= 0) { depth++; drop.hidden = false; } });
  document.addEventListener("dragleave", function () { if (--depth <= 0) { depth = 0; drop.hidden = true; } });
  document.addEventListener("dragover", function (e) { e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    e.preventDefault();
    depth = 0;
    drop.hidden = true;
    if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files);
  });

  load();
})();
