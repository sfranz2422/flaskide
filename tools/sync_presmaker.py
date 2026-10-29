#!/usr/bin/env python3
"""Brings PresMaker's editor (~/presMaker/web) into this IDE, as its tutorial
library's editor (library.py, /teacher/tutorials/<slug>/edit).

    python3 tools/sync_presmaker.py

THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE. PresMaker is edited in its own
repository — it is also a Mac app — and copied here, never edited here (the
reverse of PresMaker's tools/sync_from_pyide.sh).

  * static/presmaker/: its scripts, styles, vendor libraries and teacher-slide
    files, as they are. NOT its web/pyide/ copies of this IDE's own files:
    the page loads notes.js, style.css, autograde.js, checks_in_notes.js and
    snippets.js from this IDE's /static, so the preview is always this IDE's
    and never a stale copy (PresMaker's own were days behind once).
  * templates/presmaker.html: made from PresMaker's index.html — the
    addresses made Flask's, the IDE's files swapped in, New/Open replaced by
    the way back to the library and the tutorial's title, and the page told
    which tutorial it is (window.PM_SERVER, which bridge.js's server branch
    reads). The same in all three IDEs: what differs comes from library.py's
    page hook.
  * static/presmaker/FROM_PRESMAKER.txt: the PresMaker commit it came from.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.expanduser(os.environ.get("PRESMAKER", "~/presMaker/web"))
# Where this IDE keeps its static files and templates. GameIDE's are not
# beside this script (frontend/public/static, backend/templates): it says so.
STATIC = os.environ.get("PRESMAKER_STATIC", os.path.join(ROOT, "static"))
OUT = os.path.join(STATIC, "presmaker")
TEMPLATE = os.path.join(os.environ.get("PRESMAKER_TEMPLATES", os.path.join(ROOT, "templates")), "presmaker.html")
# An IDE with no notes.js of its own (GameIDE, which is React) gets PyIDE's,
# copied beside PresMaker: PRESMAKER_OWN_FROM=~/pyide/static.
OWN_FROM = os.environ.get("PRESMAKER_OWN_FROM")

# This IDE's own files, which PresMaker keeps copies of in web/pyide/.
OWN = {"pyide/style.css": "style.css", "pyide/notes.js": "notes.js", "pyide/checks_in_notes.js": "checks_in_notes.js",
       "pyide/autograde.js": "autograde.js", "pyide/snippets.js": "snippets.js"}


def copy_files():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for dirpath, dirnames, filenames in os.walk(SRC):
        rel = os.path.relpath(dirpath, SRC)
        if rel == "pyide" or rel.startswith("pyide" + os.sep):
            continue
        for name in filenames:
            if rel == "." and name == "index.html":
                continue
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            dest = os.path.join(OUT, rel, name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(dirpath, name), dest)
    commit = subprocess.run(["git", "-C", SRC, "log", "-1", "--format=%h %cs %s"], capture_output=True, text=True).stdout.strip()
    if OWN_FROM:
        for name in sorted(set(OWN.values()) | {"snippet_worker.js"}):
            shutil.copy2(os.path.join(os.path.expanduser(OWN_FROM), name), os.path.join(STATIC, name))
    with open(os.path.join(OUT, "FROM_PRESMAKER.txt"), "w") as f:
        f.write("Copied from ~/presMaker/web by tools/sync_presmaker.py. Edit PresMaker, then sync.\n%s\n" % commit)


def static(path):
    return "{{ url_for('static', filename='%s') }}" % path


def make_template():
    with open(os.path.join(SRC, "index.html")) as f:
        html = f.read()

    def address(m):
        attr, path = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^/|^#", path):
            return m.group(0)
        return '%s="%s"' % (attr, static(OWN.get(path, "presmaker/" + path)))
    html = re.sub(r'\b(src|href)="([^"]+)"', address, html)

    head = '''<meta name="viewport" content="width=device-width, initial-scale=1">
  {#  FlaskIDE's: every JSON body packed past Render's firewall (pack.js),
      loaded before any other script so none keeps the plain fetch. #}
  {% if pack_js %}<script src="''' + static("pack.js") + '''"></script>{% endif %}
  <script>
    try {
      var saved = {{ (user_theme or "")|tojson }} || localStorage.getItem({{ theme_key|tojson }});
      if (saved) document.documentElement.setAttribute("data-theme", saved);
    } catch (e) {}
  </script>
  '''
    html = html.replace('<meta charset="utf-8">\n  ', '<meta charset="utf-8">\n  ' + head, 1)
    html = re.sub(r"<title>[^<]*</title>", "<title>{{ item.title }} — {{ brand }}</title>", html, count=1)

    # New and Open give way to the way back to the library and the title.
    # Hidden, not taken out: app.js looks them up as it starts.
    start = html.index('    <div class="pm-group">\n      <div class="pm-menu">\n        <button class="btn" id="b-new"')
    end = html.index('      <button class="btn" data-cmd="save"', start)
    old_bits = html[start + len('    <div class="pm-group">\n'):end]
    old_bits = old_bits.replace('<div class="pm-menu">', '<div class="pm-menu" hidden>', 1)
    old_bits = old_bits.replace('<button class="btn" data-cmd="open"', '<button class="btn" data-cmd="open" hidden', 1)
    html = html[:start] + '''    <div class="pm-group">
      <a class="btn" href="{{ url_for('library.library_page') }}" title="Every tutorial, to open another or link this one">← Tutorials</a>
      <input id="lib-title" class="field pm-title" type="text" maxlength="200" value="{{ item.title }}" aria-label="Title"
             title="This tutorial's name in the library">
''' + old_bits + html[end:]
    html = html.replace('''      <button class="btn" data-cmd="save" title="Save (⌘S)">Save</button>''',
                        '''      <button class="btn" data-cmd="save" title="Save (⌘S): every assignment using it gets it">Save</button>
      {% if not no_pictures %}<button class="btn" id="lib-pic" type="button" title="Upload a picture into the tutorial at the cursor — or paste one, or drop it on the text">Add picture</button>{% endif %}''', 1)
    html = html.replace('''    <span id="status"></span>''', '''    <span id="status"></span>
    <span class="pm-uses" id="lib-uses">{% if uses %}Used in {% for u in uses %}<a href="{{ u.url }}">{{ (u.class ~ ': ') if u.class }}{{ u.title }}</a>{{ ', ' if not loop.last }}{% endfor %}{% else %}Not used yet: link it from <a href="{{ url_for('library.library_page') }}">the library</a>{% endif %}</span>''', 1)

    # The page is told which tutorial it is before any of PresMaker's scripts.
    first_pm = html.index('<script src="' + static("presmaker/compose.js"))
    html = html[:first_pm] + '''<script>
    /* Which tutorial this is (bridge.js's server branch), and this IDE's own
       notes and tests under the names PresMaker uses. */
    window.PM_SERVER = {{ pm_server|tojson }};
    window.PyIDENotes = window.PyIDENotes || window[{{ ns|tojson }} + "Notes"];
    window.PyIDETests = window.PyIDETests || window[{{ ns|tojson }} + "Tests"];
  </script>
  {% if pm_adapter == "gameide" %}
  <script>
    /* GameIDE's tutorials, drawn by PyIDE's notes.js: a ```check block (the
       checks Next waits for) as a list of them, and a highlight: line (part
       of the editor the step points at) said in words — rather than as code
       and stray text. */
    (function () {
      var N = window.PyIDENotes;
      if (!N) return;
      function adapt(md) {
        // The tutorial's header (title:, level:, starter:…) is a slide of its
        // own here, cut at its --- lines: a title card, not key: value text.
        var head = /^\\s*((?:[a-z]+\\s*:.*(?:\\n|$))+)\\s*$/i.exec(String(md || ""));
        if (head && /^\\s*title\\s*:/im.test(head[1])) {
          var f = {};
          head[1].split("\\n").forEach(function (l) { var m = /^\\s*([a-z]+)\\s*:\\s*(.*)$/i.exec(l); if (m) f[m[1].toLowerCase()] = m[2]; });
          return "## 📘 " + (f.title || "") + "\\n\\n" + (f.description ? f.description + "\\n\\n" : "") +
            "*" + [f.level, f.time, f.starter ? "starts from: " + f.starter : ""].filter(Boolean).join(" · ") + "*";
        }
        var out = [], inCheck = false, fence = null;
        String(md || "").split("\\n").forEach(function (ln) {
          var f = /^\\s*(```+|~~~+)\\s*(\\S*)/.exec(ln);
          if (inCheck) {
            if (f && !f[2]) { inCheck = false; out.push(""); return; }
            if (ln.trim()) out.push("- `" + ln.trim().replace(/`/g, "'") + "`");
            return;
          }
          if (f && fence === null && f[2].toLowerCase() === "check") {
            inCheck = true;
            out.push("", "**✔ Checks — Next waits for these:**", "");
            return;
          }
          if (f) fence = fence === null ? f[1] : null;
          var h = fence === null && /^\\s*highlight\\s*:\\s*([\\w-]+)\\s*$/i.exec(ln);
          out.push(h ? "> 🔦 Points at **" + h[1] + "** in the editor" : ln);
        });
        return out.join("\\n");
      }
      var render = N.render;
      N.render = function (el, md, opts) { return render.call(N, el, adapt(md), opts); };
    })();
  </script>
  {% endif %}
  ''' + html[first_pm:]
    html = html.replace('''</body>''', '''  {% if not no_pictures %}<script src="''' + static("pictures.js") + '''"></script>{% endif %}
  <script>
    /* Pictures (pictures.js, this IDE's): Add picture, paste or drop, put in
       at the cursor as ![name](/img/...). And the title, renamed on its own. */
    (function () {
      var P = window[{{ ns|tojson }} + "Pictures"], cm = window.PM && window.PM.editor();
      if (P && cm) {
        P.attach(cm);
        document.getElementById("lib-pic").addEventListener("click", function () {
          P.choose(function (files) { P.insertInto(cm.getDoc(), files); cm.focus(); });
        });
      }
      var box = document.getElementById("lib-title"), was = box.value;
      box.addEventListener("change", function () {
        var title = box.value.trim();
        if (!title || title === was) return;
        fetch(window.PM_SERVER.saveUrl, { method: "POST", credentials: "same-origin",
                                          headers: { "Content-Type": "application/json" },
                                          body: JSON.stringify({ title: title }) })
          .then(function (r) { if (r.ok) { was = title; window.PM_SERVER.title = title; } });
      });
    })();
  </script>
</body>''', 1)
    banner = ("{#  MADE BY tools/sync_presmaker.py FROM ~/presMaker/web/index.html — change\n"
              "    PresMaker (or the script), then sync; edits here are lost. #}\n")
    os.makedirs(os.path.dirname(TEMPLATE), exist_ok=True)
    with open(TEMPLATE, "w") as f:
        f.write(banner + html)


if __name__ == "__main__":
    if not os.path.isdir(SRC):
        sys.exit("No PresMaker at %s (set PRESMAKER=...)" % SRC)
    copy_files()
    make_template()
    print("PresMaker synced into %s and %s" % (os.path.relpath(OUT, ROOT), os.path.relpath(TEMPLATE, ROOT)))
