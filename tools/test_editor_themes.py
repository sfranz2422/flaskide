#!/usr/bin/env python3
"""Editor themes: unlocked by level or bought with tokens, applied on every
page (xp.EDITOR_THEMES; "The token shop" in app.py; style.css).

    python3 tools/test_editor_themes.py

WHY THIS FILE EXISTS

A theme costs a student real tokens, so a theme that is sold must change
something, must be theirs for good once bought, and must not be usable by
anyone who hasn't earned or bought it. This pins:

  * every theme on the list has its colours in style.css — the page's
    ([data-theme]), the code's (.cm-s-pyide-) and the shop swatch's — since a
    missing block sells a theme that does nothing, silently;
  * every page's <head> puts the account's theme on before the first paint;
  * the teacher's shop sells the token themes, once each, and doesn't put
    one back after the teacher takes it off the shelf;
  * buying spends the tokens at once, counting tokens on hold, can't happen
    twice, and makes the theme theirs and in use; a theme can't be asked
    for as an ordinary request;
  * a student can use a theme only once it's theirs — by level or bought —
    and a theme that stops being theirs stops showing.

The same file in all three editors.
"""
import glob
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(tempfile.mkdtemp(), "themes.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["TEACHER_EMAILS"] = "teacher@school.org, other@school.org"
os.environ["SECRET_KEY"] = "k" * 32
os.environ.pop("ALLOWED_EMAIL_DOMAINS", None)
sys.path.insert(0, ROOT)
import app as P                                              # noqa: E402
import accounts                                              # noqa: E402
import xp                                                    # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("  %-4s %-64s %s" % ("ok" if ok else "FAIL", label, detail))


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


def user(uid):
    db = P.SessionLocal()
    try:
        return db.get(accounts.User, uid)
    finally:
        db.close()


# ------------------------------------------------------------- the styles
print("\nEvery theme has its colours")
css = open(os.path.join(ROOT, "static", "style.css")).read()
for tid in xp.THEME_IDS:
    check("  %s: page, code and swatch" % tid,
          (':root[data-theme="%s"]' % tid) in css and (".cm-s-pyide-%s " % tid) in css
          and (".theme-swatch-%s " % tid) in css)
free = [t for t in xp.EDITOR_THEMES if t[2].startswith("level ")]
check("high contrast is free from the start, for whoever needs it",
      xp.theme_level("contrast") == 1)
check("some themes are free by level and some cost tokens",
      free and len(free) < len(xp.EDITOR_THEMES))

print("\nEvery page puts the account's theme on first")
heads = [p for p in glob.glob(os.path.join(ROOT, "templates", "*.html"))
         if re.search(r'localStorage\.getItem\("[a-z]+-theme"\)', open(p).read())]
missing = [os.path.basename(p) for p in heads if "user_theme" not in open(p).read()]
check("every page with the light/dark script uses user_theme (%d pages)" % len(heads),
      heads and not missing, missing)

# ------------------------------------------------------------- the shop
TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="Mr Franz"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy Adams"))
BEN = add(accounts.User(google_sub="b", email="ben@school.org", name="Ben Brown"))
teacher, amy, ben = client(TEACHER), client(AMY), client(BEN)
CLASS = teacher.post("/api/class", json={"name": "P4"}).get_json()["id"]
for email in ("amy@school.org", "ben@school.org"):
    add(accounts.Enrollment(class_id=CLASS, email=email, name=email))

print("\nThe shop sells them")
teacher.get("/teacher/shop")


def theme_items(**by):
    db = P.SessionLocal()
    try:
        return db.query(accounts.ShopItem).filter(accounts.ShopItem.theme != "").filter_by(**by).all()
    finally:
        db.close()


paid = [t[0] for t in xp.EDITOR_THEMES if t[2] == "token"]
items = {i.theme: i for i in theme_items(teacher_id=TEACHER)}
check("the token themes are in the teacher's shop, once each",
      sorted(items) == sorted(paid) and len(theme_items(teacher_id=TEACHER)) == len(paid))
teacher.post("/api/shop/item/%d" % items["synthwave"].id, json={"active": False})
teacher.get("/teacher/shop")
check("  one taken off the shelf isn't put back",
      len(theme_items(teacher_id=TEACHER)) == len(paid)
      and not theme_items(teacher_id=TEACHER, theme="synthwave")[0].active)

print("\nBuying")
DRAC = items["dracula"].id
r = amy.post("/api/shop/buy", json={"item": DRAC})
check("no tokens, no theme", r.status_code == 409 and not xp.owned_themes(user(AMY)))
xp.award(P.SessionLocal(), AMY, "test:t", 2 * xp.TOKEN_EVERY, "", P.APP_NAME)   # two tokens
r = amy.post("/api/shop/request", json={"item": DRAC})
check("a theme can't be asked for as a request", r.status_code == 404)
LATE = [i.id for i in P.SessionLocal().query(accounts.ShopItem).filter_by(
    teacher_id=TEACHER, name="Late pass")][0]
amy.post("/api/shop/request", json={"item": LATE})          # holds both tokens
r = amy.post("/api/shop/buy", json={"item": DRAC})
check("tokens on hold can't buy a theme", r.status_code == 409
      and user(AMY).tokens_used == 0, r.get_json())
db = P.SessionLocal()
db.query(accounts.ShopRequest).filter_by(student_id=AMY).update({"status": "cancelled"})
db.commit()
db.close()
r = amy.post("/api/shop/buy", json={"item": DRAC})
u = user(AMY)
check("buying spends a token at once and the theme is hers, in use",
      r.status_code == 200 and u.tokens_used == 1 and xp.owned_themes(u) == ["dracula"]
      and u.editor_theme == "dracula", r.get_json())
db = P.SessionLocal()
bought = db.query(accounts.ShopRequest).filter_by(student_id=AMY, name="Theme: Dracula").all()
db.close()
check("  and it's recorded as bought", len(bought) == 1 and bought[0].status == "approved")
check("  not twice", amy.post("/api/shop/buy", json={"item": DRAC}).status_code == 409
      and user(AMY).tokens_used == 1)
check("one off the shelf can't be bought",
      amy.post("/api/shop/buy", json={"item": items["synthwave"].id}).status_code == 404)
check("an ordinary item can't be 'bought' past its request",
      amy.post("/api/shop/buy", json={"item": LATE}).status_code == 404)
check("a teacher can't buy", teacher.post("/api/shop/buy", json={"item": DRAC}).status_code == 403)

print("\nUsing them")
page = amy.get("/classes").get_data(as_text=True)
check("every page she opens puts her theme on first", 'var saved = "dracula" ||' in page)
check("  her home page shows it in use", "✓ In use" in page and "Editor themes" in page)
check("  and the rest for sale", "Buy · 1 🪙" in page)
check("a level-1 student sees the higher free themes locked",
      "🔒 Level 2" in ben.get("/classes").get_data(as_text=True))
r = ben.post("/api/me/theme", json={"theme": "dracula"})
check("a theme someone else bought isn't his", r.status_code == 403 and user(BEN).editor_theme == "")
check("  nor one above his level", ben.post("/api/me/theme", json={"theme": "solarized"}).status_code == 403)
check("  nor one that doesn't exist", ben.post("/api/me/theme", json={"theme": "<b>"}).status_code == 403)
check("high contrast is his from level 1",
      ben.post("/api/me/theme", json={"theme": "contrast"}).status_code == 200
      and 'var saved = "contrast" ||' in ben.get("/classes").get_data(as_text=True))
check("back to ordinary light/dark", ben.post("/api/me/theme", json={"theme": ""}).status_code == 200
      and 'var saved = "" ||' in ben.get("/classes").get_data(as_text=True))
amy.post("/api/me/theme", json={"theme": "solarized"})      # she's level 8: hers
db = P.SessionLocal()
for a in db.query(accounts.XpAward).filter_by(user_id=AMY):
    db.delete(a)
db.commit()
db.close()
check("a level theme stops showing when the level is lost",
      'var saved = "" ||' in amy.get("/classes").get_data(as_text=True))

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
