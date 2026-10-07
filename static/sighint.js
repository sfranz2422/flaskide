/* FlaskIDE — what goes in the brackets, while you type them.
 *
 *     my_list.append(
 *     ┌────────────────────────┐
 *     │ append(item)           │   above the line, small and dim
 *     │ adds item to the end   │
 *     └────────────────────────┘
 *
 * Shown only while the cursor is inside the brackets of a call it knows,
 * with the argument being typed in bold. It inserts nothing, takes no key
 * but Escape, and goes the moment the brackets close or the cursor leaves.
 *
 * NOT TOO HELPFUL, ON PURPOSE. It says what each slot is called and, in a
 * few words, what the function does — never what to put in the slots, and
 * nothing about whether the call makes sense. That is the same line the
 * syntax card keeps: how code is written, not what it should do.
 *
 * WHERE THE HINTS COME FROM, in the order they win:
 *
 *   their own   `def move(player, steps):` in the code they are writing,
 *               read here with a small scanner — this app has no Python
 *               loaded while a student types
 *   kaypy       PyIDE only (its games engine); off here, where opts.flask
 *               is on.
 *   Python      the table below: the built-ins and methods an intro class
 *               uses, with beginner names (`item`, not Python's `object, /`)
 *   Flask       the same, for Flask, the request and sqlite3 (opts.flask)
 *
 * A method name several types share (`.pop(`, `.index(`) shows each, one
 * line apiece: the editor cannot know what type `x` is, and saying so is
 * better than guessing.
 */

window.FlaskIDESigHint = (function () {
  "use strict";

  // name: [[params...], ...forms], "what it does"
  function F(forms, doc) { return { forms: forms, doc: doc || "" }; }

  var FUNCTIONS = {
    print: F([["*values", "sep=' '", "end='\\n'"]], "shows the values, separated by spaces"),
    input: F([["prompt"]], "shows the prompt, waits for a line, gives it back as a string"),
    len: F([["thing"]], "how many items (or characters) it has"),
    range: F([["stop"], ["start", "stop"], ["start", "stop", "step"]], "counts from start up to, not including, stop"),
    int: F([["value"]], "a whole number from a string or a float"),
    float: F([["value"]], "a decimal number from a string or an int"),
    str: F([["value"]], "the value as a string"),
    bool: F([["value"]], "True or False"),
    list: F([[], ["things"]], "a new list, empty or from the things given"),
    dict: F([[], ["pairs"]], "a new dictionary"),
    tuple: F([["things"]], "a tuple of the things given"),
    set: F([[], ["things"]], "a set: no duplicates, no order"),
    round: F([["number", "digits=0"]], "rounded to that many decimal places"),
    abs: F([["number"]], "the number without its minus sign"),
    min: F([["a", "b", "*more"], ["things"]], "the smallest"),
    max: F([["a", "b", "*more"], ["things"]], "the largest"),
    sum: F([["numbers", "start=0"]], "all of them added up"),
    sorted: F([["things", "key=None", "reverse=False"]], "a new list, sorted"),
    reversed: F([["things"]], "the items in reverse order"),
    enumerate: F([["things", "start=0"]], "each item with its position"),
    zip: F([["first", "second", "*more"]], "items from each, side by side"),
    type: F([["value"]], "what kind of value it is"),
    isinstance: F([["value", "kind"]], "True if value is that kind"),
    open: F([["filename", "mode='r'"]], "opens a file: 'r' read, 'w' write, 'a' add"),
    pow: F([["base", "exponent"]], "base to the power of exponent"),
    divmod: F([["a", "b"]], "(a // b, a % b)"),
    chr: F([["code"]], "the character with that number"),
    ord: F([["character"]], "the number of that character"),
    any: F([["things"]], "True if any of them is true"),
    all: F([["things"]], "True if all of them are true"),
    "random.randint": F([["low", "high"]], "a whole number from low to high, both included"),
    "random.random": F([[]], "a decimal from 0 up to, not including, 1"),
    "random.choice": F([["things"]], "one item picked at random"),
    "random.shuffle": F([["things"]], "mixes up the list in place"),
    "random.uniform": F([["low", "high"]], "a decimal between low and high"),
    "random.sample": F([["things", "count"]], "that many different items, picked at random"),
    "random.randrange": F([["stop"], ["start", "stop", "step=1"]], "like range(), but one number picked at random"),
    "math.sqrt": F([["number"]], "the square root"),
    "math.floor": F([["number"]], "rounded down to a whole number"),
    "math.ceil": F([["number"]], "rounded up to a whole number"),
    "math.pow": F([["base", "exponent"]], "base to the power of exponent, as a float"),
    "math.sin": F([["radians"]], ""), "math.cos": F([["radians"]], ""),
    "math.radians": F([["degrees"]], "degrees to radians"),
    "math.degrees": F([["radians"]], "radians to degrees"),
    "math.hypot": F([["x", "y"]], "the length of the diagonal"),
    "time.sleep": F([["seconds"]], "waits that many seconds"),
  };

  // Methods, by name. Several types can share one: each is a line.
  function M(kind, params, doc) { return { kind: kind, forms: [params], doc: doc || "" }; }
  var METHODS = {
    append: [M("list", ["item"], "adds item to the end")],
    insert: [M("list", ["position", "item"], "puts item at that position; the rest move along")],
    extend: [M("list", ["more_items"], "adds every item from another list to the end")],
    remove: [M("list", ["item"], "removes the first item equal to it"),
             M("set", ["item"], "removes it from the set")],
    pop: [M("list", ["position=-1"], "removes and gives back an item (the last by default)"),
          M("dict", ["key", "default"], "removes the key and gives back its value")],
    index: [M("list", ["item"], "the position of the first item equal to it"),
            M("str", ["text"], "the position where text first appears")],
    count: [M("list", ["item"], "how many items equal it"),
            M("str", ["text"], "how many times text appears")],
    sort: [M("list", ["key=None", "reverse=False"], "sorts the list in place")],
    reverse: [M("list", [], "reverses the list in place")],
    clear: [M("list", [], "empties it")],
    copy: [M("list", [], "a separate copy")],
    upper: [M("str", [], "in capitals")],
    lower: [M("str", [], "in lower case")],
    title: [M("str", [], "With Each Word Capitalised")],
    capitalize: [M("str", [], "First letter capital")],
    strip: [M("str", ["chars=' '"], "without spaces (or chars) at either end")],
    split: [M("str", ["separator=' '"], "a list of the pieces between separators")],
    join: [M("str", ["things"], "the things joined into one string, this string between them")],
    replace: [M("str", ["old", "new"], "with every old replaced by new")],
    find: [M("str", ["text"], "the position where text first appears, or -1")],
    startswith: [M("str", ["text"], "True if it begins with text")],
    endswith: [M("str", ["text"], "True if it ends with text")],
    isdigit: [M("str", [], "True if it is all digits")],
    isalpha: [M("str", [], "True if it is all letters")],
    format: [M("str", ["*values"], "fills in each {} with a value")],
    get: [M("dict", ["key", "default=None"], "the value for key, or default if it is missing")],
    keys: [M("dict", [], "all the keys")],
    values: [M("dict", [], "all the values")],
    items: [M("dict", [], "all the (key, value) pairs")],
    update: [M("dict", ["other"], "adds the pairs from another dictionary")],
    add: [M("set", ["item"], "adds it to the set")],
    read: [M("file", [], "the whole file as one string")],
    readline: [M("file", [], "the next line")],
    readlines: [M("file", [], "every line, as a list")],
    write: [M("file", ["text"], "writes text to the file")],
    close: [M("file", [], "closes the file")],
  };

  // FlaskIDE's own: Flask, the request, and sqlite3.
  var FLASK_FUNCTIONS = {
    Flask: F([["__name__"]], "makes the app"),
    render_template: F([["template_name", "**values"]], "fills in a page from templates/ with the values"),
    redirect: F([["url"]], "sends the browser to another page"),
    url_for: F([["function_name", "**values"]], "the address of a route, by its function's name"),
    abort: F([["status_code"]], "stops and answers with that error, like 404"),
    jsonify: F([["data"]], "answers with JSON"),
    flash: F([["message"]], "a message for the next page to show"),
    "sqlite3.connect": F([["database_file"]], "opens the database"),
  };
  var FLASK_METHODS = {
    route: [M("app", ["path", "methods=['GET']"], "the URL this function answers")],
    get: [M("request.form / request.args", ["name", "default=None"], "a value sent by the form or in the URL")],
    execute: [M("sqlite3", ["sql", "values=()"], "runs one SQL statement; ? marks are filled from values")],
    fetchall: [M("sqlite3", [], "every row the query found")],
    fetchone: [M("sqlite3", [], "the next row, or None")],
    commit: [M("sqlite3", [], "saves the changes")],
    cursor: [M("sqlite3", [], "something to run queries with")],
  };

  // ---------------------------------------------------------- their own
  /* `def name(params):`, anywhere in their code. A def whose first
     parameter is self is a method, hinted after a dot, without the self.
     A scanner rather than Python's parser, so it works before Python has
     loaded and on half-typed code; test_sighint.py holds it to `ast`. */
  var DEF = /^[ \t]*def[ \t]+([A-Za-z_]\w*)[ \t]*\(/gm;

  /* What is between a def's brackets, brackets inside it included —
     `t=(1, 2)` must not end the list at its own `)`. null if it never
     closes, which is a def still being typed. */
  function paramText(src, from) {
    var depth = 1, quote = null;
    for (var i = from; i < src.length; i++) {
      var ch = src[i];
      if (quote) {
        if (ch === "\\") i++;
        else if (ch === quote) quote = null;
        continue;
      }
      if (ch === "'" || ch === '"') quote = ch;
      else if ("([{".indexOf(ch) >= 0) depth++;
      else if (")]}".indexOf(ch) >= 0 && --depth === 0) return src.slice(from, i);
    }
    return null;
  }

  function ownDefs(sources) {
    var fns = {}, methods = {};
    sources.forEach(function (src) {
      var m;
      src = src || "";
      DEF.lastIndex = 0;
      while ((m = DEF.exec(src))) {
        var inside = paramText(src, DEF.lastIndex);
        if (inside === null) continue;
        var params = split(inside).map(function (p) {
          // `x: int = 3` is hinted as x=3. Only a colon before any `=` is a
          // type: in `d={'a': 1}` the colon belongs to the default.
          return p.replace(/^([^=:]*?)\s*:[^=]*/, "$1").replace(/\s*=\s*/, "=");
        }).filter(Boolean);
        if (params[0] === "self" || params[0] === "cls") {
          methods[m[1]] = { forms: [params.slice(1)], doc: "", kind: "yours" };
        } else {
          fns[m[1]] = { forms: [params], doc: "" };
        }
      }
    });
    return { functions: fns, methods: methods };
  }

  function split(text) {
    var out = [], depth = 0, cur = "", quote = null;
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (quote) {                         // `sep=', '` is one parameter
        cur += ch;
        if (ch === quote) quote = null;
        continue;
      }
      if (ch === "'" || ch === '"') quote = ch;
      else if ("([{".indexOf(ch) >= 0) depth++;
      else if (")]}".indexOf(ch) >= 0) depth--;
      if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  // ------------------------------------------------- where the cursor is
  /* The innermost unclosed `(` before the cursor, ignoring brackets inside
     strings and comments, and how many top-level commas follow it. Looks
     back a few lines, for a call written across lines. */
  function openCall(text) {
    var stack = [], quote = null, triple = false;
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (quote) {
        if (ch === "\\") { i++; continue; }
        if (triple ? text.substr(i, 3) === quote + quote + quote : ch === quote) {
          if (triple) i += 2;
          quote = null;
        } else if (!triple && ch === "\n") {
          quote = null;                      // an unclosed string ends with its line
        }
        continue;
      }
      if (ch === "#") {
        var nl = text.indexOf("\n", i);
        if (nl === -1) return null;          // the cursor is in a comment
        i = nl;
        continue;
      }
      if (ch === "'" || ch === '"') {
        triple = text.substr(i, 3) === ch + ch + ch;
        quote = ch;
        if (triple) i += 2;
        continue;
      }
      if ("([{".indexOf(ch) >= 0) stack.push({ ch: ch, at: i, commas: 0, argStart: i + 1 });
      else if (")]}".indexOf(ch) >= 0) stack.pop();
      else if (ch === "," && stack.length) {
        stack[stack.length - 1].commas++;
        stack[stack.length - 1].argStart = i + 1;
      }
    }
    var top = stack[stack.length - 1];
    if (!top || top.ch !== "(") return null;
    var before = text.slice(0, top.at);
    var m = /([A-Za-z_]\w*(?:[ \t]*\.[ \t]*[A-Za-z_]\w*)*)[ \t]*$/.exec(before);
    if (!m) return null;
    // `def name(` is writing a function, not calling one
    if (/\b(def|class)[ \t]+$/.test(before.slice(0, m.index))) return null;
    var parts = m[1].split(/[ \t]*\.[ \t]*/);
    var kw = /^\s*([A-Za-z_]\w*)\s*=(?!=)/.exec(text.slice(top.argStart));
    return { parts: parts, arg: top.commas, keyword: kw ? kw[1] : "",
             openAt: top.at, inString: !!quote };
  }

  // --------------------------------------------------------------- lookup
  function lookup(call, own, kaypyOn, kaypySigs, flask) {
    var name = call.parts[call.parts.length - 1];
    var dotted = call.parts.join(".");
    var hits = [];
    function take(entry, label, kind) {
      if (entry) hits.push({ label: label, forms: entry.forms, doc: entry.doc, kind: kind || "" });
    }
    if (call.parts.length === 1) {
      take(own.functions[name], name, "yours");
      if (!hits.length && kaypyOn && kaypySigs) take(kaypySigs.functions[name], name, "kaypy");
      if (!hits.length && flask) take(FLASK_FUNCTIONS[name], name);
      if (!hits.length) take(FUNCTIONS[name], name);
      return hits;
    }
    // module.function — random.randint, math.sqrt, sqlite3.connect
    var modFn = (flask && FLASK_FUNCTIONS[dotted]) || FUNCTIONS[dotted];
    if (modFn) { take(modFn, dotted); return hits; }
    // obj.method
    take(own.methods[name], "." + name, "yours");
    if (kaypyOn && kaypySigs) take(kaypySigs.methods[name], "." + name, "kaypy");
    ((flask && FLASK_METHODS[name]) || []).forEach(function (e) { take(e, "." + name, e.kind); });
    (METHODS[name] || []).forEach(function (e) { take(e, "." + name, e.kind); });
    return hits.slice(0, 3);
  }

  /* Which parameter is being typed: the keyword if they wrote `name=`, else
     by position, sticking on a *rest parameter once past it. -1 for none. */
  function activeIndex(params, call) {
    var rest = -1;                       // a **values slot, if there is one
    for (var k = 0; k < params.length; k++) if (params[k].slice(0, 2) === "**") rest = k;
    if (call.keyword) {
      for (var i = 0; i < params.length; i++) {
        if (params[i].replace(/^\*+/, "").split("=")[0] === call.keyword) return i;
      }
      return rest;                       // name=value for **values
    }
    for (var j = 0; j < params.length; j++) {
      if (params[j].charAt(0) === "*") return j;   // *things or **values: stays bold
      if (j === call.arg) return j;
    }
    return -1;
  }

  // --------------------------------------------------------------- the box
  function render(hits, call) {
    var box = document.createElement("div");
    box.className = "sig-hint";
    box.setAttribute("aria-hidden", "true");     // the editor keeps the reader's focus
    hits.forEach(function (h) {
      // a call already past every form's slots shows the forms anyway; the
      // bold just goes away, which is its own small hint
      h.forms.slice(0, 3).forEach(function (params) {
        var line = document.createElement("div");
        line.className = "sig-line";
        if (h.kind && h.kind !== "yours") {
          var k = document.createElement("span");
          k.className = "sig-kind";
          k.textContent = h.kind + " ";
          line.appendChild(k);
        }
        line.appendChild(document.createTextNode(h.label + "("));
        var on = activeIndex(params, call);
        params.forEach(function (p, i) {
          if (i) line.appendChild(document.createTextNode(", "));
          var s = document.createElement(i === on ? "b" : "span");
          s.textContent = p;
          line.appendChild(s);
        });
        line.appendChild(document.createTextNode(")"));
        box.appendChild(line);
      });
      if (h.doc) {
        var d = document.createElement("div");
        d.className = "sig-doc";
        d.textContent = h.doc;
        box.appendChild(d);
      }
    });
    return box;
  }

  /* On one CodeMirror.
       opts.sources()  every .py file's text, for their own defs
       opts.flask      FlaskIDE's own table on
       opts.isPython() false while a .txt or .html tab is open */
  var kaypySigs = null, kaypyLoading = null;
  function loadKaypy(url) {
    if (!kaypyLoading && url) {
      kaypyLoading = fetch(url).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { kaypySigs = d; })
        .catch(function () { kaypyLoading = null; });   // no kaypy hints, nothing worse
    }
    return kaypyLoading || Promise.resolve();
  }

  function attach(cm, opts) {
    opts = opts || {};
    var box = null, dismissed = null, own = { functions: {}, methods: {} }, ownFrom = null;
    var KAYPY = /^\s*(from\s+kaypy\s+import|import\s+kaypy)\b/m;

    function hide() {
      if (box && box.parentNode) box.parentNode.removeChild(box);
      box = null;
    }

    function update() {
      hide();
      if (opts.isPython && !opts.isPython()) return;
      if (cm.somethingSelected()) return;
      var cur = cm.getCursor();
      var fromLine = Math.max(0, cur.line - 8);
      var text = cm.getRange({ line: fromLine, ch: 0 }, cur);
      var call = openCall(text);
      if (!call) { dismissed = null; return; }
      var key = cur.line + ":" + call.openAt + ":" + fromLine;
      if (dismissed === key) return;

      var sources = opts.sources ? opts.sources() : [cm.getValue()];
      var joined = sources.join("\n\u0000\n");
      if (joined !== ownFrom) { own = ownDefs(sources); ownFrom = joined; }
      var kaypyOn = !opts.flask && KAYPY.test(cm.getValue());
      // The first kaypy call of the session arrives before kaypy's hints
      // do: draw again when they land, rather than on the next keystroke.
      if (kaypyOn && !kaypySigs) loadKaypy(opts.kaypyUrl).then(function () {
        if (kaypySigs) update();
      });

      var hits = lookup(call, own, kaypyOn, kaypySigs, opts.flask);
      if (!hits.length) return;

      box = render(hits, call);
      // Above the line, at the bracket: below is where completion's list
      // opens, and the two must never sit on top of each other.
      var at = cm.posFromIndex(cm.indexFromPos({ line: fromLine, ch: 0 }) + call.openAt);
      cm.addWidget(at, box, false);
      var c = cm.charCoords(at, "local");
      var h = box.offsetHeight;
      if (c.top - h - 2 >= 0) box.style.top = (c.top - h - 2) + "px";
    }

    cm.on("cursorActivity", update);
    cm.on("blur", hide);
    cm.on("focus", update);
    cm.on("keydown", function (cm2, e) {
      if (e.key === "Escape" && box) {
        hide();
        var cur = cm.getCursor();
        var fromLine = Math.max(0, cur.line - 8);
        var call = openCall(cm.getRange({ line: fromLine, ch: 0 }, cur));
        if (call) dismissed = cur.line + ":" + call.openAt + ":" + fromLine;
      }
    });
    return { update: update, hide: hide };
  }

  return { attach: attach, openCall: openCall, lookup: lookup, ownDefs: ownDefs,
           activeIndex: activeIndex, FUNCTIONS: FUNCTIONS, METHODS: METHODS };
})();
