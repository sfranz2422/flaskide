#!/usr/bin/env python3
"""Pictures in a teacher's notes: a lesson's, and an assignment's in the editor.

    python3 tools/test_pictures.py

WHAT IS BEING GUARDED

  A teacher can put a picture in their notes without leaving the page.
      Add picture on the lesson page and on the editor's notes; paste and
      drop as well. The upload is /api/image, the same as a description's
      (test_classes.py holds that route to who may use it and what it takes).

  Nobody else is offered it.
      The route refuses a student whatever the page shows, but a button
      that can only ever fail is worse than none — and a student authoring
      their own project's notes is "authoring" too.

  The picture lands where the cursor was when it started.
      pictures.js is run in node against a stand-in CodeMirror doc. The
      teacher keeps typing during an upload; inserting at the cursor as it
      is when the upload finishes put the picture inside the next sentence.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "pictures.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


def add_user(sub, email, name):
    db = P.SessionLocal()
    try:
        user = accounts.User(google_sub=sub, email=email, name=name)
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def client(uid=None):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


teacher = client(add_user("t", "teacher@school.org", "Teacher"))
kid = client(add_user("k", "kid@school.org", "Kid"))
stranger = client()

PICS = '<script src="/static/pictures.js"></script>'

# ------------------------------------------------------------- the pages
print("\nThe lesson page")
lesson = teacher.post("/api/lesson", json={"title": "Pictures"}).get_json()["slug"]
page = teacher.get("/teacher/%s/lesson" % lesson).get_data(as_text=True)
check("has Add picture beside the notes", 'id="lesson-pic"' in page)
check("  and loads pictures.js before lesson_teacher.js, which uses it",
      PICS in page and page.index(PICS) < page.index('src="/static/lesson_teacher.js"'))
js = open(os.path.join(PYIDE, "static", "lesson_teacher.js")).read()
check("  its button opens the picker and writes into the notes",
      re.search(r'\$\("lesson-pic"\)\.addEventListener\("click", function \(\) \{\s*'
                r'window\.FlaskIDEPictures\.choose\(function \(files\) \{\s*'
                r'window\.FlaskIDEPictures\.insertInto\(editor\.getDoc\(\), files\);', js) is not None)
check("  and paste and drop go to the notes editor",
      "window.FlaskIDEPictures.attach(editor);" in js)

print("\nThe editor's notes")
hw = teacher.post("/api/assignment", json={"title": "Pics", "files": {"app.py": "from flask import Flask\n",
                                                                 "notes.md": "# Hi\n"}}).get_json()["slug"]
page = teacher.get("/teacher/%s/edit" % hw).get_data(as_text=True)
check("a teacher editing an assignment has Add picture", 'id="notes-pic"' in page)
check("  and pictures.js, before app.js", PICS in page and page.index(PICS) < page.index('src="/static/app.js"'))
page = teacher.get("/new").get_data(as_text=True)
check("  and in a new project of their own", 'id="notes-pic"' in page)
check("a student's own new project has none: the upload would refuse them",
      'id="notes-pic"' not in kid.get("/new").get_data(as_text=True))
check("  nor anyone signed out", 'id="notes-pic"' not in stranger.get("/new").get_data(as_text=True))
r = kid.get("/a/" + hw, follow_redirects=True).get_data(as_text=True)
check("  nor a student on the assignment", 'id="notes-pic"' not in r and "notes.md" in r)
js = open(os.path.join(PYIDE, "static", "app.js")).read()
check("paste and drop only while the .md source is open — the same editor holds app.py",
      re.search(r"window\.FlaskIDEPictures\.attach\(editor, function \(\) \{\s*"
                r"return mdSource && notesShown === current;", js) is not None)
check("  and a picker answered after Done writes nothing",
      re.search(r"FlaskIDEPictures\.choose\(function \(files\) \{\s*"
                r"if \(!\(mdSource && notesShown === current\)\) return;", js) is not None)

print("\nClass descriptions still use it")
desc = open(os.path.join(PYIDE, "templates", "_describe.html")).read()
check("_describe.html uploads through pictures.js",
      "pictures.js" in desc and "window.FlaskIDEPictures.upload(file).then(onSuccess" in desc)
check("  and nothing else posts to /api/image",
      'fetch("/api/image"' not in desc and 'fetch("/api/image"' not in js)

# ------------------------------------------------------- pictures.js, run
print("\npictures.js, run in node")
if not shutil.which("node"):
    check("node is available to run pictures.js", False, "brew install node")
    print("\n%d/%d passed" % (sum(results), len(results)))
    sys.exit(1)

SRC = open(os.path.join(PYIDE, "static", "pictures.js")).read()

# A stand-in for a CodeMirror 5 Doc: lines of text, a cursor, and bookmarks
# that move as text is inserted before them — the one behaviour the
# insertion depends on. fetch answers with an address after a tick, and the
# "typing" happens in that gap.
HARNESS = r"""
global.window = global;
function Doc(text) { this.lines = text.split("\n"); this.cur = {line: 0, ch: 0}; this.marks = []; }
Doc.prototype.getValue = function () { return this.lines.join("\n"); };
Doc.prototype.getLine = function (n) { return this.lines[n]; };
Doc.prototype.getCursor = function () { return {line: this.cur.line, ch: this.cur.ch}; };
Doc.prototype.idx = function (p) {
  var n = 0; for (var i = 0; i < p.line; i++) n += this.lines[i].length + 1; return n + p.ch; };
Doc.prototype.pos = function (n) {
  for (var i = 0; ; i++) { if (n <= this.lines[i].length) return {line: i, ch: n}; n -= this.lines[i].length + 1; } };
Doc.prototype.setBookmark = function (p) {
  var self = this, m = {at: this.idx(p), live: true,
    find: function () { return m.live ? self.pos(m.at) : undefined; },
    clear: function () { m.live = false; }};
  this.marks.push(m); return m; };
Doc.prototype.replaceRange = function (text, p) {
  var at = this.idx(p), v = this.getValue();
  this.marks.forEach(function (m) { if (m.at > at) m.at += text.length; });
  this.lines = (v.slice(0, at) + text + v.slice(at)).split("\n"); };
global.FormData = function () { this.append = function () {}; };
var answer = {ok: true, status: 200, body: {ok: true, url: "/img/abc123"}};
global.fetch = function () {
  return new Promise(function (r) { setTimeout(function () {
    r({ok: answer.ok, json: function () { return Promise.resolve(answer.body); }}); }, 5); }); };
var alerts = []; global.alert = function (m) { alerts.push(m); };
""" + SRC + r"""
var Pics = window.FlaskIDEPictures, out = {};
function file(name, type) { return {name: name, type: type || "image/png", size: 10}; }
function later(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
(async function () {
  out.md = Pics.markdown(file("cat photo.jpg"), "/img/x");
  out.mdPasted = Pics.markdown(file("image.png"), "/img/x");

  // Cursor at the end of "Look:", then the teacher types a line under it
  // while the picture uploads.
  var d = new Doc("# Title\nLook:");
  d.cur = {line: 1, ch: 5};
  Pics.insertInto(d, [file("cat.png")]);
  d.replaceRange("\nmore words", {line: 1, ch: 5});
  d.cur = {line: 2, ch: 10};          // typing carries the cursor with it
  await later(30);
  out.typed = d.getValue();

  // Mid-line: the picture gets a line of its own.
  d = new Doc("before after");
  d.cur = {line: 0, ch: 7};
  Pics.insertInto(d, [file("x.png")]);
  await later(30);
  out.midline = d.getValue();

  // The notes reloaded mid-upload (FlaskIDE swaps files with setValue,
  // which clears bookmarks): nothing is written into whatever is open now;
  // the markdown is handed over instead.
  var prompts = []; global.prompt = function (m, v) { prompts.push(v); };
  d = new Doc("print(1)");
  Pics.insertInto(d, [file("lost.png")]);
  d.marks.forEach(function (m) { m.live = false; });
  await later(30);
  out.lost = {text: d.getValue(), prompts: prompts};

  // Refused: nothing written, the server's words shown.
  answer = {ok: false, body: {error: "That picture is too big (4 MB at most)."}};
  d = new Doc("keep");
  Pics.insertInto(d, [file("big.png")]);
  await later(30);
  out.refused = {text: d.getValue(), alerts: alerts.slice()};

  // Paste: a picture is taken, text is left to CodeMirror, and so is
  // anything while wanted() says no.
  answer = {ok: true, body: {ok: true, url: "/img/p"}};
  var handlers = {}, prevented = [];
  var cm = {doc: new Doc(""), on: function (n, f) { handlers[n] = f; },
            getDoc: function () { return this.doc; },
            coordsChar: function () { return {line: 0, ch: 0}; }};
  var want = true;
  Pics.attach(cm, function () { return want; });
  function ev(files) { return {clipboardData: {files: files}, dataTransfer: {files: files},
                               preventDefault: function () { prevented.push(true); }}; }
  handlers.paste(cm, ev([{name: "notes.txt", type: "text/plain"}]));
  out.textPrevented = prevented.length;
  want = false;
  handlers.paste(cm, ev([file("image.png")]));
  out.unwantedPrevented = prevented.length;
  want = true;
  handlers.drop(cm, ev([file("drop.gif", "image/gif")]));
  await later(30);
  out.dropped = {prevented: prevented.length, text: cm.doc.getValue()};
  console.log(JSON.stringify(out));
})();
"""

proc = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True)
try:
    got = json.loads(proc.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    got = {}
    check("pictures.js runs", False, proc.stderr[-400:])

check("the markdown is ![name](address), named after the file",
      got.get("md") == "![cat photo](/img/x)", got.get("md"))
check("  a pasted screenshot's 'image' is no name",
      got.get("mdPasted") == "![](/img/x)", got.get("mdPasted"))
check("a picture goes where the cursor was, not where typing moved it",
      got.get("typed") == "# Title\nLook:\n![cat](/img/abc123)\nmore words", repr(got.get("typed")))
check("  on a line of its own when dropped mid-line",
      got.get("midline") == "before \n![x](/img/abc123)\nafter", repr(got.get("midline")))
check("a picture whose place was reloaded away is handed over, not written into code",
      got.get("lost") == {"text": "print(1)", "prompts": ["![lost](/img/abc123)"]}, got.get("lost"))
check("a refused picture writes nothing and says why",
      got.get("refused") == {"text": "keep", "alerts": ["That picture is too big (4 MB at most)."]},
      got.get("refused"))
check("pasted text is left to the editor", got.get("textPrevented") == 0)
check("  and a picture too, while the source isn't open", got.get("unwantedPrevented") == 0)
check("a dropped picture is uploaded and written in",
      got.get("dropped") == {"prevented": 1, "text": "![drop](/img/p)"}, got.get("dropped"))

failed = len(results) - sum(results)
print("\n%s (%d checks, %d failed)" % ("ALL PASSED" if not failed else "SOME FAILED",
                                      len(results), failed))
sys.exit(1 if failed else 0)
