/* FlaskIDE — running a student's PHP site: the page's side.
 *
 * window.PhpRuntime has the same shape as window.FlaskIDERuntime (flask.js)
 * — boot, run, request, check, setOutput, isReady — so the preview, the
 * checks and the live page ask either one the same way and need not know
 * which kind of project they are showing.
 *
 * PHP itself runs in a Web Worker (php_worker.js, with php_core.js doing
 * the work). This file posts it messages, and keeps the clock: a page that
 * never finishes — `while (true) {}`, a loop whose counter never moves —
 * cannot be interrupted from inside WebAssembly, so after LIMIT_MS the
 * worker is ended and a new one started. The student is told in a sentence,
 * and the next request runs their files again from the start (sessions and
 * database too: what was in the old worker's memory is gone with it).
 */
(function () {
  "use strict";

  const LIMIT_MS = 10000;
  const WORKER_URL = new URL("php_worker.js", document.currentScript.src).href;

  let worker = null;
  let booting = null;
  let ready = false;
  let seq = 0;
  const waiting = new Map();
  let onOutput = () => {};
  let lastFiles = null;     // what the current worker was given by run()
  let fresh = false;        // a new worker that hasn't been given them yet

  function start() {
    worker = new Worker(WORKER_URL, { type: "module" });
    worker.onmessage = (e) => {
      const m = e.data || {};
      const w = waiting.get(m.id);
      if (!w) return;
      waiting.delete(m.id);
      clearTimeout(w.timer);
      if (m.ok) w.resolve(m.result); else w.reject(new Error(m.error));
    };
    worker.onerror = (e) => {
      // A worker that cannot even start (the CDN unreachable): every
      // question still waiting gets the reason, rather than waiting forever.
      const why = new Error("PHP couldn't start: " + ((e && e.message) || "is the network blocked?"));
      waiting.forEach((w) => { clearTimeout(w.timer); w.reject(why); });
      waiting.clear();
    };
  }

  /* One question to the worker. `limit` is how long it may take before the
     worker is presumed stuck and ended; 0 for no limit (the first boot,
     which is downloading PHP and takes as long as the network does). */
  function ask(op, args, limit) {
    if (!worker) start();
    return new Promise((resolve, reject) => {
      const id = ++seq;
      const w = { resolve, reject, timer: 0 };
      if (limit) w.timer = setTimeout(() => {
        waiting.delete(id);
        restart();
        reject(Object.assign(new Error("timeout"), { timeout: true }));
      }, limit);
      waiting.set(id, w);
      worker.postMessage({ id, op, args });
    });
  }

  /* The stuck worker ended and a new one started. Anything else it was
     doing is answered with the same reason. */
  function restart() {
    if (worker) worker.terminate();
    worker = null;
    booting = null;
    ready = false;
    fresh = true;
    const why = Object.assign(new Error("timeout"), { timeout: true });
    waiting.forEach((w) => { clearTimeout(w.timer); w.reject(why); });
    waiting.clear();
  }

  async function boot(report) {
    if (ready) return;
    if (booting) return booting;
    booting = (async () => {
      report && report("Loading PHP…");
      await ask("boot", {}, 0);
      ready = true;
      report && report("");
    })();
    try { return await booting; }
    catch (e) { booting = null; throw e; }
  }

  /* Put the student's files in place. Resolves to { ok, pages, tables } or
     { ok: false, error }. */
  async function run(files, report) {
    await boot(report);
    onOutput("");
    lastFiles = files;
    fresh = false;
    try {
      return await ask("run", { files }, LIMIT_MS);
    } catch (e) {
      if (e.timeout) return { ok: false, error: tooLong("Setting up the site") };
      throw e;
    }
  }

  /* One request at a time, as flask.js does: a page's five fetch()es made
     together are answered one after another, as by a one-worker server. */
  let queue = Promise.resolve();
  function request(method, path, form, json) {
    const go = queue.then(() => requestNow(method, path, form, json));
    queue = go.catch(() => {});
    return go;
  }

  async function requestNow(method, path, form, json) {
    if (!lastFiles) throw new Error("nothing is running yet");
    if (fresh) {
      // The last worker was ended mid-page. This one starts the site over.
      await boot();
      await ask("run", { files: lastFiles }, LIMIT_MS);
      fresh = false;
      onOutput("(The site was started again from the beginning: anything saved while it ran is gone.)\n");
    }
    let res;
    try {
      res = await ask("request", { method: method || "GET", path: path || "/", form: form || null,
                                   json: json === undefined ? null : json }, LIMIT_MS);
    } catch (e) {
      if (!e.timeout) throw e;
      const msg = tooLong(path || "/");
      onOutput(msg + "\n");
      return { status: 500, headers: { "Content-Type": "text/html" }, isText: true,
               body: "<pre style=\"white-space:pre-wrap\">" + msg.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</pre>" };
    }
    if (res.errors) onOutput(res.errors + "\n");
    return res;
  }

  function tooLong(what) {
    return what + " ran for " + (LIMIT_MS / 1000) + " seconds without finishing, so it was stopped. " +
           "Look for a loop that never ends: a while whose condition never becomes false.";
  }

  /* The first .php file PHP can't read, for syntax.js's card, or null. A
     check that breaks says null: it must never be what stops a Run. */
  async function check(files, report) {
    try {
      await boot(report);
      return await ask("check", { files }, LIMIT_MS);
    } catch (e) {
      return null;
    }
  }

  /* Stop: whatever page is running is abandoned with its worker. */
  function stop() {
    if (worker && waiting.size) restart();
  }

  function setOutput(fn) { onOutput = fn || (() => {}); }
  function isReady() { return ready; }

  window.PhpRuntime = { boot, run, request, check, stop, setOutput, isReady, PROJECT: "/www", LIMIT_MS };
})();
