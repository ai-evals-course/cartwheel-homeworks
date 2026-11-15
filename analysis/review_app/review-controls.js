function isReviewShortcut(event) {
  return event.key === ' ' && !event.repeat && !event.defaultPrevented && !event.isComposing &&
    !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey &&
    !event.target?.closest('input, textarea, select, button, a, summary, [contenteditable], [role="textbox"], [role="button"], [role="combobox"]');
}

if (typeof module !== 'undefined') module.exports = {isReviewShortcut};
