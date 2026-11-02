#!/usr/bin/env python3
"""The teacher's slides on every student's screen, teacher in control.

    python3 tools/test_deck_show.py

WHAT IS BEING GUARDED

  A student is sent one slide, never the deck. The deck is the teacher's own
      scripts and would run with the student's sign-in, and it holds every
      later slide and answer. deck_show.js writes the slide out with no scripts,
      no other slides, no unrevealed answers and no class list; run in node on
      a small fake DOM below.

  The frame on a student's screen can run nothing, whatever it is sent: its
      sandbox is allow-same-origin without allow-scripts, because the clean-up
      above happens in the teacher's browser and proves nothing.

  Only the lesson's teacher can put anything on the class's screens.

  A late or overtaken slide can't replace a newer one, or restart a stopped show.

  A class is never stranded: stopping, or the teacher's tab going silent, gives
      them their page back.

  The plain link to the deck stays the file as uploaded, and showing doesn't
      move the lesson's own `version`, so "not started yet" still holds.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DB = os.path.join(tempfile.mkdtemp(), "deck_show.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org,other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)

sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-66s %s" % ("ok" if condition else "FAIL", label, detail))


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
    if uid is not None:
        with c.session_transaction() as s:
            s["uid"] = uid
    return c


def frame(body="<p>one</p>", head="<style>p{}</style>"):
    return {"head": head, "body": body, "html_attrs": "", "body_attrs": ""}


def pack(f):
    return base64.b64encode(json.dumps(f).encode()).decode()


def push(c, code, seq, f=None):
    return c.post("/api/live/%s/deck" % code,
                  json={"seq": seq, "showing": True, "data": pack(f or frame())})


def stop(c, code, seq):
    return c.post("/api/live/%s/deck" % code, json={"seq": seq, "showing": False})


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="T"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="O"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy"))
teacher, other, amy, nobody = client(TEACHER), client(OTHER), client(AMY), client(None)
add(accounts.Assignment(slug="hw1", app=P.APP_NAME, teacher_id=TEACHER, title="HW1",
                        code="print(1)\n", files=json.dumps({"notes.md": "# Hi\n"})))
add(accounts.Assignment(slug="les1", app=P.APP_NAME, teacher_id=TEACHER, title="L1",
                        code="", files=json.dumps({"lesson.md": "# Hi\n"}), kind="lesson"))
DECK = "<!doctype html><html><body><h1>Dicts</h1><script>go()</script></body></html>"
teacher.post("/api/assignment/hw1/slides",
             json={"name": "d.html", "data": base64.b64encode(DECK.encode()).decode()})

print("the teacher's way in")
page = teacher.get("/teacher/hw1").get_data(as_text=True)
at = page.index('id="deck-show"')
tag = page[page.rindex("<a", 0, at):page.index(">", at)]
check("the assignment's page has Show to class, in a new tab",
      'href="/teacher/hw1/slides?show=1"' in tag and 'target="_blank"' in tag and "hidden" not in tag, tag)
check("  the plain link is still the file as uploaded",
      teacher.get("/teacher/hw1/slides").get_data(as_text=True) == DECK)
shown = teacher.get("/teacher/hw1/slides?show=1").get_data(as_text=True)
db = P.SessionLocal()
live = db.query(accounts.LiveSession).filter_by(assignment_id=db.query(accounts.Assignment)
                                                .filter_by(slug="hw1").first().id).first()
CODE, VERSION = live.code, live.version
db.close()
check("?show=1 adds the show", 'src="/static/deck_show.js"' in shown and CODE in shown)
check("  after the deck's own script, so the first slide is drawn",
      shown.index("go()") < shown.index("deck_show.js") < shown.index("</body>"))
check("  and a student can't open it that way either",
      amy.get("/teacher/hw1/slides?show=1").status_code in (302, 403, 404))
if hasattr(P, "_is_lab"):          # only PyIDE has labs; this file is the same in all three
    add(accounts.Assignment(slug="lab1", app=P.APP_NAME, teacher_id=TEACHER, title="Lab",
                            code="", files="{}", kind="lab"))
    teacher.post("/api/assignment/lab1/slides",
                 json={"name": "d.html", "data": base64.b64encode(DECK.encode()).decode()})
    check("a lab has none: labs are never live",
          "deck_show.js" not in teacher.get("/teacher/lab1/slides?show=1").get_data(as_text=True)
          and 'id="deck-show"' not in teacher.get("/teacher/lab1").get_data(as_text=True))

print("who can put things on the class's screens")
for label, c in (("another teacher", other), ("a student", amy), ("someone signed out", nobody)):
    check("%s can't" % label, push(c, CODE, 5).status_code == 403)
    check("  nor stop it", stop(c, CODE, 6).status_code == 403)
check("nothing is showing after those", nobody.get("/api/live/%s/deck" % CODE).status_code == 304)

print("showing")
r = push(teacher, CODE, 100, frame("<p>one</p>"))
check("the teacher sends a slide", r.status_code == 200 and not r.get_json()["stale"], r.get_data(as_text=True)[:80])
r = amy.get("/api/live/%s/deck?d=0" % CODE)
got = r.get_json()
check("a student gets it", got["showing"] and got["seq"] == 100 and got["frame"]["body"] == "<p>one</p>")
check("  signed out too, as the lesson's own poll allows",
      nobody.get("/api/live/%s/deck?d=0" % CODE).status_code == 200)
check("  a capital in the code still finds it",
      nobody.get("/api/live/%s/deck?d=0" % CODE.upper()).status_code == 200)
check("no news is a bare 304", amy.get("/api/live/%s/deck?d=100" % CODE).status_code == 304)
check("a beat is no news", teacher.post("/api/live/%s/deck" % CODE, json={"seq": 101, "beat": True}).status_code == 200
      and amy.get("/api/live/%s/deck?d=100" % CODE).status_code == 304)
push(teacher, CODE, 200, frame("<p>two</p>"))
check("the next slide reaches them",
      amy.get("/api/live/%s/deck?d=100" % CODE).get_json()["frame"]["body"] == "<p>two</p>")
r = push(teacher, CODE, 150, frame("<p>old</p>"))
check("a slide that was overtaken is refused", r.get_json()["stale"])
check("  and the newer one stays",
      amy.get("/api/live/%s/deck?d=0" % CODE).get_json()["frame"]["body"] == "<p>two</p>")

print("what isn't a slide")
bad = lambda d: teacher.post("/api/live/%s/deck" % CODE, json={"seq": 900, "showing": True, "data": d})
check("base64 that isn't is refused", bad("PGh0bWw+<>").status_code == 400)
check("something that isn't JSON is refused", bad(base64.b64encode(b"<html>").decode()).status_code == 400)
check("a slide missing a part is refused", bad(pack({"body": "x"})).status_code == 400)
check("a slide of the wrong type is refused", bad(pack({"head": 1, "body": "", "html_attrs": "", "body_attrs": ""})).status_code == 400)
check("too big is refused, and says so",
      push(teacher, CODE, 901, frame("x" * P.DECK_FRAME_MAX_BYTES)).status_code == 413)
check("  and none of those changed the slide",
      amy.get("/api/live/%s/deck?d=0" % CODE).get_json()["frame"]["body"] == "<p>two</p>")

print("the class gets its page back")
check("a stop stamped before the newest slide does nothing", stop(teacher, CODE, 199).status_code == 200
      and amy.get("/api/live/%s/deck?d=0" % CODE).status_code == 200)
stop(teacher, CODE, 300)
r = amy.get("/api/live/%s/deck?d=200" % CODE)
check("stopping tells a page still showing it", r.status_code == 200 and r.get_json()["showing"] is False)
check("  and a page showing nothing hears nothing", amy.get("/api/live/%s/deck?d=0" % CODE).status_code == 304)
db = P.SessionLocal()
check("  and the slide isn't kept", db.query(P.DeckShow).filter_by(code=CODE).first().frame == "")
db.close()
push(teacher, CODE, 250, frame("<p>late</p>"))
check("a slide sent before the stop can't start it again",
      amy.get("/api/live/%s/deck?d=0" % CODE).status_code == 304)
push(teacher, CODE, 400, frame("<p>three</p>"))
check("showing again works", amy.get("/api/live/%s/deck?d=0" % CODE).get_json()["seq"] == 400)
db = P.SessionLocal()
db.query(P.DeckShow).filter_by(code=CODE).update({"beat": int(time.time()) - P.DECK_SHOW_STALE_SECONDS - 1})
db.commit()
db.close()
r = amy.get("/api/live/%s/deck?d=400" % CODE)
check("a teacher's tab gone silent lets the class go", r.status_code == 200 and r.get_json()["showing"] is False)
teacher.post("/api/live/%s/deck" % CODE, json={"seq": 401, "beat": True})
check("  and its next beat brings the slide back",
      amy.get("/api/live/%s/deck?d=0" % CODE).get_json()["seq"] == 400)

print("the lesson itself")
db = P.SessionLocal()
live = db.query(accounts.LiveSession).filter_by(code=CODE).first()
check("showing doesn't move the lesson's version, so it hasn't 'started'",
      live.version == VERSION == 0 and P._waiting(live), live.version)
db.close()

print("students' pages")
watch = amy.get("/live/%s" % CODE).get_data(as_text=True)
check("the live page loads the viewer with its code",
      'deck_view.js' in watch and 'data-code="%s"' % CODE in watch)
check("  the teacher's own view of that link doesn't",
      "deck_view.js" not in teacher.get("/live/%s" % CODE).get_data(as_text=True))
teacher.get("/teacher/les1/slides?show=1")
db = P.SessionLocal()
les = db.query(accounts.Assignment).filter_by(slug="les1").first()
lc = P._lesson_for(db, db.get(accounts.User, TEACHER), les).code
db.close()
check("a lesson's class page loads it too",
      "deck_view.js" in amy.get("/live/%s" % lc).get_data(as_text=True))

src = open(os.path.join(ROOT, "static", "deck_view.js"), encoding="utf-8").read()
check("the frame's sandbox lets nothing run",
      'frame.setAttribute("sandbox", "allow-same-origin")' in src and "allow-scripts" not in src.replace("WITHOUT\n * allow-scripts", ""))

print("View teacher lesson on the class page")
stop(teacher, CODE, 10 ** 14)
COURSE = add(accounts.Course(app=P.APP_NAME, teacher_id=TEACHER, name="P1"))
add(accounts.Enrollment(class_id=COURSE, email="amy@school.org"))
WITH = teacher.post("/api/class/%d/new" % COURSE, json={"title": "Has slides"}).get_json()["slug"]
BARE = teacher.post("/api/class/%d/new" % COURSE, json={"title": "No slides"}).get_json()["slug"]
teacher.post("/api/assignment/%s/slides" % WITH,
             json={"name": "d.html", "data": base64.b64encode(DECK.encode()).decode()})
db = P.SessionLocal()
withrow = db.query(accounts.Assignment).filter_by(slug=WITH).first()
db.query(accounts.ClassItem).filter_by(assignment_id=withrow.id).update({"show_live": 0})
db.commit()
WITH_ID = withrow.id
db.close()
teacher.get("/teacher/%s" % WITH)         # makes the lesson's link, as the page always does
db = P.SessionLocal()
WITH_CODE = P._newest_lesson(db, TEACHER, WITH_ID).code
db.close()
page = amy.get("/class/%d" % COURSE).get_data(as_text=True)
check("an assignment with slides has the button, in those words",
      'data-slug="%s"' % WITH in page and ">View teacher lesson</button>" in page)
check("  one without has none", page.count("js-view-lesson") == 1 and 'data-slug="%s"' % BARE not in page)
check("  the page can act on it", "deck_view.js" in page)
check("  and a hidden live link's code isn't in the page", WITH_CODE not in page)
token = teacher.post("/api/class/%d/view-link" % COURSE)
if token.status_code == 200:
    seen = nobody.get(token.get_json()["url"].replace("http://localhost", "")).get_data(as_text=True)
    check("a view-only visitor gets no button", "js-view-lesson" not in seen and "deck_view.js" not in seen)
showing = lambda: amy.get("/api/assignment/%s/showing" % WITH).get_json()
check("not showing: the answer gives nothing away", showing() == {"showing": False}, showing())
check("  and an assignment that doesn't exist answers the same",
      amy.get("/api/assignment/nope/showing").get_json() == {"showing": False})
push(teacher, WITH_CODE, 10 ** 14, frame("<p>class</p>"))
check("showing: it says where", showing() == {"showing": True, "code": WITH_CODE}, showing())
db = P.SessionLocal()
db.query(P.DeckShow).filter_by(code=WITH_CODE).update({"beat": 0})
db.commit()
db.close()
check("a show gone silent counts as not showing", showing() == {"showing": False})
view = open(os.path.join(ROOT, "static", "deck_view.js"), encoding="utf-8").read()
check("the button only moves on if the slides are up", "if (d.showing) watch(d.code);" in view)

print("what the slide is written out as (deck_show.js in node)")
RUN = r"""
const vm = require("vm"), fs = require("fs");
function T(v){ return {nodeType:3,nodeValue:v}; }
function E(tag, attrs, kids, style){
  const a = attrs||{};
  const el = {nodeType:1,tagName:tag.toUpperCase(),style:style||{},
    attributes:Object.keys(a).map(k=>({name:k,value:a[k]})),
    getAttribute:k=>k in a?a[k]:null,
    childNodes:kids||[], textContent:(kids||[]).map(k=>k.nodeValue||"").join(""),
    matches(sel){ return sel.split(",").some(s=>{ s=s.trim();
      const p=s.split(" "); const last=p[p.length-1];
      const hit = last[0]==="#"? a.id===last.slice(1) : last[0]==="."?(" "+(a.class||"")+" ").includes(" "+last.slice(1)+" "):tag===last;
      return hit && (p.length===1 || el.under===p[0]); }); }};
  return el;
}
const HIDE={visibility:"hidden"}, NONE={display:"none"};
const scoreBtn=E("button",{},[T("+")]); scoreBtn.under="#score";
const doc={documentElement:E("html",{class:"dark",onload:"x()"}),
  body:E("body",{class:"b"},[
    E("section",{class:"slide active"},[
      E("h2",{},[T("Now <here>")]),
      E("pre",{class:"out reveal"},[T("secret output")],{visibility:"visible"}),
      E("pre",{class:"out reveal shown"},[T("shown output")]),
      E("span",{class:"ans stage","data-a":"14"}),
      E("span",{class:"ans stage shown","data-a":"99"}),
      E("pre",{class:"py stage","data-bug":"2"},[E("span",{class:"ln isbug"},[T("broken code")])]),
      E("ol",{class:"opts stage"},[E("li",{class:"right"},[T("yes")]),E("span",{class:"verdict"},[T("because")],HIDE)]),
      E("a",{href:"https://example.com",target:"_blank",onclick:"evil()"},[T("link")]),
      E("button",{},[T("Sign Up")]),
      E("input",{value:"Ava"}),
      E("script",{},[T("evil()")]),
    ]),
    E("section",{class:"slide"},[T("LATER SLIDE")],NONE),
    E("div",{class:"hint"},[T("press N")]),
    E("div",{class:"nav"},[E("span",{id:"count"},[T("3 / 10")]),E("button",{id:"next"},[T("next")])]),
    E("div",{class:"overlay on",id:"setup"},[E("textarea",{id:"roster"},[T("Ava Leo")])]),
    E("div",{class:"score",id:"score"},[E("div",{class:"ts"},[T("7")]),scoreBtn]),
    E("div",{id:"deck-show-pill"},[T("pill")]),
  ]),
  head:E("head",{},[E("title",{},[T("t")]),E("style",{},[T("a>b{}")]),E("script",{},[T("headevil()")]),
    E("link",{rel:"stylesheet",href:"f.css"}),E("meta",{"http-equiv":"refresh",content:"0;url=x"})])};
const win={getComputedStyle:el=>Object.assign({display:"block",visibility:"visible"},el.style)};
const box={globalThis:{},btoa:()=>""}; vm.createContext(box);
box.window=undefined;
vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),box);
console.log(JSON.stringify(box.globalThis.PyIDEDeckShow.snapshot(doc,win)));
"""
script = os.path.join(tempfile.mkdtemp(), "snap.js")
with open(script, "w") as f:
    f.write(RUN)
out = subprocess.run(["node", script, os.path.join(ROOT, "static", "deck_show.js")],
                     capture_output=True, text=True)
if out.returncode:
    print(out.stderr)
snap = json.loads(out.stdout) if out.returncode == 0 else {"head": "", "body": "", "html_attrs": "", "body_attrs": ""}
body, head = snap["body"], snap["head"]
check("the slide on screen goes", "Now &lt;here&gt;" in body and 'class="slide active"' in body, body[:60])
check("a later slide doesn't", "LATER" not in body)
check("no script, in the body or the head", "evil" not in body and "evil" not in head and "<script" not in body + head)
check("no on* handler anywhere", "onclick" not in body and "onload" not in snap["html_attrs"])
check("the head keeps its style and fonts, unescaped", "<style>a>b{}</style>" in head and 'href="f.css"' in head)
check("  and no meta refresh to carry the frame away", "refresh" not in head)
check("an unrevealed output is masked, length kept", "secret" not in body and "xxxxxx xxxxxx" in body)
check("  a revealed one isn't", "shown output" in body)
check("an unrevealed answer has no data-a", '"14"' not in body)
check("  a revealed one keeps it", 'data-a="99"' in body)
check("an unrevealed bug isn't marked, its code still shown",
      "data-bug" not in body and "isbug" not in body and "broken code" in body)
check("an unmarked choice isn't marked, nor its reason shown",
      'class="right"' not in body and "because" not in body and ">yes<" in body)
check("links go nowhere", "example.com" not in body and "_blank" not in body and ">link<" in body)
check("a slide's own button and input stay: they may be the lesson",
      ">Sign Up<" in body and 'value="Ava"' in body)
check("the class list never goes", "Ava Leo" not in body and 'id="setup"' not in body)
check("the teacher's controls don't", "press N" not in body and 'id="next"' not in body
      and ">+<" not in body and "pill" not in body)
check("  the counter and the score do", "3 / 10" in body and ">7<" in body)

print()
print("ok" if all(results) else "FAIL", "%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
