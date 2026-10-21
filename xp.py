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

#: The pictures a student can be: (id, label, level it unlocks at). Each is
#: static/avatars/<id>.webp — painted portraits the teacher made with an
#: image generator, cropped square to head and shoulders and shrunk to 400px
#: (about 30 KB each). test_xp.py checks every id here has its file and every
#: file has an id, because a missing file is a broken image on the board.
#:
#: A student picks one; nothing is uploaded and nothing is typed. The list
#: is the only thing a choice is checked against, so adding a picture is a
#: file in static/avatars and a line here, in all three repos.
#:
#: These replaced a builder that drew faces from parts in SVG. The teacher
#: wanted this look, which SVG drawn in code could not reach.
AVATARS = [
    ("gamer-boy", "Gamer", 1),
    ("gamer-girl", "Streamer", 1),
    ("hacker", "Hacker", 1),
    ("neon", "Neon", 1),
    ("blocky", "Blocky warrior", 1),
    ("robot", "Robot", 1),
    ("fox", "Fox ranger", 1),
    ("slime", "Glitch slime", 1),
    ("mech", "Battle mech", 2),
    ("wizard", "Cyber wizard", 3),
    ("treant", "Treant", 5),
    ("bloom", "Void bloom", 7),
]

AVATAR_IDS = [a[0] for a in AVATARS]

#: Not chosen yet: avatar.js draws a plain silhouette for "".
DEFAULT_AVATAR = ""


def avatar_of(user):
    """The picture to show for a person, or "" for the silhouette. Anything
    saved that is not on the list now — an avatar from the parts builder, a
    picture since taken out — is the silhouette, not an error."""
    saved = (user.avatar or "").strip()
    return saved if saved in AVATAR_IDS else DEFAULT_AVATAR


def clean_avatar(raw, level):
    """(id, error or "") for the picture the page sent: one on the list, and
    unlocked at this level — the page greys the rest out, but the page is
    not what decides."""
    found = [a for a in AVATARS if a[0] == raw]
    if not found:
        return None, "That picture doesn't exist."
    if found[0][2] > level:
        return None, "%s unlocks at level %d." % (found[0][1], found[0][2])
    return raw, ""


def avatars_for_page():
    return [{"id": i, "label": label, "level": lv} for i, label, lv in AVATARS]
