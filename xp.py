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

import re
import secrets

import accounts

XP_PER_POINT = 10
ALL_ANSWERED_XP = 20
RUN_XP = 2
RUN_EVERY_SECONDS = 30 * 60
#: The XP a token costs. Was 500; raised to 1000 on 2026-10-21 by the
#: teacher. Tokens are worked out from XP, never stored (summary), so the
#: new price applies to everyone at once — a student who had earned tokens
#: at 500 has half as many, and any they had already used beyond that show
#: as none left, never as a debt.
TOKEN_EVERY = 1000

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
    (500, "halfway", "Halfway There", "\U0001F3AF"),
    (1000, "first-token", "First Token", "\U0001FA99"),
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
        "token_every": TOKEN_EVERY,
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
# The token shop
# --------------------------------------------------------------------------

#: What a teacher's shop starts with, the first time they open it: (name,
#: tokens, what it is). Theirs to change, price or take off the shelf. The
#: ones that touch a grade cost more, so they stay worth saving for.
SHOP_STARTER = [
    ("Pick your seat", 1, "Sit where you like for one class."),
    ("Music while you work", 1, "Headphones during work time, for one class."),
    ("A hint on a quiz", 1, "One hint from your teacher on one quiz question."),
    ("Name tomorrow's example", 1, "Choose the variable names or the theme of the next example."),
    ("Run the random event", 1, "You press the button at the start of class."),
    ("Late pass", 2, "Turn one assignment in a day late, no penalty."),
    ("Redo", 2, "Resubmit one assignment for a new score."),
    ("Notes card", 2, "One index card of notes on a quiz."),
    ("Drop a quiz score", 3, "Your lowest quiz score doesn't count."),
    ("Exam bonus", 3, "+5% on a test or exam."),
    ("Homework pass", 3, "Skip one homework assignment."),
    ("Design a challenge", 5, "Write a challenge or quest for the whole class."),
]

#: Editor themes: (id, name, how it's got, what it looks like). "level N" is
#: free from that level; "token" is bought in the teacher's shop (its price
#: is the shop item's, starting at THEME_PRICE). Each id has a block in
#: static/style.css — [data-theme="<id>"] and .cm-s-pyide-<id> — and
#: test_editor_themes.py checks it does, in every app, since a missing one
#: would sell a theme that changes nothing.
EDITOR_THEMES = [
    ("contrast", "High contrast", "level 1", "White on black, bright yellow — the easiest to read."),
    ("ocean", "Ocean", "level 2", "Deep blues and sea green."),
    ("forest", "Forest", "level 3", "Greens and warm browns."),
    ("solarized", "Solarized", "level 4", "The classic soft blue-grey."),
    ("dracula", "Dracula", "token", "Purple and pink on near-black."),
    ("monokai", "Monokai", "token", "The warm, bright code colors programmers love."),
    ("synthwave", "Synthwave", "token", "Neon pink and cyan, straight out of the 80s."),
    ("retro", "Retro terminal", "token", "Green on black, like a 1980s computer."),
    ("sunset", "Sunset", "token", "Warm oranges and purples."),
]
THEME_PRICE = 1
THEME_IDS = [t[0] for t in EDITOR_THEMES]


def theme_level(theme_id):
    """The level a free theme unlocks at, or None for one bought."""
    for i, _, how, _ in EDITOR_THEMES:
        if i == theme_id and how.startswith("level "):
            return int(how.split()[1])
    return None


def owned_themes(user):
    return [t for t in (user.themes_owned or "").split(",") if t in THEME_IDS]


def theme_allowed(user, theme_id, level):
    """Whether this person may use this theme now: "" (the ordinary light
    and dark) always; a free one from its level; a bought one if owned."""
    if not theme_id:
        return True
    if theme_id not in THEME_IDS:
        return False
    lv = theme_level(theme_id)
    if lv is not None:
        return level >= lv
    return theme_id in owned_themes(user)


#: The most one item can cost, and the most items a shop can hold.
SHOP_MAX_COST = 100
SHOP_MAX_ITEMS = 60


# --------------------------------------------------------------------------
# Rewards, penalties and random events
# --------------------------------------------------------------------------

#: The reasons the teacher picks from on a class's XP page: (reason, XP).
#: Programming-themed, sized to this XP — a level is a few hundred XP, so
#: these are the size of a question or two, not of a level. The teacher can
#: still type any amount and reason.
BEHAVIORS = [
    ("Helped debug a teammate's code", 10),
    ("Found a bug in the class notes", 10),
    ("Answered a question in class", 10),
    ("Clean, well-commented code", 15),
    ("Solved the challenge problem", 20),
    ("Focused and hard-working today", 20),
    ("Off task / distracting others", -5),
    ("Late to class", -5),
    ("Missing classwork", -10),
]

#: Random events, drawn by the teacher's button (app.py, class_event).
#: `who` is everyone in the class ("all"), one random student ("one"), `n`
#: random students ("some"), the student with the least XP ("lowest") or the
#: most ("highest"). `weight` makes the good ones likelier than the bad.
#: A penalty never takes a student below 0 XP (penalty_for).
EVENTS = [
    {"id": "first-try", "title": "It compiled on the first try!", "icon": "\U0001F389",
     "text": "Every program in the room runs first time. Everyone gains 5 XP.",
     "who": "all", "xp": 5, "weight": 3},
    {"id": "rubber-duck", "title": "Rubber duck debugging", "icon": "\U0001F986",
     "text": "A rubber duck on one desk starts giving excellent advice. One student gains 15 XP.",
     "who": "one", "xp": 15, "weight": 4},
    {"id": "mentor", "title": "A senior dev drops by", "icon": "\U0001F9D1\u200D\U0001F4BB",
     "text": "A senior developer mentors the newest coder. The student with the least XP gains 15 XP.",
     "who": "lowest", "xp": 15, "weight": 4},
    {"id": "hackathon", "title": "Hackathon winners", "icon": "\U0001F3C6",
     "text": "Three students' weekend project takes first place. They each gain 20 XP.",
     "who": "some", "n": 3, "xp": 20, "weight": 2},
    {"id": "missing-colon", "title": "Found the missing colon", "icon": "\U0001F50D",
     "text": "After an hour of staring, one student spots it. They gain 10 XP.",
     "who": "one", "xp": 10, "weight": 3},
    {"id": "coffee", "title": "The coffee machine is fixed", "icon": "\u2615",
     "text": "Productivity soars. Everyone gains 3 XP.",
     "who": "all", "xp": 3, "weight": 3},
    {"id": "legacy-bounty", "title": "Legacy code bounty", "icon": "\U0001F4B0",
     "text": "One student untangles code nobody has touched since 1998. They gain 50 XP.",
     "who": "one", "xp": 50, "weight": 1},
    {"id": "pair-programming", "title": "Pair programming", "icon": "\U0001F46F",
     "text": "Two students share a keyboard and fix everything. They each gain 10 XP.",
     "who": "some", "n": 2, "xp": 10, "weight": 3},
    {"id": "code-review", "title": "Glowing code review", "icon": "\u2B50",
     "text": "A reviewer calls one student's code \"beautiful\". They gain 10 XP.",
     "who": "one", "xp": 10, "weight": 3},
    {"id": "all-green", "title": "All tests pass", "icon": "\u2705",
     "text": "Green checks across the board. Everyone gains 4 XP.",
     "who": "all", "xp": 4, "weight": 3},
    {"id": "repo-star", "title": "Your repo got a star", "icon": "\U0001F31F",
     "text": "A stranger on the internet loves one student's project. They gain 20 XP.",
     "who": "one", "xp": 20, "weight": 2},
    {"id": "intern", "title": "It was the intern's fault", "icon": "\U0001F937",
     "text": "git blame clears the student with the least XP. They gain 10 XP.",
     "who": "lowest", "xp": 10, "weight": 3},
    {"id": "pizza", "title": "Pizza for the dev team", "icon": "\U0001F355",
     "text": "Someone ordered pizza for the release. Everyone gains 4 XP.",
     "who": "all", "xp": 4, "weight": 2},
    {"id": "midnight-deploy", "title": "The midnight deploy went perfectly", "icon": "\U0001F680",
     "text": "Three students shipped it and nothing broke. They each gain 10 XP.",
     "who": "some", "n": 3, "xp": 10, "weight": 2},
    {"id": "forgot-save", "title": "Forgot to save", "icon": "\U0001F4BE",
     "text": "One student's laptop died before Ctrl+S. They lose 5 XP.",
     "who": "one", "xp": -5, "weight": 2},
    {"id": "indentation", "title": "IndentationError", "icon": "\u21E5",
     "text": "Tabs and spaces, mixed. One student loses 3 XP.",
     "who": "one", "xp": -3, "weight": 2},
    {"id": "wifi-down", "title": "The Wi-Fi went down", "icon": "\U0001F4F6",
     "text": "Nobody can look anything up. Everyone loses 2 XP.",
     "who": "all", "xp": -2, "weight": 1},
    {"id": "dependency", "title": "A dependency broke overnight", "icon": "\U0001F4E6",
     "text": "Someone else's update broke three students' code. They each lose 3 XP.",
     "who": "some", "n": 3, "xp": -3, "weight": 1},
    {"id": "force-push", "title": "git push --force", "icon": "\u26A0\uFE0F",
     "text": "One student overwrote everyone's work. They lose 10 XP.",
     "who": "one", "xp": -10, "weight": 1},
    {"id": "prod-bug", "title": "Unexpected bug in production", "icon": "\U0001F41B",
     "text": "Something nobody tested breaks for real users. Everyone loses 5 XP.",
     "who": "all", "xp": -5, "weight": 2},
    {"id": "infinite-loop", "title": "Infinite loop!", "icon": "\u267E\uFE0F",
     "text": "One student's program never ends, and neither does the afternoon. They lose 5 XP.",
     "who": "one", "xp": -5, "weight": 2},
    {"id": "merge-conflict", "title": "Merge conflict", "icon": "\U0001F500",
     "text": "Two students changed the same line. They each lose 5 XP.",
     "who": "some", "n": 2, "xp": -5, "weight": 2},
    {"id": "server-down", "title": "The server crashed", "icon": "\U0001F4A5",
     "text": "Nobody saved. Everyone loses 3 XP.",
     "who": "all", "xp": -3, "weight": 1},
    {"id": "off-by-one", "title": "Off-by-one error", "icon": "\U0001F522",
     "text": "Even the best make it. The student with the most XP loses 10 XP.",
     "who": "highest", "xp": -10, "weight": 1},
]

EVENT_IDS = [e["id"] for e in EVENTS]


def pick_event(rng):
    """One event, at random by weight. `rng` is a random.Random, so a test
    can hand it a seeded one."""
    roll = rng.uniform(0, sum(e["weight"] for e in EVENTS))
    for e in EVENTS:
        roll -= e["weight"]
        if roll <= 0:
            return e
    return EVENTS[-1]


def event_targets(event, people, have, rng):
    """Which of `people` (Users) an event hits, given their XP in `have`.
    The least or most XP is one student; a tie is settled at random, so it
    isn't always whoever sorts first."""
    if not people:
        return []
    who = event["who"]
    if who == "all":
        return list(people)
    if who == "some":
        return rng.sample(list(people), min(event.get("n", 1), len(people)))
    if who in ("lowest", "highest"):
        score = [have.get(u.id, 0) for u in people]
        edge = min(score) if who == "lowest" else max(score)
        return [rng.choice([u for u in people if have.get(u.id, 0) == edge])]
    return [rng.choice(list(people))]


def penalty_for(amount, current):
    """What XP a change really moves: all of a reward, but no more of a
    penalty than the student has. XP never goes below 0 — a level-1 student
    on 3 XP who is late loses 3, not 5."""
    if amount >= 0:
        return amount
    return max(amount, -max(0, current))


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
    ("coder", "Coder", 1),
    ("techie", "Techie", 1),
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


#: A student's own approved photo, as the avatar column holds it. The slug
#: is accounts.new_id's alphabet; anything else is not one.
PHOTO_AVATAR = re.compile(r"^photo:[a-z0-9]{4,16}$")


def avatar_of(user):
    """The picture to show for a person, or "" for the silhouette. Anything
    saved that is not on the list now — an avatar from the parts builder, a
    picture since taken out — is the silhouette, not an error. A photo is
    only ever written here by a teacher's approval (app.py), so a well-
    formed one is shown."""
    saved = (user.avatar or "").strip()
    if saved in AVATAR_IDS or PHOTO_AVATAR.match(saved):
        return saved
    return DEFAULT_AVATAR


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
