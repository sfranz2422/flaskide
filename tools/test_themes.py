#!/usr/bin/env python3
"""Slide themes: `theme: <name>` on the first line of the notes.

    python3 tools/test_themes.py

WHAT IS BEING GUARDED

  The line never moves a slide.
      The teacher's "3/5", the lesson editor's cursor and every student's
      viewer all count slides with notes.js's slides(). The theme line is
      taken out there, so notes with it cut into exactly the slides they
      would without it, and slide 1 never shows the line.

  Only a name on the list, and only on the first line.
      A theme is a class whose colours live in style.css; nothing typed in
      notes reaches CSS. An unknown name is left in as text so a typo shows,
      and "theme: x" further down is ordinary text.

  The look follows the notes, on the slides and the bar under them.
      Shown whole or as slides, the notes element gets the theme's class;
      a later show() without the line takes it off, and changing only the
      theme redraws although no slide's text changed.

  Every theme on the list has its CSS, and every theme in the CSS is on
  the list — or a name would be accepted and look like nothing at all.

notes.js runs in node with marked and DOMPurify stubbed: what is checked
here is notes.js's own handling of the line, not markdown.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYIDE = os.path.dirname(HERE)

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-62s %s" % ("ok" if condition else "FAIL", label, detail))


if not shutil.which("node"):
    sys.exit("node is needed to run notes.js; brew install node")

notes_js = open(os.path.join(PYIDE, "static", "notes.js")).read()
css = open(os.path.join(PYIDE, "static", "style.css")).read()

HARNESS = r"""
function node(tag) {
  return { tag, className: "", innerHTML: "", hidden: false, children: [], textContent: "",
           scrollTop: 0, parentNode: null, type: "", title: "",
           setAttribute() {}, addEventListener() {}, querySelectorAll() { return []; },
           appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
           insertBefore(c) { this.children.push(c); c.parentNode = this; return c; } };
}
var fontLinks = 0;
var document = { createElement: node, querySelectorAll() { return []; },
                 head: { appendChild() { fontLinks++; } } };
var window = { marked: { parse: (s) => s }, DOMPurify: { sanitize: (s) => s } };
""" + notes_js + r"""
var N = window.FlaskIDENotes;
var deck = "# One\n---\n# Two\n---\n# Three";
var out = {
  themes: N.THEMES,
  plain: N.slides(deck),
  themed: N.slides("theme: ocean\n" + deck),
  blankFirst: N.slides("\n\n  theme: Ocean  \n" + deck),
  crlf: N.slides("theme: ocean\r\n" + deck.replace(/\n/g, "\r\n")),
  crlfTake: N.takeTheme("theme: ocean\r\n# Hi").name,
  aloneOnSlide: N.slides("theme: ocean\n---\n" + deck),
  take: N.takeTheme("theme: forest\n# Hi"),
  typo: N.takeTheme("theme: oceann\n# Hi"),
  later: N.takeTheme("# Hi\ntheme: ocean"),
  injected: N.takeTheme("theme: ocean; background: red\n# Hi"),
};

var parent = node("div"), body = node("div");
parent.appendChild(body);
var view = N.slideView(body);
var steps = [];
function snap(label) {
  steps.push({ label, body: body.className, bar: view.bar.className, html: body.innerHTML });
}
(async function () {
  await view.show("theme: chalkboard\n" + deck, 0); snap("deck");
  await view.go(2); snap("third");
  await view.show("theme: space\n" + deck); snap("retheme");
  await view.show(deck); snap("unthemed");
  await view.show("theme: notebook\n# Just notes, no slides"); snap("whole");
  var lone = node("div");
  await N.render(lone, "theme: arcade\n# Hi"); steps.push({ label: "render", body: lone.className, html: lone.innerHTML });
  await N.render(lone, "# Plain"); steps.push({ label: "render-off", body: lone.className });
  await N.render(lone, "theme: ocean\n# Slide 3", { theme: "forest" });
  steps.push({ label: "given", body: lone.className, html: lone.innerHTML });
  out.steps = steps;
  out.fontLinks = fontLinks;
  console.log(JSON.stringify(out));
})();
"""

res = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True)
try:
    got = json.loads(res.stdout)
except ValueError:
    print(res.stderr[-2000:])
    sys.exit(1)
step = {s["label"]: s for s in got["steps"]}

print("the line never moves a slide")
check("themed notes cut into the same slides as without the line",
      got["themed"] == got["plain"] and len(got["plain"]) == 3, got["themed"])
check("…after blank lines, in any case, with spaces round it",
      got["blankFirst"] == got["plain"], got["blankFirst"])
check("…with Windows line endings",
      got["crlf"] == got["plain"] and got["crlfTake"] == "ocean",
      (got["crlf"], got["crlfTake"]))
check("…and a line alone before the first --- makes no empty slide",
      got["aloneOnSlide"] == got["plain"], got["aloneOnSlide"])

print("only a name on the list, only on the first line")
check("a known name is taken, and its line taken out",
      got["take"] == {"name": "forest", "body": "# Hi"}, got["take"])
check("a typo stays in the notes as text, so it shows",
      got["typo"] == {"name": "", "body": "theme: oceann\n# Hi"}, got["typo"])
check("theme: further down is ordinary text", got["later"]["name"] == "", got["later"])
check("anything after the name is not a theme",
      got["injected"]["name"] == "", got["injected"])

print("the look follows the notes")
check("a deck gets its theme's class",
      "slide-theme-chalkboard" in step["deck"]["body"].split(), step["deck"])
check("…and the bar under it matches",
      "slide-theme-chalkboard" in step["deck"]["bar"].split(), step["deck"]["bar"])
check("slide 1 does not show the line", "theme:" not in step["deck"]["html"], step["deck"]["html"])
check("moving through the deck keeps it",
      "slide-theme-chalkboard" in step["third"]["body"].split()
      and step["third"]["html"] == "# Three", step["third"])
check("changing only the theme line redraws with the new one",
      "slide-theme-space" in step["retheme"]["body"].split()
      and "slide-theme-chalkboard" not in step["retheme"]["body"], step["retheme"]["body"])
check("taking the line out takes the theme off",
      "slide-theme" not in step["unthemed"]["body"]
      and "slide-themed" not in step["unthemed"]["bar"], step["unthemed"])
check("notes with no slides, shown whole, are themed too, without the line",
      "slide-theme-notebook" in step["whole"]["body"].split()
      and "theme:" not in step["whole"]["html"], step["whole"])
check("render() alone reads the line",
      "slide-theme-arcade" in step["render"]["body"].split()
      and "theme:" not in step["render"]["html"], step["render"])
check("…and takes it off again", "slide-theme" not in step["render-off"]["body"],
      step["render-off"])
check("a deck's theme given to a slide wins, and a line atop the slide stays text",
      "slide-theme-forest" in step["given"]["body"].split()
      and step["given"]["html"].startswith("theme: ocean"), step["given"])
check("the display fonts are fetched once, not per slide", got["fontLinks"] == 1,
      got["fontLinks"])

print("every theme has its CSS")
in_css = set(re.findall(r"^\.slide-theme-([a-z]+) \{", css, re.M))
check("each theme on the list is styled",
      set(got["themes"]) <= in_css, sorted(set(got["themes"]) - in_css))
check("each theme styled is on the list",
      in_css <= set(got["themes"]), sorted(in_css - set(got["themes"])))
for name in got["themes"]:
    block = re.search(r"^\.slide-theme-%s \{(.*?)^\}" % name, css, re.M | re.S)
    body = block.group(1) if block else ""
    needed = ["--theme-bg", "--nav-bg", "--text", "--heading", "--accent", "--line",
              "--bg:", "--bg-panel", "color-scheme"]
    missing = [v for v in needed if v not in body]
    check("  %s sets every colour it is drawn with" % name, not missing, missing)

# A theme whose headings name a display face must be one the fonts are
# fetched for, or its headings fall back to the page's font with nothing
# to say so — the look is simply not there.
font_themes = json.loads(re.search(r"var FONT_THEMES = (\[[^\]]*\]);", notes_js).group(1))
url = re.search(r'link\.href = ((?:"[^"]*"\s*\+?\s*)+);', notes_js).group(1)
fetched = re.findall(r"family=([A-Za-z0-9+]+)", url)
fetched = {f.replace("+", " ") for f in fetched}
needs = {}
for name, fam in re.findall(r"\.slide-theme-([a-z]+) h1[^{]*\{[^}]*font-family:\s*\"([^\"]+)\"", css):
    needs[name] = fam
check("every theme with a display face fetches it",
      needs and all(n in font_themes and f in fetched for n, f in needs.items()),
      {n: (n in font_themes, f in fetched) for n, f in needs.items()})

help_page = open(os.path.join(PYIDE, "templates", "help_questions.html")).read()
listed = re.search(r'\{% for name in (\[.*?\]) %\}', help_page)
check("the help page shows exactly these themes",
      listed and json.loads(listed.group(1)) == got["themes"],
      listed and listed.group(1))

# One slide drawn on its own has lost the deck's theme: line, which sits
# above the first slide. The teacher's "Class sees" pane and the class's
# mirror (when the teacher has the notes open) each draw one slide, and
# both showed a themed deck plain until they were handed the theme.
print("one slide on its own still has the deck's theme")
app_js = open(os.path.join(PYIDE, "static", "app.js")).read()
live_js = open(os.path.join(PYIDE, "static", "live.js")).read()
check("Class sees is drawn with the deck's theme",
      re.search(r"paintClassView\(onSlide, slide, window\.\w+Notes\.takeTheme\(notes\)\.name\)",
                app_js) is not None
      and "slide ? { theme: theme } : undefined" in app_js)
check("  and redrawn when only the theme changes", "theme === classShownTheme" in app_js)
check("the class's mirror draws the teacher's slide with the deck's theme",
      "mirrorDeck = data.notes" in live_js
      and "theme === null ? undefined : { theme: theme }" in live_js)
check("  and redraws when only the theme changes",
      'data.body + "\\u0000" + theme !== lastNotes' in live_js)

print()
print("%d/%d ok" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
