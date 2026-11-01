#!/usr/bin/env python3
"""PHP sites (static/php_core.js, static/php.js) in real PHP.

    npm install            # once: @php-wasm/node, into node_modules/
    python3 tools/test_php.py

php_core.js is the code the page's Web Worker runs. Here it runs in Node on
@php-wasm/node — the same PHP build, version for version, as the page loads
from the CDN — so a page, a form, a session, a redirect and the database are
checked in PHP itself, not described. php.js (the page's side: the clock,
the queue, starting a stuck worker over) runs here too, against a stand-in
Worker that answers from the same core, plus one that never answers.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_PHP = os.path.join(ROOT, "node_modules", "@php-wasm", "node", "index.js")
UNIVERSAL = os.path.join(ROOT, "node_modules", "@php-wasm", "universal", "index.js")
failures = 0
count = 0


def check(name, ok, detail=""):
    global failures, count
    count += 1
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  -- " + str(detail)[:400]))
    if not ok:
        failures += 1


if not shutil.which("node"):
    print("FAIL node is required: brew install node")
    sys.exit(1)
if not os.path.exists(NODE_PHP):
    print("FAIL PHP for Node is missing: run `npm install` in %s" % ROOT)
    sys.exit(1)

SITE = {
    "index.php": "<?php session_start();\ninclude 'includes/header.php';\n"
                 "$_SESSION['n'] = ($_SESSION['n'] ?? 0) + 1;\necho '<p>visits=' . $_SESSION['n'] . '</p>';\n"
                 "include 'includes/footer.php';\n",
    "includes/header.php": "<!doctype html><html><head><title>Vault</title>"
                           "<link rel=\"stylesheet\" href=\"/static/style.css\"></head><body><h1>Game Vault</h1>\n",
    "includes/footer.php": "</body></html>\n",
    "static/style.css": "body { color: navy; }\n",
    "add.php": "<?php\nif ($_SERVER['REQUEST_METHOD'] === 'POST') {\n"
               "  $db = new PDO('sqlite:data.db');\n"
               "  $s = $db->prepare('INSERT INTO games (title) VALUES (?)');\n"
               "  $s->execute([$_POST['title']]);\n"
               "  header('Location: /games.php');\n  exit;\n}\n"
               "echo '<form method=\"post\"><input name=\"title\"></form>';\n",
    "games.php": "<?php\n$db = new PDO('sqlite:data.db');\n"
                 "foreach ($db->query('SELECT title FROM games ORDER BY id') as $row) {\n"
                 "  echo '<li>' . htmlspecialchars($row['title']) . '</li>';\n}\n"
                 "echo '<p>count=' . $db->query('SELECT COUNT(*) FROM games')->fetchColumn() . '</p>';\n",
    "search.php": "<?php echo 'q=' . htmlspecialchars($_GET['q'] ?? '');\n",
    "warn.php": "<?php echo 'Hello ' . $titel;\n",
    "api.php": "<?php header('Content-Type: application/json');\n"
               "$in = json_decode(file_get_contents('php://input'), true);\n"
               "echo json_encode(['got' => $in['name'] ?? null]);\n",
    # A semicolon in a string, a comment between, and a comment-only tail:
    # split on ";" this file is three syntax errors.
    "schema.sql": "CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL);\n"
                  "-- the starting games\n"
                  "INSERT INTO games (title) VALUES ('Tom; Jerry');\n"
                  "INSERT INTO games (title) VALUES ('Pong');\n"
                  "/* that's all */\n",
}

SCRIPT = r"""
import { pathToFileURL } from "node:url";
const ROOT = %(root)s;
const { PHP, PHPRequestHandler, setPhpIniEntries } = await import(pathToFileURL(%(universal)s).href);
const { loadNodeRuntime } = await import(pathToFileURL(%(nodephp)s).href);
const { makeCore, sqlStatements } = await import(pathToFileURL(ROOT + "/static/php_core.js").href);
const SITE = %(site)s;
const out = {};
const core = makeCore({ PHP, PHPRequestHandler, setPhpIniEntries,
  load: () => loadNodeRuntime("8.4", { emscriptenOptions: { processId: 1 } }) });
const get = (path, extra) => core.request({ method: "GET", path, ...(extra || {}) });

out.split = sqlStatements(SITE["schema.sql"]);
out.noIndex = await core.run({ files: { "about.php": "<?php echo 1;" } });
out.run = await core.run({ files: SITE });
out.home1 = await get("/");
out.home2 = await get("/");
out.css = await get("/static/style.css");
out.games = await get("/games.php");
out.add = await core.request({ method: "POST", path: "/add.php", form: { title: "Zelda & Link" } });
out.gamesAfter = await get("/games.php");
out.search = await core.request({ method: "GET", path: "search.php", form: { q: "<b>" } });
out.warn = await get("/warn.php");
out.api = await core.request({ method: "POST", path: "/api.php", json: { name: "Ann" } });
out.missing = await get("/nope.php");

// A new Run: a new visitor (no session) and the database as schema.sql says.
out.rerun = await core.run({ files: SITE });
out.homeAgain = await get("/");
out.gamesAgain = await get("/games.php");

// A page deleted from the project is gone on the next Run, not left behind
// in /www answering as if it were still there.
const fewer = { ...SITE };
delete fewer["search.php"];
await core.run({ files: fewer });
out.deleted = await get("/search.php");

out.badSchema = await core.run({ files: { ...SITE, "schema.sql": "CREATE TABLE a (x);\nCREATE TABEL b (y);\n" } });
out.checkOk = await core.check({ files: SITE });
out.checkBad = await core.check({ files: { ...SITE, "add.php": "<?php\n$x = 1\necho $x;\n" } });
out.checkString = await core.check({ files: { "index.php": "<?php echo '<?php not code ?>';" } });
console.log(JSON.stringify(out));
process.exit(0);
"""

work = tempfile.mkdtemp()
try:
    path = os.path.join(work, "core.mjs")
    with open(path, "w") as fh:
        fh.write(SCRIPT % {"root": json.dumps(ROOT), "universal": json.dumps(UNIVERSAL),
                           "nodephp": json.dumps(NODE_PHP), "site": json.dumps(SITE)})
    p = subprocess.run(["node", path], capture_output=True, text=True, timeout=300)
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        print("FAIL the PHP run gave no answer\n" + p.stdout[-2000:] + p.stderr[-2000:])
        sys.exit(1)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("schema.sql")
check("statements split where SQLite would, not at a ; inside a string",
      len(r["split"]) == 3 and "'Tom; Jerry'" in r["split"][1], r["split"])
check("  and a comment-only tail is no statement", not any(s.startswith("/*") for s in r["split"]), r["split"])

print("a run")
check("a site without index.php says so", r["noIndex"]["ok"] is False and "index.php" in r["noIndex"]["error"],
      r["noIndex"])
check("a site runs, listing its pages (index first, includes/ left out)",
      r["run"]["ok"] and r["run"]["pages"][0] == "/index.php" and "/add.php" in r["run"]["pages"]
      and not any(p.startswith("/includes") for p in r["run"]["pages"]), r["run"])
check("  and the tables schema.sql made, with their rows",
      r["run"]["tables"] == [{"name": "games", "rows": 2}], r["run"].get("tables"))

print("pages")
check("/ is index.php, with its include", r["home1"]["status"] == 200 and "<h1>Game Vault</h1>" in r["home1"]["body"]
      and r["home1"]["isText"], r["home1"])
check("a session lasts from one request to the next",
      "visits=1" in r["home1"]["body"] and "visits=2" in r["home2"]["body"], (r["home1"]["body"], r["home2"]["body"]))
check("a static file is served as itself", r["css"]["body"] == SITE["static/style.css"]
      and r["css"]["headers"].get("Content-Type", "").startswith("text/css"), r["css"])
check("a page reads the database through PDO", "<li>Tom; Jerry</li>" in r["games"]["body"]
      and "count=2" in r["games"]["body"], r["games"]["body"])
check("a form POST writes with ? and redirects (Location, spelled as preview.js reads it)",
      r["add"]["status"] == 302 and r["add"]["headers"].get("Location") == "/games.php", r["add"])
check("  and the row is there afterwards, & and all", "<li>Zelda &amp; Link</li>" in r["gamesAfter"]["body"]
      and "count=3" in r["gamesAfter"]["body"], r["gamesAfter"]["body"])
check("a GET form's fields go on the address ($_GET), a path without / too",
      r["search"]["body"] == "q=&lt;b&gt;", r["search"])
check("a JSON body reaches php://input", json.loads(r["api"]["body"]) == {"got": "Ann"}
      and r["api"]["headers"]["Content-Type"].startswith("application/json"), r["api"])
check("a missing page is a 404", r["missing"]["status"] == 404, r["missing"]["status"])

print("errors")
check("a warning is shown in the page, as XAMPP shows it", "Undefined variable $titel" in r["warn"]["body"],
      r["warn"]["body"])
check("  and comes back for the output pane, naming the file without /www/",
      "Undefined variable $titel in warn.php on line 1" in r["warn"]["errors"], r["warn"]["errors"])

print("Run again")
# A new cookie, not only a new count: the session files are deleted too, so
# an old cookie sent again would ALSO count from 1 -- and hide a Run that
# kept the last Run's browser.
check("a new Run is a new visitor: the session starts over, with a new cookie",
      "visits=1" in r["homeAgain"]["body"] and "PHPSESSID=" in r["homeAgain"]["headers"].get("Set-Cookie", ""),
      (r["homeAgain"]["body"], r["homeAgain"]["headers"]))
check("  and the database is schema.sql's again", "count=2" in r["gamesAgain"]["body"]
      and "Zelda" not in r["gamesAgain"]["body"], r["gamesAgain"]["body"])
check("a page deleted from the project is gone on the next Run", r["deleted"]["status"] == 404, r["deleted"])
check("a bad statement in schema.sql is named", r["badSchema"]["ok"] is False
      and "CREATE TABEL b" in (r["badSchema"].get("statement") or "") and "schema.sql" in r["badSchema"]["error"],
      r["badSchema"])

print("the syntax check")
check("a site PHP can read has no syntax card", r["checkOk"] is None, r["checkOk"])
check("a missing ; is found, with its file and line",
      (r["checkBad"] or {}).get("file") == "add.php" and r["checkBad"]["line"] == 3
      and "syntax error" in r["checkBad"]["msg"] and r["checkBad"]["text"] == "echo $x;", r["checkBad"])
check("<?php inside a string is not code", r["checkString"] is None, r["checkString"])

# ------------------------------------------------------------------ php.js
# The page's side, in Node with a stand-in Worker: one that answers like the
# real worker (from php_core.js), and a "/loop.php" that never answers.
PAGE = r"""
import { pathToFileURL } from "node:url";
import fs from "node:fs";
const ROOT = %(root)s;
const { PHP, PHPRequestHandler, setPhpIniEntries } = await import(pathToFileURL(%(universal)s).href);
const { loadNodeRuntime } = await import(pathToFileURL(%(nodephp)s).href);
const { makeCore } = await import(pathToFileURL(ROOT + "/static/php_core.js").href);
let made = 0, ended = 0;
globalThis.window = globalThis;
globalThis.document = { currentScript: { src: "http://site.test/static/php.js" } };
globalThis.Worker = class {
  constructor(url, opts) {
    made += 1; this.url = url; this.opts = opts;
    this.core = makeCore({ PHP, PHPRequestHandler, setPhpIniEntries,
      load: () => loadNodeRuntime("8.4", { emscriptenOptions: { processId: made } }) });
  }
  async postMessage({ id, op, args }) {
    if (op === "request" && args.path === "/loop.php") return;      // stuck forever
    try { const result = await this.core[op](args); this.onmessage({ data: { id, ok: true, result } }); }
    catch (e) { this.onmessage({ data: { id, ok: false, error: String(e) } }); }
  }
  terminate() { ended += 1; }
};
eval(fs.readFileSync(ROOT + "/static/php.js", "utf8"));
const R = window.PhpRuntime;
const out = { said: [] };
R.setOutput((t) => t && out.said.push(t));
out.workerUrl = null;
out.run = await R.run(%(site)s);
out.together = await Promise.all([R.request("GET", "/"), R.request("GET", "/"), R.request("GET", "/")]);
const t0 = Date.now();
out.loop = await R.request("GET", "/loop.php");
out.loopMs = Date.now() - t0;
out.after = await R.request("GET", "/");
out.made = made; out.ended = ended; out.ready = R.isReady();
console.log(JSON.stringify(out));
process.exit(0);
"""
site = dict(SITE, **{"loop.php": "<?php while (true) {}"})
work = tempfile.mkdtemp()
try:
    path = os.path.join(work, "page.mjs")
    src = PAGE % {"root": json.dumps(ROOT), "universal": json.dumps(UNIVERSAL), "nodephp": json.dumps(NODE_PHP),
                  "site": json.dumps(site)}
    # The time limit, shortened for the test: 10 s of waiting proves nothing 1 s doesn't.
    with open(os.path.join(ROOT, "static", "php.js")) as fh:
        assert "const LIMIT_MS = 10000;" in fh.read()
    src = src.replace('eval(fs.readFileSync(ROOT + "/static/php.js", "utf8"));',
                      'eval(fs.readFileSync(ROOT + "/static/php.js", "utf8").replace("const LIMIT_MS = 10000;", "const LIMIT_MS = 1000;"));')
    with open(path, "w") as fh:
        fh.write(src)
    p = subprocess.run(["node", path], capture_output=True, text=True, timeout=300)
    try:
        g = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        print("FAIL php.js gave no answer\n" + p.stdout[-2000:] + p.stderr[-2000:])
        sys.exit(1)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("php.js, the page's side")
check("a run through the worker answers as the core does", g["run"]["ok"] and g["ready"], g["run"])
check("requests made together are answered one after another, each its own",
      ["visits=1" in x["body"] for x in g["together"]] == [True, False, False]
      and "visits=3" in g["together"][2]["body"], [x["body"][-30:] for x in g["together"]])
check("a page that never finishes is stopped at the time limit, saying why",
      g["loop"]["status"] == 500 and "ran for 1 seconds without finishing" in g["loop"]["body"]
      and 900 <= g["loopMs"] < 5000 and any("never ends" in s for s in g["said"]), (g["loop"], g["loopMs"]))
check("  its worker is ended and a new one started", g["ended"] == 1 and g["made"] == 2, (g["made"], g["ended"]))
check("  which runs the site again from the start, and says so",
      g["after"]["status"] == 200 and "visits=1" in g["after"]["body"]
      and any("started again from the beginning" in s for s in g["said"]), (g["after"]["body"][-40:], g["said"]))

print()
print("%d checks, %s" % (count, "all ok" if not failures else "%d FAILED" % failures))
sys.exit(1 if failures else 0)
