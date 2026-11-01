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

# A beginner's PHP mistakes, and a few words each card must say about it.
# Each is made in real PHP, so a PHP upgrade that rewords its message makes
# that card fall back to "PHP can't read line 3" -- and fails here.
MISTAKES = {
    "no ;": ("<?php\n$x = 1\necho $x;\n", ["line before line 3", "`$x = 1;`"]),
    "no }": ("<?php\nif ($x) {\n  echo 1;\n", ["missing a closing `}`", "line 2"]),
    "extra }": ("<?php\necho 1;\n}\n", ["extra `}`", "line 3"]),
    "no $": ("<?php\nname = 'Ann';\n", ["`$name`"]),
    "no .": ("<?php\necho 'Hi ' $name;\n", ["put a `.` between them"]),
    "open quote": ("<?php\necho 'Hi;\n", ["never closed"]),
    "no )": ("<?php\nif ($x > 1 {\n echo 1;\n}\n", ["a `(` is never closed"]),
    "array": ("<?php\n$a = ['x' => 1, 'y' 2];\n", ["missing in the array"]),
    "foreach in": ("<?php\nforeach ($pets in $p) { echo $p; }\n", ["with `as`"]),
    "no endforeach": ("<?php foreach ($p as $x): ?>\n<li></li>\n", ["end of index.php", "endforeach"]),
    "keyword": ("<?php\nfunction list() {}\n", ["`list`", "keeps for itself"]),
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

// The syntax card's words (syntax.js), for each mistake as real PHP reports it.
globalThis.window = globalThis;
(0, eval)((await import("node:fs")).readFileSync(ROOT + "/static/syntax.js", "utf8"));
out.cards = {};
for (const [k, code] of Object.entries(%(mistakes)s)) {
  const info = await core.check({ files: { "index.php": code } });
  out.cards[k] = info ? window.FlaskIDESyntax.explain(info) : null;
}
console.log(JSON.stringify(out));
process.exit(0);
"""

work = tempfile.mkdtemp()
try:
    path = os.path.join(work, "core.mjs")
    with open(path, "w") as fh:
        fh.write(SCRIPT % {"root": json.dumps(ROOT), "universal": json.dumps(UNIVERSAL),
                           "nodephp": json.dumps(NODE_PHP), "site": json.dumps(SITE),
                           "mistakes": json.dumps({k: v[0] for k, v in MISTAKES.items()})})
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
check("a warning is shown in the page, as XAMPP shows it, naming warn.php (not /www/warn.php)",
      "Undefined variable $titel" in r["warn"]["body"] and "in <b>warn.php</b>" in r["warn"]["body"],
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

print("the syntax card's words")
for name, (code, words) in MISTAKES.items():
    card = r["cards"].get(name) or {}
    check("%s: %s" % (name, card.get("friendly", "")[:70]),
          card.get("known") and card.get("lang") == "PHP" and all(w in card["friendly"] for w in words),
          card)

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
    // stuck forever: what a real worker does, which here would hang Node
    if (op === "request" && args.path === "/loop.php") return;
    if (op === "checkRequest" && args.test.path === "/loop.php") return;
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

// Check my work on a PHP site: the notes' tests, read by autograde.js and
// handed by PyIDETests.run to PhpRuntime.autograde, run in real PHP.
(0, eval)(fs.readFileSync(ROOT + "/static/autograde.js", "utf8"));
const T = window.PyIDETests.parse(%(tests_md)s).tests;
out.labels = T.map((t) => t.label);
out.grade = await window.PyIDETests.run(R, %(graded)s, T);
out.unreadable = await window.PyIDETests.run(R, Object.assign({}, %(graded)s, { "lib.php": "<?php\nfunction f( {\n" }), T.slice(0, 3));
console.log(JSON.stringify(out));
process.exit(0);
"""
site = dict(SITE, **{"loop.php": "<?php while (true) {}"})
GRADED = dict(site, **{
    "login.php": "<?php session_start();\n$_SESSION['user'] = $_POST['user'];\nheader('Location: members.php');\n",
    "members.php": "<?php session_start();\necho 'Hello ' . htmlspecialchars($_SESSION['user'] ?? 'nobody');\n",
    # Words that must NOT count: in a comment, in a string, in the HTML --
    # the string's and the HTML's tokens are EXACTLY the word ("{$title}switch"
    # splits into $title and "switch"; the page ends in the bare word eval),
    # so only the tokenizer's types keep them out, not a text match.
    "lib.php": "<?php\n// mysqli_connect is not used here\nfunction add_game($db, $title) {\n"
               "  $s = $db->PREPARE('INSERT INTO games (title) VALUES (?)');\n  echo \"{$title}switch\";\n}\n?>\neval",
})
TESTS_MD = """```tests
GET / -> 200
GET / contains Game Vault
GET /nope.php -> 404
GET /missing.php -> 200
POST /add.php title=Mario -> 302                 (2 points)
POST /add.php title=Luigi -> contains Luigi
GET /games.php contains Mario
POST /login.php user=sam -> contains Hello sam
GET /members.php contains sam
GET /search.php q=<b> contains q=<b>
GET /loop.php contains x
GET / -> 200
uses foreach
uses $_SESSION
uses $_session
uses HTMLSPECIALCHARS
avoids eval
uses mysqli_connect
uses switch
defines add_game
defines remove_game
returns 2 rows
```"""
work = tempfile.mkdtemp()
try:
    path = os.path.join(work, "page.mjs")
    src = PAGE % {"root": json.dumps(ROOT), "universal": json.dumps(UNIVERSAL), "nodephp": json.dumps(NODE_PHP),
                  "site": json.dumps(site), "graded": json.dumps(GRADED), "tests_md": json.dumps(TESTS_MD)}
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

print("Check my work on a PHP site")
G = g["grade"]["results"]
def res(n):
    return G[n] if n < len(G) else {}
check("every test is checked, in the notes' own words", len(G) == 22 and G[0]["label"] == g["labels"][0], g["labels"])
check("a page that answers 200 passes, and its words are found", res(0)["ok"] and res(1)["ok"], (res(0), res(1)))
check("a missing page is a 404, and a test wanting 200 says which page to make",
      res(2)["ok"] and not res(3)["ok"] and res(3)["detail"] == "It answered 404. Is there a page called /missing.php?", res(3))
check("a POST's redirect is seen by a status test", res(4)["ok"], res(4))
check("  and followed by a test of what it shows", res(5)["ok"], res(5))
check("what one test saved is there for the next (one site per check)", res(6)["ok"], res(6))
check("a log-in in one test is still logged in for the next (one browser per check)",
      res(7)["ok"] and res(8)["ok"], (res(7), res(8)))
check("a page's text is read as a visitor reads it (&lt; undone)", res(9)["ok"], res(9))
check("a page that never finishes fails its own test, saying why",
      not res(10)["ok"] and "Still running after 1 seconds" in res(10)["detail"], res(10))
check("  and the tests after it still run, on the site started again", res(11)["ok"], res(11))
check("uses: a keyword, a $variable, a function name in any case",
      res(12)["ok"] and res(13)["ok"] and res(15)["ok"], (res(12), res(13), res(15)))
check("  a $variable only as spelled ($_session is not $_SESSION)", not res(14)["ok"], res(14))
check("words in a comment, a string or the HTML don't count",
      res(16)["ok"] and not res(17)["ok"] and not res(18)["ok"], (res(16), res(17), res(18)))
check("defines: a function by that name", res(19)["ok"] and not res(20)["ok"]
      and "no function remove_game" in res(20)["detail"], (res(19), res(20)))
check("a SQL project's test says a PHP site has no query.sql", not res(21)["ok"] and "query.sql" in res(21)["detail"], res(21))
check("points add up from the tests that passed (Mario's POST is 2)",
      g["grade"]["possible"] == 23 and g["grade"]["earned"] == sum(r["points"] for r in G if r["ok"])
      and res(4)["points"] == 2, g["grade"])
_ta = open(os.path.join(ROOT, "templates", "teacher_assignment.html")).read()
check("the teacher's Check all checks each PHP site in PHP, decided by its own files",
      'var rt = isPhp(work[i].files) ? await phpRuntime() : await python();' in _ta
      and 'return "index.php" in files && !("app.py" in files) && !("query.sql" in files);' in _ta
      and "window.PyIDETests.run(rt, work[i].files, tests)" in _ta)
U = g["unreadable"]["results"]
check("PHP that can't be read fails every test, saying where",
      len(U) == 3 and not any(r["ok"] for r in U) and all("lib.php can't be read: line 2" in r["detail"] for r in U), U)

print()
print("%d checks, %s" % (count, "all ok" if not failures else "%d FAILED" % failures))
sys.exit(1 if failures else 0)
