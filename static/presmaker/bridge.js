/* PresMaker — the way out of the page: files, panels, the PDF, settings.
 *
 * In the app every call goes to Sources/main.swift and comes back as a
 * promise (WKScriptMessageHandlerWithReply). Opened in an ordinary browser
 * instead — handy for working on the page itself — the same calls do the
 * nearest thing a browser can: a file picker, a download, localStorage.
 * A PDF can't be made there; it says so rather than doing nothing.
 */
window.PMBridge = (function () {
  "use strict";

  var native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.native;
  /* Served by one of the IDEs as its tutorial library's editor (library.py,
     templates/presmaker.html, made by tools/sync_presmaker.py there): the
     page says which tutorial it is, and opening and saving go to the
     library rather than to files. { slug, title, kind, body, saveUrl,
     libraryUrl, brand }. */
  var server = window.PM_SERVER || null;
  var serverDirty = false;

  function call(cmd, args) {
    if (native) return native.postMessage({ cmd: cmd, args: args || {} });
    var done = server ? onServer(cmd, args || {}) : null;
    return done || browser(cmd, args || {});
  }

  function onServer(cmd, a) {
    var key = "pm-unsaved:" + server.slug;
    switch (cmd) {
      case "lastFile":
        return Promise.resolve({ path: "", name: server.title, text: server.body });
      case "save":
        return fetch(server.saveUrl, { method: "POST", credentials: "same-origin",
                                       headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ body: a.text }) })
          .then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
              if (!r.ok) throw new Error(d.error || "the library didn't take it (" + r.status + ")");
              server.body = a.text;
              return { path: "", name: server.title, updated: d.updated };
            });
          });
      case "open":
        // Another tutorial is picked in the library, not from a file.
        location.href = server.libraryUrl;
        return Promise.resolve(null);
      case "recovery.save": store(key, JSON.stringify(a)); return Promise.resolve(true);
      case "recovery.load":
        try { return Promise.resolve(JSON.parse(store(key) || "null")); }
        catch (e) { return Promise.resolve(null); }
      case "recovery.clear": store(key, null); return Promise.resolve(true);
      case "state":
        serverDirty = !!a.dirty;
        document.title = (a.dirty ? "• " : "") + server.title + " — " + (server.brand || "Tutorials");
        return Promise.resolve(true);
      case "pdf":
        return Promise.reject(new Error("PDFs aren't made here."));
    }
    return null;
  }
  window.addEventListener("beforeunload", function (e) {
    if (server && serverDirty) { e.preventDefault(); e.returnValue = ""; }
  });

  function download(text, name, type) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type || "text/plain" }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { /* private window */ }
    return null;
  }

  function browser(cmd, a) {
    switch (cmd) {
      case "open":
        return new Promise(function (resolve) {
          var input = document.createElement("input");
          input.type = "file";
          input.accept = ".md,.markdown,.txt,.html,.htm";
          input.onchange = function () {
            var f = input.files[0];
            if (!f) return resolve(null);
            f.text().then(function (t) { resolve({ path: "", name: f.name, text: t }); });
          };
          input.click();
        });
      case "save":
      case "export":
        download(a.text, a.suggested || "Untitled.md", a.ext === "html" ? "text/html" : "text/markdown");
        return Promise.resolve({ path: "", name: a.suggested });
      case "pdf":
        return Promise.reject(new Error("A PDF can only be made in the PresMaker app."));
      case "resource":
        return fetch(a.path).then(function (r) {
          if (!r.ok) throw new Error("can't read " + a.path);
          return a.base64 ? r.blob().then(function (b) {
            return new Promise(function (res) {
              var fr = new FileReader();
              fr.onload = function () { res(String(fr.result).split(",")[1]); };
              fr.readAsDataURL(b);
            });
          }) : r.text();
        });
      case "themes.load": return Promise.resolve(store("pm-themes") || "[]");
      case "themes.save": store("pm-themes", a.json); return Promise.resolve(true);
      case "recovery.save": store("pm-unsaved", JSON.stringify(a)); return Promise.resolve(true);
      case "recovery.load":
        try { return Promise.resolve(JSON.parse(store("pm-unsaved") || "null")); }
        catch (e) { return Promise.resolve(null); }
      case "recovery.clear": store("pm-unsaved", null); return Promise.resolve(true);
      case "copy":
        return navigator.clipboard ? navigator.clipboard.writeText(a.text).then(function () { return true; })
                                   : Promise.resolve(false);
      case "state": document.title = (a.dirty ? "• " : "") + a.name + " — PresMaker"; return Promise.resolve(true);
      case "fullscreen":
        try {
          if (a.on && !document.fullscreenElement) document.documentElement.requestFullscreen();
          if (!a.on && document.fullscreenElement) document.exitFullscreen();
        } catch (e) { /* not allowed here */ }
        return Promise.resolve(true);
      default: return Promise.resolve(null);
    }
  }

  return { call: call, native: !!native, server: server };
})();
