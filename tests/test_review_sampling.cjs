const {test} = require('node:test');
const assert = require('node:assert/strict');
const {dimensionValues, sampleMatches, conversationMatchesSearch} = require('../analysis/review_app/sampling.js');

test('conversation search matches scenario and run IDs in any turn, ignoring case and whitespace', () => {
  const session = {id: 'session-1', traces: [
    {id: 'abc123', scenario: 'support-0001'},
    {id: 'def456', scenario: 'support-0140'},
  ]};
  assert.equal(conversationMatchesSearch(session, ' SUPPORT-0140 '), true);
  assert.equal(conversationMatchesSearch(session, 'DEF456'), true);
  assert.equal(conversationMatchesSearch(session, 'def4'), true);
  assert.equal(conversationMatchesSearch(session, 'session-1'), true);
  assert.equal(conversationMatchesSearch(session, 'support-9999'), false);
  assert.equal(conversationMatchesSearch(session, '   '), true);
  assert.equal(conversationMatchesSearch({id: 'empty', traces: [{id: 'x', scenario: null}]}, 'support'), false);
});

const traces = [
  {id: 'a', dimensions: {'authenticated role': 'shopper', intent: 'refund'}},
  {id: 'b', dimensions: {'authenticated role': 'merchant', intent: 'refund'}},
  {id: 'c', dimensions: {'authenticated role': 'shopper', intent: 'cancellation'}},
];
const manifest = {picks: traces.map(t => ({trace_id: t.id, reason: 'dimension sampling: role ' + t.dimensions['authenticated role']}))};

test('available values are distinct and missing dimensions stay empty', () => {
  assert.deepEqual(dimensionValues(traces, 'authenticated role'), ['merchant', 'shopper']);
  assert.deepEqual(dimensionValues(traces, 'difficulty'), []);
});
test('selected values match within a dimension and intersect across dimensions', () => {
  assert.deepEqual([...sampleMatches(manifest, traces, [], {'authenticated role': ['shopper'], intent: ['refund']})], ['a']);
  assert.deepEqual([...sampleMatches(manifest, traces, [], {'authenticated role': ['shopper', 'merchant']})], ['a', 'b', 'c']);
});
test('empty value selection means all known values, while no dimensions adds no traces', () => {
  assert.equal(sampleMatches(manifest, traces, [], {intent: []}).size, 3);
  assert.equal(sampleMatches(manifest, traces, [], {}).size, 0);
  assert.equal(sampleMatches(manifest, traces, [], {difficulty: []}).size, 0);
});
test('uniform and clustered batches remain independent of dimension filters', () => {
  const mixed = {picks: [...manifest.picks, {trace_id: 'random', batch: 'uniform', reason: 'uniform random sample'}, {trace_id: 'cluster', reason: 'cluster 1 centroid representative'}]};
  assert.deepEqual([...sampleMatches(mixed, traces, ['uniform', 'clustered'], {intent: ['nonexistent']})], ['random', 'cluster']);
});

test('dimensions cover the full inventory regardless of sample batch membership', () => {
  const batches = {picks: [
    {trace_id: 'a', reason: 'cluster 0 centroid representative'},
    {trace_id: 'c', reason: 'uniform random sample'},
  ]};
  const inventory = [...traces,
    {id: 'd', dimensions: {'authenticated role': 'shopper', intent: 'cancellation'}},
    {id: 'e', dimensions: {'authenticated role': 'shopper', intent: 'cancellation'}},
  ];
  batches.picks.push({trace_id: 'e', reason: 'cluster 1 centroid representative'});
  const filters = {'authenticated role': ['shopper'], intent: ['cancellation']};
  assert.deepEqual([...sampleMatches(batches, inventory, [], filters)].sort(), ['c', 'd', 'e']);
  assert.deepEqual([...sampleMatches(batches, inventory, ['uniform'], filters)].sort(), ['c', 'd', 'e']);
  assert.deepEqual([...sampleMatches({picks: []}, inventory, [], filters)].sort(), ['c', 'd', 'e']);
});
