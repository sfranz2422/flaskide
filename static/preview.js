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
 * WebIDE uses `allow-scripts` alone and that is right for WebIDE. It is
 * wrong here, and the way it is wrong is nasty. Without `allow-forms` the
 * browser blocks a form submission BEFORE any listener runs — the submit
 * event does not fire at all, so the interception below never gets its
 * chance to preventDefault. The form simply does nothing. No error, no
 * console warning, no clue. Measured directly: a probe iframe with
 * `allow-scripts` recorded zero submit events and the same probe with
 * `allow-scripts allow-forms` recorded one.
 *
 * Half of a Flask unit is `<form method="post">`, so this would have been a
 * dead feature discovered by a fourteen-year-old rather than by a test.
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
    // Anything with a scheme is the real internet, and is left alone —
    // except that this page has no origin, so it simply will not go. Saying
    // so is kinder than a silent nothing.
    if (/^[a-z][a-z0-9+.-]*:/i.test(href)) {
      e.preventDefault();
      send({ kind: "external", href: href });
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

  class Preview {
    constructor(opts) {
      this.frame = opts.frame;
      this.bar = opts.bar || null;             // where the path is shown
      this.onStatus = opts.onStatus || (() => {});
      this.path = "/";
      this.history = [];

      window.addEventListener("message", (e) => this._fromPage(e));
      if (this.bar) {
        this.bar.addEventListener("keydown", (e) => {
          if (e.key === "Enter") this.go(this.bar.value.trim() || "/");
        });
      }
    }

    /** Ask the app for a path and show what it says. */
    async go(path, method, form, record) {
      if (record !== false && this.path && this.path !== path) {
        this.history.push(this.path);
      }
      let res;
      try {
        res = await runtime.request(method || "GET", path, form || null);
      } catch (err) {
        this._paint("<pre>" + escapeHtml(String(err && err.message || err)) +
                    "</pre>", false);
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
        this.frame.removeAttribute("srcdoc");
        this.frame.src = "data:" + kind + ";base64," + res.body;
        return;
      }
      this._paint(res.body, true);
    }

    back() {
      const to = this.history.pop();
      if (to) this.go(to, "GET", null, false);
    }

    _paint(html, injectShim) {
      this.frame.removeAttribute("src");
      this.frame.srcdoc = injectShim ? html + SHIM : html;
    }

    _fromPage(e) {
      const msg = e.data;
      if (!msg || !msg.__flaskide) return;
      if (e.source !== this.frame.contentWindow) return;

      if (msg.kind === "navigate") {
        this.go(msg.path);
      } else if (msg.kind === "submit") {
        this.go(msg.path, msg.method, msg.form);
      } else if (msg.kind === "external") {
        this.onStatus(0, "external link: " + msg.href);
      }
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  window.FlaskIDEPreview = Preview;
})();
