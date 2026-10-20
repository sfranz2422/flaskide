/* The teacher's laser pointer, in a live lesson. Identical in PyIDE, WebIDE
 * and FlaskIDE.
 *
 * The teacher holds Alt (Option on a Mac) and moves the mouse over their
 * code or a slide; every student sees a red dot there, with a short trail,
 * until Alt is let go. The highlight already went out with every push, but
 * a yellow block is easy to miss from the back of the room, and pointing at
 * a word on a slide was not possible at all.
 *
 * WHERE, NOT PIXELS. Nobody's screen is the teacher's size, so a place is
 * sent as a distance from a letter, and each student's page finds that
 * letter on its own screen:
 *
 *   c:12:2835:-120           in the code: line 12, column 28.35, and 1.2
 *                            lines above that line's top. In letters and
 *                            lines rather than pixels, so the class's own
 *                            text size changes nothing; and NOT snapped to a
 *                            letter, so blank space is a place too.
 *   s:2:0.3.1:t17:85,-140    on a slide: slide 2 (from 0); down the slide's
 *                            box by child index 0, then 3, then 1, to a text
 *                            node; 0.85 em right of and 1.4 em above the
 *                            middle of its 17th character — the character
 *                            NEAREST the mouse, wherever the mouse is. Slides
 *                            are rendered from the same markdown by the same
 *                            render() on every page, so the same path leads
 *                            to the same word however the lines wrap.
 *   s:2:4:e450,300           a picture: 450/1000 across it, 300/1000 down.
 *
 * THE FIRST VERSION SNAPPED TO LETTERS, and the teacher's first real test
 * was a circle drawn round the word THIS — in blank space, all of it. Above
 * the word was an empty line, whose only place was its start, so the class
 * saw the dot leap to the left margin and back, over and over; to the right
 * was past the end of the line, which snapped back onto the S. Measured
 * from the nearest letter, every point of the circle has a place.
 *
 * A path that does not lead all the way on a student's page — a question
 * card is drawn differently for the teacher, who sees the key — stops at
 * the deepest part that does, and the dot goes in the middle of that. Close
 * is the most it can be there; nothing is refused for it.
 *
 * NOT A PUSH. Pointing goes to /api/live/<code>/point and moves only the
 * pointer's own stamp (LiveSession.pointer), so thirty students are not
 * sent the whole file and notes several times a second. The teacher sends
 * at most every SEND_MS, and again every BEAT_MS while holding still, which
 * is how a student's page tells "still pointing here" from "the teacher's
 * tab went away with Alt held": a pointer not heard about for FADE_MS goes
 * out by itself. Otherwise a crashed laptop leaves a dot lit all lesson.
 *
 * THE PATH, NOT JUST THE PLACE. The class asks four times a second, so a
 * circle drawn in a second reached them as four points joined by straight
 * glides — a lopsided square. So the teacher's page samples the mouse every
 * SAMPLE_MS and each send carries the last PATH_MS of samples, stamped with
 * the teacher's clock; the student's page plays the ones it has not seen,
 * spaced as they were drawn, one after another. The shape arrives whole,
 * about a poll late. Faster polling would cut that, but thirty students
 * asking more than four times a second is more than two workers can answer.
 */
(function () {
  "use strict";

  var SEND_MS = 80;       // the teacher sends at most this often
  var SAMPLE_MS = 30;     // and samples the mouse at most this often
  var PATH_MS = 700;      // each send carries this much of the path
  var PATH_MAX = 16;      // or this many samples, whichever is fewer
  var BEAT_MS = 1500;     // and again this often while holding still
  var FADE_MS = 4000;     // a pointer not heard of for this long goes out
  /* How long after the dot was last lit the class keeps asking fast. A
     teacher who points once usually points again, and the first point after
     a quiet spell waits for a once-a-second poll — the slowest part of the
     whole delay, and the part that read as "it doesn't work" in class. */
  var WARM_MS = 30000;
  /* A student's page more than this far behind the path it is playing skips
     ahead to the newest point, rather than falling further and further
     behind a teacher who keeps drawing. */
  var MAX_LAG_MS = 600;
  var DEPTH = 12;         // the most child indices a path may hold
  var TRAIL = 3;          // dots behind the dot
  var CLOCK = 1e9;        // sample stamps are the teacher's clock, mod this

  // ------------------------------------------------------- shared

  function inside(r, x, y, slack) {
    return r && x >= r.left - slack && x <= r.right + slack
      && y >= r.top - slack && y <= r.bottom + slack;
  }

  function charRect(node, i) {
    if (i < 0 || i >= node.length) return null;
    var range = document.createRange();
    range.setStart(node, i);
    range.setEnd(node, i + 1);
    var rects = range.getClientRects();
    return rects.length ? rects[0] : null;
  }

  // The size of an em where a text node is, which offsets are counted in.
  function emOf(node) {
    var el = node.parentNode;
    var px = el && el.nodeType === 1 ? parseFloat(getComputedStyle(el).fontSize) : 0;
    return px > 0 ? px : 16;
  }

  // A number to send: hundredths, clamped to what LASER in app.py takes.
  function hundredths(v, most) {
    return Math.max(-most, Math.min(most, Math.round(v * 100)));
  }

  // ------------------------------------------------------- the teacher's side

  /* Child indices from `root` down to `node`, or null when it is not inside,
     or an index is too big to send (LASER in app.py: three digits). */
  function pathTo(root, node) {
    var path = [];
    while (node && node !== root) {
      var parent = node.parentNode;
      if (!parent) return null;
      var i = Array.prototype.indexOf.call(parent.childNodes, node);
      if (i < 0 || i > 999) return null;
      path.unshift(i);
      node = parent;
    }
    return node === root ? path : null;
  }

  function caretAt(x, y) {
    if (document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(x, y);
      return p && { node: p.offsetNode, offset: p.offset };
    }
    if (document.caretRangeFromPoint) {
      var r = document.caretRangeFromPoint(x, y);
      return r && { node: r.startContainer, offset: r.startOffset };
    }
    return null;
  }

  function distance(r, x, y) {
    var dx = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
    var dy = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0;
    return dx * dx + dy * dy;
  }

  /* The character nearest (x, y) on the slide: { node, i, rect }, or null
     for a slide with no text. The nearest line of text first — every line
     box of every text node, which a slide has few enough of — then the
     browser's own caret, asked at the point moved onto that line, for which
     letter on it. Not the caret at (x, y) itself: in blank space that is
     the nearest place in whatever block the mouse happens to be over, which
     can be a long way from the nearest letter. */
  function nearestChar(body, x, y) {
    var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    var best = null, bestD = Infinity, n;
    while ((n = walker.nextNode())) {
      if (!/\S/.test(n.data)) continue;
      var range = document.createRange();
      range.selectNodeContents(n);
      var rects = range.getClientRects();
      for (var k = 0; k < rects.length; k++) {
        var r = rects[k];
        if (!r.width && !r.height) continue;
        var d = distance(r, x, y);
        if (d < bestD) { bestD = d; best = { node: n, line: r }; }
      }
    }
    if (!best) return null;
    var lx = Math.max(best.line.left + 1, Math.min(best.line.right - 1, x));
    var ly = (best.line.top + best.line.bottom) / 2;
    var c = caretAt(lx, ly);
    var node = best.node;
    var i = c && c.node === node ? c.offset : -1;
    // The caret is BETWEEN two letters: whichever of them is nearer. And
    // when the browser's caret landed somewhere else, the nearest letter of
    // the node by a search, which is short: a text node is one run of words.
    var cands = i >= 0 ? [i - 1, i] : null;
    if (!cands) { cands = []; for (var j = 0; j < Math.min(node.length, 2000); j++) cands.push(j); }
    var pick = null, pickD = Infinity;
    cands.forEach(function (j) {
      var r = charRect(node, j);
      if (!r || (!r.width && !r.height)) return;
      var cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
      var d = (cx - x) * (cx - x) + (cy - y) * (cy - y);
      if (d < pickD) { pickD = d; pick = { node: node, i: j, rect: r }; }
    });
    return pick;
  }

  function thousandths(v) {
    return Math.max(0, Math.min(1000, Math.round(v * 1000)));
  }

  /* A place on a slide: `body` is the box the slide is rendered into,
     `slide` which slide it is, from 0. "" when (x, y) is not on it. */
  function pointAtSlide(body, slide, x, y) {
    if (!inside(body.getBoundingClientRect(), x, y, 0)) return "";
    var head = "s:" + Math.max(0, Math.min(9999, slide | 0)) + ":";
    // A picture is pointed at as a picture: a spot on it, which no letter
    // near it says as well.
    var el = document.elementFromPoint(x, y);
    var media = el && el.closest && el.closest("img, svg, video, canvas, iframe");
    if (!media || !body.contains(media)) {
      var c = nearestChar(body, x, y);
      var p = c ? pathTo(body, c.node) : null;
      if (p && p.length <= DEPTH) {
        var em = emOf(c.node);
        return head + p.join(".") + ":t" + c.i
          + ":" + hundredths((x - (c.rect.left + c.rect.right) / 2) / em, 99999)
          + "," + hundredths((y - (c.rect.top + c.rect.bottom) / 2) / em, 99999);
      }
      media = body;
    }
    var path = pathTo(body, media) || [];
    while (path.length > DEPTH) { media = media.parentNode; path.pop(); }
    var b = media.getBoundingClientRect();
    if (!b.width || !b.height) return head + ":e500,500";
    return head + path.join(".") + ":e" + thousandths((x - b.left) / b.width)
      + "," + thousandths((y - b.top) / b.height);
  }

  /* A place in a CodeMirror: a line, a column in it, and how far down from
     the top of that line, counted in letters and lines. "" off its text.

     The column is counted from the gap nearest the mouse, `ch`, which is a
     letter's edge on both screens, so a tab or a wrapped line on the way
     to it is the same on both. Past the end of the line, or on an empty one,
     it simply goes on counting. */
  function pointAtCode(cm, x, y) {
    if (!inside(cm.getScrollerElement().getBoundingClientRect(), x, y, 0)) return "";
    var pos = cm.coordsChar({ left: x, top: y }, "window");
    var ch = Math.min(pos.ch, cm.getLine(pos.line).length);
    var base = cm.charCoords({ line: pos.line, ch: ch }, "window");
    var col = ch + (x - base.left) / cm.defaultCharWidth();
    var down = (y - base.top) / cm.defaultTextHeight();
    return "c:" + pos.line + ":" + Math.max(0, Math.min(99999999, Math.round(col * 100)))
      + ":" + hundredths(down, 99999);
  }

  function makeDot(cls) {
    var d = document.createElement("div");
    d.className = "laser-dot " + (cls || "");
    d.setAttribute("aria-hidden", "true");
    document.body.appendChild(d);
    return d;
  }

  function moveDot(d, x, y) {
    d.style.transform = "translate(" + Math.round(x) + "px, " + Math.round(y) + "px)";
  }

  /* Pointing, on a teacher's page.

       surfaces()     what can be pointed at now: [{ el, point(x, y) }],
                      where point gives the place as above, or "". Asked on
                      every move, so a surface that comes and goes (the
                      notes pane, a markdown file open in the editor) needs
                      no bookkeeping.
       send(p, path)  tell the class: the place now, and the path to it as
                      "stamp@place;stamp@place;…". p is "" for "let go".
       active()       whether there is a class to tell (live).

     The teacher sees the dot too, under the mouse and with no delay: the
     projector is showing this screen, and a red dot reads from the back of
     the room where a mouse arrow does not. */
  function teacher(opts) {
    var samples = [];          // [{ t, p }], newest last
    var sentT = -1, lastSendAt = 0, timer = null, beat = null, lit = false;
    var mouseX = -1, mouseY = -1, on = false, dot = null;
    var sampledAt = 0, sampleTimer = null;

    function stamp() { return Date.now() % CLOCK; }

    function pathText() {
      var now = Date.now();
      var keep = samples.filter(function (s) { return now - s.at <= PATH_MS; })
                        .slice(-PATH_MAX);
      return keep.map(function (s) { return s.t + "@" + s.p; }).join(";");
    }

    function flush() {
      timer = null;
      var last = samples[samples.length - 1];
      if (!last || last.t === sentT) return;
      sentT = last.t;
      lastSendAt = Date.now();
      lit = true;
      opts.send(last.p, pathText());
      clearInterval(beat);
      // Holding still: the newest sample again, which the class has already
      // played — it says "still here" and moves nothing.
      beat = setInterval(function () {
        var l = samples[samples.length - 1];
        if (l) opts.send(l.p, l.t + "@" + l.p);
      }, BEAT_MS);
    }

    function soon() {
      if (timer) return;
      var wait = SEND_MS - (Date.now() - lastSendAt);
      if (wait <= 0) flush();
      else timer = setTimeout(flush, wait);
    }

    // Out for the class: at once, a send already waiting or not, so the
    // class does not see the dot linger after the teacher has moved on.
    function out() {
      if (dot) dot.classList.remove("on");
      clearTimeout(timer);
      timer = null;
      clearInterval(beat);
      beat = null;
      samples = [];
      sentT = -1;
      if (lit) { lit = false; opts.send("", ""); }
    }

    function letGo() {
      on = false;
      clearTimeout(sampleTimer);
      sampleTimer = null;
      out();
    }

    // Where the mouse is now, as a place, into the path.
    function sample() {
      sampleTimer = null;
      sampledAt = Date.now();
      if (!opts.active()) { letGo(); return; }
      var x = mouseX, y = mouseY;
      var list = opts.surfaces() || [];
      for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (!s || !s.el || !s.el.isConnected) continue;
        var r = s.el.getBoundingClientRect();
        if (!r.width || !inside(r, x, y, 0)) continue;
        var p = s.point(x, y);
        if (!p) continue;
        dot.classList.add("on");
        var last = samples[samples.length - 1];
        if (last && last.p === p) return;           // not moved anywhere new
        samples.push({ t: stamp(), at: sampledAt, p: p });
        if (samples.length > 64) samples.splice(0, samples.length - 64);
        soon();
        return;
      }
      // Off everything that can be pointed at: out, for the class too,
      // until the mouse comes back onto something with Alt still held.
      out();
    }

    function at(x, y) {
      if (!opts.active()) { if (on) letGo(); return; }
      on = true;
      // The teacher's own dot follows every move; the class's path is a
      // sample at most every SAMPLE_MS, the last one always taken.
      if (!dot) dot = makeDot("laser-here");
      moveDot(dot, x, y);          // lit by sample(), once it is over something
      if (sampleTimer) return;
      var wait = SAMPLE_MS - (Date.now() - sampledAt);
      if (wait <= 0) sample();
      else sampleTimer = setTimeout(sample, wait);
    }

    document.addEventListener("mousemove", function (e) {
      mouseX = e.clientX;
      mouseY = e.clientY;
      if (e.altKey) at(mouseX, mouseY);
      else if (on) letGo();
    }, { passive: true, capture: true });

    document.addEventListener("keydown", function (e) {
      // Pressed with the mouse already resting on something: point there now.
      if (e.key === "Alt" && !e.repeat && mouseX >= 0) at(mouseX, mouseY);
    }, true);

    document.addEventListener("keyup", function (e) {
      if (e.key !== "Alt") return;
      /* Alt pressed and let go on its own moves the keyboard to the
         browser's menu on Windows, so the next key the teacher types goes
         there instead of into the code. Only after pointing: an Alt that
         was not the laser is left to do what it always did. */
      if (on) e.preventDefault();
      letGo();
    }, true);

    // Alt let go in another window never arrives here.
    window.addEventListener("blur", letGo);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) letGo();
    });

    return { letGo: letGo };
  }

  // ------------------------------------------------------- the class's side

  /* Where a slide place is on this screen, or null: not this slide, not on
     screen, or nothing there to point at. */
  function slideSpot(body, onSlide, pointer) {
    var m = /^s:(\d+):([\d.]*):(?:t(\d+)(?::(-?\d+),(-?\d+))?|e(\d+),(\d+))$/.exec(pointer);
    if (!m || +m[1] !== onSlide) return null;
    var node = body, whole = true;
    var path = m[2] ? m[2].split(".") : [];
    for (var i = 0; i < path.length; i++) {
      var next = node.childNodes[+path[i]];
      if (!next) { whole = false; break; }
      node = next;
    }
    var x, y;
    var r = whole && m[3] !== undefined && node.nodeType === 3 && node.length
      ? charRect(node, Math.min(+m[3], node.length - 1)) : null;
    if (r) {
      var em = emOf(node);
      x = (r.left + r.right) / 2 + (m[4] ? +m[4] / 100 * em : 0);
      y = (r.top + r.bottom) / 2 + (m[5] ? +m[5] / 100 * em : 0);
    } else {
      var fx = 0.5, fy = 0.5;
      if (node.nodeType === 3) {
        var range = document.createRange();
        range.selectNodeContents(node);
        r = range.getBoundingClientRect();
      } else {
        r = node.getBoundingClientRect();
        if (whole && m[6] !== undefined) { fx = +m[6] / 1000; fy = +m[7] / 1000; }
      }
      if (!r || (!r.width && !r.height)) return null;
      x = r.left + r.width * fx;
      y = r.top + r.height * fy;
    }
    return inside(body.getBoundingClientRect(), x, y, 0) ? { x: x, y: y } : null;
  }

  /* A code place read back: { line, ch, col, down }. The first version sent
     "c:line:ch" for a letter, which an editor tab opened before the change
     still sends; that is the middle of that letter. */
  function codePlace(cm, pointer) {
    var m = /^c:(\d+):(\d+)(?::(-?\d+))?$/.exec(pointer);
    if (!m) return null;
    var col = m[3] === undefined ? +m[2] + 0.5 : +m[2] / 100;
    var down = m[3] === undefined ? 0.5 : +m[3] / 100;
    var line = Math.min(+m[1], cm.lastLine());
    var ch = Math.min(Math.floor(col), cm.getLine(line).length);
    return { line: line, ch: ch, col: col, down: down };
  }

  function codePos(cm, pointer) {
    var p = codePlace(cm, pointer);
    return p && { line: p.line, ch: p.ch };
  }

  function codeSpot(cm, pointer) {
    var p = codePlace(cm, pointer);
    if (!p) return null;
    var base = cm.charCoords({ line: p.line, ch: p.ch }, "window");
    var x = base.left + (p.col - p.ch) * cm.defaultCharWidth();
    var y = base.top + p.down * cm.defaultTextHeight();
    return inside(cm.getScrollerElement().getBoundingClientRect(), x, y, 0)
      ? { x: x, y: y } : null;
  }

  // "stamp@place;…" to [{ t, p }], oldest first. Anything unreadable is left out.
  function readPath(text) {
    if (typeof text !== "string" || !text) return [];
    return text.split(";").map(function (item) {
      var at = item.indexOf("@");
      return at > 0 ? { t: +item.slice(0, at), p: item.slice(at + 1) } : null;
    }).filter(function (s) { return s && isFinite(s.t) && s.p; });
  }

  /* The dot, on a student's page.

       code    { cm, follow(pos) } — the mirror, and what to do when the
               teacher points at a line that is scrolled out of sight
               (the page decides: a student reading elsewhere is not yanked).
       slides  { body, at() } — the slide box, and which slide the student
               is on. A student who has read ahead sees no dot: the teacher
               is pointing at a slide that is not in front of them.

     show(pointer, path) with each answer that carries one. Placed again on
     every frame while lit, because the slide re-renders and the mirror
     scrolls under it, and neither says so. */
  function student(opts) {
    var pointer = "", heard = 0, frame = 0, spot = null, dots = [], litAt = 0;
    var queue = [];          // [{ at, p }]: places still to play, in order
    var lastT = -1;          // the newest sample already queued
    var queueEnd = 0;        // when the last one queued plays

    function hide() {
      dots.forEach(function (d) { d.classList.remove("on"); });
      spot = null;
    }

    function follow(p) {
      if (!opts.code || !opts.code.follow || p.charAt(0) !== "c") return;
      var pos = codePos(opts.code.cm, p);
      if (pos) opts.code.follow(pos);
    }

    function place() {
      frame = 0;
      var now = Date.now();
      // The newest place whose time has come; the ones before it are passed.
      while (queue.length && queue[0].at <= now) {
        var q = queue.shift();
        if (q.p !== pointer && q.p) follow(q.p);
        pointer = q.p;
      }
      if ((!pointer && !queue.length) || now - heard > FADE_MS) {
        pointer = ""; queue = []; hide(); return;
      }
      var s = null;
      if (pointer.charAt(0) === "c" && opts.code) s = codeSpot(opts.code.cm, pointer);
      if (pointer.charAt(0) === "s" && opts.slides) {
        s = slideSpot(opts.slides.body, opts.slides.at(), pointer);
      }
      if (!s) hide();
      else {
        if (!dots.length) {
          for (var i = TRAIL; i >= 1; i--) dots.push(makeDot("laser-trail laser-trail-" + i));
          dots.push(makeDot());
        }
        // A dot that was out appears where it is, rather than gliding in
        // from wherever it last was.
        var jump = !spot;
        if (jump || s.x !== spot.x || s.y !== spot.y) {
          dots.forEach(function (d) {
            if (jump) d.classList.add("laser-jump");
            moveDot(d, s.x, s.y);
          });
          if (jump) {
            void dots[0].offsetWidth;          // take the position, unanimated
            dots.forEach(function (d) { d.classList.remove("laser-jump"); });
          }
        }
        dots.forEach(function (d) { d.classList.add("on"); });
        spot = s;
      }
      frame = requestAnimationFrame(place);
    }

    /* Queue the samples not seen yet, spaced as the teacher drew them,
       after whatever is still playing. A gap between two sends is not
       drawn out: the first new sample plays as soon as the last one queued
       has. Too far behind, it skips to the newest. */
    function enqueue(items) {
      var now = Date.now();
      var prev = null;
      items.forEach(function (s) {
        // The teacher's clock wraps at CLOCK; a stamp far below the last is
        // after the wrap, not before.
        var newer = lastT < 0 || s.t > lastT || lastT - s.t > CLOCK / 2;
        if (!newer) { prev = s; return; }
        var gap = prev && s.t > prev.t ? Math.min(s.t - prev.t, 200) : 0;
        var at = Math.max(now, queueEnd + gap);
        queue.push({ at: at, p: s.p });
        queueEnd = at;
        lastT = s.t;
        prev = s;
      });
      if (queueEnd - now > MAX_LAG_MS && queue.length) {
        var newest = queue[queue.length - 1];
        queue = [{ at: now, p: newest.p }];
        queueEnd = now;
      }
    }

    return {
      show: function (p, path) {
        p = typeof p === "string" ? p : "";
        heard = Date.now();
        if (!p) {
          // Let go: out once what was drawn before it has played.
          queue.push({ at: Math.max(heard, queueEnd), p: "" });
          lastT = -1;
        } else {
          litAt = heard;
          var items = readPath(path);
          // A teacher's page from before the path sends the place alone.
          if (!items.length) {
            if (p !== pointer) { queue.push({ at: Math.max(heard, queueEnd), p: p }); queueEnd = Math.max(heard, queueEnd); }
          } else {
            enqueue(items);
          }
        }
        if (!frame) frame = requestAnimationFrame(place);
      },
      // Whether the page should poll fast: lit now, or lit not long ago.
      lit: function () { return !!litAt && Date.now() - litAt <= WARM_MS; }
    };
  }

  window.LiveLaser = {
    pointAtSlide: pointAtSlide,
    pointAtCode: pointAtCode,
    teacher: teacher,
    student: student,
    // For tools/test_laser.py.
    _pathTo: pathTo,
    _slideSpot: slideSpot,
    _codePos: codePos,
    _readPath: readPath
  };
})();
