"""
The tutorial library: a teacher's tutorials (the markdown students read —
slides, questions, tests) and teacher decks (HTML lessons they present
from), each kept ONCE and linked to any number of assignments.

THE SAME FILE IN PYIDE, WEBIDE, FLASKIDE AND GAMEIDE (backend/), like
accounts.py. What differs between them — the editor's name, where its
notes file is, how it keeps answer keys — comes in through init()'s hooks.
Change it in one, copy it to the others.

Why it exists. Notes used to live only inside each assignment
(Assignment.files), and copying an assignment to another period copied
them. The copies drifted: the teacher's own file on their computer, Period
2's and Period 5's were three different things. Now a tutorial is one row
(LibraryItem), and an assignment says which it uses (Assignment.tutorial_id).

Write-through, not read-through. A linked assignment still holds the
tutorial's text in its notes file, written there whenever the tutorial is
saved (fan_out). Every way a student reaches notes — the draft, the lesson
page, the live link, the view-only link — reads that file and takes the
answers out on the way (quiz.redact), and answer keys are kept per
assignment; none of it had to change, and a route that forgot the library
cannot leak or lose anything. The library is the ONLY place a tutorial is
edited (the teacher's call): an assignment's notes are never written
anywhere else, so nothing can overwrite a tutorial behind its back.

tutorial_id: NULL means the import (import_existing) hasn't looked at the
assignment yet; 0 means unlinked on purpose, its notes its own copy.
"""
import base64
import json
import re
import secrets

from flask import Blueprint, Response, jsonify, redirect, render_template, request
from sqlalchemy import func

import accounts

bp = Blueprint("library", __name__)

KINDS = ("tutorial", "deck")
MAX_TUTORIAL = 1_500_000          # characters of markdown
MAX_DECK = 8_000_000              # bytes of HTML (PyIDE's DECK_MAX_BYTES)
MAX_UPLOAD_FILES = 200
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

H = {}   # the editor's hooks, set by init()


def init(app, **hooks):
    """Registers the library in an editor. Hooks:
        app_name      "pyide", "webide"…: whose tutorials these are
        session       makes a database session
        current_user  (db) -> User or None
        is_teacher    (user) -> bool
        notes_of      (assignment) -> its notes text
        write_notes   (db, assignment, text): put text in its notes and keep
                      its answer keys; commits
        page          () -> dict for the pages: brand, logo, ns, home, user_theme…
        assignment_url (assignment) -> the teacher's page for it
      and, optionally:
        old_decks     (db, user) -> [(assignment, name, html)] from an old table
        known         (text) -> {origin, title} for notes that ARE a known
                      tutorial (GameIDE's built-ins), else None
        page_url      the library's page, when it's the editor's own (GameIDE's
                      is a React page): /teacher/tutorials goes there
        visibilities  who a tutorial may be shown to (default only "private")
        is_admin      (user) -> bool: may make one "site" wide
    """
    H.update(hooks)
    app.register_blueprint(bp)


# ---------------------------------------------------------------- reading markdown

_FENCE = re.compile(r"^\s*(```+|~~~+)")


def title_of(text, fallback):
    """A tutorial's title: its header's `title:` (GameIDE's tutorials have
    one), else its first # heading outside code, else the fallback."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for ln in lines[1:40]:
            if ln.strip() == "---":
                break
            m = re.match(r"\s*title\s*:\s*(.+)$", ln, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()[:200]
    fence = None
    for ln in lines:
        f = _FENCE.match(ln)
        if f:
            fence = None if fence else f.group(1)
            continue
        if fence is None:
            m = re.match(r"#{1,3}\s+(.+?)\s*#*\s*$", ln)
            if m:
                return re.sub(r"[*_`]", "", m.group(1)).strip()[:200] or fallback
    return fallback


def _new_slug(db):
    while True:
        slug = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        if not db.query(accounts.LibraryItem).filter_by(slug=slug).first():
            return slug


# ---------------------------------------------------------------- who may

def _teacher(db):
    user = H["current_user"](db)
    if user is None or not H["is_teacher"](user):
        return None, (jsonify(error="Only a teacher can do that."), 403)
    return user, None


def _own_item(db, user, slug):
    item = db.query(accounts.LibraryItem).filter_by(slug=str(slug)[:16], app=H["app_name"]).first()
    if item is None or item.teacher_id != user.id or item.archived:
        return None
    return item


def _own_assignments(db, user):
    return (db.query(accounts.Assignment)
            .filter_by(teacher_id=user.id, app=H["app_name"])
            .order_by(accounts.Assignment.created_at.desc()).all())


# ---------------------------------------------------------------- keeping assignments in step

def linked(db, item):
    field = accounts.Assignment.tutorial_id if item.kind == "tutorial" else accounts.Assignment.deck_id
    return db.query(accounts.Assignment).filter(field == item.id, accounts.Assignment.app == H["app_name"]).all()


def fan_out(db, item):
    """Every assignment linked to this tutorial gets its text as its notes
    (and keeps its answer keys, by the editor's own write_notes)."""
    if item.kind != "tutorial":
        return 0
    n = 0
    for a in linked(db, item):
        if H["notes_of"](a) != item.body:
            H["write_notes"](db, a, item.body)
            n += 1
    return n


def save(db, item, body, title=None):
    item.body = body
    item.size = len(body.encode("utf-8"))
    if title is not None:
        item.title = title
    item.updated_at = accounts.now()
    db.commit()
    return fan_out(db, item)


def link(db, item, a):
    if item.kind == "tutorial":
        a.tutorial_id = item.id
        db.commit()
        if H["notes_of"](a) != item.body:
            H["write_notes"](db, a, item.body)
    else:
        a.deck_id = item.id
        db.commit()


def unlink(db, item, a):
    """Its notes stay as they are, its own copy now (tutorial_id 0, so the
    import never takes it back)."""
    if item.kind == "tutorial" and a.tutorial_id == item.id:
        a.tutorial_id = 0
    elif item.kind == "deck" and a.deck_id == item.id:
        a.deck_id = None
    db.commit()


def builtin_row(db, teacher_id, origin, title, body):
    """The teacher's row for a known tutorial (origin "builtin:<name>"),
    made the first time it's used."""
    row = (db.query(accounts.LibraryItem)
           .filter_by(teacher_id=teacher_id, app=H["app_name"], origin=origin, archived=0).first())
    if row is None:
        row = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=teacher_id, kind="tutorial",
                                   title=title[:200], body=body, size=len(body.encode("utf-8")), origin=origin)
        db.add(row)
        db.flush()
    return row


def adopt(db, a, title=None):
    """A new assignment's notes, made its own tutorial at once (a lesson's
    starter, a project published from the editor). Not left to the import:
    it would merge every untouched lesson starter, word for word the same,
    into one tutorial."""
    text = H["notes_of"](a)
    if a.tutorial_id is not None or not text.strip():
        return None
    item = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=a.teacher_id, kind="tutorial",
                                title=(title or title_of(text, a.title))[:200], body=text,
                                size=len(text.encode("utf-8")))
    db.add(item)
    db.flush()
    a.tutorial_id = item.id
    db.commit()
    return item


def import_existing(db, user):
    """Every assignment of theirs with notes and no tutorial yet gets one:
    identical notes make ONE tutorial, linked to all of them (a period's
    copies of the same lesson). Runs each time the library opens, so notes
    added before the library existed are never lost from it; an assignment
    is taken once (tutorial_id set), and one unlinked on purpose (0) never."""
    todo = (db.query(accounts.Assignment)
            .filter(accounts.Assignment.teacher_id == user.id,
                    accounts.Assignment.app == H["app_name"],
                    accounts.Assignment.tutorial_id.is_(None))
            .order_by(accounts.Assignment.created_at).with_for_update().all())
    groups = {}
    for a in todo:
        text = H["notes_of"](a)
        if text.strip():
            groups.setdefault(text, []).append(a)
    made = 0
    for text, items in groups.items():
        # A known tutorial (GameIDE's built-ins): the teacher's row for it,
        # found by where it came from, so it's one row however its text changes.
        known = H["known"](text) if H.get("known") else None
        if known:
            same = builtin_row(db, user.id, known["origin"], known["title"], text)
            for a in items:
                a.tutorial_id = same.id
            continue
        # Already in the library word for word (another period's copy imported
        # earlier, or the same file uploaded): link to that one.
        same = (db.query(accounts.LibraryItem)
                .filter_by(teacher_id=user.id, app=H["app_name"], kind="tutorial", archived=0, body=text).first())
        if same is None:
            same = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=user.id, kind="tutorial",
                                        title=title_of(text, items[0].title), body=text,
                                        size=len(text.encode("utf-8")))
            db.add(same)
            db.flush()
            made += 1
        for a in items:
            a.tutorial_id = same.id
    db.commit()
    # Teacher decks from before the library (an editor's own old table, by
    # its old_decks hook): each becomes a library deck, linked to its
    # assignment; the same file on several assignments, one deck.
    if H.get("old_decks"):
        decks = {}
        for a, name, html in H["old_decks"](db, user):
            decks.setdefault(html, []).append((a, name))
        for html, uses in decks.items():
            same = (db.query(accounts.LibraryItem)
                    .filter_by(teacher_id=user.id, app=H["app_name"], kind="deck", archived=0, body=html).first())
            if same is None:
                name = re.sub(r"\.html?$", "", uses[0][1] or "", flags=re.I).strip() or uses[0][0].title
                same = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=user.id, kind="deck",
                                            title=name[:200], body=html, size=len(html.encode("utf-8")))
                db.add(same)
                db.flush()
                made += 1
            for a, _ in uses:
                a.deck_id = same.id
        db.commit()
    return made


def deck_of(db, a):
    """An assignment's library deck (a LibraryItem), or None."""
    if not a.deck_id:
        return None
    d = db.query(accounts.LibraryItem).get(a.deck_id)
    return d if d is not None and not d.archived and d.kind == "deck" else None


def set_deck(db, a, name, html):
    """The assignment page's Upload / Replace teacher lesson: into the
    library — its deck replaced, or a new one made and linked."""
    d = deck_of(db, a)
    if d is None:
        title = re.sub(r"\.html?$", "", name or "", flags=re.I).strip() or a.title
        d = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=a.teacher_id, kind="deck",
                                 title=title[:200], body=html, size=len(html.encode("utf-8")))
        db.add(d)
        db.flush()
        a.deck_id = d.id
        db.commit()
    else:
        # Named as the file just uploaded (Download gives it that name back).
        save(db, d, html, re.sub(r"\.html?$", "", name or "", flags=re.I).strip()[:200] or None)
    return d


# ---------------------------------------------------------------- what the page is sent

def _class_names(db, assignment_ids):
    """assignment id -> its class's name (an assignment is in one class at most)."""
    if not assignment_ids:
        return {}
    rows = (db.query(accounts.ClassItem.assignment_id, accounts.Course.name)
            .join(accounts.Course, accounts.Course.id == accounts.ClassItem.class_id)
            .filter(accounts.ClassItem.assignment_id.in_(assignment_ids)).all())
    return {aid: name for aid, name in rows}


def _assignment_out(a, classes):
    return {"slug": a.slug, "title": a.title, "kind": a.kind, "class": classes.get(a.id, ""),
            "archived": bool(a.archived), "url": H["assignment_url"](a)}


def _item_out(item, uses):
    return {"id": item.id, "slug": item.slug, "kind": item.kind, "title": item.title, "size": item.size, "origin": item.origin,
            "updated": item.updated_at.isoformat() + "Z", "visibility": item.visibility, "uses": uses}


def tutorial_box(db, user, a):
    """What an assignment's page shows of its tutorial (and deck): which it
    is, how many other assignments use it, and the teacher's other tutorials
    to choose from."""
    tut = db.query(accounts.LibraryItem).get(a.tutorial_id) if a.tutorial_id else None
    if tut is not None and (tut.teacher_id != user.id or tut.archived):
        tut = None
    others = 0
    if tut is not None:
        others = len([x for x in linked(db, tut) if x.id != a.id])
    choices = (db.query(accounts.LibraryItem.slug, accounts.LibraryItem.title)
               .filter_by(teacher_id=user.id, app=H["app_name"], kind="tutorial", archived=0)
               .order_by(accounts.LibraryItem.title).all())
    return {"tutorial": tut, "tutorial_others": others,
            "tutorial_choices": [{"slug": s, "title": t} for s, t in choices]}


# ---------------------------------------------------------------- pages

@bp.get("/teacher/tutorials")
def library_page():
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return Response("Only a teacher can open the tutorial library.", 403)
        if H.get("page_url"):
            return redirect(H["page_url"])
        import_existing(db, user)
        return render_template("library.html", **H["page"](db, user))
    finally:
        db.close()


@bp.get("/teacher/tutorials/<slug>/edit")
def library_edit_page(slug):
    """PresMaker, as the library's editor (templates/presmaker.html, made by
    tools/sync_presmaker.py): a tutorial in its markdown editor, a teacher
    deck in its slides editor. Saving comes back here (save_item)."""
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return Response("Only a teacher can edit tutorials.", 403)
        item = _own_item(db, user, slug)
        if item is None:
            return Response("No such tutorial.", 404)
        uses = linked(db, item)
        classes = _class_names(db, [a.id for a in uses])
        page = H["page"](db, user)
        server = {"slug": item.slug, "title": item.title, "kind": item.kind, "body": item.body,
                  "saveUrl": "/api/library/" + item.slug, "libraryUrl": "/teacher/tutorials", "brand": page["brand"],
                  # PyIDE's tests have a form; the others' are typed as lines,
                  # read by their own autograde.js as they're typed.
                  "tests": page.get("pm_tests", "form"), "testExamples": page.get("pm_test_examples", []),
                  # GameIDE's: ```check lines, read by its own editor, not autograde.js.
                  "testsFence": page.get("pm_tests_fence", "tests"), "testsUnchecked": page.get("pm_tests_fence") == "check"}
        return render_template("presmaker.html", item=item, uses=[_assignment_out(a, classes) for a in uses],
                               pm_server=server, **page)
    finally:
        db.close()


# ---------------------------------------------------------------- the API

@bp.get("/api/library")
def list_items():
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        import_existing(db, user)
        items = (db.query(accounts.LibraryItem).filter_by(teacher_id=user.id, app=H["app_name"], archived=0)
                 .order_by(accounts.LibraryItem.updated_at.desc()).all())
        mine = _own_assignments(db, user)
        classes = _class_names(db, [a.id for a in mine])
        uses = {}
        for a in mine:
            for field, kind in ((a.tutorial_id, "tutorial"), (a.deck_id, "deck")):
                if field:
                    uses.setdefault((kind, field), []).append(_assignment_out(a, classes))
        return jsonify(items=[_item_out(i, uses.get((i.kind, i.id), [])) for i in items],
                       assignments=[dict(_assignment_out(a, classes), tutorial=a.tutorial_id or None, deck=a.deck_id)
                                    for a in mine])
    finally:
        db.close()


def _clean_body(kind, body):
    if not isinstance(body, str):
        return None, "Nothing to save."
    if kind == "tutorial" and len(body) > MAX_TUTORIAL:
        return None, "That tutorial is too long to save."
    if kind == "deck":
        if len(body.encode("utf-8")) > MAX_DECK:
            return None, "That deck is too big (8 MB at most)."
        if body.strip() and "<" not in body[:2000]:
            return None, "A teacher deck is an HTML file."
    return body, None


@bp.post("/api/library")
def new_item():
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        data = request.get_json(silent=True) or {}
        kind = data.get("kind", "tutorial")
        if kind not in KINDS:
            return jsonify(error="Not a kind of library item."), 400
        body, problem = _clean_body(kind, data.get("body", ""))
        if problem:
            return jsonify(error=problem), 400
        title = str(data.get("title") or "").strip()[:200] or title_of(body, "Untitled tutorial")
        origin = str(data.get("origin") or "")
        if origin:
            # A known tutorial taken into the library (GameIDE's built-ins):
            # their one row for it, made now if it isn't yet.
            if not re.fullmatch(r"builtin:[a-z0-9-]{1,40}", origin) or not H.get("known"):
                return jsonify(error="Not a tutorial the library knows."), 400
            item = builtin_row(db, user.id, origin, title, body)
            db.commit()
        else:
            item = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=user.id, kind=kind,
                                        title=title, body=body, size=len(body.encode("utf-8")))
            db.add(item)
            db.commit()
        # Made for an assignment ("New tutorial" in its Tutorial box): linked to it at once.
        if data.get("linkTo"):
            a = db.query(accounts.Assignment).filter_by(slug=str(data["linkTo"])[:16], app=H["app_name"],
                                                        teacher_id=user.id).first()
            if a is not None:
                link(db, item, a)
        return jsonify(slug=item.slug), 201
    finally:
        db.close()


@bp.get("/api/library/<slug>")
def get_item(slug):
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        return jsonify(_item_out(item, []), body=item.body)
    finally:
        db.close()


@bp.post("/api/library/<slug>")
def save_item(slug):
    """Saves it — and every assignment linked to it gets the new text."""
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        data = request.get_json(silent=True) or {}
        title = data.get("title")
        title = str(title).strip()[:200] if isinstance(title, str) and title.strip() else None
        # assignment_notes.js saves {notes}; the library's own pages {body};
        # a new name alone, {title}.
        vis = data.get("visibility")
        if vis is not None:
            if vis not in H.get("visibilities", ("private",)) or (vis == "site" and not (H.get("is_admin") and H["is_admin"](user))):
                return jsonify(error="It can't be shown to them."), 400
            item.visibility = vis
            item.updated_at = accounts.now()
            db.commit()
        sent = data.get("body", data.get("notes"))
        if sent is None and (title is not None or vis is not None):
            if title is None:
                return jsonify(ok=True, updated=0)
            item.title = title
            item.updated_at = accounts.now()
            db.commit()
            return jsonify(ok=True, updated=0)
        body, problem = _clean_body(item.kind, sent)
        if problem:
            return jsonify(error=problem), 400
        n = save(db, item, body, title)
        return jsonify(ok=True, updated=n)
    finally:
        db.close()


@bp.delete("/api/library/<slug>")
def delete_item(slug):
    """Gone from the library; every assignment that used it keeps its notes as they are, its own."""
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        for a in linked(db, item):
            unlink(db, item, a)
        db.delete(item)
        db.commit()
        return jsonify(ok=True)
    finally:
        db.close()


@bp.post("/api/library/<slug>/duplicate")
def duplicate_item(slug):
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        copy = accounts.LibraryItem(slug=_new_slug(db), app=item.app, teacher_id=user.id, kind=item.kind,
                                    title=(item.title + " (copy)")[:200], body=item.body, size=item.size)
        db.add(copy)
        db.commit()
        return jsonify(slug=copy.slug), 201
    finally:
        db.close()


@bp.get("/api/library/<slug>/download")
def download_item(slug):
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        ext = "md" if item.kind == "tutorial" else "html"
        name = re.sub(r"[^\w -]+", "", item.title).strip().replace(" ", "-").lower() or "tutorial"
        return Response(item.body, mimetype="text/markdown" if ext == "md" else "text/html",
                        headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})
    finally:
        db.close()


@bp.post("/api/library/<slug>/link")
def link_item(slug):
    """{link: [assignment slugs], unlink: [...]}: which assignments use it."""
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        item = _own_item(db, user, slug)
        if item is None:
            return jsonify(error="No such tutorial."), 404
        data = request.get_json(silent=True) or {}
        mine = {a.slug: a for a in _own_assignments(db, user)}
        for s in data.get("unlink") or []:
            if s in mine:
                unlink(db, item, mine[s])
        for s in data.get("link") or []:
            if s in mine:
                link(db, item, mine[s])
        return jsonify(ok=True)
    finally:
        db.close()


@bp.post("/api/library/upload")
def upload():
    """Many files at once, from the teacher's computer: {files: [{name, data
    (base64)}], replace: true}. A .md is a tutorial, an .html a deck. One
    with the same title as one of theirs REPLACES it — links kept, so every
    assignment using it gets the new version — unless replace is false.

    Base64, because Render's firewall blocks a request with <script> in it
    before the app sees it (a deck is full of them; upload_teacher_deck)."""
    db = H["session"]()
    try:
        user, bounce = _teacher(db)
        if bounce:
            return bounce
        data = request.get_json(silent=True) or {}
        files = data.get("files") or []
        if not isinstance(files, list) or not files:
            return jsonify(error="No files."), 400
        if len(files) > MAX_UPLOAD_FILES:
            return jsonify(error=f"{MAX_UPLOAD_FILES} files at a time at most."), 400
        replace = data.get("replace", True) is not False
        report = []
        for f in files:
            name = str((f or {}).get("name", ""))[:200]
            low = name.lower()
            kind = "tutorial" if low.endswith((".md", ".markdown", ".txt")) else "deck" if low.endswith((".html", ".htm")) else None
            if kind is None:
                report.append({"name": name, "result": "skipped", "why": "Not a .md or .html file."})
                continue
            try:
                text = base64.b64decode(str(f.get("data", "")), validate=True).decode("utf-8")
            except Exception:
                report.append({"name": name, "result": "skipped", "why": "It couldn't be read as text."})
                continue
            body, problem = _clean_body(kind, text)
            if problem:
                report.append({"name": name, "result": "skipped", "why": problem})
                continue
            stem = re.sub(r"\.(md|markdown|txt|html?)$", "", name, flags=re.I)
            title = title_of(body, stem) if kind == "tutorial" else stem
            same = None
            if replace:
                same = (db.query(accounts.LibraryItem)
                        .filter(accounts.LibraryItem.teacher_id == user.id, accounts.LibraryItem.app == H["app_name"],
                                accounts.LibraryItem.kind == kind, accounts.LibraryItem.archived == 0,
                                func.lower(accounts.LibraryItem.title) == title.lower())
                        .order_by(accounts.LibraryItem.updated_at.desc()).first())
            if same is not None:
                if same.body == body:
                    report.append({"name": name, "result": "unchanged", "slug": same.slug, "title": same.title})
                    continue
                n = save(db, same, body)
                report.append({"name": name, "result": "replaced", "slug": same.slug, "title": same.title, "updated": n})
            else:
                item = accounts.LibraryItem(slug=_new_slug(db), app=H["app_name"], teacher_id=user.id, kind=kind,
                                            title=title, body=body, size=len(body.encode("utf-8")))
                db.add(item)
                db.commit()
                report.append({"name": name, "result": "added", "slug": item.slug, "title": item.title})
        return jsonify(report=report)
    finally:
        db.close()
