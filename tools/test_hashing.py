#!/usr/bin/env python3
"""Password hashing in the browser (_flaskide_patch_hashing in static/flask.js).

    python3 tools/test_hashing.py

Pyodide has no OpenSSL, so hashlib has no scrypt and no pbkdf2_hmac, and
Werkzeug's generate_password_hash raised AttributeError: a sign-up page
crashed in the editor while the same code passed every test, because the
tests ran on this computer's Python. So this runs in the REAL Pyodide (PyIDE's
copy, ../pyide/node_modules/pyodide, as test_syntax.py uses), checks hashlib
there really lacks them, and holds the plain-Python pbkdf2_hmac to RFC 6070's
published answers. The Werkzeug half is checked on this computer with
hashlib's two missing, as Pyodide has them missing.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYODIDE = os.path.join(ROOT, "..", "pyide", "node_modules", "pyodide", "pyodide.mjs")
failures = 0
count = 0


def check(name, ok, detail=""):
    global failures, count
    count += 1
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else "  -- " + str(detail)[:400]))
    if not ok:
        failures += 1


src = open(os.path.join(ROOT, "static", "flask.js")).read()
m = re.search(r"\ndef _flaskide_patch_hashing\(\):.*?\n(?=\n\ndef )", src, re.S)
check("flask.js has _flaskide_patch_hashing", m is not None)
fn = m.group(0) if m else ""
check("…and the load calls it before the student's app is imported",
      re.search(r"_flaskide_patch_hashing\(\)\s*\n\s*try:\s*\n\s*import importlib\s*\n\s*module = importlib.import_module\(\"app\"\)", src) is not None)

# RFC 6070 (PBKDF2-HMAC-SHA1) answers, and one SHA-256 one.
VECTORS = [("sha1", "password", "salt", 1, 20, "0c60c80f961f0e71f3a9b524af6012062fe037a6"),
           ("sha1", "password", "salt", 2, 20, "ea6c014dc72d6f8ccd1ed92ace1d41f0d8de8957"),
           ("sha1", "password", "salt", 4096, 20, "4b007901b765489abead49d926f721d065a429c1"),
           ("sha1", "passwordPASSWORDpassword", "saltSALTsaltSALTsaltSALTsaltSALTsalt", 4096, 25,
            "3d2eec4fe41c849b80c8d83662c0e44a8b291a964cf2f07038"),
           ("sha256", "password", "salt", 1, 32, "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b")]

if os.path.exists(PYODIDE):
    harness = """
import { loadPyodide } from %s;
const py = await loadPyodide();
py.globals.set("FN", %s);
py.globals.set("VECTORS", %s);
console.log(py.runPython(`
import hashlib, json
missing = [not hasattr(hashlib, "pbkdf2_hmac"), not hasattr(hashlib, "scrypt")]
exec(FN)
_flaskide_patch_hashing()
got = [hashlib.pbkdf2_hmac(h, p.encode(), s.encode(), n, d).hex() for h, p, s, n, d, _ in VECTORS.to_py()]
json.dumps({"missing": missing, "got": got})
`));
""" % (json.dumps(PYODIDE), json.dumps(fn), json.dumps(VECTORS))
    out = subprocess.run(["node", "--input-type=module", "-e", harness], capture_output=True, text=True, timeout=300)
    try:
        r = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {}
        print(out.stderr[-1500:])
    check("Pyodide really has no pbkdf2_hmac and no scrypt (why this exists)", r.get("missing") == [True, True], r)
    check("in Pyodide, the plain-Python pbkdf2_hmac gives RFC 6070's answers",
          r.get("got") == [v[5] for v in VECTORS], r.get("got"))
else:
    check("PyIDE's Pyodide is beside this repo (../pyide/node_modules/pyodide)", False, PYODIDE)

# Werkzeug, with hashlib as Pyodide has it.
saved = {k: getattr(hashlib, k) for k in ("pbkdf2_hmac", "scrypt") if hasattr(hashlib, k)}
for k in saved:
    delattr(hashlib, k)
try:
    scope = {}
    exec(fn, scope)
    scope["_flaskide_patch_hashing"]()
    import werkzeug.security as ws
    h = ws.generate_password_hash("secret")
    h2 = ws.generate_password_hash("secret", method="scrypt")
    check("generate_password_hash works with no scrypt, making a pbkdf2 hash",
          h.startswith("pbkdf2:sha256:") and h2.startswith("pbkdf2:sha256:"), (h[:30], h2[:30]))
    check("…that check_password_hash accepts, and refuses the wrong password",
          ws.check_password_hash(h, "secret") and not ws.check_password_hash(h, "Secret"))
    scope["_flaskide_patch_hashing"]()
    check("…and patching twice doesn't wrap it twice", ws.generate_password_hash("x").startswith("pbkdf2:sha256:20000$"))
finally:
    for k, v in saved.items():
        setattr(hashlib, k, v)
print("\n%d checks, %s" % (count, "all ok" if not failures else "%d FAILED" % failures))
sys.exit(1 if failures else 0)
