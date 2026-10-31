#!/usr/bin/env python3
"""The preview's rewrites of a page (static/preview.js), in node: the shim
goes in first, and the page's own static files are put into it.

    python3 tools/test_preview.py

Both fail without a sign when broken. A shim at the end of the page came
after the page's own scripts, so their first fetch() went nowhere ("Failed
to fetch"); and a <link href="/static/style.css"> in a sandboxed iframe with
no address loads nothing, so a student's CSS silently did nothing.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = 0
count = 0


def check(name, ok, detail=""):
    global failures, count
    count += 1
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  -- " + str(detail)[:500]))
    if not ok:
        failures += 1


SCRIPT = r"""
const fs = require("fs");
const asked = [];
global.window = { addEventListener() {}, FlaskIDERuntime: { request: async (method, path) => {
  asked.push(path);
  const files = { "/static/style.css": ["text/css", "h1{color:red}", true],
                  "/static/app.js": ["text/javascript", "go('</script>')", true],
                  "/static/logo.png": ["image/png", "iVBORw0KGgo=", false] };
  const f = files[path.split("?")[0]];
  return f ? { status: 200, headers: { "Content-Type": f[0] }, body: f[1], isText: f[2] }
           : { status: 404, headers: {}, body: "nope", isText: true };
} } };
eval(fs.readFileSync(%(preview)s, "utf8"));
const P = window.FlaskIDEPreview;
(async () => {
  const out = {};
  out.head = P.withShim("<!doctype html><html><head><title>x</title></head><body><script>fetch('/a')</script></body></html>");
  out.bare = P.withShim("<h1>Hi</h1>");
  out.doctype = P.withShim("<!DOCTYPE html><h1>Hi</h1>");
  out.inlined = await P.inlineResources('<link rel="stylesheet" href="/static/style.css"><link rel="icon" href="/static/x.ico">' +
    '<script src="/static/app.js"></script><img src="/static/logo.png" alt="l"><img src="https://example.com/a.png">' +
    '<link rel="stylesheet" href="/static/missing.css">');
  out.asked = asked;
  process.stdout.write(JSON.stringify(out));
})();
"""

proc = subprocess.run(["node", "-e", SCRIPT % {"preview": json.dumps(os.path.join(ROOT, "static", "preview.js"))}],
                      capture_output=True, text=True)
try:
    o = json.loads(proc.stdout)
except ValueError:
    print(proc.stdout[-500:], proc.stderr[-1500:])
    sys.exit(1)

head = o["head"]
check("the shim goes just inside <head>, before the page's own scripts",
      head.index("__flaskideReply") < head.index("fetch('/a')") and head.index("<head>") < head.index("__flaskideReply"), head[:200])
check("  never before the doctype (quirks mode)", head.startswith("<!doctype html>")
      and o["doctype"].startswith("<!DOCTYPE html>"), o["doctype"][:80])
check("  and first on a page with no <head> at all", o["bare"].startswith("<script>"), o["bare"][:40])
i = o["inlined"]
check("a stylesheet from static/ is put into the page as <style>", "<style>h1{color:red}</style>" in i, i)
check("a script from static/ is put in too, its </script> made safe", "<script>go('<\\/script>')</script>" in i, i)
check("a picture from static/ becomes a data: address", 'src="data:image/png;base64,iVBORw0KGgo="' in i, i)
check("a link that isn't a stylesheet, and an address on the internet, are left alone",
      'rel="icon" href="/static/x.ico"' in i and 'src="https://example.com/a.png"' in i
      and "/static/x.ico" not in o["asked"] and not any("example.com" in a for a in o["asked"]), o["asked"])
check("a stylesheet that isn't there stays as it was (the page still shows)",
      'href="/static/missing.css"' in i, i)
# Two requests at once (a page's fetch()es as it loads). flask.js hands each
# to Python through one global and awaits; together they overwrote each
# other's, and both got the last one's answer. A fake Pyodide that, like the
# real one, reads the global only after a pause.
RACE = r"""
const fs = require("fs");
global.window = {};
global.loadPyodide = async () => {
  const g = {};
  return {
    globals: { set: (k, v) => { g[k] = v; }, delete: (k) => { delete g[k]; } },
    loadPackage: async () => {},
    runPythonAsync: async (code) => {
      if (!code.startsWith("_flaskide_request(")) return "{}";
      await new Promise((r) => setTimeout(r, 5));
      const req = JSON.parse(g._req_json);
      return JSON.stringify({ status: 200, headers: {}, body: "answer for " + req.path, isText: true });
    }
  };
};
eval(fs.readFileSync(%(flask)s, "utf8"));
(async () => {
  await window.FlaskIDERuntime.boot();
  const got = await Promise.all(["/a", "/b", "/c"].map((p) => window.FlaskIDERuntime.request("GET", p)));
  process.stdout.write(JSON.stringify(got.map((r) => r.body)));
})();
"""
race = subprocess.run(["node", "-e", RACE % {"flask": json.dumps(os.path.join(ROOT, "static", "flask.js"))}],
                      capture_output=True, text=True)
check("requests made together each get their own answer (one at a time)",
      race.stdout.strip() == '["answer for /a","answer for /b","answer for /c"]', race.stdout + race.stderr[-400:])

# A page that handles a submit or a click itself (preventDefault in its own
# handler) is left to it: the shim used to catch both first and navigate.
SHIMTEST = r"""
const fs = require("fs");
const src = fs.readFileSync(%(preview)s, "utf8");
const shim = /const SHIM = `<script>([\s\S]*?)<\\\/script>`;/.exec(src)[1];
const listeners = {}, sent = [];
const document = { addEventListener: (t, f) => { listeners[t] = f; } };
const parent = { postMessage: (m) => sent.push(m) };
const location = { pathname: "/" };
eval(shim);
function ev(prevented, target) {
  return { defaultPrevented: prevented, target: target, preventDefault() { this.defaultPrevented = true; } };
}
const form = { tagName: "FORM", getAttribute: (k) => (k === "method" ? "post" : "/add") };
global.FormData = function () { return { forEach() {} }; };
listeners.submit(ev(true, form));
const afterHandled = sent.length;
listeners.submit(ev(false, form));
const link = { getAttribute: () => "/about", href: "/about" };
const target = { closest: () => link };
listeners.click(ev(true, target));
const afterHandledClick = sent.length;
listeners.click(ev(false, target));
process.stdout.write(JSON.stringify({ afterHandled, afterHandledClick, total: sent.length }));
"""
sh = subprocess.run(["node", "-e", SHIMTEST % {"preview": json.dumps(os.path.join(ROOT, "static", "preview.js"))}],
                    capture_output=True, text=True)
try:
    so = json.loads(sh.stdout)
except ValueError:
    so = {}
check("a form the page's own script handled (preventDefault) is left to it",
      so.get("afterHandled") == 0, sh.stdout + sh.stderr[-400:])
check("  and so is a link it handled; an unhandled form and link still go to the app",
      so.get("afterHandledClick") == 1 and so.get("total") == 2, so)

print("\n%d checks, %s" % (count, "all ok" if not failures else "%d FAILED" % failures))
sys.exit(1 if failures else 0)
