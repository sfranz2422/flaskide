#!/usr/bin/env python3
"""Notes played a section at a time (`animate:`; notes.js slideView).

    python3 tools/test_reveal.py

A teacher writes `animate: words` (or `animate: type`) beside `theme:` at
the top of the notes, and `...` lines to divide a slide into sections. A
student reading their notes presses ▶ Play for each section in turn, and
the next slide waits until this one has been played. node runs notes.js's
own functions here for what can be checked without a page:

  * the header lines are taken out — in either order, alongside a theme —
    and a name notes.js doesn't know stays in as text, like a theme's typo
  * the `animate:` line never changes how many slides there are: the
    teacher's "3/5" and every student's count must agree
  * `...` divides a slide into sections, but never inside fenced code,
    where it's a line of output
  * `:::pop` … `:::` marks what stands out — the teacher's choice; nothing
    pops by itself — and never inside fenced code
  * it plays where notes are read at their own pace: a student's editor,
    the lesson page from the assignment link, and the teacher's own
    previews (with Skip) — never live, never the projector

The playing itself (Play waits while a section plays, the arrow waits for
the slide, slides already played show whole) was watched in a browser;
GameIDE's e2e/notes.spec.ts plays its copy of it through.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NOTES_JS = open(os.path.join(ROOT, "static", "notes.js")).read()
GLOBAL = re.search(r"window\.(\w+) = \(function", NOTES_JS).group(1)

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else "   " + str(detail)[:300]))


if not shutil.which("node"):
    print("  FAIL node is needed: brew install node")
    sys.exit(1)

CASES = {
    "words": "animate: words\n# Hi",
    "both": "theme: ocean\nanimate: type\n# Hi",
    "swapped": "animate: on\ntheme: forest\n\n# Hi",
    "unknown": "animate: fast\n# Hi",
    "late": "# Hi\nanimate: words",
    "deck": "animate: words\n# One\n...\nmore\n---\n# Two",
    "plain_deck": "# One\n...\nmore\n---\n# Two",
}
SECTIONS = {
    "split": "A\n...\nB\n\n...\nC",
    "fenced": "A\n```text\n...\n```\nB",
    "none": "Just one",
    "edges": "...\nA\n...",
}
harness = "var window = {};\n" + NOTES_JS + """
var N = window.%s;
var out = { header: {}, slides: {}, sections: {} };
var cases = %s, secs = %s;
Object.keys(cases).forEach(function (k) {
  out.header[k] = N.takeHeader(cases[k]);
  out.slides[k] = N.slides(cases[k]).length;
});
Object.keys(secs).forEach(function (k) { out.sections[k] = N.sections(secs[k]); });
out.theme = N.takeTheme(cases.both);
out.pops = N.popMarks(":::pop\\nLook!\\n:::\\n```\\n:::pop\\n```\\n::: pop\\nx");
console.log(JSON.stringify(out));
""" % (GLOBAL, json.dumps(CASES), json.dumps(SECTIONS))
res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
try:
    got = json.loads(res.stdout)
except ValueError:
    got = None
check("node ran notes.js", got is not None, res.stderr[-300:])
if got:
    h = got["header"]
    print("\nThe header lines")
    check("animate: words is taken out, and named", h["words"] == {"theme": "", "animate": "words", "body": "# Hi"}, h["words"])
    check("  beside a theme, in either order; on means words, type a typewriter",
          h["both"] == {"theme": "ocean", "animate": "type", "body": "# Hi"}
          and h["swapped"]["theme"] == "forest" and h["swapped"]["animate"] == "words"
          and h["swapped"]["body"].strip() == "# Hi", (h["both"], h["swapped"]))
    check("  a name it doesn't know stays in, as text, so the typo shows",
          h["unknown"]["animate"] == "" and h["unknown"]["body"].startswith("animate: fast"), h["unknown"])
    check("  and only at the top counts", h["late"]["animate"] == "" and "animate: words" in h["late"]["body"], h["late"])
    check("takeTheme still gives the theme, and the notes without both lines",
          got["theme"] == {"name": "ocean", "body": "# Hi"}, got["theme"])
    check("the animate: line never changes how many slides there are",
          got["slides"]["deck"] == got["slides"]["plain_deck"] == 2, got["slides"])
    print("\nSections")
    s = got["sections"]
    check("... divides a slide into sections", s["split"] == ["A", "B\n", "C"], s["split"])
    check("  but not inside fenced code, where it's output", s["fenced"] == ["A\n```text\n...\n```\nB"], s["fenced"])
    check("  a slide with none is one section, and a divider at either end makes no empty one",
          s["none"] == ["Just one"] and s["edges"] == ["A"], (s["none"], s["edges"]))

print("\nPop")
if got:
    pops = got["pops"].split("\n")
    check(":::pop and ::: lines become the markers wrapPops gathers between",
          pops[:4] == ["", "%%POPSTART%%", "", "Look!"] and "%%POPEND%%" in pops[4:7], pops)
    check("  but not inside fenced code", "```\n:::pop\n```" in got["pops"], got["pops"])
    check("  ::: pop with a space opens one too", got["pops"].count("%%POPSTART%%") == 2, got["pops"])
check("nothing pops by itself: only what's wrapped",
      'block.classList.contains("pop-box") ? "reveal-pop" : ""' in NOTES_JS
      and not re.search(r"/check my work/i|CHECK_WORDS|language-text", NOTES_JS))

print("\nWhere it's on")
app_js = open(os.path.join(ROOT, "static", "app.js")).read()
lesson_js = open(os.path.join(ROOT, "static", "lesson.js")).read()
others = {name: open(os.path.join(ROOT, "static", name)).read()
          for name in ("live.js", "present.js")
          if os.path.exists(os.path.join(ROOT, "static", name))}
lesson_teacher = open(os.path.join(ROOT, "static", "lesson_teacher.js")).read()
others["lesson_teacher.js (presenting)"] = lesson_teacher[lesson_teacher.find("var present"):]
check("the editor plays them, except while teaching live, with Skip for whoever is writing them",
      re.search(r"slideView\([^,]+, \{\s*animate: function \(\) \{ return !(?:window\.\w+|cfg)\.readonly && !liveCode; \},\s*"
                r"skip: function \(\) \{ return !!(?:window\.\w+|cfg)\.authoring; \},", app_js) is not None)
check("  and going live, or ending the lesson, redraws them",
      re.search(r"function paintLive\(\) \{[^}]*?(?:notesSlides\.show\(|showNotes\(notesShown\))", app_js) is not None)
for name in ("assignment_notes.js", "lesson_teacher.js"):
    js = open(os.path.join(ROOT, "static", name)).read()
    check("  the teacher's preview in %s plays them, with Skip" % name,
          'slideView($("' in js and "{ animate: true, skip: true, key: \"author:\" + location.pathname }" in js)
check("the lesson page plays them at the student's own pace, never following a live lesson",
      'slideView($("lesson-body"), { animate: !L.live && !L.viewOnly, key: L.slug })' in lesson_js)
check("live and the projector never ask for it",
      all("animate" not in re.findall(r"slideView\([^)]*\)", js)[0] for js in others.values() if re.findall(r"slideView\([^)]*\)", js)),
      [n for n, js in others.items() if "animate:" in js])
check("the next slide waits until this one has been played, and Play while a section plays",
      "if (by > 0 && unfinished()) return;" in NOTES_JS
      and "next.disabled = at >= cut.length - 1 || unfinished() || busy;" in NOTES_JS
      and "play.disabled = busy;" in NOTES_JS)
check("someone who asks for reduced motion gets each section at once",
      'matchMedia("(prefers-reduced-motion: reduce)")' in NOTES_JS)
check("Skip shows the part playing at once, or between parts the whole slide — and only where it's offered",
      "if (playing && playing.finish) playing.finish();" in NOTES_JS and "reached.played = sectionsHere().length;" in NOTES_JS
      and "skip.hidden = !skippable() || !(busy || more);" in NOTES_JS)

failed = results.count(False)
print("\n" + ("ALL PASSED" if not failed else "SOME FAILED") + " (%d checks, %d failed)" % (len(results), failed))
sys.exit(1 if failed else 0)
