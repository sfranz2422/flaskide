"""
Tests in an assignment's notes, for Check my work and Check all.

A ```tests block in the notes is the assignment's tests, one per line:

    GET / -> 200                        the page answers with that status
    GET /nope -> 404
    GET / contains Welcome              the page shows Welcome (case and
                                        spacing ignored; checked against the
                                        page with its tags stripped as well
                                        as the raw HTML)
    POST /login name=sam&pw=1 -> contains Hello, sam
    POST /login name=sam -> 200         a form sent to the route
    uses render_template                code checks over the .py files: a
    avoids eval                         name used, a name nowhere, a def
    defines home
    returns 3 rows                      SQL projects: the last query's rows
    result contains Alice               ... and a value somewhere in them
    # a comment                         ignored

Each is worth 1 point, or "(2 points)" at the end of its line says so.

THE TESTS RUN IN A BROWSER, NEVER ON THE SERVER — the server never runs a
student's code (CLAUDE.md). A student's Check my work runs them in their own
browser and is feedback, and a determined student could fake it; it is kept
only so the teacher can see it. What counts toward the grade is the
teacher's Check all, which runs every turned-in project in the TEACHER's
browser and posts the result from there (app.py, "Tests").

The tests are not secret: the notes go to students whole, so they see what
they will be checked against, which is the point of a visible test.

static/autograde.js reads a block exactly as parse() here does, and runs
it; test_autograde.py holds the two to each other. Same API as PyIDE's
autograde.py, different tests: PyIDE's run a console program.
"""

import re

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
POINTS = re.compile(r"\s*\((\d{1,4}(?:\.\d{1,2})?)\s*points?\)\s*$", re.I)
REQUEST = re.compile(r"^(GET|POST)\s+(/\S*)\s*(.*)$", re.I)
STATUS = re.compile(r"^\d{3}$")
CONTAINS = re.compile(r"^contains\s+(.+)$", re.I)
CODE = re.compile(r"^(uses|avoids|defines)\s+(.+?)\s*$", re.I)
ROWS = re.compile(r"^returns\s+(\d{1,6})\s+rows?$", re.I)
RESULT = re.compile(r"^result\s+contains\s+(.+)$", re.I)

#: How a code check on a Python word reads to a student.
WORDS = {"for": "a for loop", "while": "a while loop", "if": "an if statement",
         "def": "a function", "function": "a function", "return": "return",
         "else": "else", "elif": "elif", "try": "try / except",
         "list": "a list", "dict": "a dictionary", "class": "a class"}


def _blocks(md):
    """The text of every ```tests block, in order."""
    out, lines, i = [], (md or "").split("\n"), 0
    while i < len(lines):
        f = FENCE.match(lines[i])
        if f and f.group(2).strip().lower() == "tests":
            fence, body, i = f.group(1), [], i + 1
            while i < len(lines):
                g = FENCE.match(lines[i])
                if g and g.group(1)[0] == fence[0] and len(g.group(1)) >= len(fence) \
                        and not g.group(2).strip():
                    break
                body.append(lines[i])
                i += 1
            out.append("\n".join(body))
        i += 1
    return out


def _label(t):
    k = t["kind"]
    if k == "request":
        said = "%s %s" % (t["method"], t["path"])
        if t["form"]:
            said += " with " + t["form"]
        if t["status"] is not None:
            return said + " answers " + str(t["status"])
        return said + " shows " + t["expect"]
    if k == "rows":
        return "The query returns %d row%s" % (t["count"], "" if t["count"] == 1 else "s")
    if k == "result":
        return "The query's result contains " + t["expect"]
    if k == "defines":
        return "Defines %s()" % t["name"]
    word = WORDS.get(t["name"].lower(), t["name"])
    return ("Uses " if k == "uses" else "Doesn't use ") + word


def _request(line):
    """A GET or POST line as a test, or None when it isn't one."""
    m = REQUEST.match(line)
    if not m:
        return None
    rest, form = m.group(3).strip(), ""
    if rest.startswith("->"):
        rest = rest[2:].strip()
    elif not CONTAINS.match(rest):
        # A form first: name=sam&pw=1, one word, then the expectation.
        parts = rest.split(None, 1)
        if len(parts) < 2 or "=" not in parts[0]:
            return None
        form, rest = parts[0], parts[1].strip()
        if rest.startswith("->"):
            rest = rest[2:].strip()
    t = {"kind": "request", "method": m.group(1).upper(), "path": m.group(2),
         "form": form, "status": None, "expect": ""}
    c = CONTAINS.match(rest)
    if STATUS.match(rest):
        t["status"] = int(rest)
    elif c:
        t["expect"] = c.group(1).strip()
    else:
        return None
    return t


def parse_block(body):
    """(tests, errors) for one block's text. An error is a line the teacher
    wrote that isn't a test — said, not skipped, or a typo silently becomes
    a test nobody can fail."""
    tests, errors = [], []
    for n, raw in enumerate((body or "").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        points = 1.0
        m = POINTS.search(line)
        if m:
            points = float(m.group(1))
            line = line[:m.start()].rstrip()
        t = _request(line)
        if t is None:
            m = ROWS.match(line)
            if m:
                t = {"kind": "rows", "count": int(m.group(1))}
        if t is None:
            m = RESULT.match(line)
            if m:
                t = {"kind": "result", "expect": m.group(1).strip()}
        if t is None:
            m = CODE.match(line)
            if m:
                name = m.group(2).strip()
                if name.endswith("()"):
                    name = name[:-2]
                t = {"kind": m.group(1).lower(), "name": name}
        if t is None:
            errors.append("Line %d of the tests isn't a test: %s" % (n, line))
            continue
        t["points"] = points
        t["label"] = _label(t)
        tests.append(t)
    return tests, errors


def parse(md):
    """Every test in a notes file, and every line that isn't one."""
    tests, errors = [], []
    for body in _blocks(md):
        got, bad = parse_block(body)
        tests += got
        errors += bad
    return tests, errors


def file_tests(files):
    """The tests in an assignment's notes (every .md), and the errors."""
    tests, errors = [], []
    for name in sorted(files or {}):
        if name.lower().endswith(".md") and isinstance(files[name], str):
            got, bad = parse(files[name])
            tests += got
            errors += bad
    return tests, errors


def possible(files):
    return round(sum(t["points"] for t in file_tests(files)[0]), 2)
