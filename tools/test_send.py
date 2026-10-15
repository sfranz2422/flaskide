#!/usr/bin/env python3
"""Send to students: code the teacher highlights, offered to the class.

    python3 tools/test_send.py

Ported from PyIDE, where these checks live in test_live.py.

WHAT IS BEING GUARDED

  Only the lesson's teacher can send, and a send reaches the class.
      It moves the lesson's version, or every student polling with the
      version they have would be answered 304 and never see it; a student
      who joins late is handed it in the page; a late send is refused like
      a late push, and a push that loses to a send says so, because the
      editor pushes again on `stale`. Sending "" takes it back, and a
      teacher who reloads is told whether something is still out.

  Nothing from the network writes into a student's editor but the Insert
  button. insertSnippet is the only writer, Insert the only caller, and
  the poll only ever fills the card.

  Insert goes where the student is: indented to their line, on the next
  line when mid-code, without the teacher's own indentation.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "send.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


def add(row):
    db = P.SessionLocal()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def client(uid=None):
    c = P.app.test_client()
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


teacher = client(add(accounts.User(google_sub="t", email="teacher@school.org", name="T")))
other = client(add(accounts.User(google_sub="o", email="other@school.org", name="O")))
student = client(add(accounts.User(google_sub="s", email="s@school.org", name="S")))
stranger = client()

CODE = teacher.post("/api/live/start", json={"body": "the lesson"}).get_json()["code"]
teacher.post("/api/live/%s/push" % CODE, json={"body": "the lesson", "seq": 1000})


def poll_json(v=-1):
    return stranger.get("/api/live/%s?v=%s" % (CODE, v)).get_json()


print("sending")
before = poll_json()
r = teacher.post("/api/live/%s/send" % CODE, json={"snippet": "scores = [3, 1, 4]", "seq": 4000})
check("the host can send a snippet",
      r.status_code == 200 and (r.get_json() or {}).get("sent") is True, r.get_json())
r = stranger.get("/api/live/%s?v=%s" % (CODE, before["version"]))
check("  and a student polling with the old version gets it",
      r.status_code == 200 and r.get_json().get("snippet") == "scores = [3, 1, 4]",
      r.status_code)
check("  with the stamp that tells a new send from an old one",
      r.get_json().get("snippet_seq") == 4000, r.get_json().get("snippet_seq"))
check("  and the teacher's file is untouched by it",
      r.get_json().get("body") == before.get("body"))
page = stranger.get("/live/%s" % CODE).get_data(as_text=True)
check("a student who joins late is handed it in the page",
      '"scores = [3, 1, 4]"' in page and "snippetSeq: 4000" in page)
check("  with the card and its Insert button",
      'id="snippet"' in page and 'id="snippet-insert"' in page)

for who, label in ((other, "another teacher cannot send to this class"),
                   (student, "  nor can a student"), (stranger, "  nor anyone signed out")):
    r = who.post("/api/live/%s/send" % CODE, json={"snippet": "x", "seq": 9999})
    check(label, r.status_code == 403, r.status_code)
check("  and none of them changed it", poll_json().get("snippet") == "scores = [3, 1, 4]")

r = teacher.post("/api/live/%s/send" % CODE, json={"snippet": "old", "seq": 3999})
check("a send that arrives late is refused like a late push",
      r.get_json().get("stale") is True
      and poll_json().get("snippet") == "scores = [3, 1, 4]", r.get_json())
r = teacher.post("/api/live/%s/push" % CODE, json={"body": "lost", "seq": 3998})
check("  and a push that loses to a send says it was stale",
      r.get_json().get("stale") is True, r.get_json())

r = teacher.post("/api/live/%s/send" % CODE, json={"snippet": "", "seq": 4001})
check("sending nothing takes it back",
      r.status_code == 200 and poll_json().get("snippet") == "", r.get_json())
r = teacher.post("/api/live/start", json={})
check("a teacher who reloads is told whether something is out",
      r.get_json().get("snippet_out") is False, r.get_json())
teacher.post("/api/live/%s/send" % CODE, json={"snippet": "y = 1", "seq": 4002})
r = teacher.post("/api/live/start", json={})
check("  (and it says so when there is)", r.get_json().get("snippet_out") is True, r.get_json())
big = "#" * (P.MAX_FILE_BYTES + 1)
r = teacher.post("/api/live/%s/send" % CODE, json={"snippet": big, "seq": 4003})
check("an oversized snippet is refused", r.status_code == 413, r.status_code)
check("the teacher's bar has the Sent chip to take it back",
      'id="live-sent"' in open(os.path.join(ROOT, "templates", "index.html")).read())

print("the student's editor")
live_code = open(os.path.join(ROOT, "static", "live.js")).read()
app_js = open(os.path.join(ROOT, "static", "app.js")).read()


def fn_body(src, name):
    start = src.find("function %s(" % name)
    if start < 0:
        return ""
    depth, i = 0, src.index("{", start)
    while i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            return src[start:i + 1]
        i += 1
    return ""


insert_fn = fn_body(live_code, "insertSnippet")
writes = re.findall(r"mine\.(replaceRange|replaceSelection)\(", live_code.replace(insert_fn, ""))
check("the snippet is written into their editor only by insertSnippet",
      bool(insert_fn) and not writes, writes)
calls = [m.start() for m in re.finditer(r"insertSnippet\(", live_code)
         if not live_code[:m.start()].endswith("function ")]
click = live_code.find('$("snippet-insert").addEventListener("click"')
click_block = live_code[click:live_code.find("});", click)] if click >= 0 else ""
check("  and insertSnippet runs only from the Insert button",
      len(calls) == 1 and "insertSnippet(" in click_block, "%d call(s)" % len(calls))
check("  and the poll only fills the card",
      "insertSnippet" not in fn_body(live_code, "showSnippet")
      and "insertSnippet" not in fn_body(live_code, "showMirror")
      and "showSnippet(data);" in fn_body(live_code, "showMirror"))
check("the editor pushes again after losing to a send",
      re.search(r"data\.stale\) lastSent = null", app_js) is not None)
check("  and the send menu only opens while live with a selection",
      "if (!liveCode || !cm.somethingSelected()) return;" in app_js)

if not shutil.which("node"):
    sys.exit("node is needed to run insertSnippet; brew install node")
harness = r"""
function makeEditor(text, line, ch) {
  var lines = text.split("\n");
  return {
    getCursor: function () { return { line: line, ch: ch }; },
    getLine: function (n) { return lines[n]; },
    replaceRange: function (t, from, to) {
      var all = lines.join("\n");
      function off(p) {
        var o = 0; for (var i = 0; i < p.line; i++) o += lines[i].length + 1;
        return o + p.ch;
      }
      var a = off(from), b = to ? off(to) : a;
      lines = (all.slice(0, a) + t + all.slice(b)).split("\n");
    },
    focus: function () {},
    value: function () { return lines.join("\n"); }
  };
}
function note() {}
var mine;
%s
var out = {};
mine = makeEditor("<ul>\n  ", 1, 2);
insertSnippet("<li>a</li>\n<li>b</li>\n");
out.inBlock = mine.value();
mine = makeEditor("print(1)", 0, 3);
insertSnippet("if a:\n    b()");
out.midLine = mine.value();
mine = makeEditor("", 0, 0);
insertSnippet("        z = 3\n        w = 4");
out.teacherIndent = mine.value();
console.log(JSON.stringify(out));
""" % insert_fn
res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
try:
    got = json.loads(res.stdout)
except ValueError:
    got = {}
check("Insert on an indented blank line keeps its indentation",
      got.get("inBlock") == "<ul>\n  <li>a</li>\n  <li>b</li>",
      repr(got.get("inBlock") or res.stderr[-200:]))
check("  mid-line it goes on the next line, not through their code",
      got.get("midLine") == "print(1)\nif a:\n    b()", repr(got.get("midLine")))
check("  and the teacher's own indentation is not carried over",
      got.get("teacherIndent") == "z = 3\nw = 4", repr(got.get("teacherIndent")))

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
