/**
 * Wave Explorer — Keyboard shortcuts
 *
 *   D            toggle draw-region mode
 *   X            exclude / restore the selected region
 *   Z            undo the last pending change
 *   Ctrl/⌘ + S   save the curated file
 *   Esc          deselect the active region
 *
 * Each shortcut simply clicks the existing control, so all behaviour
 * stays owned by the Dash callbacks — this layer only routes keystrokes.
 */

(function () {
  "use strict";

  function clickIfLive(id) {
    var el = document.getElementById(id);
    // getClientRects() is empty when the element (or an ancestor) is
    // display:none — unlike offsetParent, this also works for elements
    // inside position:fixed containers.
    if (el && !el.disabled && el.isConnected &&
        el.getClientRects().length > 0) {
      el.click();
      return true;
    }
    return false;
  }

  function isTyping(e) {
    var t = e.target;
    if (!t) return false;
    var tag = (t.tagName || "").toUpperCase();
    return (
      tag === "INPUT" ||
      tag === "SELECT" ||
      tag === "TEXTAREA" ||
      t.isContentEditable === true
    );
  }

  function onKey(e) {
    if (isTyping(e)) return;
    var k = e.key;

    // Ctrl/⌘ + S is the only modified shortcut we own.
    if ((k === "s" || k === "S") && (e.metaKey || e.ctrlKey) && !e.altKey) {
      if (clickIfLive("save-changes-btn")) e.preventDefault();
      return;
    }
    // Never hijack other browser/OS chords (Ctrl+D bookmark, Ctrl+Z, …).
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    if (k === "d" || k === "D") {
      if (clickIfLive("draw-mode-toggle")) e.preventDefault();
    } else if (k === "Escape") {
      clickIfLive("selected-clear-btn");
    } else if (k === "z" || k === "Z") {
      if (clickIfLive("undo-btn")) e.preventDefault();
    } else if (k === "x" || k === "X") {
      // Whichever of exclude / restore is currently visible.
      if (!clickIfLive("selected-exclude-btn")) {
        clickIfLive("selected-restore-btn");
      }
    }
  }

  window.addEventListener("keydown", onKey);
})();
