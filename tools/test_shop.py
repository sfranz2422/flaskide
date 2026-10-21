#!/usr/bin/env python3
"""The token shop: what tokens buy ("The token shop" in app.py).

    python3 tools/test_shop.py

WHY THIS FILE EXISTS

Tokens become real things — a late pass, exam points — so the shop must
never let a student spend a token they don't have, spend one twice, or have
one spent for them by someone who isn't their teacher. This pins:

  * a teacher's shop is stocked from xp.SHOP_STARTER once, and a teacher
    who empties the shelf isn't stocked again;
  * a student sees their teachers' shelves on their home page;
  * asking holds the tokens: a student can't ask for more than they have,
    counting what they're already waiting on; cancelling gives them back;
  * only the teacher answers; Approve spends the tokens, Decline doesn't,
    and Approve is refused if the tokens went meanwhile;
  * only the teacher stocks the shop, with sensible prices;
  * the class's XP page lists the requests, and the class page counts them.

The same file in all three editors.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(tempfile.mkdtemp(), "shop.db")
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


def q(model, **by):
    db = P.SessionLocal()
    try:
        return db.query(model).filter_by(**by).all()
    finally:
        db.close()


def plain_items(**by):
    """The teacher's ordinary items: editor themes are shop items too, but
    stocked and sold their own way (test_editor_themes.py)."""
    return [i for i in q(accounts.ShopItem, **by) if not i.theme]


def used(uid):
    return q(accounts.User, id=uid)[0].tokens_used


TEACHER = add(accounts.User(google_sub="t", email="teacher@school.org", name="Mr Franz"))
OTHER = add(accounts.User(google_sub="o", email="other@school.org", name="Ms Other"))
AMY = add(accounts.User(google_sub="a", email="amy@school.org", name="Amy Adams"))
BEN = add(accounts.User(google_sub="b", email="ben@school.org", name="Ben Brown"))
teacher, other, amy, ben = client(TEACHER), client(OTHER), client(AMY), client(BEN)
CLASS = teacher.post("/api/class", json={"name": "P4"}).get_json()["id"]
for email in ("amy@school.org", "ben@school.org"):
    add(accounts.Enrollment(class_id=CLASS, email=email, name=email))

# ------------------------------------------------------------- stocking
print("\nStocking the shop")
page = teacher.get("/teacher/shop").get_data(as_text=True)
items = plain_items(teacher_id=TEACHER)
check("the first visit stocks it from the starter list",
      len(items) == len(xp.SHOP_STARTER) and "Late pass" in page, len(items))
teacher.get("/teacher/shop")
check("  once", len(plain_items(teacher_id=TEACHER)) == len(xp.SHOP_STARTER))
for i in items:
    teacher.post("/api/shop/item/%d" % i.id, json={"active": False})
teacher.get("/teacher/shop")
check("a teacher who empties the shelf isn't stocked again",
      len(plain_items(teacher_id=TEACHER)) == len(xp.SHOP_STARTER)
      and not plain_items(teacher_id=TEACHER, active=1))
for i in items:
    teacher.post("/api/shop/item/%d" % i.id, json={"active": True})
r = teacher.post("/api/shop/item", json={"name": "Pizza party", "cost": 4,
                                         "description": "For the class"})
check("the teacher adds an item", r.status_code == 200, r.get_json())
PIZZA = r.get_json()["id"]
check("  a price has to be 1 to %d whole tokens" % xp.SHOP_MAX_COST,
      teacher.post("/api/shop/item", json={"name": "x", "cost": 0}).status_code == 400
      and teacher.post("/api/shop/item", json={"name": "x", "cost": xp.SHOP_MAX_COST + 1}).status_code == 400
      and teacher.post("/api/shop/item", json={"name": "x", "cost": "two"}).status_code == 400)
check("  and a name", teacher.post("/api/shop/item", json={"name": " ", "cost": 1}).status_code == 400)
check("a student can't stock a shop", amy.post("/api/shop/item", json={"name": "Free A", "cost": 1}).status_code == 403)
check("another teacher can't change this one's items",
      other.post("/api/shop/item/%d" % PIZZA, json={"cost": 1}).status_code == 404
      and q(accounts.ShopItem, id=PIZZA)[0].cost == 4)
SEAT = [i.id for i in items if i.name == "Pick your seat"][0]
LATE = [i.id for i in items if i.name == "Late pass"][0]

# ------------------------------------------------------------- asking
print("\nAsking")
home = amy.get("/classes").get_data(as_text=True)
check("a student sees their teacher's shop on their home page",
      'id="shop"' in home and "Pizza party" in home and "Late pass" in home)
r = amy.post("/api/shop/request", json={"item": SEAT})
check("no tokens, no asking", r.status_code == 409 and not q(accounts.ShopRequest), r.get_json())

xp.award(P.SessionLocal(), AMY, "test:tokens", 2 * xp.TOKEN_EVERY, "", P.APP_NAME)   # 2 tokens
r = amy.post("/api/shop/request", json={"item": LATE})
check("with 2 tokens she asks for a 2-token late pass", r.status_code == 200
      and r.get_json()["free"] == 0, r.get_json())
REQ = r.get_json()["request"]["id"]
check("  which holds them: nothing more", amy.post("/api/shop/request", json={"item": SEAT}).status_code == 409)
check("  and spends nothing yet", used(AMY) == 0)
home = amy.get("/classes").get_data(as_text=True)
check("  her home page says they're on hold", "2 on hold" in home and "Waiting" in home)
r = amy.post("/api/shop/request/%d/cancel" % REQ)
check("cancelling gives them back", r.status_code == 200 and r.get_json()["free"] == 2)
check("  and it's cancelled, not deleted", q(accounts.ShopRequest, id=REQ)[0].status == "cancelled")

OTHER_CLASS = other.post("/api/class", json={"name": "Elsewhere"}).get_json()["id"]
other.get("/teacher/shop")
OTHER_ITEM = q(accounts.ShopItem, teacher_id=OTHER)[0].id
check("not from a teacher who doesn't teach her",
      amy.post("/api/shop/request", json={"item": OTHER_ITEM}).status_code == 404)
teacher.post("/api/shop/item/%d" % SEAT, json={"active": False})
check("not an item off the shelf", amy.post("/api/shop/request", json={"item": SEAT}).status_code == 404)
teacher.post("/api/shop/item/%d" % SEAT, json={"active": True})
check("a teacher can't ask", teacher.post("/api/shop/request", json={"item": SEAT}).status_code == 403)

# ------------------------------------------------------------- answering
print("\nAnswering")
r1 = amy.post("/api/shop/request", json={"item": SEAT}).get_json()["request"]["id"]
r2 = amy.post("/api/shop/request", json={"item": SEAT}).get_json()["request"]["id"]
check("someone else's request can't be cancelled",
      ben.post("/api/shop/request/%d/cancel" % r1).status_code == 404
      and q(accounts.ShopRequest, id=r1)[0].status == "pending")
page = teacher.get("/teacher/class/%d/xp" % CLASS).get_data(as_text=True)
check("the class's XP page lists the requests", "Shop requests" in page
      and page.count('data-request="') == 2)
check("  and shows her tokens on hold, so they aren't used by hand", "2 on hold" in page)
check("  and the class page counts them",
      "2 to approve" in teacher.get("/teacher/class/%d" % CLASS).get_data(as_text=True))
check("a student can't approve", amy.post("/api/shop/request/%d/approve" % r1).status_code == 403)
check("  nor another teacher", other.post("/api/shop/request/%d/approve" % r1).status_code == 404
      and used(AMY) == 0)
r = teacher.post("/api/shop/request/%d/approve" % r1)
check("approving spends the tokens", r.status_code == 200 and used(AMY) == 1
      and r.get_json()["tokens"] == 1, r.get_json())
check("  once: approving again does nothing",
      teacher.post("/api/shop/request/%d/approve" % r1).status_code == 404 and used(AMY) == 1)
r = teacher.post("/api/shop/request/%d/decline" % r2)
check("declining spends nothing", r.status_code == 200 and used(AMY) == 1
      and q(accounts.ShopRequest, id=r2)[0].status == "declined")

# She asks for her last token's worth; the teacher uses it by hand meanwhile.
r3 = amy.post("/api/shop/request", json={"item": SEAT}).get_json()["request"]["id"]
db = P.SessionLocal()
db.query(accounts.User).filter_by(id=AMY).update({"tokens_used": 2})
db.commit()
db.close()
r = teacher.post("/api/shop/request/%d/approve" % r3)
check("approving is refused if the tokens went meanwhile", r.status_code == 409
      and used(AMY) == 2 and q(accounts.ShopRequest, id=r3)[0].status == "pending", r.get_json())

print()
failed = results.count(False)
print("%d checks, %s" % (len(results), "all ok" if not failed else "%d FAILED" % failed))
sys.exit(1 if failed else 0)
