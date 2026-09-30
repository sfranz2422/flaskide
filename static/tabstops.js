/* FlaskIDE — Tab and Backspace that move between tab stops.
 *
 * Used by both editors a student types into: the main one (app.js) and
 * their own copy during a live lesson (live.js). It was once written inside
 * app.js alone, and the live editor, built separately, quietly went without
 * it — which in this app means Tab put a literal tab character into Python
 * that auto-indent had written with spaces (see below), in exactly the
 * lesson where a whole class is copying indentation off the board. One file
 * means an editor either has it or visibly does not bind it.
 */

window.FlaskIDETabStops = (function () {
  "use strict";

  /*
   * THIS EDITOR WAS INSERTING LITERAL TAB CHARACTERS.
   *
   * With no Tab binding at all, CodeMirror falls back to its own default:
   * defaultTab -> insertTab -> replaceSelection("\t"). Checked against a
   * live CodeMirror 5, not from memory. So every Tab a student pressed put
   * a hard tab in the file, while Enter's auto-indent put spaces — and
   * Python 3 rejects that mixture outright with a TabError, on a line that
   * looks perfectly aligned on screen. In a Flask project the traceback
   * arrives in the preview pane, one step removed from the line that caused
   * it, which makes it about as hard to find as it gets.
   *
   * Binding Tab fixes that on its own. Aligning both keys to stops is the
   * rest of the change: Tab goes to the next multiple of the indent unit
   * rather than always inserting four, and Backspace comes back to the
   * previous one rather than eating a single space at a time.
   *
   * Same pair as PyIDE, WebIDE and the playground. The unit is read from
   * the editor rather than written down, because it is four here and two in
   * WebIDE.
   */
  function spaces(n) {
    return new Array(n + 1).join(" ");
  }

  function indentToTabStop(cm) {
    if (cm.somethingSelected()) {
      cm.indentSelection("add");
      return;
    }
    var unit = cm.getOption("indentUnit");
    // More than one caret: no single column to align to, so fall back to a
    // whole unit at each. Rare enough not to be worth a wrong answer.
    if (cm.listSelections().length > 1) {
      cm.replaceSelection(spaces(unit), "end");
      return;
    }
    var head = cm.getCursor();
    var col = CodeMirror.countColumn(cm.getLine(head.line), head.ch,
                                     cm.getOption("tabSize"));
    // Never 0 and never more than a full unit: at a stop it moves a whole
    // one, off a stop it moves just enough to land on the next.
    cm.replaceSelection(spaces(unit - (col % unit)), "end");
  }

  function backspaceToTabStop(cm) {
    if (cm.somethingSelected() || cm.listSelections().length > 1) {
      return CodeMirror.Pass;
    }
    var head = cm.getCursor();
    var before = cm.getLine(head.line).slice(0, head.ch);

    /* ONLY IN THE INDENTATION, AND ONLY SPACES.
     *
     * With anything but spaces to the left, this is ordinary typing and one
     * press must delete one character — a Backspace that swallowed four
     * characters of a word would be unusable. A literal tab is excluded
     * too, and this editor will have files full of them from before Tab was
     * bound: one tab is one character but four columns, so "delete back to
     * the stop" has two different right answers and the wrong one eats
     * code. Both fall through to CodeMirror. */
    if (before.length === 0 || !/^ +$/.test(before)) {
      return CodeMirror.Pass;
    }

    var unit = cm.getOption("indentUnit");
    var col = before.length;
    var target = (col % unit === 0) ? col - unit : col - (col % unit);
    if (target < 0) target = 0;
    cm.replaceRange("", { line: head.line, ch: target }, head, "+delete");
  }

  return {
    indentToTabStop: indentToTabStop,
    backspaceToTabStop: backspaceToTabStop
  };
})();
