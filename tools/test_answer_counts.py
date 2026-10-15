#!/usr/bin/env python3
"""While live, each question card in the teacher's editor says how many of
the students here have answered it: "18 / 22 answered".

    python3 tools/test_answer_counts.py

WHAT IS BEING GUARDED

  The count is of the students here now, out of the students here now.
      "Here" is the class's attendance sittings active in the last
      VISIT_GAP_MINUTES. A student who answered from the link last week and
      is not in the room must not count, or the card reads 23 / 22.

  The questions are the ones the class was sent, in order, keys out.
      A fill-in-the-blank comes with its blanks emptied, as the class's
      copy has them, because that is how the editor finds its own card.

  A lesson in no class has no "here", and shows the count alone.

  Only the lesson's teacher can ask.

  The editor puts the right count on the right card, and takes it off.
      Its own code (cut out of app.js) runs in node on stand-in cards: found
      by prompt, blanks and all; green when everyone here has answered; gone
      when the lesson ends; and never rewritten when nothing changed, or the
      MutationObserver that puts counts back after a redraw would never
      stop.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "answer_counts.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, PYIDE)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402
import quiz                                                  # noqa: E402

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


def client(uid):
    c = P.app.test_client()
    with c.session_transaction() as s:
        s["uid"] = uid
    return c


NOTES = ("# Lists\n\n```quiz\nWhat is enemies[1]?\n- [ ] bat\n- [x] slime\n```\n\n---\n\n"
         "```quiz\ntype: blank\nA [[for]] loop goes once per item.\n```\n")
QIDS = [quiz.parse("\n".join(p[2]))["qid"] for p in quiz._blocks(NOTES) if p[0] == "quiz"]

TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
BEN = add(accounts.User(google_sub="b", email="ben@school.org", name="Ben"))
CAL = add(accounts.User(google_sub="c", email="cal@school.org", name="Cal"))
DAN = add(accounts.User(google_sub="d", email="dan@school.org", name="Dan"))
CLASS = add(accounts.Course(app=P.APP_NAME, teacher_id=TEACHER, name="P4"))
HW = add(accounts.Assignment(slug="hw1", app=P.APP_NAME, teacher_id=TEACHER, title="Lists",
                             code="", files=json.dumps({"notes.md": NOTES})))
add(accounts.ClassItem(class_id=CLASS, assignment_id=HW))
add(accounts.LiveSession(code="live01", app=P.APP_NAME, host_id=TEACHER, title="Lists",
                         assignment_id=HW, version=1, notes=quiz.redact(NOTES)))
LOOSE = add(accounts.Assignment(slug="hw2", app=P.APP_NAME, teacher_id=TEACHER, title="Loose",
                                code="", files=json.dumps({"notes.md": NOTES})))
add(accounts.LiveSession(code="live02", app=P.APP_NAME, host_id=TEACHER, title="Loose",
                         assignment_id=LOOSE, version=1, notes=quiz.redact(NOTES)))

now = accounts.now()
# Amy and Ben are here; Cal was here this morning.
for uid, ago in ((AMY, 2), (BEN, 10), (CAL, 120)):
    t = now - P.timedelta(minutes=ago)
    add(accounts.Visit(class_id=CLASS, user_id=uid, email="x", name="x",
                       started_at=t - P.timedelta(minutes=30), last_at=t))
for aid, uid, qid in ((HW, AMY, QIDS[0]), (HW, CAL, QIDS[0]), (HW, AMY, QIDS[1]),
                      (HW, BEN, QIDS[1]), (LOOSE, AMY, QIDS[0]), (LOOSE, CAL, QIDS[0]),
                      # Dan answered the other copy only: never Loose's count.
                      (HW, DAN, QIDS[0])):
    add(accounts.QuizAnswer(assignment_id=aid, student_id=uid, qid=qid, response="x"))

print("the server's count")
r = client(TEACHER).get("/api/live/live01/answers")
d = r.get_json() or {}
check("the lesson's teacher is answered", r.status_code == 200, r.status_code)
check("out of the students here now (two; the third left hours ago)", d.get("here") == 2, d)
qs = d.get("questions") or []
check("both questions, in the order the class has them", len(qs) == 2, qs)
check("a student not here does not count (1, not 2)",
      len(qs) == 2 and qs[0]["answered"] == 1, qs)
check("everyone here answering the second reads 2", len(qs) == 2 and qs[1]["answered"] == 2, qs)
check("the prompt as the class has it, blanks emptied",
      len(qs) == 2 and qs[0]["prompt"] == "What is enemies[1]?"
      and qs[1]["prompt"] == "A [[]] loop goes once per item.", [q["prompt"] for q in qs])
d2 = client(TEACHER).get("/api/live/live02/answers").get_json() or {}
check("a lesson in no class: the count alone, no 'here'",
      d2.get("here") is None and (d2.get("questions") or [{}])[0].get("answered") == 2, d2)
check("another teacher cannot ask",
      client(OTHER).get("/api/live/live01/answers").status_code == 404)
check("nor a student", client(AMY).get("/api/live/live01/answers").status_code == 404)

print("the editor's cards, in node")
if not shutil.which("node"):
    sys.exit("node is needed to run app.js; brew install node")
notes_js = open(os.path.join(PYIDE, "static", "notes.js")).read()
check("every card notes.js builds carries its prompt",
      "box.quizPrompt = q.prompt;" in notes_js)

app_js = open(os.path.join(PYIDE, "static", "app.js")).read()
start = app_js.index("    // ---------------------------------------------------- answers, counted")
end = app_js.index("\n  } else {", start)
block = app_js[start:end]

HARNESS = r"""
const block = %(block)s;
let intervals = [], answer = null, asked = 0;
global.setInterval = (fn) => intervals.push(fn);
global.fetch = () => { asked++; return Promise.resolve({ ok: true, json: () => Promise.resolve(answer) }); };
let observers = [], observed = [];
global.window = { MutationObserver: function (fn) {
  observers.push(fn);
  this.observe = (root) => observed.push(root);
} };
global.MutationObserver = window.MutationObserver;
global.document = { createElement: (t) => el(t) };
const flush = () => new Promise((r) => setImmediate(r));

function el(tag) {
  const n = { tag, className: "", children: [], parent: null, writes: 0, _text: "",
    classList: { has: new Set(),
      contains(c) { return this.has.has(c); },
      toggle(c, on) { on ? this.has.add(c) : this.has.delete(c); } },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    remove() { const s = this.parent.children; s.splice(s.indexOf(this), 1); },
    querySelector(sel) { return this.all().find((c) => c.className === sel.slice(1)) || null; },
    querySelectorAll(sel) { return this.all().filter((c) => c.className === sel.slice(1)); },
    all() { return this.children.flatMap((c) => [c].concat(c.all())); } };
  Object.defineProperty(n, "textContent", { get() { return this._text; },
                                            set(v) { this._text = v; this.writes++; } });
  return n;
}
function card(prompt) {
  const box = el("div"); box.className = "quiz"; box.quizPrompt = prompt;
  const head = el("div"); head.className = "quiz-head"; box.appendChild(head);
  return box;
}
const classNotes = el("div"), notesBody = el("div");
const a = card("What is enemies[1]?"), b = card("A [[for]] loop goes once per item.");
const c = card("A question the class was never sent");
classNotes.appendChild(a); notesBody.appendChild(b); notesBody.appendChild(c);
let liveCode = "live01";
const notes = "```quiz\nWhat is enemies[1]?\n```";
function liveNotes() { return notes; }
function $(id) { return id === "notes-body" ? notesBody : id === "class-notes" ? classNotes : null; }
eval(block);
const badge = (box) => box.querySelector(".quiz-count");
const out = {};
(async function () {
  answer = { here: 2, questions: [{ prompt: "What is enemies[1]?", answered: 1 },
                                  { prompt: "A [[]] loop goes once per item.", answered: 2 }] };
  intervals.forEach((f) => f()); await flush(); await flush();
  out.a = badge(a) && badge(a).textContent;
  out.aGreen = badge(a) && badge(a).classList.contains("all-in");
  out.b = badge(b) && badge(b).textContent;
  out.bGreen = badge(b) && badge(b).classList.contains("all-in");
  out.c = !!badge(c);
  // The notes drawn again (a keystroke, the class moving on): new cards,
  // no counts on them, and the observer told.
  const a2 = card("What is enemies[1]?");
  classNotes.children.splice(0, 1, a2); a2.parent = classNotes;
  observers.forEach((f) => f());
  out.redrawn = badge(a2) && badge(a2).textContent;
  out.watched = observed.length;
  const writes = badge(a2) ? badge(a2).writes : 0;
  paintCounts(); paintCounts();
  out.rewrites = badge(a2) ? badge(a2).writes - writes : -1;
  answer = { here: null, questions: [{ prompt: "What is enemies[1]?", answered: 3 }] };
  intervals.forEach((f) => f()); await flush(); await flush();
  out.alone = badge(a2) && badge(a2).textContent;
  liveCode = null;
  const before = asked;
  intervals.forEach((f) => f()); await flush(); await flush();
  out.ended = { a: !!badge(a2), asked: asked - before };
  console.log(JSON.stringify(out));
})();
"""
res = subprocess.run(["node", "-e", HARNESS % {"block": json.dumps(block)}],
                     capture_output=True, text=True, timeout=60)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    print(res.stdout[-1000:], res.stderr[-2000:])
    sys.exit(1)
check("a card shows its count out of the students here", o["a"] == "1 / 2 answered", o["a"])
check("  not green while some here have not answered", o["aGreen"] is False)
check("a fill-in-the-blank card is found by its emptied prompt",
      o["b"] == "2 / 2 answered", o["b"])
check("  and is green once everyone here has", o["bGreen"] is True)
check("a card for a question the class was not sent gets nothing", o["c"] is False)
check("a card drawn again gets its count back at once",
      o["redrawn"] == "1 / 2 answered" and o["watched"] == 2, (o["redrawn"], o["watched"]))
check("nothing is rewritten when nothing changed", o["rewrites"] == 0, o["rewrites"])
check("with no 'here', the count alone", o["alone"] == "3 answered", o["alone"])
check("the lesson ended: counts come off, and it stops asking",
      o["ended"] == {"a": False, "asked": 0}, o["ended"])

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
