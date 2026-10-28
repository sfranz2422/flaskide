// The class's week, at the top of its page (Course.calendar).
//
// THE SAME FILE IN PYIDE, WEBIDE AND FLASKIDE. It is handed each app's own
// markdown renderer (PyIDENotes / WebIDENotes / FlaskIDENotes .render), so
// nothing in here names an app.
//
// The teacher pastes one block of text, the way they would type it in an
// email:
//
//     Week of Oct 27            <- anything before the first day is the title
//     Monday:
//     Loops worksheet
//     - Quiz on [chapter 4](https://...)
//     Tuesday: Lab day          <- text after the colon is that day's first line
//
// and it becomes a row of day cards. The text is what is stored, never the
// cards, so the format can grow without touching a row in the database.
//
// WHAT COUNTS AS A DAY. A line that starts with a day's name (Monday, Mon,
// Tues, Thurs…), optionally a date (10/27, Oct 27), and then a colon, a
// spaced dash, or nothing at all. "Friday: quiz" and "Friday" are days;
// "Friday quiz on loops" is not — it is a line of whatever day came before.
// Without that rule, the first to-do that happens to start with a day's name
// ("Monday's homework is…") would silently split a day in two. Markdown
// around the header (**Monday:**, ## Monday) is allowed, since a block
// copied out of a doc or the old HTML table often carries it.
//
// TODAY. A day with a date is today only on that date, so a calendar left up
// from last week doesn't point at the wrong Wednesday. With no dates written
// anywhere, today is whichever day has today's name.
(function (root) {
  "use strict";

  var DAYS = [
    ["Sunday", "sun", "sunday"],
    ["Monday", "mon", "monday"],
    ["Tuesday", "tue", "tues", "tuesday"],
    ["Wednesday", "wed", "weds", "wednesday"],
    ["Thursday", "thu", "thur", "thurs", "thursday"],
    ["Friday", "fri", "friday"],
    ["Saturday", "sat", "saturday"]
  ];
  var MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
                "jul", "aug", "sep", "oct", "nov", "dec"];

  var NAMES = [];
  DAYS.forEach(function (d) { NAMES = NAMES.concat(d.slice(1)); });
  // Longest first, so "thursday" is never read as "thu" + "rsday".
  NAMES.sort(function (a, b) { return b.length - a.length; });

  var DATE = "(\\d{1,2}[/.-]\\d{1,2}(?:[/.-]\\d{2,4})?" +
             "|(?:" + MONTHS.join("|") + ")[a-z]*\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?)";
  var HEADER = new RegExp(
    "^[\\s#>*_]*(" + NAMES.join("|") + ")\\.?" +   // the day, markdown before it
    "(?:,?\\s*\\(?" + DATE + "\\)?)?" +            // a date, maybe in brackets
    "[*_]*\\s*(?::|[-–—]\\s|$)[*_]*\\s*(.*)$",       // colon, " - ", or the end
    "i");

  function dayIndex(word) {
    word = word.toLowerCase();
    for (var i = 0; i < DAYS.length; i++) {
      if (DAYS[i].indexOf(word, 1) > 0) return i;
    }
    return -1;
  }

  // "10/27", "10-27-26", "Oct 27th" → { month: 9, day: 27 }, or null.
  function readDate(text) {
    if (!text) return null;
    var m = /^(\d{1,2})[/.-](\d{1,2})/.exec(text);
    if (m) return { month: +m[1] - 1, day: +m[2] };
    m = /^([a-z]+)\.?\s+(\d{1,2})/i.exec(text);
    if (m) {
      var at = MONTHS.indexOf(m[1].slice(0, 3).toLowerCase());
      if (at >= 0) return { month: at, day: +m[2] };
    }
    return null;
  }

  // A line under a day as a markdown list item: it keeps a bullet the
  // teacher typed (and its indent, for a sub-point), and gets one if not.
  function asItem(line) {
    var m = /^(\s*)(?:[-*+•]|\d+[.)])\s+(.*)$/.exec(line);
    if (m) return m[1].replace(/\t/g, "  ") + "- " + m[2];
    return "- " + line.trim();
  }

  // The text → { title, days: [{ index, name, date, when, lines }] }.
  // `days` is empty when no line is a day — the teacher's preview says so.
  function parse(text) {
    var title = [], days = [], day = null;
    String(text || "").replace(/\r\n?/g, "\n").split("\n").forEach(function (line) {
      var m = HEADER.exec(line);
      if (m) {
        var index = dayIndex(m[1]);
        day = { index: index, name: DAYS[index][0], date: (m[2] || "").trim(),
                when: readDate(m[2]), lines: [] };
        days.push(day);
        if (m[3].trim()) day.lines.push(m[3]);
        return;
      }
      if (!line.trim()) return;
      (day ? day.lines : title).push(line);
    });
    return { title: title.join("\n").trim(), days: days };
  }

  // Which of the parsed days is today, as an index into `days`, or -1.
  function todayIn(days, now) {
    now = now || new Date();
    var dated = days.some(function (d) { return d.when; });
    for (var i = 0; i < days.length; i++) {
      var d = days[i];
      if (dated ? (d.when && d.when.month === now.getMonth() && d.when.day === now.getDate())
                : d.index === now.getDay()) {
        return i;
      }
    }
    return -1;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  // Draw the week into `box`, and its title into `heading` ("This week" when
  // the text has none). `render(el, markdown)` is the app's markdown renderer
  // (it sanitises, and opens links in a new tab), used for the title and each
  // day's lines so links and **bold** work there as in a banner. Returns the
  // parse, so the teacher's preview can tell a week with no days in it.
  function draw(box, heading, text, render, now) {
    var week = parse(text);
    box.textContent = "";
    if (heading) {
      heading.textContent = week.title ? "" : "This week";
      if (week.title) render(heading, week.title);
    }
    if (!week.days.length) return week;

    var grid = el("div", "cal-grid");
    grid.style.setProperty("--cal-days", String(Math.min(week.days.length, 7)));
    var today = todayIn(week.days, now);
    week.days.forEach(function (d, i) {
      var card = el("section", "cal-day" + (i === today ? " is-today" : ""));
      var top = el("header", "cal-day-head");
      top.appendChild(el("span", "cal-dow", d.name));
      if (d.date) top.appendChild(el("span", "cal-date", d.date));
      if (i === today) top.appendChild(el("span", "cal-today", "Today"));
      card.appendChild(top);
      var body = el("div", "cal-body md");
      card.appendChild(body);
      if (d.lines.length) render(body, d.lines.map(asItem).join("\n"));
      else body.appendChild(el("p", "cal-nothing", "—"));
      grid.appendChild(card);
    });
    box.appendChild(grid);
    return week;
  }

  var api = { parse: parse, todayIn: todayIn, asItem: asItem, draw: draw };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ClassCalendar = api;
})(typeof window !== "undefined" ? window : this);
