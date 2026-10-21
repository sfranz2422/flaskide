"""
XP, levels, badges, tokens and avatars — the rules, in one place.

ONE FILE IN THREE REPOS, like accounts.py. A student's XP is one number
across PyIDE, WebIDE and FlaskIDE (accounts.XpAward says why), so the level
it makes, the badges it earns, the tokens it is worth and the avatar parts
it unlocks have to be the same whichever editor is showing them. Change it
here and copy it to the other two, byte for byte.

WHAT PAYS, and why each is safe to pay:

  * a question the notes mark themselves, answered right: XP_PER_POINT for
    each of its points, part of it for part right (a blank or a match).
    Paid once, when it is answered — there is one try, and the award's
    source is the question, so it can never pay again. A teacher who fixes
    a key afterwards fixes the mark, not the XP already given.
  * answering every question in an assignment's notes: ALL_ANSWERED_XP.
  * full marks on an assignment that carries a bonus (Assignment.xp_bonus).
  * XP a teacher gives by hand, with a reason.
  * a program that ran without an error: RUN_XP, at most once per
    RUN_EVERY_SECONDS of time the student was actually working, and only
    when the code has changed since the last run that paid. THE SERVER
    CANNOT SEE A RUN — it happens in the student's browser — so a student
    who knows how can claim one that never happened. That is why the limit
    is the whole design: a faked claim earns exactly what a real one would,
    so there is nothing to gain by faking it.

Nothing here touches a grade. Tokens are redeemed by the teacher, by hand,
outside the app; the Use button only lowers the count.
"""

import json
import secrets

import accounts

XP_PER_POINT = 10
ALL_ANSWERED_XP = 20
RUN_XP = 5
RUN_EVERY_SECONDS = 30 * 60
TOKEN_EVERY = 500

#: What a teacher can give or take in one go. Negative is allowed — taking
#: back XP given by mistake is the only undo there is.
GRANT_LIMIT = 1000


# --------------------------------------------------------------------------
# Levels and badges
# --------------------------------------------------------------------------

#: The XP each level starts at. Each step is a little longer than the last,
#: so early levels come quickly and later ones mean something. Past the end
#: of the list every level is LEVEL_STEP_AFTER more.
LEVEL_STARTS = [0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200, 4000]
LEVEL_STEP_AFTER = 1000

LEVEL_TITLES = ["Newcomer", "Hello, World", "Looper", "Bug Hunter",
                "Function Fan", "List Wrangler", "Code Crafter",
                "Algorithm Ace", "Python Pro", "Code Wizard", "Legend"]

#: (XP, id, name, icon). Earned by reaching the XP, kept for ever after
#: unless a teacher takes XP back below it — they are worked out from the
#: total, never stored, so they can't disagree with it.
BADGES = [
    (10, "first-steps", "First Steps", "\U0001F463"),
    (100, "century", "Century", "\U0001F4AF"),
    (250, "rising-star", "Rising Star", "⭐"),
    (500, "first-token", "First Token", "\U0001FA99"),
    (1000, "thousand-club", "Thousand Club", "\U0001F3C6"),
    (2000, "liftoff", "Liftoff", "\U0001F680"),
    (3500, "diamond", "Diamond Coder", "\U0001F48E"),
    (5000, "royalty", "Code Royalty", "\U0001F451"),
    (7500, "dragon", "Dragon Tamer", "\U0001F409"),
    (10000, "galaxy", "Galaxy Brain", "\U0001F30C"),
]


def level_start(level):
    """The XP that level `level` (1 and up) begins at."""
    if level <= len(LEVEL_STARTS):
        return LEVEL_STARTS[level - 1]
    return LEVEL_STARTS[-1] + (level - len(LEVEL_STARTS)) * LEVEL_STEP_AFTER


def level_of(total):
    level = 1
    while level_start(level + 1) <= total:
        level += 1
    return level


def title_of(level):
    return LEVEL_TITLES[min(level, len(LEVEL_TITLES)) - 1]


def tokens_earned(total):
    return max(0, total) // TOKEN_EVERY


def summary(total, tokens_used=0):
    """Everything a page shows about one total, as plain data."""
    total = int(total or 0)
    level = level_of(total)
    start, nxt = level_start(level), level_start(level + 1)
    return {
        "xp": total,
        "level": level,
        "title": title_of(level),
        "level_start": start,
        "level_next": nxt,
        # How far through this level, 0 to 100, for the bar.
        "progress": int(100 * (total - start) / (nxt - start)) if total > start else 0,
        "to_next": nxt - total,
        "tokens": max(0, tokens_earned(total) - (tokens_used or 0)),
        "tokens_earned": tokens_earned(total),
        "badges": [{"id": b, "name": n, "icon": i, "xp": x, "have": total >= x}
                   for x, b, n, i in BADGES],
    }


# --------------------------------------------------------------------------
# Paying it
# --------------------------------------------------------------------------

def award(db, user_id, source, xp, reason, app, detail="", by_id=None):
    """Give `xp` to a person for `source`, once. The XP given, or 0 when
    this source has paid them already (or is worth nothing).

    The unique constraint is the guard, not a look first: two workers can
    both look, see nothing, and both pay. Commits on its own, so call it
    after whatever the request was for has been committed — a failure here
    must never take the student's answer or score down with it."""
    xp = int(round(xp or 0))
    if not xp or not user_id:
        return 0
    db.add(accounts.XpAward(user_id=user_id, source=source[:80], xp=xp,
                            reason=(reason or "")[:200], app=app,
                            detail=(detail or "")[:64], by_id=by_id))
    try:
        db.commit()
        return xp
    except Exception:
        db.rollback()
        return 0


def grant_source():
    """A teacher's grant is a new thing every time, so its source is new."""
    return "grant:" + secrets.token_hex(8)


def totals(db, user_ids):
    """{user id: XP} for these people. Missing means none yet — 0."""
    from sqlalchemy import func
    ids = list(user_ids)
    if not ids:
        return {}
    rows = (db.query(accounts.XpAward.user_id, func.sum(accounts.XpAward.xp))
              .filter(accounts.XpAward.user_id.in_(ids))
              .group_by(accounts.XpAward.user_id))
    return {uid: int(total or 0) for uid, total in rows}


def total(db, user_id):
    return totals(db, [user_id]).get(user_id, 0)


def recent(db, user_id, limit=8):
    return (db.query(accounts.XpAward)
              .filter_by(user_id=user_id)
              .order_by(accounts.XpAward.created_at.desc(),
                        accounts.XpAward.id.desc())
              .limit(limit).all())


def board_name(user):
    """First name and last initial — what a leaderboard shows, never the
    email. Google's first and last name when we have them (sign-in stores
    them); otherwise the full name split at its last space."""
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    if not first:
        parts = (user.name or "").split()
        if parts:
            first = parts[0]
            last = last or (parts[-1] if len(parts) > 1 else "")
    if not first:
        return "Student"
    return first + (" " + last[0].upper() + "." if last else "")


# --------------------------------------------------------------------------
# Avatars
# --------------------------------------------------------------------------

#: Every part an avatar is built from, by kind, in the order the editor
#: shows them: (id, label, level it unlocks at). static/avatar.js draws each
#: id, and test_xp.py checks it can draw every one listed here.
AVATAR_PARTS = {
    "skin": [("s1", "Light", 1), ("s2", "Fair", 1), ("s3", "Medium", 1),
             ("s4", "Tan", 1), ("s5", "Brown", 1), ("s6", "Deep", 1)],
    "face": [("round", "Round", 1), ("oval", "Oval", 1), ("square", "Square", 1)],
    "hair": [("none", "None", 1), ("short", "Short", 1), ("buzz", "Buzz", 1),
             ("long", "Long", 1), ("curly", "Curly", 1), ("bun", "Bun", 1),
             ("spiky", "Spiky", 3), ("mohawk", "Mohawk", 5)],
    "hair_color": [("black", "Black", 1), ("brown", "Brown", 1),
                   ("blonde", "Blonde", 1), ("red", "Red", 1),
                   ("gray", "Gray", 1), ("blue", "Blue", 4),
                   ("pink", "Pink", 4), ("green", "Green", 6),
                   ("gold", "Gold", 9)],
    "eyes": [("dots", "Dots", 1), ("round", "Round", 1), ("happy", "Happy", 1),
             ("sleepy", "Sleepy", 2), ("wink", "Wink", 3), ("stars", "Stars", 7)],
    "mouth": [("smile", "Smile", 1), ("grin", "Grin", 1), ("flat", "Flat", 1),
              ("open", "Open", 2), ("tongue", "Tongue", 5)],
    "glasses": [("none", "None", 1), ("round", "Round", 1),
                ("square", "Square", 2), ("shades", "Shades", 4),
                ("visor", "Visor", 8)],
    "hat": [("none", "None", 1), ("beanie", "Beanie", 2), ("cap", "Cap", 3),
            ("headphones", "Headphones", 5), ("wizard", "Wizard hat", 9),
            ("crown", "Crown", 10)],
    "background": [("sky", "Sky", 1), ("mint", "Mint", 1), ("peach", "Peach", 1),
                   ("lilac", "Lilac", 1), ("night", "Night", 3),
                   ("sunset", "Sunset", 6), ("galaxy", "Galaxy", 8)],
}

AVATAR_KINDS = list(AVATAR_PARTS)

DEFAULT_AVATAR = {kind: parts[0][0] for kind, parts in AVATAR_PARTS.items()}
DEFAULT_AVATAR.update(hair="short", hair_color="brown", eyes="round")


def avatar_of(user):
    """The avatar to draw for a person: their saved one, with anything
    unreadable or unknown replaced by the default's part."""
    out = dict(DEFAULT_AVATAR)
    try:
        saved = json.loads(user.avatar or "{}")
    except (ValueError, TypeError):
        saved = {}
    if isinstance(saved, dict):
        for kind, parts in AVATAR_PARTS.items():
            if saved.get(kind) in {p[0] for p in parts}:
                out[kind] = saved[kind]
    return out


def clean_avatar(raw, level):
    """(avatar, error or "") for what the editor sent. Only known parts,
    and only parts this level has unlocked — the page greys the rest out,
    but the page is not what decides."""
    if not isinstance(raw, dict):
        return None, "That avatar couldn't be read."
    out = {}
    for kind, parts in AVATAR_PARTS.items():
        want = raw.get(kind, DEFAULT_AVATAR[kind])
        found = [p for p in parts if p[0] == want]
        if not found:
            return None, "That avatar has a part that doesn't exist."
        if found[0][2] > level:
            return None, "%s unlocks at level %d." % (found[0][1], found[0][2])
        out[kind] = want
    return out, ""


def parts_for_page():
    """The parts list as the avatar editor wants it. A list, not a dict:
    Jinja's tojson sorts a dict's keys, and the editor came out Background,
    Eyes, Face… instead of starting from the face."""
    return [{"kind": kind,
             "options": [{"id": i, "label": label, "level": lv} for i, label, lv in parts]}
            for kind, parts in AVATAR_PARTS.items()]
