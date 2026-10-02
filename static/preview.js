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

  document.addEventListener("click", function (e) {
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
  }, true);

  document.addEventListener("submit", function (e) {
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
  }, true);
})();
<\/script>`;

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
      await this._paint(res.body, true);
    }

    back() {
      const to = this.history.pop();
      if (to) this.go(to, "GET", null, false);
    }

    _paint(html, injectShim) {
      return this._show((f) => {
        f.removeAttribute("src");
        f.srcdoc = injectShim ? html + SHIM : html;
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

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  window.FlaskIDEPreview = Preview;
})();
