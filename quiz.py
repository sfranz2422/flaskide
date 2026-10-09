"""Questions written into a project's notes, and the answers kept off the wire.

A teacher writes a question in the markdown notes as a fenced block:

    ```quiz
    What does len("hello") return?
    - [ ] "hello"
    - [x] 5
    - [ ] 4
    points: 2
    ```

    ```quiz
    Which keyword repeats code while a condition stays true?
    answer: while
    ```

    ```quiz
    Explain, in a paragraph, why a while loop needs its condition to change.
    type: long
    points: 5
    ```

Choices make it multiple choice and `[x]` marks the right one (more than one
`[x]` means any of them counts). No choices makes it short answer, and every
`answer:` line is one accepted answer. `type: long` (or `type: essay`) makes
it a long response: the student writes in a box with a small formatting
toolbar, and the teacher marks it by hand on the assignment's page — there
is no key, so choices and `answer:` lines in it are ignored. Until the
teacher gives it a score it counts 0, and the class page says the
assignment needs grading. `points:` defaults to 1. Code can go in
the question inside a `~~~` fence, which the outer ``` fence leaves alone, and
nothing inside that inner fence is read as a choice or an answer.

THE NOTES ARE SENT TO STUDENTS WHOLE. They are copied into every student's
draft from the assignment's files, and they ride along on every live push. So
the answer key cannot simply be hidden by the page: anyone who opened the
page source would have it. Every route that hands an assignment's files to a
student goes through `redact_files`, and every live push through `redact`,
and what comes out has the `[x]` and the `answer:` lines removed and an `id:`
line put in, which is how the student's page says which question it is
answering. The key is kept server side in the quiz_questions table, written
by `keys` whenever a teacher saves notes or pushes them live.

Redacting at the exits means a missed exit leaks the answers with no sign at
all — the page looks exactly the same. test_quiz.py opens each one as a
student and looks for the key. Add a route that hands out an assignment's
files and it needs a line there too.

notes.js has the browser's half of this (`parseQuiz`) and must read a block
exactly as `parse` does; test_quiz.py runs both on the same blocks.
"""
import hashlib
import re
from html import escape
from html.parser import HTMLParser

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CHOICE = re.compile(r"^[-*+]\s+\[([ xX])\]\s+(.*)$")
ANSWER = re.compile(r"^answer\s*:\s*(.*)$", re.I)
POINTS = re.compile(r"^points?\s*:\s*(\d{1,4}(?:\.\d{1,2})?)\s*$", re.I)
QID = re.compile(r"^id\s*:\s*([0-9a-f]{12})\s*$")
LONG = re.compile(r"^type\s*:\s*(long|essay)\s*$", re.I)


def parse(body):
    """One quiz block's inside, as a dict.

    `qid` is a hash of what the student sees — the kind, the question and
    the choices — so the same question gets the same id from the teacher's
    notes and from the redacted copy, and editing its wording makes it a new
    question rather than quietly regrading answers to the old one. Points
    and the key are NOT in it, so fixing a wrong `[x]` or changing the points
    regrades the answers already given, which is what a teacher fixing a
    mistake wants.
    """
    lines = str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    prompt, choices, correct, answers = [], [], [], []
    points, given_id, inner, long_ = 1.0, "", None, False
    for ln in lines:
        s = ln.strip()
        f = FENCE.match(ln)
        if f:
            if inner is None:
                inner = f.group(1)
            elif f.group(1)[0] == inner[0] and len(f.group(1)) >= len(inner):
                inner = None
            prompt.append(ln)
            continue
        if inner is not None:
            prompt.append(ln)
            continue
        m = CHOICE.match(s)
        if m:
            choices.append(m.group(2).strip())
            if m.group(1) in "xX":
                correct.append(m.group(2).strip())
            continue
        m = ANSWER.match(s)
        if m:
            if m.group(1).strip():
                answers.append(m.group(1).strip())
            continue
        m = POINTS.match(s)
        if m:
            points = float(m.group(1))
            continue
        m = QID.match(s)
        if m:
            given_id = m.group(1)
            continue
        if LONG.match(s):
            long_ = True
            continue
        prompt.append(ln)
    while prompt and not prompt[0].strip():
        prompt.pop(0)
    while prompt and not prompt[-1].strip():
        prompt.pop()
    if long_:
        # Marked by hand, so there is no key to keep — and a stray `[x]` or
        # `answer:` must not become one, or redact would print it back out.
        kind, choices, correct, answers = "long", [], [], []
    else:
        kind = "choice" if choices else "text"
    text = "\n".join(prompt)
    has_key = bool(correct) if kind == "choice" else bool(answers)
    usable = bool(text.strip()) and points > 0 and (
        kind == "long" or (has_key and (kind == "text" or len(choices) >= 2)))
    qid = hashlib.sha1("\0".join([kind, text] + choices).encode("utf-8")
                       ).hexdigest()[:12]
    return {
        "qid": qid if usable else "",
        "given_id": given_id,
        "kind": kind,
        "prompt": text,
        "choices": choices,
        "correct": correct,
        "answers": answers,
        "points": points,
        "has_key": bool(correct or answers),
    }


def _blocks(md):
    """Split markdown into ("text", lines) and ("quiz", opener, lines, closer)
    pieces, skipping anything inside an ordinary code fence — a ```quiz
    written inside a ```markdown example is an example, not a question."""
    lines = str(md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i, fence = [], 0, None
    while i < len(lines):
        ln = lines[i]
        f = FENCE.match(ln)
        if fence is None and f and f.group(2).strip().lower() == "quiz":
            mark, body, j = f.group(1), [], i + 1
            while j < len(lines):
                g = FENCE.match(lines[j])
                if (g and not g.group(2).strip() and g.group(1)[0] == mark[0]
                        and len(g.group(1)) >= len(mark)):
                    break
                body.append(lines[j])
                j += 1
            closer = lines[j] if j < len(lines) else mark
            out.append(("quiz", ln, body, closer))
            i = j + 1
            continue
        if f:
            if fence is None:
                fence = f.group(1)
            elif (f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence)
                  and not f.group(2).strip()):
                fence = None
        out.append(("text", ln))
        i += 1
    return out


def _points_text(points):
    return "%g" % points


def redact(md):
    """The notes with every answer key taken out. Safe to run twice.

    A block that already has an `id:` and no key is one this has redacted
    before, and is left exactly as it is — otherwise the second pass, finding
    no key, would drop the id and the question would stop being answerable.
    A long response never has a key, so this is the only thing telling the
    teacher's copy (no id yet) from one already redacted.
    """
    if not md or "quiz" not in md:
        return md
    out = []
    for piece in _blocks(md):
        if piece[0] == "text":
            out.append(piece[1])
            continue
        _, opener, body, closer = piece
        q = parse("\n".join(body))
        if not q["has_key"] and q["given_id"]:
            out.extend([opener] + body + [closer])
            continue
        lines = [opener]
        if q["qid"]:
            lines.append("id: " + q["qid"])
        lines.append("points: " + _points_text(q["points"]))
        if q["kind"] == "long":
            lines.append("type: long")
        if q["prompt"]:
            lines.extend(q["prompt"].split("\n"))
        lines.extend("- [ ] " + c for c in q["choices"])
        lines.append(closer)
        out.extend(lines)
    return "\n".join(out)


def is_notes(name):
    return bool(re.search(r"\.(md|markdown)$", name or "", re.I))


def redact_files(files):
    """A project's files as a student may have them."""
    return {name: (redact(text) if is_notes(name) and isinstance(text, str)
                   else text)
            for name, text in (files or {}).items()}


def keys(md):
    """Every question in these notes that can be answered, with its key."""
    if not md or "quiz" not in md:
        return []
    found = []
    for piece in _blocks(md):
        if piece[0] == "quiz":
            q = parse("\n".join(piece[2]))
            if q["qid"]:
                found.append(q)
    return found


def file_keys(files):
    found = []
    for name, text in (files or {}).items():
        if is_notes(name) and isinstance(text, str):
            found.extend(keys(text))
    return found


def normalize(text):
    """How a short answer is compared: case, spacing and a full stop at the
    end do not matter. Nothing else is forgiven — `print()` and `print` are
    different answers in a programming class."""
    text = " ".join(str(text or "").split()).casefold()
    return text[:-1].rstrip() if text.endswith(".") else text


def is_correct(kind, correct, answers, response):
    """Right or wrong, for the kinds a machine can mark. A long response is
    never "correct" here: its points are the teacher's score on the answer."""
    if kind == "long":
        return False
    if kind == "choice":
        return response in correct
    want = {normalize(a) for a in answers}
    return normalize(response) in want


# ------------------------------------------------------------ long responses
#
# A long response arrives as HTML from the student's formatting toolbar, and
# is shown to the teacher as HTML on the assignment's page. That makes it the
# one place a student's text is drawn as markup on the teacher's screen, so
# it is cut down to a handful of tags with NO attributes at all — no href, no
# style, no on-anything — when it is saved AND again whenever it is shown.
# The browser sanitises too (notes.js), but a request can be made without the
# browser, and a missed step here would fail silently: the page would look
# exactly the same with a script in it.

LONG_TAGS = {"p", "div", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li"}
_DROP_WITH_CONTENT = {"script", "style", "template", "iframe", "object",
                      "textarea", "title", "head"}
_VOID = {"br"}


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.open, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_WITH_CONTENT:
            self.skip += 1
        elif not self.skip and tag in LONG_TAGS:
            self.out.append("<%s>" % tag)
            if tag not in _VOID:
                self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag in _VOID:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in self.open:
            # Close everything opened since, so the nesting stays whole.
            while self.open:
                t = self.open.pop()
                self.out.append("</%s>" % t)
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))


def clean_html(html):
    """A long response as it may be stored and shown: only LONG_TAGS, no
    attributes, every tag closed, text escaped."""
    p = _Cleaner()
    p.feed(str(html or ""))
    p.close()
    return "".join(p.out) + "".join("</%s>" % t for t in reversed(p.open))


def plain_text(html):
    """What a long response says, without its tags: for "is it empty?", and
    for anywhere it is shown as a line of text."""
    text = re.sub(r"<(br|/p|/div|/li)>", " ", clean_html(html))
    text = re.sub(r"<[^>]*>", "", text)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        text = text.replace(a, b)
    return " ".join(text.split())
