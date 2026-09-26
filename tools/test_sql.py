#!/usr/bin/env python3
"""SQL mode, run against real SQLite.

    python3 tools/test_sql.py

WHAT THIS ACTUALLY RUNS

Not the source of static/flask.js. The Python that does the work lives inside
a JavaScript template literal, and JavaScript eats one level of escaping on
the way through: `\\*` in the file arrives at Python as `\*`. So this file
extracts the bridge the way the browser receives it -- template literal
unescaped, ${PROJECT} substituted -- and executes THAT.

That is not pedantry. The comment-stripping regex was written with single
backslashes first, and what reached Python was `/*.*?*/`:

    re.error: multiple repeat at position 5

raised at import, on the first Run, before a student had typed anything. A
test reading the .js file as if it were Python would have passed.

THE FOUR THINGS THAT GO WRONG HERE AND LOOK FINE

  * Foreign keys off. SQLite ignores REFERENCES unless every connection asks,
    so a course taught by teacher 4242 is stored and reported as a success.
    The schema looks right, the insert looks right, and the data is nonsense.

  * A statement split on the wrong semicolon. `SELECT 'a ; b'` is one
    statement; splitting on `;` makes two, and both are syntax errors on a
    file that is perfectly valid.

  * A query that returns everything. A join written the wrong way round asks
    for tens of thousands of rows, and a browser handed that many table cells
    stops responding -- which a student reads as the editor crashing.

  * NULL rendered as an empty cell. The LEFT JOIN lesson IS the row with
    nothing on one side. If NULL and '' look the same, the lesson is invisible.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
import types

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLES = ROOT / "examples"

results = []


def check(label, ok, detail=""):
    """Detail prints only on a failure -- on a pass it argues the opposite."""
    results.append(bool(ok))
    print("  %-4s %-58s %s" % ("ok" if ok else "FAIL", label,
                               "" if ok else detail))


def done():
    bad = results.count(False)
    print("\n%s (%d checks, %d failed)"
          % ("SOME FAILED" if bad else "ALL PASSED", len(results), bad))
    sys.exit(1 if bad else 0)


# ------------------------------------------------- the bridge, as JS hands it

def unescape_template_literal(text):
    """What a JavaScript template literal evaluates to.

    \\n is a newline, \\\\ is one backslash, and \\X for anything else is just
    X -- which is the rule that silently ate the regex.
    """
    out, i = [], 0
    simple = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "`": "`", "$": "$"}
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            out.append(simple.get(text[i + 1], text[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_bridge(project_dir):
    source = (ROOT / "static" / "flask.js").read_text()
    match = re.search(r"const BRIDGE = `([\s\S]*?)\n`;", source)
    if not match:
        sys.exit("No BRIDGE template literal in static/flask.js.")
    code = unescape_template_literal(match.group(1)).replace(
        "${PROJECT}", project_dir)
    module = types.ModuleType("bridge")
    exec(compile(code, "flask.js:BRIDGE", "exec"), module.__dict__)
    return module


project = tempfile.mkdtemp(prefix="flaskide-test-")
bridge = load_bridge(project)
check("the bridge imports the way the browser receives it", True)

SCHEMA = (EXAMPLES / "schema.sql").read_text()
QUERY = (EXAMPLES / "query.sql").read_text()


def run(files):
    return json.loads(bridge._flaskide_run_sql(json.dumps(files)))


# ============================================================ the starter runs
out = run({"schema.sql": SCHEMA, "query.sql": QUERY})
check("the starter project runs", out["ok"], out.get("error", ""))

tables = {t["name"]: t["rows"] for t in out.get("tables", [])}
check("  and builds all four tables",
      sorted(tables) == ["courses", "enrollments", "students", "teachers"],
      str(sorted(tables)))
check("  with rows in them", all(n > 0 for n in tables.values()), str(tables))

check("  and every statement in it returns something",
      len(out["results"]) >= 5, "%d results" % len(out["results"]))
check("  all of them SELECTs, so the starter shows tables not counts",
      all("columns" in r for r in out["results"]),
      str([r for r in out["results"] if "columns" not in r][:1]))

# The trailing "-- Your turn" comment is not a statement. Executed, it adds an
# empty result table under the real ones with "-1 changed" beside it.
check("  and a trailing comment is not counted as one",
      not any(r.get("changed") == -1 for r in out["results"]))

# ========================================== the dataset teaches what it claims
#
# The starter's comments make specific promises about what these queries show.
# A dataset edited later could quietly stop keeping them -- remove the one
# teacher with no courses and the LEFT JOIN lesson has nothing to point at.
def rows_of(sql):
    got = run({"schema.sql": SCHEMA, "query.sql": sql})
    if not got["ok"]:
        return None, got["error"]
    return got["results"][0]["rows"], None


inner, err = rows_of("SELECT t.id FROM teachers t "
                     "JOIN courses c ON c.teacher_id = t.id;")
outer, err2 = rows_of("SELECT t.id FROM teachers t "
                      "LEFT JOIN courses c ON c.teacher_id = t.id;")
check("JOIN and LEFT JOIN give different answers",
      inner is not None and outer is not None and len(outer) > len(inner),
      "%s vs %s" % (len(inner or []), len(outer or [])))

lonely, _ = rows_of("SELECT t.name FROM teachers t "
                    "LEFT JOIN courses c ON c.teacher_id = t.id "
                    "WHERE c.id IS NULL;")
check("  because exactly one teacher has no courses",
      lonely is not None and len(lonely) == 1, str(lonely))

many, _ = rows_of("SELECT teacher_id, COUNT(*) c FROM courses "
                  "GROUP BY teacher_id HAVING c > 1;")
check("  and some teachers have several, so it is a one-to-many",
      many is not None and len(many) >= 2, str(many))

both, _ = rows_of("SELECT student_id FROM enrollments GROUP BY student_id "
                  "HAVING COUNT(*) > 1;")
check("  and students take several courses, so enrollments is many-to-many",
      both is not None and len(both) >= 3, "%d students" % len(both or []))

nulls, _ = rows_of("SELECT t.name, c.title FROM teachers t "
                   "LEFT JOIN courses c ON c.teacher_id = t.id "
                   "WHERE c.title IS NULL;")
check("  and the LEFT JOIN really produces a NULL for the grid to show",
      nulls is not None and nulls and nulls[0][1] is None, str(nulls))

# ====================================================== foreign keys are ON
bad = run({"schema.sql": SCHEMA, "query.sql":
           "INSERT INTO courses (id, title, period, teacher_id) "
           "VALUES (99, 'Ghost', 9, 4242);"})
check("a row pointing at a teacher who does not exist is REJECTED",
      not bad["ok"] and "FOREIGN KEY" in bad.get("error", ""),
      "it was accepted -- PRAGMA foreign_keys is not on")

good = run({"schema.sql": SCHEMA, "query.sql":
            "INSERT INTO courses (id, title, period, teacher_id) "
            "VALUES (99, 'Real', 9, 1); SELECT COUNT(*) FROM courses;"})
check("  and a row pointing at one that does exist is accepted",
      good["ok"] and good["results"][-1]["rows"][0][0] == 9,
      good.get("error", ""))

# ================================================= statements are split right
stmts = bridge._flaskide_sql_statements(
    "-- a note with ; in it\n"
    "/* and a block ; comment */\n"
    "SELECT 'a ; b' AS tricky;\n"
    "SELECT 1;\n"
    "-- trailing\n")
check("a semicolon inside a string or comment does not split a statement",
      len(stmts) == 2, "%d statements: %s" % (len(stmts), stmts))

quoted = run({"schema.sql": SCHEMA, "query.sql": "SELECT 'a ; b' AS t;"})
check("  and such a statement actually runs",
      quoted["ok"] and quoted["results"][0]["rows"][0][0] == "a ; b",
      quoted.get("error", ""))

# TWO STATEMENTS ON ONE LINE. The first splitter accumulated whole LINES and
# cut when the buffer became complete, so `SELECT 1; SELECT 2;` arrived as a
# single chunk and SQLite answered "You can only execute one statement at a
# time" -- which names nothing a student could act on, on a line that is
# perfectly ordinary SQL.
for text, want in [("SELECT 1; SELECT 2;", 2),
                   ("SELECT 1;SELECT 2;SELECT 3;", 3),
                   ("SELECT 'a;b'; SELECT 2;", 2),
                   ("/* x; */ SELECT 1; -- y;\nSELECT 2;", 2)]:
    got = bridge._flaskide_sql_statements(text)
    check("  %r splits into %d" % (text, want), len(got) == want,
          "%d: %s" % (len(got), got))

pair = run({"schema.sql": SCHEMA, "query.sql":
            "SELECT COUNT(*) FROM teachers; SELECT COUNT(*) FROM courses;"})
check("  and two statements on one line both run",
      pair["ok"] and [r["rows"][0][0] for r in pair["results"]] == [6, 8],
      pair.get("error", ""))

check("a chunk of only comments is not a statement",
      not bridge._flaskide_sql_has_code("-- hi\n/* there */\n;\n"))
check("  but one with a query in it is",
      bridge._flaskide_sql_has_code("-- hi\nSELECT 1;"))

# ======================================================= a runaway is clipped
huge = run({"schema.sql": SCHEMA, "query.sql":
            "SELECT a.grade FROM enrollments a, enrollments b, enrollments c;"})
first = huge["results"][0]
check("a query asking for 21,952 rows is clipped, not handed to the browser",
      huge["ok"] and len(first["rows"]) == bridge._FLASKIDE_MAX_ROWS,
      "%d rows came back" % len(first["rows"]))
check("  and says so, rather than silently showing the wrong answer",
      first["clipped"] is True)
check("  while a small query is not marked clipped",
      run({"schema.sql": SCHEMA,
           "query.sql": "SELECT * FROM teachers;"})["results"][0]["clipped"]
      is False)

# ================================================== errors name the statement
broken = run({"schema.sql": SCHEMA, "query.sql":
              "SELECT * FROM teachers;\nSELECT name FORM courses;\n"
              "SELECT 1;"})
check("a broken statement fails the run", not broken["ok"])
check("  and the error names which statement it was",
      "FORM" in broken.get("statement", ""), repr(broken.get("statement")))
check("  while the statements that already ran are kept",
      len(broken.get("results", [])) == 1,
      "%d kept" % len(broken.get("results", [])))
check("  and the statements after it are not run",
      len(broken.get("results", [])) < 3)

wrecked = run({"schema.sql": "CREATE TABLE oops (;", "query.sql": "SELECT 1;"})
check("a broken schema blames schema.sql by name",
      not wrecked["ok"] and wrecked["error"].startswith("schema.sql:"),
      wrecked.get("error", ""))

# ================================================== the missing-file messages
check("no schema.sql says so in a sentence",
      run({"query.sql": "SELECT 1;"})["error"].startswith("There is no schema.sql"))
check("no query.sql says so in a sentence",
      run({"schema.sql": SCHEMA})["error"].startswith("There is no query.sql"))

# ============================================ a Flask app reads the same data
#
# This is the whole reason SQL lives in THIS editor rather than a separate
# one: learn the query on its own, then put a page in front of it.
APP = '''
import sqlite3
from flask import Flask, jsonify
app = Flask(__name__)

@app.route("/teachers")
def teachers():
    con = sqlite3.connect("data.db")
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT t.name, COUNT(c.id) AS n FROM teachers t "
        "LEFT JOIN courses c ON c.teacher_id = t.id "
        "GROUP BY t.id ORDER BY n DESC, t.name").fetchall()
    con.close()
    return jsonify([[r["name"], r["n"]] for r in rows])
'''
loaded = json.loads(bridge._flaskide_load(
    json.dumps({"app.py": APP, "schema.sql": SCHEMA})))
check("a Flask project with a schema.sql still loads", loaded["ok"],
      loaded.get("error", ""))
check("  and the editor is told what tables it built",
      len(loaded.get("tables", [])) == 4, str(loaded.get("tables")))

answer = json.loads(bridge._flaskide_request(json.dumps(
    {"method": "GET", "path": "/teachers", "form": {}, "headers": {}})))
check("  and a route can query the database sqlite3-style",
      answer.get("status") == 200, str(answer.get("status")))
if answer.get("status") == 200:
    payload = json.loads(answer["body"])
    check("    getting the same answer the SQL project gets",
          payload[0][1] == 2 and payload[-1][1] == 0, str(payload))

# A Flask project WITHOUT a schema.sql must not become an error. Most of them
# have no database and never will.
plain = json.loads(bridge._flaskide_load(json.dumps(
    {"app.py": "from flask import Flask\napp = Flask(__name__)\n"})))
check("a Flask project with no schema.sql is not an error", plain["ok"],
      plain.get("error", ""))
check("  and reports no tables", plain.get("tables") == [],
      str(plain.get("tables")))

# ===================================== the database is rebuilt, never carried
#
# The promise made in the starter's first comment: press Run and it is back.
run({"schema.sql": SCHEMA, "query.sql":
     "INSERT INTO teachers (id, name, department) "
     "VALUES (77, 'Ghost', 'Nowhere');"})
after = run({"schema.sql": SCHEMA,
             "query.sql": "SELECT COUNT(*) FROM teachers;"})
# WITHOUT THE DROP STATEMENTS TOO.
#
# The check below passes for a reason that has nothing to do with the file
# being fresh: the shipped schema.sql opens with DROP TABLE IF EXISTS, so the
# tables are emptied even if data.db survives. A student editing that file
# will very reasonably delete those lines -- to a beginner they are noise at
# the top -- and the promise has to survive it.
#
# THREE THINGS KEEP THE PROMISE and any one of them is enough: the DROPs, the
# rmtree in _flaskide_clear(), and the os.remove in _flaskide_build_db(). This
# checks the PROMISE rather than any one of them, so it stays true while they
# are rearranged and fails only when the last one goes. Verified by removing
# them: one at a time, this passes; all three, it fails with "table teachers
# already exists".
NO_DROPS = "\n".join(line for line in SCHEMA.splitlines()
                     if not line.upper().startswith("DROP TABLE"))
check("  (the no-DROP schema really has none)",
      "DROP TABLE" not in NO_DROPS.upper())

run({"schema.sql": NO_DROPS, "query.sql":
     "INSERT INTO teachers (id, name, department) "
     "VALUES (78, 'Ghost', 'Nowhere');"})
again = run({"schema.sql": NO_DROPS,
             "query.sql": "SELECT COUNT(*) FROM teachers;"})
check("a schema with no DROP statements still starts clean",
      again["ok"] and again["results"][0]["rows"][0][0] == 6,
      again.get("error")
      or "%d teachers -- data.db was not deleted, so a student who removes "
         "the DROP lines keeps their mistakes forever"
         % again["results"][0]["rows"][0][0])

check("a row inserted on one Run is gone by the next",
      after["results"][0]["rows"][0][0] == 6,
      "%d teachers -- the database survived, and the starter says it will not"
      % after["results"][0]["rows"][0][0])

done()
