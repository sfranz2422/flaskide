# FlaskIDE

A browser-based editor for teaching Flask — and SQL. A real Flask app runs in
Pyodide and answers requests through its test client, so the preview is a
route's actual reply and has an address bar to prove it. Nothing a student
writes runs on the server.

**Two kinds of project, and the files decide which.** `app.py` present means
Flask; `query.sql` present means SQL, which builds `data.db` from `schema.sql`
and runs the query statement by statement. `kind_of(files)` in `app.py` is the
rule, and `app.js` reads the same thing off the same files. There is no mode
setting to get out of step.

## Running it

```
pip install -r requirements.txt
python3 app.py                 # http://localhost:5001
```

Sign-in is optional, as in the other two: no Google credentials means the
editor still works anonymously, and signing in only ever adds abilities.
`TEACHER_EMAILS` decides who gets the dashboard.

## Tests

```
for t in tools/test_*.py; do
  printf "%-26s " "$(basename "$t")"
  python3 "$t" >/tmp/out.$$ 2>&1 && tail -1 /tmp/out.$$ \
    || { echo "FAILED"; tail -20 /tmp/out.$$; }
done
```

Each suite prints `ok`/`FAIL` per check and exits non-zero on failure. The
loop above keeps the last line of a passing run and shows the tail of a
failing one, so a red suite cannot scroll past unnoticed — a bare
`for ... do python3 "$t"; done` will let it.

**`node` is required** by `test_complete.py`, `test_pack.py`, `test_quiz.py`,
`test_rescue.py`, `test_sighint.py`, `test_syntax.py`, `test_tabstops.py`, `test_xp.py`, `test_keep_place.py` and `test_autograde.py`. `test_syntax.py`
also needs PyIDE checked out beside this (`../pyide`), for its Pyodide: they load this repo's own JavaScript and drive it, rather
than grepping it — which is the only way those get checked at all.
`brew install node` if it is missing.

`test_sql.py` executes the SQL bridge exactly
as the browser receives it, which matters: the bridge is built inside a
JavaScript template literal, and a template literal eats one level of
escaping. A regex that is correct in the file arrived at Python as
`/*.*?*/` and raised `multiple repeat` on every Run. Backslashes in
`static/flask.js` are doubled for that reason — check any change to it
against `test_sql.py` rather than by eye.

**Every check must have been watched to fail.** Whole features here have gone
untested because nothing exercised them: SQL mode in the live lesson could be
broken on two separate code paths with the suite still green, until a real
SQL lesson was added to the test.

## Things that are invisible from the code

**`accounts.py` is byte-identical across PyIDE, WebIDE and FlaskIDE.** Change
it in one and copy it to the other two. This app owns `flask_projects`; the
account tables are shared and rows carry an `app` column.

**It shares PyIDE's Postgres** rather than provisioning a third one.

**Render's firewall reads every request body, and every JSON body is sent
as base64 for that reason** (`static/pack.js`, `PackedRequest` in `app.py`).
Notes full of HTML in f-strings, Flask routes and `127.0.0.1:5000` were
answered with Render's 403 "Blocked" page before they reached gunicorn: no
POST in the logs, and the editor said "Couldn't reach the server." No single
line was to blame, so avoiding patterns is not a fix. `pack.js` wraps
`fetch` and must load before any other script on every page that sends
anything; `test_pack.py` checks that. A new page that saves without it
fails exactly as silently.

**`gunicorn --workers 2`** — two processes, no shared memory, so per-session
state in a module dict is invisible to half the users. Live sessions are a
table for this reason.

**A project lives in `files`, and `code` is always `""`.**

**The entry file is not fixed.** `ENTRY` is `app.py` and `SQL_ENTRY` is
`query.sql`, and anything that writes into "the project's main file" has to
pick between them by looking at what is there. A live save into a SQL
assignment that lands in `app.py` creates a project that is neither kind, and
the student watches their work disappear from the editor they typed it in.

**Entry names come from the server, never typed again in `app.js`.**
`cfg.entry` and `cfg.sqlEntry`. There is a check in `test_app.py` that fails
if `"query.sql"` appears in the editor's JavaScript outside its one fallback.

**SQLite foreign keys are off by default** and have to be switched on per
connection with `PRAGMA foreign_keys = ON`. Splitting SQL is done with
`sqlite3.complete_statement`, not by looking for semicolons — a semicolon
inside a string or a comment is not the end of a statement.

## Features worth knowing about

**Teaching live** (`/live`, `static/live.js`). The teacher's file mirrored
above, the student's own editor below, and this app's preview on the right,
address bar and status code included. Running goes through `FlaskIDERuntime`,
the same runtime the editor uses. A SQL lesson runs as SQL, decided by the
filename being taught — so nothing needs switching by hand.

There is no Stop button, deliberately: a Flask request runs to completion on
this thread and there is nothing to interrupt. The editor has none either.

**Handles between the panes** (`static/split.js`, ported from PyIDE), on
the class's live page and in the editor. A handle sizes the pane before it,
or with `data-size="next"` the one after it, or with `data-pane` the one it
names (the editor's console, whose neighbour above is the preview or the
SQL results, whichever is shown). On the live page the preview is what's
left; the handles size the console and the notes from above, so a folded
console or a lesson without notes only loses its own handle. Sizes are kept
per browser in localStorage and dropped while the page is stacked. The
class is `.resizer`, never `.split`: that is the editor's own `<main>`, and
in PyIDE handle rules written as `.split` blanked every editor page.

**Name completion** (`static/complete.js`) is a JavaScript scanner, not
Python's `ast` as in PyIDE, because Pyodide is not loaded until the first
Run. `test_complete.py` holds it to the same answers as `ast` on real
programs; add a program there before changing the scanner.

**A lesson for an assignment starts the student's editor** where
`/a/<slug>` would: their own draft of it if they have one, else the
assignment's copy of the file the live Save writes back to. It is rendered
into the page (`starter`), never sent on the poll, and anything already
typed in that browser for the lesson wins. The draft matters more than it
looks — the live Save overwrites that file in the draft, so starting from
the bare starter would erase earlier work on the first Save.

**The project's notes** (its first `.md` file) go out with every live push
whichever file is open, and show in a pane under the console on the
student's page. A push that sends no `notes` key leaves them alone, so an
old editor tab cannot wipe them.

**Slides, and links made ahead.** Notes with `---` are always shown as
slides (`notes.js`, `slideView`), in the editor and on the class's page. A
live push sends the whole notes file and the teacher's slide (`"3/5"`);
each student moves through the slides freely and is jumped to the teacher's
slide only when the teacher *moves* — typing on the same slide must not drag
back a student who has read ahead. The assignment page makes the lesson's
link ahead of time (`_lesson_for`) so it can be posted in Classroom the day
before: an ended lesson with `version` 0 is "not started yet" (`_waiting`),
which is why a lesson started normally begins at `version` 1.

**What goes in the brackets** (`static/sighint.js`). While the cursor is inside
a call it knows, a small hint above the line shows the slots, the one being
typed in bold. It inserts nothing and takes no clicks. Sources, in the order
they win: the student's own `def`s (a scanner, held to `ast` by
`test_sighint.py`), then a hand-written table of Python's built-ins and
methods in beginner words, and Flask's, the request's and sqlite3's. `test_sighint.py` checks every table entry
against Python itself, so a hint can never show a call Python would refuse.

**The syntax card** (`static/syntax.js`). Before Run does anything, the page
asks Python to *compile* every `.py` file (`_flaskide_check` in `flask.js`, through `FlaskIDERuntime.check`); if one can't be read, a card
covering the output pane says what is wrong in plain words, with Python's own message
under it, and nothing runs. **Syntax only, by construction**: it compiles and
never runs, so a program that reads fine never gets a card, however wrong it
is. Keep every sentence about how a line is *written*; a hint about logic
would be answering the exercise. The words are a table keyed on Python's
message, and `test_syntax.py` runs each one against the real Pyodide, so a
Python upgrade that rewords a message fails there.

**Lessons** (`kind = "lesson"` on an assignment; `lesson.html`, `lesson.js`,
`lesson_teacher.html`, `lesson_teacher.js`; "Lessons" in `app.py`). Notes
with questions and no code, for non-programming classes, made with Create
lesson on the dashboard. The notes are `lesson.md` in the assignment's
`files`, so answer keys, marking, Classroom and the live link work unchanged.
Students get the slides full screen: at their own pace from the assignment
link, following the teacher's slide from the live link — the only
difference. No draft; Turn in makes a Submission with an empty
`snippet_slug`, and the results page lists answers where code would have an
Open link. Anything that builds a `view_shared` link from a submission must
allow for that empty slug.

**Questions in the notes** (`quiz.py`, identical in all three apps;
`notes.js`'s `parseQuiz`/`buildQuiz`; `/api/quiz/*`). A ```` ```quiz ````
block in an assignment's notes is a question: `- [x]` choices, or `answer:`
lines for short answer, `points:` (default 1). One try, marked at once; the
points are added to the teacher's score and Sync sends the total. **The notes
go to students whole, so the key is taken out at every exit** —
`quiz.redact_files` wherever an assignment's files reach a student,
`quiz.redact` on every live push — and kept in `quiz_questions`. A new route
that hands out an assignment's files must redact too, and needs a line in
`test_quiz.py`'s leak section: a missed exit leaks the answers with no
visible sign.

In the editor, a `.md` tab shows the notes in the preview's place on the
right — there is no room for both — and the editor stays on the code. The
Notes | Preview switch, a code tab or Run brings the preview back; an
assignment opens on its notes, except for its author, who gets Edit source.

**The rescue** (`static/rescue.js`, identical in all three apps). Work typed
while signed out is kept in the browser and restored after signing in.

**An assignment's notes are edited on its page** (`assignment_notes.js`,
the same file in all three editors; `save_assignment_notes`). Most visits to
an assignment are to change its notes, not its code, so its page opens with
them: markdown on the left, the slides as students get them on the right,
Add picture / paste / drop, Save or Ctrl+S. The route saves the notes ALONE
— the notes file is a lesson's `lesson.md`, else the first `.md`, else a new
`notes.md` (emptied, it goes) — so the code and data files can't be changed
from there; keys are stored as for any save, and students already working
see the new notes (`_current_notes`). For the code, Edit project at the
top of the page opens the whole thing in the editor (`edit_assignment`).
A lesson's page links to its lesson page instead. `test_notes_page.py` is the same in all three.

**The teacher's own slides** (`TeacherDeck` in `app.py`, table
`teacher_decks`; `teacher_deck`, `upload_teacher_deck`). One HTML file per
assignment that the teacher made elsewhere and presents from: Upload / Replace
teacher lesson at the top of the assignment's page, and a link that opens it
in a new tab at `/teacher/<slug>/slides`. This editor's own table, not
`accounts.py`'s, so nothing has to be copied to the other repos. It is served
as uploaded, scripts and all, with the viewer's sign-in, so **only the teacher
who set the assignment can open it**. It is not sandboxed like `/img`,
because the decks keep their class list in localStorage and a sandboxed page
has none. The page sends it base64 in JSON, because Render's firewall blocks a
body full of `<script>` before the app sees it. `test_teacher_deck.py` (the same file in PyIDE).

**An assignment's notes follow the teacher's edits** (`_current_notes`,
`_keep_notes` in `app.py`). A draft copies the assignment's files, notes
included, but every page that shows a student their draft swaps in the
assignment's notes as they are now. Saving never writes notes into a draft:
the automatic turn-in compares the draft with what was handed in, so new notes
there would turn everyone's work in again over a typo. Every `.md` counts as
notes. `test_notes_follow.py` pins it.

**Signed out after two idle hours** (`_sign_out_idle_student` in `app.py`,
`templates/_idle.html`). Students only: signing a teacher out would end their
live lesson. Polls (any GET to `/api/`) must never count as activity, or an
open tab keeps itself signed in forever, which is the bug this exists for.
The page sends a beat to `/api/alive` at most every 5 minutes while it is
used, and gives up 2 minutes before the server does, so it always notices
first. A new page a student works on needs `{% include "_idle.html" %}`.
Time up, it goes straight to Google's sign-in and back to the page — no card.
Chrome reopens yesterday's tabs from its cache without asking the server, so
signed-in pages are `no-store`, the page GETs `/api/alive` (not activity) as
it opens and on focus, and an idle student opening a page is redirected to
`/login?next=` rather than shown it signed out.

**Attendance** (`accounts.Visit`, table `class_visits`;
`/teacher/class/<id>/attendance`). One row per sitting: made when a
signed-in student opens the class's page, one of its assignments or its live
lesson (`_attend`), kept open by the beat, and split by a 20-minute gap.
Times are UTC, and the page groups them into days in the teacher's browser.

**XP** (`xp.py`; "XP" in `app.py`; `static/xp.js`, `static/avatar.js`).
Students earn XP for questions the notes mark themselves (`XP_PER_POINT` a
point, part for part right), for answering every question in the notes, for
full marks on an assignment with an `xp_bonus`, from the teacher by hand
(`/teacher/class/<id>/xp`, negative takes it back), and for a program that
ran without an error. It makes levels, badges and tokens (one per `TOKEN_EVERY`, 1000 XP),
all worked out from the total and never stored; `users.tokens_used` is the
only token state, lowered by Use with a conditional UPDATE. **Nothing here
touches a grade** — the teacher trades tokens for points by hand.

One total per *person*, across every class and all three apps, so **`xp.py`,
`avatar.js`, `xp.js`, `static/avatars/` and `tools/test_xp.py` are shared
like `accounts.py`**: the same in all three repos, PyIDE's the original. XP is rows in `xp_awards`, never updated, and
the unique `(user_id, source)` is what stops anything paying twice — a
double click, two workers, a page sent twice. `xp.award` commits on its own
and is called *after* the thing it pays for is committed.

**The server cannot see a run.** In FlaskIDE a run that worked is the
student's app importing without an error, or a SQL project's queries all
running (`reportRun` in `app.js` and `live.js`). The page posts a hash of
its code files (never the code), and the server pays `RUN_XP` only after
`RUN_EVERY_SECONDS` of *working* time since the last paid run, never twice
in that much clock time across all three apps, and only when the hash
changed. Working time is `session["busy"]`, counted in
`_sign_out_idle_student` as `act` moves — one `BUSY_STEP_SECONDS` at most per
gap, and never for a GET to `/api/`. A faked claim earns what a real one
would, which is the whole defence.

A class's leaderboard (`_board`) shows its roster's signed-in students by
their whole XP, **first name and last initial only** (`xp.board_name`),
never an email, and not on the view-only link. Students can hide and still
earn. Their home page (`/classes`) shows all of it. An avatar is one
picture from `xp.AVATARS` — `static/avatars/<id>.webp`, painted portraits
the teacher made with Gemini, cropped square and shrunk to 400px — never an
upload or text, checked by `xp.clean_avatar` against the level that unlocks
it. Adding one is a file and a line in `AVATARS`, in all three repos;
`test_xp.py` fails on a picture without its file or a file without its
line. (A parts builder drawn in SVG came first and was replaced: it could
not reach the look the teacher wanted.)

**Rewards, penalties and random events** (`xp.BEHAVIORS`, `xp.EVENTS`; the
XP & tokens page). The teacher ticks students and picks a programming-themed
reason, or types one; a random event (Classcraft's, renamed for code) is
applied the moment it is drawn and shown big for the projector. **XP never
goes below 0** (`xp.penalty_for`): a penalty takes only what a student has.
An event's XP is `XpAward` rows sourced `event:<ClassEvent id>:<user id>`,
which is how Undo removes exactly those — the one place award rows are
deleted. The class page shows the last event for a day, a hidden student as
"A classmate"; `/me/xp` is a student's every award and its reason. Events
move XP only, never tokens, because tokens become real points.

**Every student in the class sees an event**, in the green popup on whatever
page they're on (`_event_news`, in `/api/me/xp/news` when the page sends
`events_after`; `eventText` in xp.js): "⭐ Glowing code review · Ana +10 XP",
"You" for themselves. It once reached only the students it gave XP to, so
for the rest an event set off in front of them never appeared. Students see
first names only (`xp.first_name`), there and on the class page; the
teacher's XP page keeps the initial, to tell two Anas apart. An event pops
up for `EVENT_NEWS_MINUTES` (30) — later than that, the class page has it.

**Quests** are assignments with an `xp_bonus` ("Quest reward" on the
assignment page), paid once on full marks. "Complete" is not stored: it is
that student having the `bonus:<assignment id>` award (`_quests_done`). The
class page marks quests, and a student's home page lists their open ones
(`_open_quests`: not hidden, archived or closed).

**Leaderboards** come in two sizes: a class's own, and — when its teacher
has more than one class here — all of that teacher's classes together
(`_all_classes_board`), so Programming 1 sees both Intro periods. A
student's home page shows the top five of each, plus their own row.

**Students' own photos need the teacher's approval first**
(`accounts.StudentPhoto`, `/photo/<slug>`). A waiting photo is served only
to its student and the teachers of their classes, never cached, and is on
no board; approving makes it their avatar (`"photo:<slug>"`), rejecting
deletes it. They are not `images`, because `/img/<slug>` serves anyone with
the address. The page crops and shrinks a photo to 400px before sending.
**An approved photo is served by every editor**, whichever one it was sent
in: an avatar is one per person across all four, and serving only this
app's photos made a photo approved elsewhere a broken picture on this app's
class pages. A waiting one, only by the app it was sent in.

The XP pages load `pack.js` first like every page here that sends JSON.

**Tests: Check my work and Check all** (`autograde.py`,
`static/autograde.js`, "Tests" in `app.py`, `/help/questions#tests`). A
```` ```tests ```` block in an assignment's notes is checked against the
student's project, one test per line: a request (`GET / -> 200`,
`GET / contains Welcome`, `POST /login name=sam&pw=1 -> contains Hello`),
the code's shape (`uses render_template`, `avoids eval`, `defines home`),
or, in a SQL project, the last query's result (`returns 3 rows`,
`result contains Alice`). The app is loaded as Run loads it
(`_flaskide_load`) and each request goes through Flask's test client, under
a time limit. **They run in a browser, never on the server.** A student's
Check my work runs in theirs — feedback, which could be faked, so it is kept
(`TestResult`, kind "self") for the teacher to see and counts toward no grade. Each test it finds passing for the first time pays `SELF_TEST_XP` (2), once per test ever (`_self_tests_xp`, source `selftest:<assignment>:<label hash>`), and only for a label the notes really have, so a faked check takes at most that times the tests there are.
The teacher's Check all loads Python and Flask in the TEACHER's browser,
runs every turned-in snapshot, and posts kind "verified", which is added to
the grade through `_earned` — every total goes through it, so Classroom,
Skyward, My work, the class page and quests all include it. Points are
summed from the lines posted, never a total a page claims. A verified result
older than the last turn-in is shown stale (⟳). autograde.js reads a block
exactly as autograde.py; `test_autograde.py` holds them together and runs
the tests on flask.js's own bridge with real Flask, as `test_bridge.py`
does. The global is `PyIDETests` in all three editors (notes.js looks for
it); each editor's tests are its own. Each test the teacher's check finds passing also pays
`XP_PER_POINT` XP a point, once per test (`_tests_xp`, source
`test:<assignment>:<label hash>`), so checking again never pays twice and
fixed code is paid only for what now passes; a student's own check pays
nothing.

**Check my work happens in the notes** (`static/checks_in_notes.js`, the
same file in all three). A ```` ```tests ```` block is a card: each test a
line, ✓ or ✗ with why, and its own ✔ Check my work wherever the page has
registered a runner (`IDENotesChecks.setRunner` — the editor and the live
page; a lesson or class page has none, so its card is the plain list). The
toolbar's Check my work puts the results in the card too when one is on
screen; when none is, it opens the notes and turns them to the first slide
with a check failing (all passing: the last slide with checks), never past
a slide the lock or `animate:` still holds (slideView `reach`). The console
is only for notes with no tests in them — the teacher asked that checking
never open it. Every test runs
each time, never one card's, so the result kept for the teacher stays the
whole check. With **`locked: yes`** as a header line of the notes (beside
`theme:`/`animate:`, notes.js `takeHeader`), a slide with a card holds the
next slide until every check on it passes — in the student's own editor
only (slideView's `locked` option), never the teacher's preview or live. A
slide once passed stays open in that browser (`pyide-unlocked:<key>`).
`test_checks_in_notes.py` (the same in all three) runs the card and the
lock in node on a small fake DOM.

**The token shop** ("The token shop" in `app.py`; `accounts.ShopItem`,
`ShopRequest`; `/teacher/shop`). What tokens buy: one shop per teacher,
shared by their classes and all three editors (tokens are), stocked from
`xp.SHOP_STARTER` the first time it's opened — only then, so a teacher who
empties the shelf isn't restocked; items are taken off the shelf, never
deleted. A student asks from their home page; the request HOLDS its tokens
(`_tokens_free` = earned − used − held), so they can't ask for more than
they have. The teacher answers on the class's XP & tokens page: Approve
spends the tokens in one UPDATE conditional on them still being there,
Decline spends nothing. `test_shop.py` is the same file in all three.

**Editor themes** (`xp.EDITOR_THEMES`; the end of `style.css`). Looks
beyond light/dark: some free from a level (high contrast from level 1, for
whoever needs it), the rest sold in the teacher's shop as items with a
`theme` — bought at once, no request, since they only change the buyer's
own screen; owned for good (`users.themes_owned`). The chosen one
(`users.editor_theme`) is checked by `_user_theme` on every page and put on
`<html>` by each page's head script before the first paint, so a theme that
stops being theirs stops showing. Each theme is a `[data-theme]` block, a
`.cm-s-pyide-<id>` CodeMirror theme and a shop swatch, generated from one
palette; `test_editor_themes.py` (the same in all three) fails on a theme
missing any of them, since a missing block sells a theme that does nothing.

**The class pages look like GameIDE's** (`static/site_look.css`, the same
in all three). The teacher's and students' pages — dashboard, class,
assignment, XP & tokens, shop, attendance, material, a student's classes,
My work, their XP and avatar — load it after `style.css`; the editors never
do. It sets colours only for the default looks (no `data-theme`, or
`dark`/`light`), so **a student's bought theme still wins** there: a colour
written outright anywhere else in it would quietly paint over every theme
sold. `test_site_look.py` (the same in all three) fails on that, on a page
that stops loading it, and on an editor that starts.

## Style

Comments explain *why*, and name the silent failures. The two-kinds-of-project
design is the main source of them here: almost every bug in this app has been
something that was correct for Flask projects and wrong for SQL ones, or the
reverse.
