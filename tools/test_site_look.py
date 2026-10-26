#!/usr/bin/env python3
"""The class pages' look (static/site_look.css), GameIDE's.

    python3 tools/test_site_look.py

THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE.

WHAT IS BEING GUARDED

  Every teacher's and student's page loads it, after style.css (before, and
      style.css wins every tie and nothing changes), with the fonts it names.
      The editors never do: their look is their own.

  A student's own theme wins. Colours are set only for the default looks —
      no data-theme, or "dark"/"light" — so a bought theme (data-theme=
      "ocean") keeps its colours. A colour written outright anywhere else
      would paint over every bought theme, silently: the theme would still be
      sold and chosen, and simply stop showing on these pages.

  Slides keep their own look. A slide theme sets its colours on the slide,
      and the assignment page's preview is what students see: every rule for
      buttons, boxes, links or headings leaves slides alone (a site button
      rule once made light buttons with light text on a dark theme).

  site_look.css is the same in all three (checked when the other repos are
      beside this one, skipped when not).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print("  %-4s %-66s %s" % ("ok" if condition else "FAIL", label, detail))


PAGES = ("teacher class_teacher teacher_assignment class_xp shop_teacher attendance "
         "material_teacher class_student classes my my_xp avatar").split()
EDITORS = ("index", "live", "lesson")
CSS = open(os.path.join(ROOT, "static", "site_look.css")).read()


def template(name):
    return open(os.path.join(ROOT, "templates", name + ".html")).read()


print("the pages")
for p in PAGES:
    html = template(p)
    look, style = html.find("site_look.css"), html.find("filename='style.css'")
    check("%s loads it after style.css" % p, look > style >= 0)
    check("  with Ubuntu and Source Sans 3", "family=Ubuntu" in html and "family=Source+Sans+3" in html)
for p in EDITORS:
    if os.path.exists(os.path.join(ROOT, "templates", p + ".html")):
        check("the editor page %s doesn't" % p, "site_look.css" not in template(p))

print("a bought theme keeps its colours")
# The rules, comments out: selector and body.
body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
DEFAULT = re.compile(r':root(:not\(\[data-theme\]\)|\[data-theme="(dark|light)"\])$')
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(|\b(white|black)\b")
rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"@media[^{]*\{", "", body))
check("there are rules to look at", len(rules) > 20, len(rules))
painted = []
for sel, decls in rules:
    sel = " ".join(sel.split())
    every_default = all(DEFAULT.match(s.strip()) for s in sel.split(","))
    if every_default:
        continue
    for d in decls.split(";"):
        if COLOUR.search(d.split(":", 1)[-1]):
            painted.append("%s { %s }" % (sel[:50], d.strip()[:40]))
check("no colour is written outside the default looks' own blocks", not painted, painted[:3])
default_blocks = [s for s, _ in rules if all(DEFAULT.match(x.strip()) for x in " ".join(s.split()).split(","))]
check("  which are there: dark (or none), and light twice",
      len(default_blocks) == 3, len(default_blocks))
top = [d for s, d in rules if s.strip() == ":root"]
check("a bought theme's buttons are its own brand colour", top and "--go: var(--brand)" in top[0])
check("the bar is only GameIDE's in the default looks",
      re.search(r':root:is\(:not\(\[data-theme\]\), \[data-theme="dark"\], \[data-theme="light"\]\) \.bar \{', CSS))

print("slides keep their own look")


def top_level(selector):
    """A selector list split at its own commas, not the ones inside :not(…)."""
    parts, depth, cur = [], 0, ""
    for ch in selector:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


SPARE = ":not(.notes-body *, .slide-nav *, .slide-themed *)"
REACHES = re.compile(r"(\.btn|\.linkbtn|\.field|\binput\b|\bselect\b|\btextarea\b|(^|\s)h[123]\b|^a\b|\.kind-tag)")
reaching = []
for sel, _ in rules:
    for part in top_level(" ".join(sel.split())):
        part = part.strip()
        if part.startswith(":root") or part.startswith(".bar") or not REACHES.search(part):
            continue
        reaching.append(part)
check("there are rules for buttons, boxes and headings", len(reaching) > 10, len(reaching))
leaky = [p for p in reaching if SPARE not in p]
check("every one of them leaves slides alone", not leaky, leaky[:3])

print("the same in all three")
mine = open(os.path.join(ROOT, "static", "site_look.css"), "rb").read()
home = os.path.expanduser("~")
for repo in ("pyide", "webide", "flaskide"):
    there = os.path.join(home, repo)
    if os.path.realpath(there) == os.path.realpath(ROOT) or not os.path.isdir(there):
        continue
    other = os.path.join(there, "static", "site_look.css")
    check("site_look.css is the same as %s's" % repo,
          os.path.exists(other) and open(other, "rb").read() == mine)

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
