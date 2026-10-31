/* FlaskIDE — the preview pane, which is a browser made out of one iframe.
 *
 * The runtime can answer a request. This turns that into something that
 * behaves like a website: a page appears, links go places, forms submit,
 * the back button works, and the address bar says where you are.
 *
 * HOW A LINK BECOMES A REQUEST
 *
 * The response HTML is written into a sandboxed iframe. Inside it, a click
 * on `<a href="/about">` would normally try to fetch /about from a server
 * that does not exist. So every click is caught, the href is read, the
 * default is prevented, and the path is handed to the runtime instead. What
 * comes back is written into the same iframe. Forms work the same way, with
 * the fields collected into an object first.
 *
 * WHY THE PAGE IS WRITTEN IN RATHER THAN NAVIGATED TO
 *
 * There is nowhere to navigate to. Every URL the student writes is
 * imaginary: it exists only as a rule in their app's url_map. srcdoc means
 * the iframe never issues a request to anywhere, which also means a typo in
 * an href cannot quietly reach the real internet.
 *
 * THE SANDBOX, AND WHY IT IS WHAT IT IS
 *
 * `sandbox="allow-scripts allow-forms"`, and deliberately NOT
 * `allow-same-origin`. Leaving that last one out is what gives the student's
 * page a null origin: their JavaScript runs normally, and cannot read this
 * page's DOM, cookies or storage.
 *
 * `allow-forms` is the part that is easy to leave out and impossible to
 * debug. Without it the browser blocks a submission BEFORE any listener
 * runs — the submit event does not fire at all, so the interception below
 * never gets its chance to preventDefault. The form simply does nothing. No
 * error, no console warning, no clue. Measured directly: a probe iframe with
 * `allow-scripts` recorded zero submit events and the same probe with
 * `allow-scripts allow-forms` recorded one.
 *
 * Half of a Flask unit is `<form method="post">`, so this would otherwise be
 * a dead feature found by a fourteen-year-old rather than by a test.
 *
 * `allow-forms` costs nothing in isolation: it permits submission, and every
 * submission is caught here and answered from Pyodide. Nothing reaches the
 * network. `allow-same-origin` is the one that would matter, and it stays
 * off.
 *
 * The cost is that the iframe cannot be reached into from here. So the
 * interception is not done from outside — a small script is injected INTO
 * the page, and it talks back by postMessage.
 */

(function () {
  "use strict";

  const runtime = window.FlaskIDERuntime;

  /* The script that rides along inside every page the student's app returns.
   * It is their page's only visitor from us, and it does three things: catch
   * clicks, catch submits, and report its height. */
  const SHIM = `<script>
(function () {
  function send(msg) { parent.postMessage(Object.assign({ __flaskide: 1 }, msg), "*"); }

  // Bubbling, not capturing, and only what the page's own script left
  // alone: a page that handles a click or a submit itself (a JavaScript
  // search box in a <form>, a link that opens a menu) calls preventDefault,
  // and catching it first navigated anyway, so such a page could not work.
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented) return;
    var a = e.target.closest && e.target.closest("a");
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href) return;
    // Anything with a scheme (or a //host) is the real internet. This frame
    // cannot go there — it has no allow-popups, and following it here would
    // replace the student's page — so it asks the editor to open a new tab.
    // a.href, not the raw attribute: "//example.com" resolved to a full URL.
    // No \/ in the regex: this is a template literal, which eats the
    // backslash and hands the page a regex that does not compile — taking
    // every link and form on it down with the whole shim.
    if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.slice(0, 2) === "//") {
      e.preventDefault();
      send({ kind: "external", href: a.href });
      return;
    }
    if (href.charAt(0) === "#") return;
    e.preventDefault();
    send({ kind: "navigate", path: href });
  });

  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var f = e.target;
    if (!f || f.tagName !== "FORM") return;
    e.preventDefault();
    var data = {};
    var items = new FormData(f);
    items.forEach(function (v, k) { data[k] = typeof v === "string" ? v : ""; });
    send({
      kind: "submit",
      path: f.getAttribute("action") || location.pathname || "/",
      method: (f.getAttribute("method") || "GET").toUpperCase(),
      form: data
    });
  });

  // fetch() to the app's own routes ("/api/games") is answered by the app,
  // through the editor, as a click is: there is no server for it to reach.
  // Anything with a scheme goes to the real internet as before.
  var pending = {}, seq = 0, realFetch = typeof window !== "undefined" && window ? window.fetch : null;
  if (realFetch) window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || String(input);
    if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.slice(0, 2) === "//") {
      return realFetch.apply(window, arguments);
    }
    init = init || {};
    var body = init.body, json = null, form = null;
    if (typeof body === "string") {
      try { json = JSON.parse(body); }
      catch (err) { form = {}; new URLSearchParams(body).forEach(function (v, k) { form[k] = v; }); }
    } else if (body && typeof body.forEach === "function") {
      form = {};
      body.forEach(function (v, k) { form[k] = typeof v === "string" ? v : ""; });
    }
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      pending[id] = { resolve: resolve, reject: reject };
      send({ kind: "fetch", id: id, method: String(init.method || "GET").toUpperCase(),
             path: url, json: json, form: form });
    });
  };
  if (realFetch) window.addEventListener("message", function (e) {
    var m = e.data;
    if (!m || !m.__flaskideReply) return;
    var p = pending[m.id];
    if (!p) return;
    delete pending[m.id];
    if (m.error) { p.reject(new TypeError(m.error)); return; }
    var body = m.status === 204 || m.status === 304 ? null : m.body;
    if (body !== null && !m.isText) body = Uint8Array.from(atob(body), function (c) { return c.charCodeAt(0); });
    p.resolve(new Response(body, { status: m.status || 200, headers: m.headers || {} }));
  });
})();
<\/script>`;

  /* A page's own files from static/ — its stylesheet, its script, its
   * pictures — put into the page itself before it is shown. The page sits
   * in a sandboxed iframe with no address, so a <link href="/static/…"> had
   * nowhere to load from and the student's CSS silently did nothing.
   * Each is asked of the app, as the browser would have asked a server. */
  const LOCAL = (url) => url && !/^[a-z][a-z0-9+.-]*:/i.test(url) && url.slice(0, 2) !== "//" &&
                         url.charAt(0) !== "#";
  function attr(tag, name) {
    const m = new RegExp("\\s" + name + "\\s*=\\s*(\"[^\"]*\"|'[^']*'|[^\\s>]+)", "i").exec(tag);
    return m ? m[1].replace(/^["']|["']$/g, "") : null;
  }
  async function fetchOwn(url) {
    try {
      const res = await runtime.request("GET", url, null);
      return res.status >= 200 && res.status < 300 ? res : null;
    } catch (err) { return null; }
  }
  async function inlineResources(html) {
    const jobs = [];
    html.replace(/<link\b[^>]*>/gi, (tag) => {
      if (/rel\s*=\s*["']?stylesheet/i.test(tag) && LOCAL(attr(tag, "href"))) jobs.push(tag);
      return tag;
    });
    html.replace(/<script\b[^>]*\bsrc\s*=[^>]*>\s*<\/script>/gi, (tag) => {
      if (LOCAL(attr(tag, "src"))) jobs.push(tag);
      return tag;
    });
    html.replace(/<img\b[^>]*>/gi, (tag) => {
      if (LOCAL(attr(tag, "src"))) jobs.push(tag);
      return tag;
    });
    const done = {};
    for (const tag of jobs) {
      if (done[tag] !== undefined) continue;
      if (/^<link/i.test(tag)) {
        const res = await fetchOwn(attr(tag, "href"));
        done[tag] = res && res.isText ? "<style>" + res.body + "</style>" : tag;
      } else if (/^<script/i.test(tag)) {
        const res = await fetchOwn(attr(tag, "src"));
        done[tag] = res && res.isText ? "<script>" + res.body.replace(/<\/script/gi, "<\\/script") + "</script>" : tag;
      } else {
        const res = await fetchOwn(attr(tag, "src"));
        const kind = res && (res.headers["Content-Type"] || res.headers["content-type"] || "image/png");
        const data = res && (res.isText ? "data:" + kind + "," + encodeURIComponent(res.body)
                                        : "data:" + kind + ";base64," + res.body);
        done[tag] = data ? tag.replace(/(\ssrc\s*=\s*)("[^"]*"|'[^']*'|[^\s>]+)/i, "$1\"" + data + "\"") : tag;
      }
    }
    return jobs.length ? html.replace(/<link\b[^>]*>|<script\b[^>]*\bsrc\s*=[^>]*>\s*<\/script>|<img\b[^>]*>/gi,
                                      (tag) => (done[tag] !== undefined ? done[tag] : tag)) : html;
  }

  /* TWO IFRAMES, NOT ONE
   *
   * Assigning `srcdoc` tears the iframe's document down and builds a new
   * one, and the browser paints white in between. On a page that changes on
   * every link and every form submit, that is a white flash several times a
   * minute — and on a slow first Pyodide response it is long enough that a
   * student thinks their app has broken.
   *
   * The usual fix, writing into the document with open/write/close, is not
   * available here: the frame is sandboxed WITHOUT allow-same-origin, so
   * this page cannot reach `contentDocument` at all. That is deliberate and
   * worth keeping — it is what gives the student's JavaScript a null origin.
   *
   * So the new page is built in a second, invisible iframe, and the two are
   * swapped once it has loaded. The old page stays on screen until the new
   * one is ready, so there is no gap to paint white.
   */
  function twinOf(frame) {
    const twin = frame.cloneNode(false);       // same sandbox, same styling
    twin.id = frame.id ? frame.id + "-b" : "";
    twin.classList.add("is-back");
    frame.parentNode.insertBefore(twin, frame.nextSibling);
    return twin;
  }

  class Preview {
    constructor(opts) {
      this.frames = [opts.frame, twinOf(opts.frame)];
      this.live = 0;
      this.bar = opts.bar || null;             // where the path is shown
      this.onStatus = opts.onStatus || (() => {});
      // A line for the console. onStatus(0, ...) only sets a hover title,
      // which nobody reads, so anything the student must see comes here.
      // `failed` is true when nothing happened, so a folded console can open.
      this.onNote = opts.onNote || ((text) => this.onStatus(0, text));
      this.path = "/";
      /* The HTML of the page on screen, as the app returned it — before the
         shim goes in. A live lesson sends this to the class, and reads it
         rather than the frame because the frame cannot be read: no
         allow-same-origin. "" for an image or a download, which are not
         pages anyone can be shown second-hand. */
      this.shown = "";
      this.history = [];
      this._seq = 0;

      window.addEventListener("message", (e) => this._fromPage(e));
      if (this.bar) {
        this.bar.addEventListener("keydown", (e) => {
          if (e.key === "Enter") this.go(this.bar.value.trim() || "/");
        });
      }
    }

    /** The iframe currently on screen. */
    get frame() { return this.frames[this.live]; }

    /** Ask the app for a path and show what it says. */
    async go(path, method, form, record) {
      if (record !== false && this.path && this.path !== path) {
        this.history.push(this.path);
      }
      let res;
      try {
        res = await runtime.request(method || "GET", path, form || null);
      } catch (err) {
        this.shown = "<pre>" + escapeHtml(String(err && err.message || err)) +
                     "</pre>";
        this._paint(this.shown, false);
        return;
      }

      // A redirect is followed here rather than shown, because that is what
      // a browser does and what every Flask tutorial's POST-then-redirect
      // expects to happen.
      let hops = 0;
      while (res.status >= 300 && res.status < 400 &&
             (res.headers.Location || res.headers.location) && hops < 10) {
        path = res.headers.Location || res.headers.location;
        res = await runtime.request("GET", path, null);
        hops += 1;
      }

      this.path = path;
      if (this.bar) this.bar.value = path;
      this.onStatus(res.status, path);

      if (!res.isText) {
        // An image or a download. Nothing to intercept inside it.
        const kind = res.headers["Content-Type"] || "application/octet-stream";
        this.shown = "";
        await this._show((f) => {
          f.removeAttribute("srcdoc");
          f.src = "data:" + kind + ";base64," + res.body;
        });
        return;
      }
      this.shown = res.body;
      const kind = res.headers["Content-Type"] || res.headers["content-type"] || "";
      if (/json/i.test(kind)) {
        // An API route's reply, shown as the browser shows JSON: as text.
        await this._paint("<pre style=\"white-space:pre-wrap;font:13px ui-monospace,monospace\">" +
                          escapeHtml(res.body) + "</pre>", false);
        return;
      }
      // What the class's live page is sent, too: with the CSS and pictures
      // in it, since their screens can't ask this app for /static either.
      this.shown = await inlineResources(res.body);
      await this._paint(this.shown, true);
    }

    back() {
      const to = this.history.pop();
      if (to) this.go(to, "GET", null, false);
    }

    _paint(html, injectShim) {
      return this._show((f) => {
        f.removeAttribute("src");
        f.srcdoc = injectShim ? withShim(html) : html;
      });
    }

    /* Fill the hidden frame, wait for it, then swap the two.
     *
     * THE TIMEOUT IS NOT BELT AND BRACES
     *
     * If `load` never arrives, a swap that only happens on load would leave
     * the previous page on screen for ever — the student presses a link,
     * nothing changes, and there is no error anywhere to say why. A frozen
     * preview is a far worse failure than the flash this replaces, so after
     * a second the swap happens regardless.
     *
     * `seq` drops a slow paint that a newer one has overtaken. Without it,
     * clicking two links quickly could finish in the wrong order and leave
     * the earlier page showing under the later path in the address bar.
     */
    _show(fill) {
      const back = this.frames[1 - this.live];
      const mine = ++this._seq;

      return new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          back.removeEventListener("load", finish);
          if (mine === this._seq) this._swap();
          resolve();
        };
        const timer = setTimeout(finish, 1000);
        back.addEventListener("load", finish);
        fill(back);
      });
    }

    _swap() {
      this.frames[this.live].classList.add("is-back");
      this.live = 1 - this.live;
      this.frames[this.live].classList.remove("is-back");
    }

    _fromPage(e) {
      const msg = e.data;
      if (!msg || !msg.__flaskide) return;
      // A fetch() is answered for either frame: a page's script fetches as
      // it loads, which is while it is still the hidden frame being filled.
      // It only asks the app; it can't steer the preview.
      if (msg.kind === "fetch" && this.frames.some((f) => f.contentWindow === e.source)) {
        const page = e.source;
        runtime.request(msg.method, msg.path, msg.form, msg.json).then((res) => {
          page.postMessage({ __flaskideReply: 1, id: msg.id, status: res.status, headers: res.headers,
                             body: res.body, isText: res.isText }, "*");
        }, (err) => {
          page.postMessage({ __flaskideReply: 1, id: msg.id, error: String(err && err.message || err) }, "*");
        });
        return;
      }
      // Only the page on screen may steer. The hidden frame still holds the
      // previous document, and a stray timer in a student's script must not
      // be able to navigate from a page nobody is looking at.
      if (e.source !== this.frame.contentWindow) return;

      if (msg.kind === "navigate") {
        this.go(msg.path);
      } else if (msg.kind === "submit") {
        this.go(msg.path, msg.method, msg.form);
      } else if (msg.kind === "external") {
        this._openExternal(String(msg.href));
      }
    }

    /* A link to another site, opened in a new tab on the page's behalf. It
     * used to only land in the status line, which reads as a broken link.
     * The click inside the frame is what keeps the browser from calling this
     * an unprompted pop-up. The URL comes from student content, so the scheme
     * is checked here rather than trusted: a javascript: or mailto: href goes
     * nowhere and says so. */
    _openExternal(url) {
      if (!/^https?:\/\//i.test(url)) {
        this.onNote("That link didn't point at a web address, so nothing opened: " + url, true);
        return;
      }
      let opened = null;
      try {
        opened = window.open(url, "_blank");
        // the opened page must not be able to reach back into the editor
        if (opened) { try { opened.opener = null; } catch (err) {} }
      } catch (err) { /* blocked; reported below */ }
      this.onNote(opened
        ? "Opened in a new tab: " + url
        : "Your browser blocked a new tab for " + url +
          "\nAllow pop-ups for this site, or copy the address above.", !opened);
    }
  }

  /* The shim goes in FIRST — just inside <head>, or <html>, or before
   * everything — so a page script that calls fetch() as it loads gets the
   * shim's fetch. At the end it came after the page's own scripts, whose
   * first fetch went to nowhere ("Failed to fetch"). Never before the
   * doctype, which would drop the page into quirks mode. */
  function withShim(html) {
    let m = /<head\b[^>]*>/i.exec(html) || /<html\b[^>]*>/i.exec(html);
    if (m) return html.slice(0, m.index + m[0].length) + SHIM + html.slice(m.index + m[0].length);
    m = /^\s*<!doctype[^>]*>/i.exec(html);
    if (m) return m[0] + SHIM + html.slice(m[0].length);
    return SHIM + html;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  // For tests (tools/test_preview.py): the two page rewrites, on their own.
  Preview.withShim = withShim;
  Preview.inlineResources = inlineResources;
  window.FlaskIDEPreview = Preview;
})();
