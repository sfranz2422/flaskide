/* FlaskIDE — completion for names the student has defined in their Python.
 *
 * The same idea as PyIDE's: only their own names — variables, loop targets,
 * unpacked tuples, with-as and except-as targets, functions and their
 * parameters, classes, imports. No builtins, no Flask API. The point is to
 * stop NameError typos, not to write the program. What goes in a call's
 * brackets is sighint.js's, which shows it without inserting anything.
 *
 * WHY THIS IS NOT PYTHON'S OWN `ast`, AS IT IS IN PYIDE
 *
 * PyIDE has Pyodide loaded before anyone types, so it asks Python. Here
 * Pyodide — and Flask on top of it — is loaded on the first Run, because it
 * is several seconds and megabytes a student who is still typing their first
 * route does not need yet. Completion that waited for it would be absent for
 * exactly the part of the lesson where typos are made. So the names are found
 * by a small scanner instead, and tools/test_complete.py holds it to the same
 * answers as `ast` on a set of real programs, so it cannot drift quietly.
 *
 * Nothing is executed to find them.
 */

window.FlaskIDEComplete = (function () {
  "use strict";

  var KEYWORDS = ("False None True and as assert async await break class " +
    "continue def del elif else except finally for from global if import in " +
    "is lambda nonlocal not or pass raise return try while with yield")
    .split(" ");
  var IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
  var COMPOUND = /^\s*(if|elif|else|while|for|with|try|except|finally|def|class|async)\b/;

  function isPy(name) { return /\.py$/i.test(name || ""); }

  /* Strings and comments blanked out, keeping every newline, so nothing
     inside "x = 1" or a # comment is mistaken for code — and so the line
     structure the rest of this depends on is unchanged. */
  function blank(src) {
    var out = "", i = 0, n = src.length;
    while (i < n) {
      var c = src.charAt(i);
      if (c === "#") {
        while (i < n && src.charAt(i) !== "\n") i++;
        continue;
      }
      if (c === "'" || c === '"') {
        var triple = src.substr(i, 3) === c + c + c;
        var close = triple ? c + c + c : c;
        i += close.length;
        out += '""';
        while (i < n) {
          if (src.charAt(i) === "\\") { i += 2; continue; }
          if (src.substr(i, close.length) === close) { i += close.length; break; }
          // an unclosed one-line string ends at the line, as Python's would
          if (!triple && src.charAt(i) === "\n") break;
          if (src.charAt(i) === "\n") out += "\n";
          i++;
        }
        continue;
      }
      out += c;
      i++;
    }
    return out;
  }

  /* The source cut into statements: newlines and semicolons at bracket depth
     zero, with backslash continuations joined. Each comes back with the
     positions of its top-level `=` signs (not ==, <=, >=, != or :=), which is
     what separates assignment targets from values. */
  function statements(src) {
    var list = [], cur = "", eqs = [], depth = 0;
    function flush() {
      if (cur.trim()) list.push({ text: cur, eqs: eqs });
      cur = ""; eqs = [];
    }
    for (var i = 0; i < src.length; i++) {
      var c = src.charAt(i);
      if (c === "\\" && src.charAt(i + 1) === "\n") { cur += " "; i++; continue; }
      if ("([{".indexOf(c) >= 0) depth++;
      else if (")]}".indexOf(c) >= 0) depth = Math.max(0, depth - 1);
      if (depth === 0 && (c === "\n" || c === ";")) { flush(); continue; }
      if (depth === 0 && c === "=") {
        var prev = src.charAt(i - 1), next = src.charAt(i + 1);
        if (next !== "=" && "=<>!:".indexOf(prev) < 0) eqs.push(cur.length);
        else if (next === "=") { cur += "=="; i++; continue; }
      }
      cur += c;
    }
    flush();
    return list;
  }

  /* Bare names in a target like `a, (b, *c)` or `x: int`. Anything reached
     through a dot or a subscript is an existing object being changed, not a
     new name — `self.x = 1` defines nothing — and is skipped. */
  function targetNames(text, into) {
    // `self.x`, `a[0]`, `grid[r][c].name` — whole chains out first, or the
    // split below would leave `a` looking like a bare name
    text = text.replace(/[A-Za-z_]\w*(\s*(\.\s*\w+|\[[^\]]*\]))+/g, " ");
    text.split(/[,()\[\]]/).forEach(function (part) {
      var t = part.trim().replace(/^\*+/, "");
      if (IDENT.test(t)) into.push(t);
    });
  }

  /* `a, b=1, *args, c: int = 2, **kw` → a b args c kw */
  function params(text, into) {
    var depth = 0, piece = "", parts = [];
    for (var i = 0; i < text.length; i++) {
      var c = text.charAt(i);
      if ("([{".indexOf(c) >= 0) depth++;
      else if (")]}".indexOf(c) >= 0) depth--;
      if (c === "," && depth === 0) { parts.push(piece); piece = ""; continue; }
      piece += c;
    }
    parts.push(piece);
    parts.forEach(function (p) {
      var name = p.split(/[:=]/)[0].trim().replace(/^\*+/, "");
      if (IDENT.test(name)) into.push(name);
    });
  }

  function matching(text, open) {
    var depth = 0;
    for (var i = open; i < text.length; i++) {
      var c = text.charAt(i);
      if (c === "(") depth++;
      else if (c === ")") { depth--; if (depth === 0) return i; }
    }
    return text.length;
  }

  function names(source) {
    var found = [];
    var src = blank(source || "");

    statements(src).forEach(function (st) {
      var text = st.text, m;

      // def / class, with a def's parameters
      var re = /\b(def|class)\s+([A-Za-z_]\w*)\s*(\()?/g;
      while ((m = re.exec(text))) {
        found.push(m[2]);
        if (m[1] === "def" && m[3]) {
          var open = m.index + m[0].length - 1;
          params(text.slice(open + 1, matching(text, open)), found);
        }
      }

      // for targets, including in comprehensions
      re = /\bfor\s+(.+?)\s+in\b/g;
      while ((m = re.exec(text))) targetNames(m[1], found);

      // with ... as x  /  except E as e
      re = /\bas\s+(\(?[A-Za-z_][\w\s,()]*?)\s*(?=[:,)]|$)/g;
      if (!/^\s*(from|import)\b/.test(text)) {
        while ((m = re.exec(text))) targetNames(m[1], found);
      }

      // walrus
      re = /([A-Za-z_]\w*)\s*:=/g;
      while ((m = re.exec(text))) found.push(m[1]);

      // imports
      if ((m = /^\s*import\s+(.+)$/.exec(text))) {
        m[1].split(",").forEach(function (part) {
          var bits = part.trim().split(/\s+as\s+/);
          var name = bits[1] ? bits[1].trim() : bits[0].trim().split(".")[0];
          if (IDENT.test(name)) found.push(name);
        });
      } else if ((m = /^\s*from\s+\S+\s+import\s+([\s\S]+)$/.exec(text))) {
        // [\s\S], not `.`: a bracketed import runs over several lines
        m[1].replace(/[()]/g, "").split(",").forEach(function (part) {
          var bits = part.trim().split(/\s+as\s+/);
          var name = (bits[1] || bits[0]).trim();
          if (IDENT.test(name)) found.push(name);
        });
      }

      // assignment: every piece before the last top-level `=` is a target
      if (st.eqs.length) {
        var from = 0;
        st.eqs.forEach(function (at) {
          var target = text.slice(from, at);
          from = at + 1;
          // augmented: `n += 1`
          target = target.replace(/(\*\*|\/\/|>>|<<|[-+*\/%@&|^])\s*$/, "");
          if (COMPOUND.test(target)) {
            // `if ready: x = 1` — the target is after the header's colon
            target = target.slice(target.lastIndexOf(":") + 1);
          } else if (target.indexOf(":") >= 0) {
            // `x: int = 5` — the target is before the annotation
            target = target.slice(0, target.indexOf(":"));
          }
          if (/\blambda\b/.test(target)) return;
          targetNames(target, found);
        });
      } else if ((m = /^\s*([A-Za-z_]\w*)\s*:[^=]+$/.exec(text)) &&
                 !COMPOUND.test(text)) {
        found.push(m[1]);                 // bare annotation: `count: int`
      }
    });

    var seen = {};
    return found.filter(function (n) {
      if (seen[n] || n.charAt(0) === "_" || KEYWORDS.indexOf(n) >= 0) return false;
      seen[n] = true;
      return true;
    }).sort();
  }

  function hint(cm, pool) {
    var cur = cm.getCursor();

    // never inside a string or a comment
    var type = cm.getTokenTypeAt(cur);
    if (type === "string" || type === "comment") return null;

    var line = cm.getLine(cur.line);
    var start = cur.ch;
    while (start > 0 && /[A-Za-z0-9_]/.test(line.charAt(start - 1))) start--;
    var word = line.slice(start, cur.ch);

    // two characters before suggesting, so it stays out of the way
    if (word.length < 2 || !/^[A-Za-z_]/.test(word)) return null;

    // don't suggest straight after a dot — that's an attribute, not a name
    if (start > 0 && line.charAt(start - 1) === ".") return null;

    var lower = word.toLowerCase();
    var list = pool.filter(function (n) {
      return n !== word && n.toLowerCase().indexOf(lower) === 0;
    });
    if (!list.length) return null;

    return {
      list: list,
      from: CodeMirror.Pos(cur.line, start),
      to: CodeMirror.Pos(cur.line, cur.ch)
    };
  }

  /* Enter is deliberately not a pick key: a student pressing Enter to start a
     new line must get a new line, not a surprise completion. Tab picks. */
  var KEYS = {
    Up: function (cm, h) { h.moveFocus(-1); },
    Down: function (cm, h) { h.moveFocus(1); },
    Tab: function (cm, h) { h.pick(); },
    Esc: function (cm, h) { h.close(); }
  };

  /* `sources` is every Python file whose names count — in the editor, the
     whole project, so a name from models.py is offered in app.py. */
  function show(cm, sources) {
    var pool = [];
    (sources || []).forEach(function (s) { pool = pool.concat(names(s)); });
    pool = pool.filter(function (n, i) { return pool.indexOf(n) === i; });
    if (!pool.length) return;
    cm.showHint({
      hint: function (editor) { return hint(editor, pool); },
      completeSingle: false,   // never insert without the student choosing
      customKeys: KEYS
    });
  }

  /* Shared by both editors: suggestions only while a word is being typed,
     and only in Python — `isPython` is asked at the moment, because the
     main editor's open file changes under it. */
  function attach(cm, isPython, sources) {
    var timer = null;
    cm.on("change", function (cm, change) {
      if (!isPython()) return;
      var typed = change.origin === "+input" && change.text.join("");
      if (!typed || !/^[A-Za-z0-9_]$/.test(typed)) return;
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (!cm.state.completionActive) show(cm, sources());
      }, 120);
    });
  }

  return { names: names, show: show, attach: attach, isPy: isPy };
})();
