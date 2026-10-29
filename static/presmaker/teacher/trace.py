"""PresMaker — runs a lesson's Python for the teacher slides.

    python3 -I trace.py < job.json

job: {"mode": "trace" | "run", "code": "...", "prefix": "..."}

`prefix` is the lesson's code from the steps before this one (students type
every step into one main.py, so a step's code can use a function from an
earlier step). It runs first, silently. Then `code` runs:

  run    -> {"out": what it printed, "error": "..." if it raised}
  trace  -> {"steps": [...]} — one step per line as it FINISHES, the way a
            teacher talks through it: "line 4 calls give_candy()", "return 5
            hands back 5", "pieces is now 5". Each step is
            {l, note (HTML), vars {name: repr}, out (everything printed so
            far), skip [lines that will never run]}.

Prints one line of JSON. Never asks for input: input() raises, and the
teacher's dialog says that code can't be traced.
"""

import ast, builtins, contextlib, html, io, json, signal, sys

MAX_STEPS = 60


def short(v):
    try:
        r = repr(v)
    except Exception:
        r = "?"
    return r if len(r) <= 40 else r[:37] + "..."


def code(s):
    return "<code>" + html.escape(s) + "</code>"


def no_input(prompt=""):
    raise RuntimeError("this code asks for input(), so it can't be run here")


def fresh():
    return {"__name__": "__main__", "__builtins__": builtins, "input": no_input}


def run_prefix(prefix):
    g = fresh()
    if prefix.strip():
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(prefix, "<prefix>", "exec"), g)
        except BaseException:
            g = fresh()          # an earlier step that doesn't run alone: start clean
    return g


def module_names(tree):
    """Names the step's own top-level code assigns: the variables worth showing."""
    names = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.For)):
            targets = [node.target]
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name) and n.id not in names:
                    names.append(n.id)
    return names


def statements(tree):
    """line -> the statement that starts there, and line -> the function it's in."""
    at, fn = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno not in at:
            at[node.lineno] = node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(node):
                if isinstance(n, ast.stmt) and n is not node:
                    fn.setdefault(n.lineno, node)
    return at, fn


def trace(job):
    src = job["code"]
    lines = src.split("\n")
    tree = ast.parse(src)
    at, fn_of = statements(tree)
    names = module_names(tree)
    g = run_prefix(job.get("prefix", ""))
    out = io.StringIO()
    steps = []
    frames = {}                  # id(frame) -> {"open": line or None, "notes": [], "printed": int}
    calls = {}                   # id(frame) -> "double(15)", for functions from earlier steps
    module = {"frame": None}

    def shown_vars(frame):
        if frame.f_code.co_name == "<module>":
            return {k: short(g[k]) for k in names if k in g and not callable(g[k])}
        return {k: short(v) for k, v in frame.f_locals.items() if not callable(v)}

    def text_of(l):
        return lines[l - 1].strip() if 0 < l <= len(lines) else ""

    def add(l, note, frame, skip=None):
        if len(steps) >= MAX_STEPS:
            raise StopIteration
        steps.append({"l": l, "note": note, "vars": shown_vars(frame),
                      "out": out.getvalue(), "skip": skip or []})

    def finished(frame, st):
        """The note for a line that has just run."""
        l = st["open"]
        node = at.get(l)
        before = " ".join(st["notes"])
        st["notes"] = []
        printed = out.getvalue()[st["printed"]:]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            note = "Python remembers " + code(node.name + "()") + " for later. Its body doesn't run yet."
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            vs = shown_vars(frame)
            parts = [code(t.id) + " is now <b>" + html.escape(vs[t.id]) + "</b>"
                     for t in targets if isinstance(t, ast.Name) and t.id in vs]
            note = (", ".join(parts) + ".") if parts else "Runs " + code(text_of(l)) + "."
        elif printed:
            shown = printed.rstrip("\n").replace("\n", " / ")
            note = "Prints " + code(shown if len(shown) <= 60 else shown[:57] + "...") + "."
        else:
            note = "Runs " + code(text_of(l)) + "."
        return (before + " " + note).strip()

    def tracer(frame, event, arg):
        name = frame.f_code.co_filename
        if name == "<prefix>":
            # A function from an earlier step, called from this one: say what it gave back.
            if event == "call":
                co = frame.f_code
                calls[id(frame)] = co.co_name + "(" + ", ".join(
                    short(frame.f_locals.get(a)) for a in co.co_varnames[:co.co_argcount]) + ")"
            elif event == "return":
                parent = frames.get(id(frame.f_back))
                call = calls.pop(id(frame), frame.f_code.co_name + "()")
                if parent is not None:
                    parent["notes"].append(code(call) + " runs first and gives back <b>" +
                                           html.escape(short(arg)) + "</b>.")
            return tracer
        if name != "<step>":
            return None
        key = id(frame)
        if event == "call":
            st = frames[key] = {"open": None, "notes": [], "printed": len(out.getvalue())}
            if frame.f_code.co_name == "<module>":
                module["frame"] = frame
            else:
                parent = frames.get(id(frame.f_back))
                co = frame.f_code
                args = ", ".join(short(frame.f_locals.get(a)) for a in co.co_varnames[:co.co_argcount])
                call = co.co_name + "(" + args + ")"
                if parent is not None and parent["open"]:
                    # what already happened on that line (an inner call's answer) comes first
                    before = " ".join(parent["notes"])
                    parent["notes"] = []
                    calling = (" Then it calls " + code(call) + "." if before else
                               "Calls " + code(call) + " first.")
                    add(parent["open"], (before + calling).strip(), frame.f_back)
                st["notes"].append(code(call) + " runs.")
                st["call"] = call
            return tracer
        st = frames.get(key)
        if st is None:
            return tracer
        if event == "line":
            if st["open"] is not None:
                add(st["open"], finished(frame, st), frame)
            st["open"] = frame.f_lineno
            st["printed"] = len(out.getvalue())
        elif event == "return":
            l = st["open"]
            if frame.f_code.co_name == "<module>":
                if l is not None:
                    add(l, finished(frame, st), frame)
            else:
                node = at.get(l)
                val = "<b>" + html.escape(short(arg)) + "</b>"
                skip = []
                fn = fn_of.get(l)
                if isinstance(node, ast.Return):
                    expr = ast.get_source_segment(src, node) or "return"
                    note = code(expr) + " hands back " + val + ". The call " + code(st.get("call", "")) + " becomes " + val + "."
                    if fn is not None:
                        skip = [n for n in range(l + 1, fn.end_lineno + 1) if n in at and fn_of.get(n) is fn]
                        if skip:
                            note += " Line" + ("s " if len(skip) > 1 else " ") + ", ".join(map(str, skip)) + \
                                    (" never run." if len(skip) > 1 else " never runs.")
                else:
                    printed = out.getvalue()[st["printed"]:]
                    note = ("Prints " + code(printed.rstrip("\n").replace("\n", " / ")) + ". " if printed else "") + \
                           "The function ends with no " + code("return") + ", so it hands back " + val + "."
                if l is not None:
                    before = " ".join(st["notes"])
                    add(l, (before + " " + note).strip(), frame, skip)
            frames.pop(key, None)
        return tracer

    error = None
    with contextlib.redirect_stdout(out):
        sys.settrace(tracer)
        try:
            exec(compile(src, "<step>", "exec"), g)
        except StopIteration:
            error = "stopped after " + str(MAX_STEPS) + " steps"
        except BaseException as e:
            error = type(e).__name__ + ": " + str(e)
        finally:
            sys.settrace(None)
    result = {"steps": steps}
    if error:
        result["error"] = error
    return result


def run(job):
    g = run_prefix(job.get("prefix", ""))
    out = io.StringIO()
    result = {}
    with contextlib.redirect_stdout(out):
        try:
            exec(compile(job["code"], "<step>", "exec"), g)
        except BaseException as e:
            result["error"] = type(e).__name__ + ": " + str(e)
    result["out"] = out.getvalue()
    return result


def main():
    job = json.load(sys.stdin)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("took too long")))
    signal.alarm(5)
    try:
        result = trace(job) if job.get("mode") == "trace" else run(job)
    except SyntaxError as e:
        result = {"error": "SyntaxError: " + str(e), "steps": [], "out": ""}
    except BaseException as e:
        result = {"error": type(e).__name__ + ": " + str(e), "steps": [], "out": ""}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
