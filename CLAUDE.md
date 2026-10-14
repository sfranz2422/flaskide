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
`test_rescue.py`, `test_sighint.py`, `test_syntax.py` and `test_tabstops.py`. `test_syntax.py`
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

## Style

Comments explain *why*, and name the silent failures. The two-kinds-of-project
design is the main source of them here: almost every bug in this app has been
something that was correct for Flask projects and wrong for SQL ones, or the
reverse.
