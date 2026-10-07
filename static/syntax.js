/* FlaskIDE — a syntax error, said so a beginner can fix it.
 *
 * When a student presses Run, the page first asks Python whether it can READ
 * the program at all (_flaskide_check in flask.js: compile, never run). If it
 * cannot, nothing runs, and this shows a card over the output pane —
 * where the result of Run would have gone, and where the student looks:
 *
 *     Line 4: you're missing a closing `)`. The `(` here is never closed.
 *     Python says: SyntaxError: '(' was never closed
 *
 * with that line highlighted in the editor and the cursor put on it. The
 * card covers the output pane rather than sitting under Python's message
 * there: one clear message, not the friendly one and the raw one stacked.
 * The raw one is still in the pane, underneath, once the card is closed.
 *
 * SYNTAX ONLY, AND BY CONSTRUCTION. The card can only appear for code that
 * Python cannot read. A program that reads but does the wrong thing runs
 * normally and fails, or not, in the output, exactly as before — this never
 * sees it. Every sentence below is about how a line is WRITTEN (a missing
 * bracket, a colon, a quote, the indentation), never about what the program
 * should do. Keep it that way: a hint about logic here would be answering
 * the exercise.
 *
 * No AI and no server: the words are a table keyed on Python's own message,
 * which since Python 3.10 already says precisely what is wrong. The table
 * makes it plainer. Python's own message is always shown under it, small,
 * so students learn to read the real thing.
 *
 * test_syntax.py runs every entry against the messages this very Pyodide
 * produces, so a Python upgrade that rewords one is caught, not shown as
 * the generic fallback in front of a class.
 */

window.FlaskIDESyntax = (function () {
  "use strict";

  var CLOSER = { "(": ")", "[": "]", "{": "}" };
  var OPENER = { ")": "(", "]": "[", "}": "{" };
  var KIND = { "(": "parenthesis", "[": "square bracket", "{": "curly brace",
               ")": "parenthesis", "]": "square bracket", "}": "curly brace" };

  /* Words a beginner misspells at the start of a line, where Python only
     says "invalid syntax". Matched only when the word is ONE edit away and
     is not already a real keyword — a hint, never a guess at their intent. */
  var KEYWORDS = ["while", "for", "if", "elif", "else", "def", "return",
                  "import", "from", "class", "print", "input", "try",
                  "except", "break", "continue", "pass", "and", "or", "not",
                  "in", "range", "True", "False", "None"];

  function oneEditAway(a, b) {
    if (a === b) return false;
    if (Math.abs(a.length - b.length) > 1) return false;
    // a swap of two neighbours (whlie -> while) counts as one edit here
    if (a.length === b.length) {
      var diff = [];
      for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) diff.push(i);
      if (diff.length === 1) return true;
      return diff.length === 2 && diff[1] === diff[0] + 1
        && a[diff[0]] === b[diff[1]] && a[diff[1]] === b[diff[0]];
    }
    var s = a.length < b.length ? a : b, l = a.length < b.length ? b : a;
    for (var j = 0, k = 0, skipped = false; j < s.length; j++, k++) {
      if (s[j] !== l[k]) {
        if (skipped) return false;
        skipped = true;
        j--;
      }
    }
    return true;
  }

  function misspelled(word) {
    if (!word || word.length < 2 || KEYWORDS.indexOf(word) !== -1) return "";
    for (var i = 0; i < KEYWORDS.length; i++) {
      if (KEYWORDS[i].length >= 3 && oneEditAway(word, KEYWORDS[i])) return KEYWORDS[i];
    }
    return "";
  }

  /* Each rule: Python's message → what to tell the student. `L` is the line
     number as words, `t` the line's text. Backticks mark code; the card
     shows them as code. Ordered: the first match wins. */
  var RULES = [
    [/^'([(\[{])' was never closed/, function (m, L) {
      return "You're missing a closing `" + CLOSER[m[1]] + "`. The `" + m[1]
        + "` on " + L + " is opened but never closed.";
    }],
    [/^unmatched '([)\]}])'/, function (m, L) {
      return "There's an extra `" + m[1] + "` on " + L + ". It has no `"
        + OPENER[m[1]] + "` before it to close.";
    }],
    [/^closing parenthesis '(.)' does not match opening parenthesis '(.)'(?: on line (\d+))?/,
     function (m, L) {
      return "The `" + m[1] + "` on " + L + " is closing a `" + m[2] + "`"
        + (m[3] ? " from line " + m[3] : "") + ". A `" + m[2] + "` is closed with `"
        + CLOSER[m[2]] + "`. Check the brackets are closed in the right order.";
    }],
    [/^expected ':'/, function (m, L, t) {
      if (/^\s*else\s+if\b/.test(t)) {
        return "On " + L + ", Python writes `else if` as one word: `elif`.";
      }
      return L.charAt(0).toUpperCase() + L.slice(1) + " needs a colon `:` at the end. "
        + "Lines that start with `if`, `elif`, `else`, `for`, `while`, `def` or `class` end with `:`.";
    }],
    [/^unterminated triple-quoted string/, function (m, L) {
      return "A string that starts with three quotes (`\"\"\"` or `'''`) on " + L
        + " is never closed. Add the three closing quotes.";
    }],
    [/^unterminated string literal/, function (m, L, t, info) {
      var q = (t || "").charAt(Math.max(0, (info.col || 1) - 1));
      q = q === "'" || q === '"' ? q : "";
      return "A string on " + L + " starts with a quote" + (q ? " `" + q + "`" : "")
        + " but never ends. Add the matching closing quote" + (q ? " `" + q + "`" : "")
        + " on the same line.";
    }],
    [/^invalid syntax\. Perhaps you forgot a comma\?/, function (m, L) {
      return "On " + L + " it looks like a comma `,` is missing between two items.";
    }],
    [/^invalid syntax\. Maybe you meant '==' or ':=' instead of '='\?/, function (m, L) {
      return "On " + L + ", use `==` to compare two things. A single `=` stores a value in a variable.";
    }],
    [/^cannot assign to (.*?) here\. Maybe you meant '==' instead of '='\?/, function (m, L) {
      return "The left side of `=` on " + L + " must be a variable name. "
        + "To compare two things use `==`.";
    }],
    [/^cannot assign to (True|False|None)/, function (m, L) {
      return "`" + m[1] + "` on " + L + " is a word Python keeps for itself, so it can't be "
        + "used as a variable name.";
    }],
    [/^cannot assign to /, function (m, L) {
      return "The left side of `=` on " + L + " must be a variable name.";
    }],
    [/^expected an indented block after '(\w+)' statement on line (\d+)/, function (m, L) {
      var a = /^(if|elif|else|except)$/.test(m[1]) ? "an" : "a";
      return "The line after the `" + m[1] + "` on line " + m[2] + " needs to be indented. "
        + "Lines inside " + a + " `" + m[1] + "` go in by 4 spaces.";
    }],
    [/^expected an indented block after (?:function definition|class definition)/, function (m, L) {
      return "The line after the definition needs to be indented. The lines inside a "
        + "`def` or `class` go in by 4 spaces.";
    }],
    [/^expected an indented block/, function (m, L) {
      return L.charAt(0).toUpperCase() + L.slice(1) + " should be indented by 4 spaces.";
    }],
    [/^unexpected indent/, function (m, L) {
      return L.charAt(0).toUpperCase() + L.slice(1) + " is indented, but nothing above it "
        + "asks for that. Line it up with the line before it.";
    }],
    [/^unindent does not match any outer indentation level/, function (m, L) {
      return "The indentation on " + L + " doesn't line up with any line above it. "
        + "Make it line up exactly with the lines in the same block.";
    }],
    [/^inconsistent use of tabs and spaces/, function (m, L) {
      return L.charAt(0).toUpperCase() + L.slice(1) + " mixes tabs and spaces. "
        + "Use spaces only to indent.";
    }],
    [/^Missing parentheses in call to '(\w+)'/, function (m, L) {
      return "`" + m[1] + "` needs parentheses: `" + m[1] + "(...)`. Put what you want "
        + "to show inside them on " + L + ".";
    }],
    [/^invalid character '(.)' \(U\+([0-9A-F]+)\)/, function (m, L) {
      var curly = /^(201C|201D|2018|2019)$/.test(m[2]);
      return L.charAt(0).toUpperCase() + L.slice(1) + " has a character Python can't read: `"
        + m[1] + "`." + (curly ? " That's a curly quote, often from copying out of a "
        + "document. Retype it with a plain `\"` or `'`." : "");
    }],
    [/^invalid decimal literal/, function (m, L) {
      return "On " + L + " a number runs straight into letters (like `2x`). A name "
        + "can't start with a digit, and multiplying needs `*`.";
    }],
    [/^'(return)' outside function/, function (m, L) {
      return "`return` on " + L + " can only be used inside a `def`. Check its indentation.";
    }],
    [/^'(break|continue)' (?:not properly in|outside) loop/, function (m, L) {
      return "`" + m[1] + "` on " + L + " can only be used inside a loop. Check its indentation.";
    }],
    [/^expected 'except' or 'finally' block/, function (m, L) {
      return "A `try:` needs an `except:` or `finally:` block after it. Python reached "
        + L + " without finding one.";
    }],
    [/^Expected one or more names after 'import'/, function (m, L) {
      return "`import` on " + L + " needs the name of what to import after it.";
    }],
    [/^f-string: (.*)/, function (m, L) {
      return "Something inside the `{ }` of the f-string on " + L + " can't be read.";
    }],
    // The vague one. Look at how the line is written for one safe hint.
    [/^invalid syntax/, function (m, L, t) {
      var word = ((t || "").match(/^\s*([A-Za-z_]\w*)/) || [])[1] || "";
      if (word === "else" || word === "elif") {
        return "The `" + word + "` on " + L + " has no `if` right above it. "
          + "It must line up exactly with the `if` it belongs to.";
      }
      var fix = misspelled(word);
      if (fix) return "On " + L + ", did you mean `" + fix + "` instead of `" + word + "`?";
      if (/[+\-*\/%=,(]\s*(#.*)?$/.test(t || "")) {
        return L.charAt(0).toUpperCase() + L.slice(1) + " ends in the middle of something: "
          + "there's nothing after the last symbol.";
      }
      return "Python can't read " + L + ". Look closely at the highlighted spot for a "
        + "missing or extra symbol, or a misspelled word.";
    }]
  ];

  /* What to say about one error: the friendly sentence, and Python's own. */
  function explain(info) {
    // A Flask project is several .py files, so the file is always named.
    var place = "line " + info.line + (info.file ? " of " + info.file : "");
    var friendly = "";
    for (var i = 0; i < RULES.length && !friendly; i++) {
      var m = RULES[i][0].exec(info.msg || "");
      if (m) friendly = RULES[i][1](m, place, info.text || "", info);
    }
    if (!friendly) {
      friendly = "Python can't read " + place + ". Its message is below.";
    }
    return {
      friendly: friendly,
      python: (info.kind || "SyntaxError") + ": " + info.msg
        + " (" + (info.file || "app.py") + ", line " + info.line + ")",
      known: friendly.indexOf("Its message is below") === -1
    };
  }

  /* Ask Python, before running. null when every file reads. FlaskIDE's
     pages ask through FlaskIDERuntime.check instead, which boots Python
     first; this stays so the file keeps the same shape in every app. */
  function check(pyodide, source, files) {
    var fn = pyodide.globals.get("_pyide_check");
    if (!fn) return null;
    try {
      var out = fn(source, JSON.stringify(files || {}));
      return out ? JSON.parse(out) : null;
    } catch (e) {
      return null;               // a broken check must never stop a Run
    } finally {
      if (fn.destroy) fn.destroy();
    }
  }

  /* `text` with `code` in backticks, as DOM — never innerHTML, since the
     message quotes the student's own characters. */
  function withCode(el, text) {
    text.split("`").forEach(function (part, i) {
      if (!part) return;
      if (i % 2) {
        var c = document.createElement("code");
        c.textContent = part;
        el.appendChild(c);
      } else {
        el.appendChild(document.createTextNode(part));
      }
    });
  }

  /* One card per page, covering the output pane.

       opts.host     the output pane; the card fills it
       opts.editor   the CodeMirror instance, for the highlight
       opts.reveal   function(file) that makes `file` the open tab, and
                     returns the CodeMirror doc to mark, or null

     The card and the highlight go as soon as the student types, so neither
     stays on screen describing code that is no longer there. */
  function attach(opts) {
    var card = null, marks = [], lineHandle = null, lineDoc = null, unhook = null;

    function clear() {
      if (card && card.parentNode) card.parentNode.removeChild(card);
      card = null;
      marks.forEach(function (m) { m.clear(); });
      marks = [];
      if (lineHandle && lineDoc) {
        try { lineDoc.removeLineClass(lineHandle, "background", "syntax-bad-line"); }
        catch (e) { /* the line went with an edit */ }
      }
      lineHandle = lineDoc = null;
      if (unhook) { unhook(); unhook = null; }
    }

    function mark(info) {
      var doc = opts.reveal ? opts.reveal(info.file || "main.py") : null;
      if (!doc) return;
      var n = Math.max(0, Math.min((info.line || 1) - 1, doc.lastLine()));
      lineDoc = doc;
      lineHandle = doc.addLineClass(n, "background", "syntax-bad-line");
      var len = doc.getLine(n).length;
      var from = Math.max(0, Math.min((info.col || 1) - 1, len));
      var to = info.end_line === info.line && info.end_col > info.col
        ? Math.min(info.end_col - 1, len) : Math.min(from + 1, len);
      if (to > from) {
        marks.push(doc.markText({ line: n, ch: from }, { line: n, ch: to },
                                { className: "syntax-bad-spot" }));
      }
      doc.setCursor({ line: n, ch: from });
      if (opts.editor) opts.editor.scrollIntoView({ line: n, ch: from }, 80);
    }

    function show(info) {
      clear();
      var said = explain(info);
      card = document.createElement("div");
      card.className = "syntax-card";
      card.setAttribute("role", "alert");

      var head = document.createElement("div");
      head.className = "syntax-head";
      var title = document.createElement("strong");
      title.textContent = "Python can't read this yet";
      head.appendChild(title);
      var x = document.createElement("button");
      x.type = "button";
      x.className = "syntax-x";
      x.title = "Close";
      x.textContent = "×";
      x.addEventListener("click", clear);
      head.appendChild(x);
      card.appendChild(head);

      var p = document.createElement("p");
      p.className = "syntax-say";
      withCode(p, said.friendly);
      card.appendChild(p);

      var raw = document.createElement("div");
      raw.className = "syntax-python";
      raw.textContent = "Python says: " + said.python;
      card.appendChild(raw);

      opts.host.classList.add("syntax-host");    // the card is placed inside it
      opts.host.appendChild(card);
      mark(info);

      // Gone on the next keystroke, and with Escape.
      var ed = opts.editor;
      var onChange = function () { clear(); };
      var onKey = function (e) { if (e.key === "Escape") clear(); };
      if (ed) ed.on("change", onChange);
      document.addEventListener("keydown", onKey);
      unhook = function () {
        if (ed) ed.off("change", onChange);
        document.removeEventListener("keydown", onKey);
      };
    }

    return { show: show, clear: clear };
  }

  return { explain: explain, check: check, attach: attach, RULES: RULES };
})();
