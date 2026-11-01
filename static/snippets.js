/* Code in the notes that runs — the same file in PyIDE, WebIDE and FlaskIDE.
 *
 * A teacher writes, in an assignment's notes:
 *
 *     ```python run            a box of code with ▶ Run under it
 *     ```python predict        the student says what it will print, and
 *                              must get it RIGHT (buildPredict, below)
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
  /* What the page tells this file (configure): claim(code) is called when a
     prediction is right on its first try — on an assignment's page (the
     editor, the live page, a lesson) it's posted for XP; teacher puts a "Show the output" link on every predict
     box, so whoever writes or presents the notes is never held by one. */
  var page = { claim: null, teacher: false };
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

  function build(code, kind) {
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
        if (error) out.appendChild(el("span", "snippet-err", (text && !/\n$/.test(text) ? "\n" : "") + error));
        if (!text && !error) out.appendChild(el("span", "dim", "(It ran, and printed nothing.)"));
        if (text.length >= OUTPUT_MAX) out.appendChild(el("span", "dim", "\n… (more output than fits here)"));
        status.textContent = "";
      });
    });
    return box;
  }

  // ------------------------------------------------------- a prediction
  /* ```python predict: the student types what the code will print, and
     has to get it RIGHT to see it run. The teacher's call (Nov 2026):
     predicting first is the step's whole point, and a box that ran on any
     guess was passed by typing "x" — or by pressing Enter, which ran it
     with the first line of a two-line prediction. So:

       * the guess is a box of lines; Enter is a new line, and only the
         button (or Ctrl+Enter) checks it
       * the code can't be changed until the guess is right — before, a
         student could edit the example to print("x") and predict "x"
       * a wrong guess NEVER shows the output (it would be copied): each
         line of the guess is marked ✓ or ✗, and the next hint is shown
       * right: the output, ✓, the code opens up to try changes, and the
         box is data-predicted — what `locked: yes` waits for (notes.js)

     HINTS are Python comments in the block, `# hint: ...`, one a line:
     taken out of the code shown and run, and given one more after each
     wrong guess. A comment, so the block is still plain Python and needs
     nothing new in PresMaker.

     Capitals count (S and s are different answers in a strings lesson);
     extra spaces and blank lines don't. A guess right on the FIRST try
     calls page.claim, once — XP, paid by the server once per block. How
     many tries is kept in this browser, so a reload doesn't make a fourth
     guess a first one; a page could still lie, which takes at most the
     small XP once per block (app.py, predict_xp). */
  var HINT = /^\s*#\s*hint\s*:\s*(.*)$/i;
  function splitHints(text) {
    var code = [], hints = [];
    String(text).split("\n").forEach(function (ln) {
      var m = ln.match(HINT);
      if (m) { if (m[1].trim()) hints.push(m[1].trim()); } else code.push(ln);
    });
    return { code: code.join("\n").replace(/\s+$/, ""), hints: hints };
  }
  // Output as lines to compare: spaces squeezed, blank lines gone, capitals kept.
  function outLines(text) {
    return String(text).replace(/\r/g, "").split("\n")
      .map(function (l) { return l.replace(/\s+/g, " ").trim(); })
      .filter(function (l) { return l !== ""; });
  }
  function hashOf(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
    return h.toString(36);
  }
  // Kept here too, so a box drawn again asks nothing even where storage is refused.
  var states = {};
  function stateKey(code) { return "pyide-predict:" + location.pathname + ":" + hashOf(code); }
  function loadState(code) {
    if (states[code]) return states[code];
    var st = null;
    try { st = JSON.parse(localStorage.getItem(stateKey(code))); } catch (e) { /* none kept */ }
    return (states[code] = st && typeof st.tries === "number" ? st : { tries: 0, right: false });
  }
  function saveState(code, st) {
    states[code] = st;
    try { localStorage.setItem(stateKey(code), JSON.stringify(st)); } catch (e) { /* this visit only */ }
  }
  function tellLock(box) {
    var ev;
    try { ev = new CustomEvent("ide-checks", { bubbles: true }); }
    catch (e) { ev = document.createEvent("Event"); ev.initEvent("ide-checks", true, false); }
    box.dispatchEvent(ev);
  }

  // PresMaker (window.PM — the Mac app and the library's editor) is a
  // teacher's page without asking; its page is generated, not ours to edit.
  function teacher() { return page.teacher || !!window.PM; }

  function buildPredict(codeEl) {
    var parts = splitHints(codeEl.textContent.replace(/\n$/, ""));
    var original = parts.code, hints = parts.hints;
    var st = loadState(original);
    var box = el("div", "snippet snippet-python snippet-predict");
    box.setAttribute("data-predict", "");

    var area = el("textarea", "snippet-code");
    area.spellcheck = false;
    area.value = original;
    area.rows = Math.max(2, Math.min(24, original.split("\n").length));
    box.appendChild(area);

    var ask = el("label", "snippet-ask small", "🤔 What will it print? Type every line it prints.");
    box.appendChild(ask);
    var guess = el("textarea", "field snippet-guess");
    guess.spellcheck = false;
    guess.setAttribute("aria-label", "Your prediction");
    guess.placeholder = "One line for each line it prints";
    guess.value = predicted[original] || "";
    function fitGuess() { guess.rows = Math.max(2, Math.min(12, guess.value.split("\n").length + 1)); }
    fitGuess();
    box.appendChild(guess);

    var bar = el("div", "snippet-bar");
    var check = el("button", "btn btn-primary snippet-run", "✔ Check my prediction");
    check.type = "button";
    var run = el("button", "btn btn-primary snippet-run", "▶ Run");
    run.type = "button";
    var reset = el("button", "linkbtn snippet-reset", "Reset");
    reset.type = "button";
    var show = el("button", "linkbtn snippet-show", "Show the output");
    show.type = "button";
    show.title = "Teachers only: the output, without predicting";
    var status = el("span", "snippet-status small");
    [check, run, reset, show, status].forEach(function (b) { bar.appendChild(b); });
    box.appendChild(bar);

    var marks = el("div", "snippet-marks");
    marks.hidden = true;
    box.appendChild(marks);
    var hintList = el("ul", "snippet-hints");
    hintList.hidden = true;
    box.appendChild(hintList);
    var out = el("pre", "snippet-out");
    out.hidden = true;
    box.appendChild(out);

    function paintHints() {
      hintList.textContent = "";
      var n = Math.min(st.right ? 0 : st.tries, hints.length);
      for (var i = 0; i < n; i++) hintList.appendChild(el("li", "", "💡 " + hints[i]));
      hintList.hidden = n === 0;
    }
    // Locked until right: the code is read only, and there is only Check.
    function paint() {
      area.readOnly = !st.right;
      area.title = st.right ? "Change it and run it again" : "Predict it first; then you can change it";
      guess.readOnly = st.right;
      check.hidden = st.right;
      check.disabled = !guess.value.trim();
      run.hidden = reset.hidden = !st.right;
      show.hidden = !teacher() || st.right;
      if (st.right) box.setAttribute("data-predicted", "");
      else box.removeAttribute("data-predicted");
      paintHints();
    }

    function runIt(code, then) {
      var text = "", seen = [];
      status.className = "snippet-status small dim";
      status.textContent = worker ? "Running…" : "Loading Python… the first time takes a few seconds.";
      runPython(code, function (chunk, err) {
        if (text.length >= OUTPUT_MAX) return;
        text += chunk;
        seen.push([chunk, err]);
      }, function (error) {
        status.textContent = "";
        then(text, error, seen);
      });
    }
    function showOut(seen, error) {
      out.textContent = "";
      seen.forEach(function (s) { out.appendChild(el("span", s[1] ? "snippet-err" : "", s[0])); });
      if (error) out.appendChild(el("span", "snippet-err", "\n" + error));
      if (!seen.length && !error) out.appendChild(el("span", "dim", "(It ran, and printed nothing.)"));
      out.hidden = false;
    }
    function markLines(want, got) {
      marks.textContent = "";
      var n = Math.max(want.length, got.length);
      for (var i = 0; i < n; i++) {
        var ok = i < got.length && got[i] === want[i];
        var row = el("div", "snippet-mark " + (ok ? "is-right" : "is-wrong"));
        row.appendChild(el("span", "snippet-mark-sign", ok ? "✓" : "✗"));
        row.appendChild(el("code", "", i < got.length ? got[i] : "(a line is missing here)"));
        marks.appendChild(row);
      }
      if (got.length > want.length) marks.appendChild(el("div", "dim small", "It prints fewer lines than that."));
      marks.hidden = false;
    }

    guess.addEventListener("input", function () { predicted[original] = guess.value; fitGuess(); paint(); });
    guess.addEventListener("keydown", function (e) {
      // Enter is a new line: a prediction is often more than one.
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); check.click(); }
    });
    area.addEventListener("keydown", function (e) {
      if (st.right && (e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run.click(); }
    });

    check.addEventListener("click", function () {
      if (check.disabled || st.right) return;
      check.disabled = true;
      runIt(original, function (text, error, seen) {
        check.disabled = false;
        if (/^Python couldn't load|^Stopped:/.test(error || "")) {
          // Not their guess's fault: no try counted.
          status.className = "snippet-status small is-wrong";
          status.textContent = error;
          return;
        }
        if (error) {
          // An example that stops with an error has nothing fair to
          // predict; never hold a student on the teacher's mistake.
          st.right = true;
          saveState(original, st);
          showOut(seen, error);
          status.className = "snippet-status small dim";
          status.textContent = "This example stops with an error. Look at what it says.";
          paint();
          tellLock(box);
          return;
        }
        var want = outLines(text), got = outLines(guess.value);
        var right = want.length === got.length && want.every(function (l, i) { return l === got[i]; });
        var first = st.tries === 0;
        st.tries += 1;
        if (right) {
          st.right = true;
          saveState(original, st);
          marks.hidden = true;
          showOut(seen, "");
          status.className = "snippet-status small is-right";
          status.textContent = first ? "✓ Right on the first try!" : "✓ Right!";
          paint();
          tellLock(box);
          if (first && page.claim) { try { page.claim(original); } catch (e) { /* XP is a bonus */ } }
          return;
        }
        saveState(original, st);
        markLines(want, got);
        status.className = "snippet-status small is-wrong";
        status.textContent = "Not yet. Fix the lines marked ✗ and check again.";
        paint();
      });
    });

    run.addEventListener("click", function () {
      if (!st.right) return;
      run.disabled = true;
      runIt(area.value, function (text, error, seen) { run.disabled = false; showOut(seen, error); });
    });
    reset.addEventListener("click", function () { area.value = original; });
    show.addEventListener("click", function () {
      runIt(original, function (text, error, seen) { showOut(seen, error); });
    });

    if (st.right) {
      // Shown again after it was right: the output's back, nothing to redo.
      status.className = "snippet-status small is-right";
      status.textContent = "✓ You predicted this one.";
    }
    paint();
    return box;
  }

  var KINDS = [
    ["code.language-python-run, code.language-py-run", "python"],
    ["code.language-python-predict, code.language-py-predict", "predict"],
    ["code.language-html-run, code.language-html-predict", "html"]
  ];

  function renderBlocks(root) {
    KINDS.forEach(function (k) {
      Array.prototype.forEach.call(root.querySelectorAll(k[0]), function (code) {
        var pre = code.parentNode;
        if (!pre || pre.tagName !== "PRE") return;
        pre.parentNode.replaceChild(k[1] === "predict" ? buildPredict(code) : build(code, k[1]), pre);
      });
    });
  }

  /* JavaScript, for WebIDE's predict questions: run in a frame sandboxed as
     an html block is (scripts, no same origin), with console.log sent back
     line by line. What it logged, or the error, comes back the way run()'s
     does; a page that never finishes is given up on after TIME_LIMIT. */
  function runJs(code) {
    return new Promise(function (resolve) {
      var token = "js" + Math.random().toString(36).slice(2);
      var frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-scripts");
      frame.style.display = "none";
      var text = "", finished = false;
      function finish(error) {
        if (finished) return;
        finished = true;
        window.removeEventListener("message", heard);
        clearTimeout(timer);
        frame.remove();
        resolve({ text: text, error: error || "" });
      }
      function heard(e) {
        var d = e.data || {};
        if (e.source !== frame.contentWindow || d.token !== token) return;
        if (d.type === "log" && text.length < OUTPUT_MAX) text += d.text + "\n";
        else if (d.type === "error") finish(d.text);
        else if (d.type === "done") finish("");
      }
      var timer = setTimeout(function () {
        finish("Stopped: it was still running after " + TIME_LIMIT / 1000 + " seconds. Is there a loop that never ends?");
      }, TIME_LIMIT);
      window.addEventListener("message", heard);
      var t = JSON.stringify(token);
      frame.srcdoc = "<script>(function(){var T=" + t + ";function send(type,text){parent.postMessage({token:T,type:type,text:text},'*');}"
        + "console.log=function(){send('log',Array.prototype.map.call(arguments,function(a){return typeof a==='string'?a:JSON.stringify(a);}).join(' '));};"
        + "window.onerror=function(m,s,l){send('error','Line '+(l||'?')+': '+m);return true;};})();<\/script>"
        + "<script>" + String(code).replace(/<\/script/gi, "<\\/script") + "\n<\/script>"
        + "<script>parent.postMessage({token:" + t + ",type:'done'},'*');<\/script>";
      document.body.appendChild(frame);
    });
  }

  /* A question's code, run (notes.js: a `type: predict` question once it's
     answered, and the teacher's preview): what it printed and any error. */
  function run(code) {
    return new Promise(function (resolve) {
      var text = "";
      runPython(code, function (chunk) {
        if (text.length < OUTPUT_MAX) text += chunk;
      }, function (error) {
        resolve({ text: text, error: error || "" });
      });
    });
  }

  /* The page says who's reading (teacher: a Show the output link) and how
     a first-try prediction is paid (claim). */
  function configure(o) {
    o = o || {};
    if ("claim" in o) page.claim = o.claim;
    if ("teacher" in o) page.teacher = !!o.teacher;
    // An assignment's page: a first-try prediction is posted for its XP.
    if ("assignment" in o) {
      page.claim = o.assignment && o.signedIn && !o.viewOnly ? function (code) { claimXp(o.assignment, code); } : null;
    }
  }
  /* The server pays once per block per student, and only for a block
     that's really in the assignment's notes (app.py, predict_xp). */
  function claimXp(assignment, code) {
    fetch("/api/predict/xp", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignment: assignment, code: code })
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.xp > 0 && window.PyIDEXP) window.PyIDEXP.toast("+" + d.xp + " XP · predicted it on the first try");
      })
      .catch(function () {});
  }

  return { renderBlocks: renderBlocks, run: run, runJs: runJs, configure: configure,
           TIME_LIMIT: TIME_LIMIT, _same: same, _splitHints: splitHints, _outLines: outLines };
})();
