/* Code in the notes that runs — the same file in PyIDE, WebIDE and FlaskIDE.
 *
 * A teacher writes, in an assignment's notes:
 *
 *     ```python run            a box of code with ▶ Run under it
 *     ```python predict        the same, but Run waits until the student
 *                              has typed what they think it will print
 *     ```html run              a page (WebIDE): Run shows it in a frame
 *
 * notes.js joins the second word onto the language (language-python-run),
 * and calls renderBlocks on everything it draws, where this file is loaded.
 * Elsewhere — a class page's preview — the blocks stay code to read.
 *
 * THE CODE IS THE STUDENT'S TO CHANGE: try a different number, run it
 * again. Reset puts the teacher's version back. What's typed survives the
 * notes being drawn again (a live page redraws them when the teacher
 * types) because it's kept here by the block's original text.
 *
 * PYTHON RUNS IN A WORKER OF ITS OWN, with its own Pyodide, never the
 * page's: a snippet's variables can't leak into the student's program or
 * the other way round, and a `while True:` in a snippet is stopped after
 * TIME_LIMIT by ending the worker — the page never freezes. The first Run
 * loads Python (a few seconds); after that each run is a fresh namespace in
 * the same worker. input() can't be answered there, so it says so plainly.
 *
 * HTML RUNS IN A SANDBOXED FRAME, allow-scripts without allow-same-origin,
 * exactly as WebIDE's own preview does (runner.js says why): the snippet's
 * JavaScript runs, but it has a null origin and can't touch this page.
 */
window.IDESnippets = (function () {
  "use strict";

  var TIME_LIMIT = 10000;        // ms a Python snippet may run before it's stopped
  var OUTPUT_MAX = 20000;        // characters of output shown
  var here = document.currentScript && document.currentScript.src;
  var WORKER = here ? here.replace(/snippets\.js(\?.*)?$/, "snippet_worker.js") : "/static/snippet_worker.js";

  var edited = {};               // original code -> what the student has made of it
  var predicted = {};            // original code -> their prediction
  var worker = null, ready = null, nextId = 1, waiting = {};

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ------------------------------------------------------------ the worker
  function startWorker() {
    worker = new Worker(WORKER, { type: "module" });
    ready = new Promise(function (resolve, reject) {
      worker.onmessage = function (e) {
        var d = e.data || {};
        if (d.type === "ready") return resolve();
        if (d.type === "failed") return reject(new Error(d.message));
        var job = waiting[d.id];
        if (!job) return;
        if (d.type === "out") job.write(d.text, d.err);
        else if (d.type === "done") {
          clearTimeout(job.timer);
          delete waiting[d.id];
          job.done(d.error || "");
        }
      };
      worker.onerror = function () { reject(new Error("Python couldn't start.")); };
    });
    ready.catch(function () { worker = null; });
  }

  /* Ends the worker (a runaway loop, or a failed start): the next Run
     starts a new one, which loads Python again. */
  function stopWorker() {
    if (worker) worker.terminate();
    worker = null;
    Object.keys(waiting).forEach(function (id) {
      clearTimeout(waiting[id].timer);
      delete waiting[id];
    });
  }

  function runPython(code, write, done) {
    if (!worker) startWorker();
    var id = nextId++;
    ready.then(function () {
      waiting[id] = {
        write: write,
        done: done,
        timer: setTimeout(function () {
          stopWorker();
          done("Stopped: it was still running after " + TIME_LIMIT / 1000 + " seconds. Is there a loop that never ends?");
        }, TIME_LIMIT)
      };
      worker.postMessage({ id: id, code: code });
    }, function (e) {
      done("Python couldn't load here (" + e.message + "). Check the internet connection and try again.");
    });
  }

  // ------------------------------------------------------------- one block
  function same(a, b) {
    var norm = function (t) { return String(t).replace(/\s+/g, " ").trim().toLowerCase(); };
    return norm(a) === norm(b);
  }

  function build(code, kind, predict) {
    var original = code.textContent.replace(/\n$/, "");
    var box = el("div", "snippet snippet-" + kind);
    var area = el("textarea", "snippet-code");
    area.spellcheck = false;
    area.setAttribute("aria-label", "Code you can change and run");
    area.value = edited[original] !== undefined ? edited[original] : original;
    function fit() { area.rows = Math.max(2, Math.min(24, area.value.split("\n").length)); }
    fit();
    area.addEventListener("input", function () { edited[original] = area.value; fit(); });
    // Tab indents, as in the editor, instead of leaving the box.
    area.addEventListener("keydown", function (e) {
      if (e.key === "Tab" && !e.shiftKey) {
        e.preventDefault();
        var a = area.selectionStart, b = area.selectionEnd;
        area.value = area.value.slice(0, a) + "    " + area.value.slice(b);
        area.selectionStart = area.selectionEnd = a + 4;
        edited[original] = area.value;
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        run.click();
      }
    });
    box.appendChild(area);

    var guess = null;
    if (predict) {
      guess = el("input", "field snippet-guess");
      guess.type = "text";
      guess.placeholder = "What will it print? Type your prediction first.";
      guess.setAttribute("aria-label", "Your prediction");
      guess.value = predicted[original] || "";
      box.appendChild(guess);
    }

    var bar = el("div", "snippet-bar");
    var run = el("button", "btn btn-primary snippet-run", "▶ Run");
    run.type = "button";
    run.title = "Run this code (Ctrl+Enter)";
    var reset = el("button", "linkbtn snippet-reset", "Reset");
    reset.type = "button";
    reset.title = "Put the code back as the notes have it";
    var status = el("span", "snippet-status dim small");
    bar.appendChild(run);
    bar.appendChild(reset);
    bar.appendChild(status);
    box.appendChild(bar);

    var out = kind === "html" ? el("iframe", "snippet-frame") : el("pre", "snippet-out");
    out.hidden = true;
    if (kind === "html") {
      out.setAttribute("sandbox", "allow-scripts");
      out.setAttribute("title", "What this page looks like");
    }
    box.appendChild(out);

    function locked() {
      run.disabled = !!(guess && !guess.value.trim());
      run.title = run.disabled ? "Type your prediction first" : "Run this code (Ctrl+Enter)";
    }
    if (guess) {
      guess.addEventListener("input", function () { predicted[original] = guess.value; locked(); });
      guess.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !run.disabled) { e.preventDefault(); run.click(); }
      });
      locked();
    }

    reset.addEventListener("click", function () {
      area.value = original;
      delete edited[original];
      fit();
    });

    run.addEventListener("click", function () {
      if (run.disabled) return;
      if (kind === "html") {
        out.hidden = false;
        out.srcdoc = area.value;
        status.textContent = "";
        return;
      }
      var text = "";
      out.hidden = false;
      out.textContent = "";
      run.disabled = true;
      status.textContent = worker ? "Running…" : "Loading Python… the first time takes a few seconds.";
      runPython(area.value, function (chunk, err) {
        if (text.length >= OUTPUT_MAX) return;
        status.textContent = "Running…";
        text += chunk;
        var span = el("span", err ? "snippet-err" : "", chunk);
        out.appendChild(span);
      }, function (error) {
        run.disabled = false;
        if (guess) locked();
        if (error) out.appendChild(el("span", "snippet-err", (text && !/\n$/.test(text) ? "\n" : "") + error));
        if (!text && !error) out.appendChild(el("span", "dim", "(It ran, and printed nothing.)"));
        if (text.length >= OUTPUT_MAX) out.appendChild(el("span", "dim", "\n… (more output than fits here)"));
        status.textContent = "";
        if (guess && !error) {
          status.textContent = same(text, guess.value)
            ? "✓ Your prediction was right!"
            : "Not what you predicted. Can you see why?";
          status.className = "snippet-status small " + (same(text, guess.value) ? "is-right" : "is-wrong");
        }
      });
    });
    return box;
  }

  var KINDS = [
    ["code.language-python-run, code.language-py-run", "python", false],
    ["code.language-python-predict, code.language-py-predict", "python", true],
    ["code.language-html-run, code.language-html-predict", "html", false]
  ];

  function renderBlocks(root) {
    KINDS.forEach(function (k) {
      Array.prototype.forEach.call(root.querySelectorAll(k[0]), function (code) {
        var pre = code.parentNode;
        if (!pre || pre.tagName !== "PRE") return;
        pre.parentNode.replaceChild(build(code, k[1], k[2]), pre);
      });
    });
  }

  return { renderBlocks: renderBlocks, TIME_LIMIT: TIME_LIMIT, _same: same };
})();
