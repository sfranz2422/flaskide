/* FlaskIDE — the PHP half: a student's PHP site, run in their own browser.
 *
 * The same idea as flask.js. A PHP site looks like it needs a web server per
 * student, and it does not: PHP compiled to WebAssembly (WordPress
 * Playground's @php-wasm) runs a request the way Apache would — $_GET,
 * $_POST, $_SESSION, header(), include — with the files on a filesystem in
 * memory, and hands back the status, headers and page.
 *
 * THIS FILE IS SHARED. The page runs it inside a Web Worker (php_worker.js
 * loads PHP from the CDN and hands it in), and tools/test_php.py runs it in
 * Node with @php-wasm/node. Anything that decides what a student sees lives
 * here, once, so the tests run the code the browser runs. php.js — the
 * page's side — only talks to the worker and keeps the clock.
 *
 * makeCore({ PHP, PHPRequestHandler, setPhpIniEntries, load }) answers
 * { boot, run, request, check }, each taking and returning plain objects
 * (they cross postMessage).
 */

export const WWW = "/www";
const DB = WWW + "/data.db";
const SESSIONS = "/tmp/sessions";
const SCHEMA = "schema.sql";

/* What a page shows when it goes wrong, as XAMPP shows it: warnings and
   fatal errors written into the page, where a student is looking. Off is
   the right setting for a real site and the worst one for learning — a
   blank page that should have said "Undefined variable $titel on line 4". */
const INI = {
  display_errors: "1",
  display_startup_errors: "1",
  error_reporting: "E_ALL",
  html_errors: "1",
  "session.save_path": SESSIONS,
  "date.timezone": "America/New_York",
};

export function makeCore({ PHP, PHPRequestHandler, setPhpIniEntries, load }) {
  let php = null;
  let handler = null;

  async function boot() {
    if (php) return;
    php = new PHP(await load());
    await setPhpIniEntries(php, INI);
  }

  function clear(path) {
    if (php.fileExists(path)) php.rmdir(path, { recursive: true });
    php.mkdirTree(path);
  }

  /* Put the student's files in /www and start a fresh "browser": a new
     handler is a new cookie jar, so a session from the last Run is not
     carried into this one — the same as Flask's one test client per Run.
     Their saved sessions go too, for the same reason. */
  async function run({ files }) {
    await boot();
    clear(WWW);
    clear(SESSIONS);
    for (const [name, text] of Object.entries(files || {})) {
      if (typeof text !== "string") continue;
      const path = WWW + "/" + name;
      php.mkdirTree(path.slice(0, path.lastIndexOf("/")));
      php.writeFile(path, text);
    }
    php.chdir(WWW);
    handler = new PHPRequestHandler({ php, documentRoot: WWW, absoluteUrl: "http://localhost/" });

    const names = Object.keys(files || {});
    if (!names.includes("index.php")) {
      return { ok: false, error: "There is no index.php. A PHP site needs one: it is the page that opens first, at /." };
    }
    let tables = [];
    if (typeof files[SCHEMA] === "string") {
      const built = await buildDb(files[SCHEMA]);
      if (!built.ok) return { ok: false, error: built.error, statement: built.statement };
      tables = built.tables;
    }
    // The pages a visitor can open, for the console's "Your site's pages".
    // includes/ is left out: those are pieces of pages, not pages.
    const pages = names.filter((n) => n.endsWith(".php") && !n.startsWith("includes/"))
      .sort((a, b) => (a === "index.php" ? -1 : b === "index.php" ? 1 : a.localeCompare(b)))
      .map((n) => "/" + n);
    return { ok: true, pages, tables };
  }

  /* data.db from schema.sql, from nothing, every Run — the promise Flask
     projects make, kept the same way. One statement at a time, so an error
     names the statement it came from: "near FORM: syntax error" alone does
     not say which of twenty. */
  async function buildDb(text) {
    const statements = sqlStatements(text);
    // The statements go in a file rather than into the code above: a quote
    // or a backslash in a student's SQL must never become PHP syntax.
    php.writeFile("/tmp/schema.json", JSON.stringify(statements));
    const done = await php.run({
      code: `<?php
        $out = ["ok" => true, "tables" => []];
        $db = new PDO('sqlite:${DB}');
        $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $db->exec('PRAGMA foreign_keys = ON');
        foreach (json_decode(file_get_contents('/tmp/schema.json')) as $s) {
          try { $db->exec($s); }
          catch (Throwable $e) {
            $msg = $e instanceof PDOException && isset($e->errorInfo[2]) ? $e->errorInfo[2] : $e->getMessage();
            echo json_encode(["ok" => false, "error" => "schema.sql: " . $msg, "statement" => $s]);
            exit;
          }
        }
        foreach ($db->query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name") as $row) {
          $n = $row['name'];
          $out["tables"][] = ["name" => $n, "rows" => (int) $db->query('SELECT COUNT(*) FROM "' . str_replace('"', '""', $n) . '"')->fetchColumn()];
        }
        echo json_encode($out);`,
    });
    try { return JSON.parse(done.text); }
    catch (e) { return { ok: false, error: "schema.sql couldn't be read: " + (done.errors || done.text).trim() }; }
  }

  /* One request, as a browser would send it. `form` is { name: value } as
     preview.js gathers a form; on a GET it goes on the address, as a GET
     form's fields do. */
  async function request({ method, path, form, json }) {
    if (!handler) return { status: 0, headers: {}, body: "Nothing is running.", isText: true, errors: "" };
    method = (method || "GET").toUpperCase();
    let url = path || "/";
    if (url.charAt(0) !== "/") url = "/" + url;
    const headers = {};
    let body;
    if (json !== undefined && json !== null) {
      headers["content-type"] = "application/json";
      body = new TextEncoder().encode(JSON.stringify(json));
    } else if (form) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(form)) q.append(k, v == null ? "" : String(v));
      if (method === "GET") {
        const s = q.toString();
        if (s) url = url.split("?")[0] + "?" + s;
      } else {
        headers["content-type"] = "application/x-www-form-urlencoded";
        body = new TextEncoder().encode(q.toString());
      }
    }
    const r = await handler.request({ method, url, headers, ...(body ? { body } : {}) });
    const out = {};
    for (const [k, v] of Object.entries(r.headers || {})) {
      // Content-Type, Location: the spelling preview.js and the checks read.
      const name = k.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("-");
      out[name] = Array.isArray(v) ? v.join(", ") : String(v);
    }
    const kind = out["Content-Type"] || "text/html";
    const isText = /^text\/|json|javascript|xml|svg/i.test(kind);
    const bytes = r.bytes instanceof Uint8Array ? r.bytes : new TextEncoder().encode(r.text || "");
    return {
      status: r.httpStatusCode,
      headers: out,
      // A warning in the page names the file as add.php, not /www/add.php
      // (only inside PHP's own "in <b>…</b> on line" wording, so nothing a
      // student's page says is touched).
      body: isText ? (r.text || "").split("in <b>" + WWW + "/").join("in <b>") : base64(bytes),
      isText,
      // PHP's own warnings and errors, for the output pane. The page has
      // them too (display_errors), but a warning on a redirect or inside a
      // tag is in no page anyone sees.
      errors: plainErrors(r.errors || ""),
    };
  }

  /* The first PHP file that PHP cannot read, as syntax.js's card wants it,
     or null. token_get_all with TOKEN_PARSE parses without running, so this
     can never do what a page does — only say it cannot be read. */
  async function check({ files }) {
    await boot();
    const names = Object.keys(files || {}).filter((n) => n.endsWith(".php") && typeof files[n] === "string").sort();
    if (names.includes("index.php")) names.splice(names.indexOf("index.php"), 1), names.unshift("index.php");
    php.writeFile("/tmp/check.json", JSON.stringify(names.map((n) => [n, files[n]])));
    const r = await php.run({
      code: `<?php
        foreach (json_decode(file_get_contents('/tmp/check.json')) as [$name, $code]) {
          try { token_get_all($code, TOKEN_PARSE); }
          catch (ParseError $e) {
            $lines = explode("\\n", $code);
            echo json_encode(["file" => $name, "kind" => "ParseError", "msg" => $e->getMessage(),
                              "line" => $e->getLine(), "col" => 0, "end_line" => 0, "end_col" => 0,
                              "text" => rtrim($lines[$e->getLine() - 1] ?? ""),
                              // the line before, skipping blanks: where a missing ; was
                              "prev" => (function ($lines, $n) {
                                  for ($i = $n - 2; $i >= 0; $i--) if (trim($lines[$i]) !== "") return rtrim($lines[$i]);
                                  return "";
                              })($lines, $e->getLine())]);
            exit;
          }
        }`,
    });
    const text = (r.text || "").trim();
    return text ? JSON.parse(text) : null;
  }

  return { boot, run, request, check };
}

/* "PHP Warning:  Undefined variable $x in /www/add.php on line 4" with the
   /www/ taken off: the student's file is add.php, and /www is ours. */
export function plainErrors(text) {
  return String(text).split(WWW + "/").join("").trim();
}

function base64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/* schema.sql split into statements. NOT text.split(";"): a semicolon inside
   a string ('Tom; Jerry') or a comment is not the end of a statement, and
   splitting there makes two halves that are each a syntax error in a file
   that is fine. Comment-only pieces are dropped, as flask.js drops them. */
export function sqlStatements(text) {
  const out = [];
  let start = 0, i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === "'" || c === '"' || c === "`") {
      i += 1;
      while (i < n) {
        if (text[i] === c) { if (text[i + 1] === c) { i += 2; continue; } break; }
        i += 1;
      }
      i += 1;
    } else if (c === "-" && text[i + 1] === "-") {
      while (i < n && text[i] !== "\n") i += 1;
    } else if (c === "/" && text[i + 1] === "*") {
      const end = text.indexOf("*/", i + 2);
      i = end < 0 ? n : end + 2;
    } else if (c === ";") {
      out.push(text.slice(start, i + 1));
      i += 1;
      start = i;
    } else {
      i += 1;
    }
  }
  if (text.slice(start).trim()) out.push(text.slice(start));
  return out.map((s) => s.trim()).filter((s) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/--[^\n]*/g, " ").trim().replace(/;$/, "").trim());
}
