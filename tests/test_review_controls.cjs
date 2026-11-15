const {test} = require('node:test');
const assert = require('node:assert/strict');
const {isReviewShortcut} = require('../analysis/review_app/review-controls.js');

const key = overrides => ({key: ' ', target: {closest: () => null}, ...overrides});
test('plain Space toggles, while held keys and modified shortcuts do not', () => {
  assert.equal(isReviewShortcut(key()), true);
  for (const name of ['repeat', 'ctrlKey', 'metaKey', 'altKey', 'shiftKey', 'isComposing', 'defaultPrevented']) {
    assert.equal(isReviewShortcut(key({[name]: true})), false);
  }
  assert.equal(isReviewShortcut(key({key: 'Enter'})), false);
});
test('Space belongs to editable fields and focused interactive controls', () => {
  for (const selector of ['textarea', 'input', 'select', 'button', 'a', 'summary', '[contenteditable]', '[role="textbox"]']) {
    const target = {closest: selectors => selectors.includes(selector) ? {} : null};
    assert.equal(isReviewShortcut(key({target})), false, selector);
  }
});
