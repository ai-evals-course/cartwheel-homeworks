/* No trace content is interpreted as HTML. Anchors refer to source fields. */
const $ = (id) => document.getElementById(id);
const state = {catalog: null, review: null, session: null, view: 'read', busy: false, loading: false, request: 0, editor: null, disclosures: new Map(), noteTarget: null, taxonomyMode: null, taxonomyTab: 'summary', selectedSuggestions: new Set(), suggestionBatchBusy: false, suggestionFeedback: ''};
const allTraces = () => state.catalog.sessions.flatMap(s => s.traces);
const finalModes = () => state.review.modes.filter(m => m.final);
const reviewed = id => ['reviewed', 'first_failure', 'no_failure'].includes(state.review.reviews[id]?.status);
const notesFor = id => state.review.annotations.filter(n => n.trace_id === id);
const conversationReviewed = ids => ids.some(id => notesFor(id).length > 0) || (ids.length > 0 && ids.every(reviewed));
const pendingFor = id => state.review.suggestions.filter(s => s.trace_id === id && !state.review.decisions[s.id]);
const pretty = value => value === undefined || value === null ? 'Not captured' : JSON.stringify(value, null, 2);
const backupKey = () => 'cartwheel-review-draft:' + location.origin + ':' + state.catalog.namespace;

function el(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value !== undefined) node.textContent = String(value);
  return node;
}
function button(title, action, cls = '') {
  const node = el('button', cls, title);
  node.type = 'button';
  node.onclick = action;
  return node;
}
function details(title, content, open = false, key = null) {
  const node = el('details');
  if (key) node.dataset.disclosure = key;
  node.open = key ? (state.disclosures.get(key) ?? open) : open;
  node.append(el('summary', '', title), content);
  return node;
}
function notice(message) {
  $('notice').hidden = false;
  $('notice').replaceChildren(document.createTextNode(message), button('Dismiss', () => {$('notice').hidden = true;}));
}
async function get(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
async function act(event) {
  if (state.busy) return false;
  state.busy = true;
  $('save-status').textContent = 'Saving…';
  try {
    const response = await fetch('/api/action', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...event, revision: state.review.revision})});
    const data = await response.json();
    if (!response.ok) {
      if (event.action === 'delete_note' && data.error === 'Unknown review action')
        throw new Error('Restart the review server to enable comment deletion.');
      throw new Error(data.error || 'Save failed');
    }
    state.review = data;
    render();
    return true;
  } catch (error) {
    $('save-status').textContent = 'Save failed · draft retained';
    notice(error.message);
    return false;
  } finally {state.busy = false;}
}
function saveStatus() {
  const pending = Object.values(state.review.labels).filter(l => l.sync === 'pending').length;
  $('save-status').replaceChildren(document.createTextNode(pending ? `${pending} label(s) saved locally · sync pending` : 'Local state saved'));
  if (pending) $('save-status').append(button('Retry sync', () => act({action: 'retry'})));
}
function roleLegend() {
  const row = el('div', 'legend quiet');
  for (const [name, color] of [['User', 'user'], ['Agent', 'assistant'], ['Tool', 'tool']]) {
    const span = el('span', '', name);
    span.style.setProperty('--role-color', `var(--${color})`);
    row.append(span);
  }
  return row;
}
function roleBadge(role) {
  const badge = el('span', 'audience-badge', role || 'Unknown role');
  badge.dataset.audience = role || 'unknown';
  return badge;
}
function setSamplingMenu(open) {
  $('sampling-menu').hidden = !open;
  $('sampling-arrow').setAttribute('aria-expanded', String(open));
  if (!open) closeDimensionOptions();
}
function closeDimensionOptions() {
  for (const button of document.querySelectorAll('.dimension-arrow')) {
    button.setAttribute('aria-expanded', 'false');
    $(button.getAttribute('aria-controls')).hidden = true;
  }
}
function positionDimensionOptions(panel, row) {
  panel.removeAttribute('style');
  if (window.innerWidth <= 650) return;
  const rect = row.getBoundingClientRect();
  panel.style.left = Math.max(8, Math.min(rect.right, window.innerWidth - panel.offsetWidth - 12)) + 'px';
  panel.style.top = Math.max(8, Math.min(rect.top, window.innerHeight - panel.offsetHeight - 12)) + 'px';
}
window.addEventListener('resize', closeDimensionOptions);
function initDimensionOptions() {
  for (const input of $('sampling-dimensions').querySelectorAll('input[data-dimension]')) {
    const name = input.dataset.dimension, label = input.closest('label');
    const row = el('div', 'dimension-row');
    label.replaceWith(row);
    const arrow = button('▸', () => {
      const open = panel.hidden;
      closeDimensionOptions();
      panel.hidden = !open;
      arrow.setAttribute('aria-expanded', String(open));
      if (open) {
        positionDimensionOptions(panel, row);
        panel.querySelector('input')?.focus();
      }
    }, 'dimension-arrow');
    const panel = el('fieldset', 'dimension-options');
    panel.id = 'dimension-options-' + name.replaceAll(' ', '-');
    panel.hidden = true;
    panel.append(el('legend', '', label.textContent.trim()));
    arrow.setAttribute('aria-label', 'Choose ' + name + ' values');
    arrow.setAttribute('aria-expanded', 'false');
    arrow.setAttribute('aria-controls', panel.id);
    const values = dimensionValues(allTraces(), name);
    for (const value of values) {
      const option = el('label'), checkbox = el('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.dimensionValue = value;
      option.append(checkbox, document.createTextNode(value.replaceAll('_', ' ')));
      checkbox.addEventListener('change', () => {
        input.checked = true;
        updateDimensionSummary(row);
        positionDimensionOptions(panel, row);
      });
      panel.append(option);
    }
    if (!values.length) panel.append(el('p', 'quiet', 'No values available in this trace source.'));
    const summary = el('div', 'dimension-selected');
    summary.setAttribute('aria-live', 'polite');
    summary.hidden = true;
    row.append(label, arrow, summary, panel);
    input.addEventListener('change', () => updateDimensionSummary(row));
    arrow.addEventListener('keydown', event => {
      if (event.key === 'ArrowRight' && panel.hidden) {event.preventDefault(); arrow.click();}
    });
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape' || event.key === 'ArrowLeft') {
        event.preventDefault(); event.stopPropagation();
        closeDimensionOptions(); arrow.focus();
      }
    });
  }
}
function updateDimensionSummary(row) {
  const summary = row.querySelector('.dimension-selected');
  const values = [...row.querySelectorAll('input[data-dimension-value]:checked')];
  summary.replaceChildren(...values.map(input => el('span', 'dimension-chip', input.dataset.dimensionValue.replaceAll('_', ' '))));
  summary.hidden = !row.querySelector('input[data-dimension]').checked || !values.length;
}
$('sampling-enabled').addEventListener('change', () => {
  const enabled = $('sampling-enabled').checked;
  $('sampling-arrow').hidden = !enabled;
  setSamplingMenu(enabled);
  renderQueue();
});
$('sampling-arrow').addEventListener('click', () => setSamplingMenu($('sampling-menu').hidden));
$('sampling-menu').addEventListener('change', () => {
  $('sampling-dimensions').hidden = !$('sampling-dimension').checked;
  if ($('sampling-dimensions').hidden) closeDimensionOptions();
  renderQueue();
});
document.addEventListener('pointerdown', event => {
  if (!$('sampling-menu').contains(event.target) &&
      !$('sampling-arrow').contains(event.target) &&
      !$('sampling-enabled').closest('label').contains(event.target)) setSamplingMenu(false);
}, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('sampling-menu').hidden) {
    setSamplingMenu(false);
    $('sampling-arrow').focus();
  }
});
function renderQueue() {
  const enabled = $('sampling-enabled').checked;
  const selected = [...$('sampling-menu').querySelectorAll(':scope > label input[value]:checked')].map(input => input.value);
  const dimensions = {};
  if ($('sampling-dimension').checked) {
    for (const input of $('sampling-dimensions').querySelectorAll('input[data-dimension]:checked')) {
      dimensions[input.dataset.dimension] = [...input.closest('.dimension-row').querySelectorAll('input[data-dimension-value]:checked')].map(option => option.dataset.dimensionValue);
    }
  }
  const manifest = state.catalog.sample_manifest || {};
  const matches = sampleMatches(manifest, allTraces(), selected, dimensions);
  const query = $('queue-search').value.trim();
  const sampledGroups = enabled ? state.catalog.sessions.filter(session => session.traces.some(trace => matches.has(trace.id))) : state.catalog.sessions;
  const groups = sampledGroups.filter(session => conversationMatchesSearch(session, query));
  const totalReviewed = state.catalog.sessions.filter(session => conversationReviewed(session.traces.map(trace => trace.id))).length;
  $('total-reviews').textContent = `${totalReviewed} reviewed`;
  $('total-reviews').title = `${totalReviewed} reviewed conversations across the full list`;
  $('total-reviews').setAttribute('aria-label', `${totalReviewed} reviewed conversations across the full list`);
  $('queue-count').textContent = query
    ? `${groups.reduce((count, session) => count + session.traces.length, 0)} traces · ${groups.length} conversations`
    : enabled
    ? `${allTraces().filter(trace => matches.has(trace.id)).length} matching traces · ${groups.length} conversations`
    : `${allTraces().length} traces · ${state.review.annotations.length} comments`;
  const list = $('queue-list');
  list.replaceChildren();
  for (const session of groups) {
    const first = session.traces[0];
    const comments = session.traces.reduce((count, trace) => count + notesFor(trace.id).length, 0);
    const item = button('', () => openSession(session.id), 'conversation' + (state.session?.id === session.id ? ' active' : ''));
    item.setAttribute('aria-current', state.session?.id === session.id ? 'true' : 'false');
    const title = el('span', 'conversation-title');
    const status = el('span', 'conversation-status');
    const commentCount = el('span', 'reviewed-count', comments);
    commentCount.setAttribute('aria-label', `${comments} comments`);
    commentCount.title = `${comments} comments`;
    status.append(roleBadge(first.role));
    const name = el('span', 'conversation-name');
    name.append(el('strong', '', first.scenario || 'Unassigned scenario'));
    if (conversationReviewed(session.traces.map(trace => trace.id))) {
      const indicator = el('span', 'reviewed-indicator', 'R');
      indicator.setAttribute('aria-label', 'Reviewed');
      indicator.title = 'Reviewed';
      name.append(indicator);
    }
    title.append(name, status);
    const counts = el('span', 'conversation-counts quiet');
    counts.append(el('span', '', `${session.traces.length} ${session.traces.length === 1 ? 'trace' : 'traces'}`));
    if (comments) counts.append(commentCount);
    item.append(title, counts);
    list.append(item);
  }
  if (!groups.length) list.append(el('p', 'empty', query ? 'No conversations match this ID in the current filters.' : enabled ? (selected.length || Object.keys(dimensions).length ? 'No traces match these selections.' : 'Choose one or more sampling methods or dimensions.') : 'No conversations available.'));
}
$('queue-search').addEventListener('input', () => {
  if (state.catalog && state.review) renderQueue();
});
$('queue-search').addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    event.preventDefault();
    $('queue-search').value = '';
    if (state.catalog && state.review) renderQueue();
  }
});
async function openSession(id, traceId) {
  if (state.editor) closeNote();
  const request = ++state.request;
  state.loading = true;
  $('session-header').textContent = 'Loading conversation…';
  try {
    const session = await get('/api/session?id=' + encodeURIComponent(id));
    if (request !== state.request) return;
    state.session = session;
    state.loading = false;
    $('view-scroll').scrollTop = 0;
    const hash = new URLSearchParams({session: id});
    history.replaceState(null, '', '#' + hash);
    render();
    if (traceId) document.getElementById('trace-' + traceId)?.scrollIntoView({behavior: 'smooth'});
  } catch (error) {if (request === state.request) {state.loading = false; notice(error.message);}}
}
function jumpTrace(id) {
  const session = state.catalog.sessions.find(s => s.traces.some(t => t.id === id));
  if (!session) return notice('That trace is not in this project inventory.');
  switchView('read');
  openSession(session.id, id);
}
function switchView(view) {
  if (state.editor) closeNote();
  setSamplingMenu(false);
  state.view = view;
  $('view-scroll').scrollTop = 0;
  for (const node of document.querySelectorAll('[data-view]')) node.setAttribute('aria-pressed', String(node.dataset.view === view));
  for (const node of document.querySelectorAll('.view')) node.hidden = node.id !== view + '-view';
  render();
}
function anchorMatches(anchor, blockId, field, content) {
  return anchor && anchor.block_id === blockId && anchor.field === field && Number.isInteger(anchor.start) &&
    anchor.end > anchor.start && content.slice(anchor.start, anchor.end) === anchor.quote;
}
function anchored(content, traceId, blockId, field, mono = false) {
  content = String(content);
  const node = el(mono ? 'pre' : 'div', mono ? 'annotatable' : 'prose annotatable');
  node.dataset.trace = traceId; node.dataset.block = blockId; node.dataset.field = field;
  const items = [...notesFor(traceId), ...pendingFor(traceId).map(s => ({...s, ai: true}))];
  let spans = items.filter(n => anchorMatches(n.anchor, blockId, field, content)).map(n => ({...n.anchor, id: n.id, ai: n.ai}));
  const draft = state.editor;
  if (draft?.trace_id === traceId && anchorMatches(draft.anchor, blockId, field, content)) {
    spans = spans.filter(s => s.end <= draft.anchor.start || s.start >= draft.anchor.end);
    spans.push({...draft.anchor, id: 'pending', pending: true});
  }
  spans.sort((a,b) => a.start - b.start || Number(!!b.pending) - Number(!!a.pending));
  let offset = 0;
  for (const span of spans) {
    if (span.start < offset) continue; // Both overlapping notes remain visible in the margin.
    node.append(document.createTextNode(content.slice(offset, span.start)));
    const mark = el('mark', span.pending ? 'pending' : span.ai ? 'ai' : '', content.slice(span.start, span.end));
    mark.dataset.note = span.id;
    node.append(mark);
    offset = span.end;
  }
  node.append(document.createTextNode(content.slice(offset)));
  return node;
}
function renderTool(block, tid) {
  const outer = el('div', 'block tool-message'); outer.dataset.role = 'assistant';
  outer.append(el('div', 'role-label', 'Tool'));
  const node = el('details', 'tool-disclosure'); node.dataset.role = 'tool'; node.dataset.blockId = block.id;
  const key = tid + ':' + block.id;
  node.dataset.disclosure = key;
  node.open = state.disclosures.get(key) ?? false;
  const result = block.result;
  const heading = el('summary', 'tool-heading');
  heading.append(el('span', 'tool-name', block.name + '()'));
  const status = result?.error || result?.status || (result?.ok === false ? 'failed' : null);
  if (status) heading.append(el('span', 'tool-summary-status', String(status)));
  node.append(heading);
  const body = el('div', 'tool-body');
  for (const [title, field, value] of [['Arguments', 'input', block.arguments], ['Complete result', 'output', result]]) {
    const section = el('section', 'tool-section');
    section.append(el('h3', 'tool-section-title', title), anchored(pretty(value), tid, block.id, field, true));
    body.append(section);
  }
  node.append(body);
  outer.append(node);
  return outer;
}
function noteCard(note, kind = 'human') {
  const node = el('div', 'note-card ' + (kind === 'suggestion' ? 'suggestion' : kind === 'legacy' ? 'legacy' : ''));
  node.dataset.noteCard = note.id;
  const label = kind === 'suggestion' ? 'AI suggestion · unaccepted' : kind === 'legacy' ? 'Existing annotation · read only' : note.source === 'human_accepted_ai' ? 'Human accepted · AI origin' : '';
  if (label) node.append(el('strong', '', label));
  const quote = note.anchor?.quote || note.quote;
  if (quote) node.append(el('blockquote', '', quote));
  node.append(el('p', '', note.note || note.reason || 'No note text'));
  if (!note.anchor?.block_id) node.append(el('p', 'quiet', 'Trace-level evidence · no precise source anchor'));
  const actions = el('div', 'actions');
  if (kind === 'suggestion') {
    actions.append(button('Accept', () => act({action:'suggestion', id: note.id, decision:'accept'})), button('Reject', () => act({action:'suggestion', id: note.id, decision:'reject'})));
  } else if (kind !== 'legacy') {
    actions.hidden = true;
    actions.classList.add('note-edit-actions');
    node.tabIndex = 0;
    node.setAttribute('aria-label', 'Comment. Activate to show edit action.');
    const reveal = () => { actions.hidden = false; requestAnimationFrame(layoutNotes); };
    node.addEventListener('click', reveal);
    node.addEventListener('keydown', e => {
      if (e.target === node && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); reveal(); }
    });
    const remove = button('×', () => act({action:'delete_note', trace_id:note.trace_id, id:note.id}), 'delete-note');
    remove.setAttribute('aria-label', 'Delete comment');
    remove.title = 'Delete comment';
    actions.append(button('Edit note', e => editNote(note, e.currentTarget)), remove);
  }
  node.append(actions);
  node.onmouseenter = () => {for (const m of document.querySelectorAll('mark')) if (m.dataset.note === note.id) m.classList.add('pending');};
  node.onmouseleave = () => {for (const m of document.querySelectorAll('mark')) if (m.dataset.note === note.id) m.classList.remove('pending');};
  return node;
}
document.addEventListener('click', event => {
  for (const actions of document.querySelectorAll('.note-edit-actions')) {
    if (!actions.closest('.note-card').contains(event.target) && !actions.hidden) {
      actions.hidden = true;
      requestAnimationFrame(layoutNotes);
    }
  }
});
function renderRead() {
  for (const disclosure of $('read-view').querySelectorAll('[data-disclosure]')) state.disclosures.set(disclosure.dataset.disclosure, disclosure.open);
  const root = $('read-view'); root.replaceChildren();
  if (!state.session) return root.append(el('p', 'empty', 'No session selected.'));
  const systems = new Map();
  for (const turn of state.session.turns) {
    const captured = [...new Set((turn.raw.observations || []).filter(o => o.type === 'GENERATION').flatMap(o => (o.input?.messages || []).filter(m => m.role === 'system').flatMap(m => (m.parts || []).filter(p => p.type === 'text').map(p => p.content))))];
    captured.forEach((content, index) => {
      if (!systems.has(content)) systems.set(content, {traceId: turn.id, blockId: 'system-' + index});
    });
  }
  state.session.turns.forEach((turn, index) => {
    const article = el('article', 'trace'); article.id = 'trace-' + turn.id;
    article.setAttribute('aria-label', 'Trace ' + turn.id);
    const grid = el('div', 'turn-grid'), body = el('div', 'evidence'), notes = el('aside', 'notes');
    notes.setAttribute('aria-label', 'Evidence notes for trace ' + turn.id);
    for (const warning of turn.warnings) body.append(el('p', 'warning', warning));
    if (index === 0 && systems.size) {
      const wrapper = el('div');
      systems.forEach((source, content) => wrapper.append(anchored(content, source.traceId, source.blockId, 'system', true)));
      const instructions = details('System instructions', wrapper, false, state.session.id + ':system');
      instructions.className = 'system'; body.append(instructions);
    }
    const lastActivity = turn.blocks.filter(block => block.role !== 'thinking').at(-1);
    for (const block of turn.blocks) {
      if (block.role === 'tool') {body.append(renderTool(block, turn.id)); continue;}
      const item = el('div', 'block'); item.dataset.role = block.role; item.dataset.blockId = block.id;
      let label = block.role;
      if (block.role === 'assistant') {
        const final = lastActivity?.role === 'assistant' && block.observation_id === lastActivity.observation_id;
        item.dataset.agentPhase = final ? 'final' : 'in-between';
        label = final ? 'Agent (Final)' : 'Agent (In-between)';
      }
      const content = anchored(block.text, turn.id, block.id, block.field);
      if (block.role === 'user' || block.role === 'assistant') {
        const inner = el('div', 'message-content');
        inner.append(content);
        item.append(el('div', 'role-label', label), inner);
      } else {
        item.append(el('div', 'role-label', label), content);
      }
      body.append(item);
    }
    notesFor(turn.id).forEach(n => notes.append(noteCard(n)));
    state.catalog.legacy_annotations.filter(n => n.trace_id === turn.id).forEach(n => notes.append(noteCard(n, 'legacy')));
    pendingFor(turn.id).forEach(n => notes.append(noteCard(n, 'suggestion')));
    grid.append(body, notes); article.append(grid);
    root.append(article);
  });
  requestAnimationFrame(layoutNotes);
}
function layoutNotes() {
  for (const article of document.querySelectorAll('.trace')) {
    const column = article.querySelector('.notes');
    if (!column) continue;
    const cards = [...column.querySelectorAll('.note-card')];
    cards.forEach(card => { card.style.marginTop = ''; });
    if (getComputedStyle(column).display === 'flex') continue;
    const marks = [...article.querySelectorAll('mark')];
    const columnTop = column.getBoundingClientRect().top;
    const targets = new Map(cards.map(card => {
      const mark = marks.find(m => m.dataset.note === card.dataset.noteCard);
      return [card, mark ? mark.getBoundingClientRect().top - columnTop : Infinity];
    }));
    cards.sort((a, b) => targets.get(a) - targets.get(b));
    cards.forEach(card => column.append(card));
    for (const card of cards) {
      const target = targets.get(card);
      const current = card.getBoundingClientRect().top - columnTop;
      if (Number.isFinite(target)) card.style.marginTop = Math.max(0, target - current) + 'px';
    }
  }
}
function renderLabels() {
  const root = $('labels-view'); root.replaceChildren();
  root.append(el('h2', '', 'Structured labeling'), el('p', 'quiet', 'Label each individual trace against every final mode. Unreviewed is distinct from Absent. Each choice is an explicit human judgment saved locally and synchronized to Langfuse.'));
  if (!finalModes().length) return root.append(el('p', 'empty', 'No modes are final yet. Complete open coding, then define and confirm your modes in Taxonomy.'));
  if (!state.session) return;
  for (const turn of state.session.turns) {
    const panel = el('div', 'panel'); panel.append(el('h3', '', `Trace ${turn.id}`), button('Read evidence', () => jumpTrace(turn.id)));
    const table = el('table'); const header = el('tr'); ['Mode', 'Definition', 'Human decision', 'Save status'].forEach(s => header.append(el('th', '', s))); table.append(header);
    for (const mode of finalModes()) {
      const row = el('tr'), label = state.review.labels[turn.id + ':' + mode.id], choice = el('td'), actions = el('div', 'actions');
      for (const [name,value] of [['Present',1], ['Absent',0]]) {
        const b = button(name, () => act({action:'label', trace_id:turn.id, mode:mode.id, value,
          comment: notesFor(turn.id).map(n => n.note).join('\n')}));
        b.setAttribute('aria-pressed', String(label?.value === value)); actions.append(b);
      }
      choice.append(actions, el('p', 'quiet', label ? 'Current: ' + (label.value ? 'Present' : 'Absent') : 'Unreviewed'));
      row.append(el('td', '', mode.id), el('td', '', mode.definition), choice,
        el('td', '', label ? label.sync === 'synced' ? 'Langfuse verified' : 'Saved locally · sync pending' : 'No judgment'));
      table.append(row);
    }
    const wrap = el('div', 'table-wrap'); wrap.append(table); panel.append(wrap); root.append(panel);
  }
}
function field(form, label, name, value = '', multiline = false) {
  const outer = el('label', '', label), input = el(multiline ? 'textarea' : 'input');
  input.name = name; input.value = value; if (multiline) input.rows = 3;
  outer.append(input); form.append(outer); return input;
}
function renderTaxonomy() {
  const root = $('taxonomy-view'); root.replaceChildren();
  root.append(el('h2', '', 'Failure taxonomy'));
  if (!state.review.modes.length) {
    root.append(el('p', 'empty', 'No failure modes recorded yet.'));
  }
  const modes = state.review.modes.map((mode, index) => ({
    mode, index, notes: state.review.annotations.filter(n => (mode.annotation_ids || []).includes(n.id))
  })).sort((a, b) => b.notes.length - a.notes.length);
  const assignedIds = new Set(modes.flatMap(item => item.notes.map(note => note.id)));
  const unassigned = state.review.annotations.filter(note => !assignedIds.has(note.id));
  const mapGroups = [...modes];
  if (unassigned.length) mapGroups.push({mode: {id: '__unassigned', name: 'Unassigned'}, index: 0, notes: unassigned});
  mapGroups.sort((a, b) => b.notes.length - a.notes.length);
  const traceById = new Map(allTraces().map(trace => [trace.id, trace]));
  const runName = note => traceById.get(note.trace_id)?.scenario || note.trace_id;
  if (!mapGroups.some(item => item.mode.id === state.taxonomyMode)) state.taxonomyMode = null;
  const selectMode = id => {
    state.taxonomyMode = state.taxonomyMode === id ? null : id;
    state.suggestionFeedback = '';
    renderTaxonomy();
    document.querySelector('.taxonomy-tile[data-selected="true"] .taxonomy-select')?.focus({preventScroll: true});
  };
  root.append(el('p', 'quiet', 'Groups link observations to proposed failure modes. Select a group to list its conversations below; these links are not confirmed failure labels.'));
  const map = el('div', 'taxonomy-map');
  function buildTiles(items, depth = 0) {
    if (items.length === 1) {
      const {mode, index, notes} = items[0];
      const seenComments = new Set();
      const uniqueNotes = notes.filter(note => {
        const key = note.note.trim().replace(/\s+/g, ' ').replace(/[.,!;:]+$/g, '').toLowerCase();
        if (seenComments.has(key)) return false;
        seenComments.add(key);
        return true;
      });
      const tile = el('section', 'taxonomy-tile');
      tile.dataset.color = index % 6;
      tile.dataset.unassigned = String(mode.id === '__unassigned');
      tile.dataset.selected = String(state.taxonomyMode === mode.id);
      const choose = button(mode.name || mode.id.replaceAll('_', ' '), () => selectMode(mode.id), 'taxonomy-select');
      choose.setAttribute('aria-pressed', String(state.taxonomyMode === mode.id));
      choose.setAttribute('aria-controls', 'taxonomy-summary');
      const heading = el('h3'); heading.append(choose);
      tile.append(heading, el('p', 'taxonomy-count', `${uniqueNotes.length} ${uniqueNotes.length === 1 ? 'comment' : 'comments'}`));
      const previews = el('div', 'taxonomy-previews');
      previews.tabIndex = 0;
      previews.setAttribute('role', 'region');
      previews.setAttribute('aria-label', `${mode.name || mode.id.replaceAll('_', ' ')} comments`);
      uniqueNotes.forEach(note => {
        const preview = el('div', 'taxonomy-comment');
        const excerpt = el('span', 'taxonomy-excerpt');
        const quote = note.anchor?.quote;
        if (quote) excerpt.append(el('em', 'taxonomy-quote', `"${quote}"`), document.createTextNode(' '));
        const comment = el('span', 'taxonomy-note');
        comment.append(el('span', 'taxonomy-comment-label', 'Comment:'), document.createTextNode(` ${note.note}`));
        excerpt.append(comment);
        preview.append(el('span', 'taxonomy-run', runName(note)), excerpt);
        preview.title = `${runName(note)}: ${quote ? `"${quote}"\n` : ''}Comment: ${note.note}`;
        previews.append(preview);
      });
      tile.append(previews);
      tile.addEventListener('click', event => {
        if (!event.target.closest('button')) selectMode(mode.id);
      });
      return tile;
    }
    const weight = item => Math.max(1, item.notes.length);
    const total = items.reduce((sum, item) => sum + weight(item), 0);
    let sum = 0, split = 0;
    while (split < items.length - 1 && (sum < total / 2 || split === 0)) sum += weight(items[split++]);
    const group = el('div', 'taxonomy-group');
    group.style.flexDirection = depth % 2 ? 'column' : 'row';
    const left = buildTiles(items.slice(0, split), depth + 1);
    const right = buildTiles(items.slice(split), depth + 1);
    const basis = depth % 2 ? 'auto' : '0px';
    left.style.flex = `${sum} 1 ${basis}`;
    right.style.flex = `${total - sum} 1 ${basis}`;
    group.append(left, right);
    return group;
  }
  if (mapGroups.length) {
    map.append(buildTiles(mapGroups));
    root.append(map);
  }
  const selected = mapGroups.find(item => item.mode.id === state.taxonomyMode);
  const summary = el('section'); summary.id = 'taxonomy-summary';
  const tabs = el('div', 'taxonomy-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Taxonomy details');
  const tabOptions = [{id: 'summary', title: 'Failure mode summary'}, {id: 'suggestions', title: 'Agent suggestions'}];
  const activateTab = id => {
    state.taxonomyTab = id;
    renderTaxonomy();
    $(`taxonomy-tab-${id}`).focus({preventScroll: true});
  };
  for (const [index, option] of tabOptions.entries()) {
    const tab = button(option.title, () => activateTab(option.id));
    tab.id = `taxonomy-tab-${option.id}`;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', String(state.taxonomyTab === option.id));
    tab.setAttribute('aria-controls', 'taxonomy-tab-panel');
    tab.tabIndex = state.taxonomyTab === option.id ? 0 : -1;
    tab.addEventListener('keydown', event => {
      const next = {ArrowRight: (index + 1) % 2, ArrowLeft: (index + 1) % 2, Home: 0, End: 1}[event.key];
      if (next !== undefined) {event.preventDefault(); activateTab(tabOptions[next].id);}
    });
    tabs.append(tab);
  }
  const panel = el('div', 'taxonomy-tab-panel'); panel.id = 'taxonomy-tab-panel';
  panel.setAttribute('role', 'tabpanel');
  panel.setAttribute('aria-labelledby', `taxonomy-tab-${state.taxonomyTab}`);
  summary.append(tabs, panel);
  root.append(summary);
  if (state.taxonomyTab === 'suggestions') {
    renderTaxonomySuggestions(panel, runName);
    return;
  }
  const summaryHeading = el('div', 'taxonomy-summary-heading');
  if (selected) {
    summaryHeading.append(el('h3', '', 'Conversations in this group'), button('Show all comments', () => {state.taxonomyMode = null; renderTaxonomy();}));
    panel.append(summaryHeading);
  }
  panel.append(el('p', 'quiet', selected
    ? `${selected.notes.length} comments in this group`
    : `${state.review.annotations.length} comments · ${assignedIds.size} grouped · ${state.review.annotations.length - assignedIds.size} unassigned`));
  const table = el('table', 'taxonomy-summary-table');
  const head = el('thead'), header = el('tr');
  ['Run', 'Failure taxonomy', 'Comment'].forEach(title => {const cell = el('th', '', title); cell.scope = 'col'; header.append(cell);});
  head.append(header); table.append(head);
  const body = el('tbody');
  for (const note of selected ? selected.notes : state.review.annotations) {
      const groups = modes.filter(item => item.notes.some(linked => linked.id === note.id));
      const row = el('tr'); row.dataset.mode = selected?.mode.id || groups.map(item => item.mode.id).join(' '); row.dataset.trace = note.trace_id;
      row.dataset.annotation = note.id;
      row.tabIndex = 0;
      row.setAttribute('aria-label', `Open ${runName(note)}: ${note.note}`);
      row.addEventListener('click', () => jumpTrace(note.trace_id));
      row.addEventListener('keydown', event => {
        if (event.target === row && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          jumpTrace(note.trace_id);
        }
      });
      const run = el('td'), taxonomy = el('td');
      row.title = `Open conversation · ${note.trace_id}`;
      run.append(el('span', 'taxonomy-run', runName(note)));
      if (groups.length) {
        for (const {mode, index} of groups) {
          const label = el('span', 'taxonomy-label', mode.name || mode.id.replaceAll('_', ' '));
          label.dataset.color = index % 6;
          taxonomy.append(label);
        }
      } else taxonomy.append(el('span', 'taxonomy-unassigned', 'Unassigned'));
      row.append(run, taxonomy, el('td', '', note.note)); body.append(row);
  }
  const tableScroll = el('div', 'taxonomy-table-scroll');
  tableScroll.tabIndex = 0;
  tableScroll.setAttribute('role', 'region');
  tableScroll.setAttribute('aria-label', 'Failure taxonomy comments');
  table.append(body); tableScroll.append(table); panel.append(tableScroll);
  if (!body.children.length) panel.append(el('p', 'empty', selected ? 'No linked conversations yet.' : 'No comments recorded yet.'));
}
function renderTaxonomySuggestions(panel, runName) {
  const pending = state.review.suggestions.filter(suggestion => !state.review.decisions[suggestion.id]
    && (!state.taxonomyMode || (suggestion.mode || '__unassigned') === state.taxonomyMode));
  const pendingIds = new Set(pending.map(suggestion => suggestion.id));
  for (const id of state.selectedSuggestions) if (!pendingIds.has(id)) state.selectedSuggestions.delete(id);
  if (state.taxonomyMode) {
    const mode = state.review.modes.find(item => item.id === state.taxonomyMode);
    const heading = el('div', 'taxonomy-summary-heading');
    heading.append(el('h3', '', mode?.name || state.taxonomyMode.replaceAll('_', ' ')), button('Show all suggestions', () => {
      state.taxonomyMode = null;
      state.suggestionFeedback = '';
      renderTaxonomy();
    }));
    panel.append(heading);
  }
  panel.append(el('p', 'quiet', 'Search candidates for your review. Retrieval matches are not failure labels.'));
  const toolbar = el('div', 'suggestion-toolbar');
  toolbar.setAttribute('aria-label', 'Suggestion selection actions');
  const count = el('span', 'suggestion-selected-count');
  count.setAttribute('role', 'status');
  const actions = el('div', 'suggestion-bulk-actions');
  const decide = async decision => {
    if (state.suggestionBatchBusy || state.busy || !state.selectedSuggestions.size) return;
    const ids = [...state.selectedSuggestions];
    state.suggestionBatchBusy = true;
    state.suggestionFeedback = '';
    renderTaxonomy();
    let completed = 0;
    try {
      for (const id of ids) {
        if (!await act({action: 'suggestion', id, decision})) break;
        state.selectedSuggestions.delete(id);
        completed++;
      }
      state.suggestionFeedback = `${decision === 'accept' ? 'Accepted' : 'Rejected'} ${completed} ${completed === 1 ? 'suggestion' : 'suggestions'}.`;
    } finally {
      state.suggestionBatchBusy = false;
      renderTaxonomy();
    }
  };
  const accept = button('Accept selected', () => decide('accept'), 'primary');
  const reject = button('Reject selected', () => decide('reject'));
  actions.append(accept, reject); toolbar.append(count, actions); panel.append(toolbar);
  if (state.suggestionFeedback) {
    const feedback = el('p', 'quiet', state.suggestionFeedback);
    feedback.setAttribute('role', 'status'); panel.append(feedback);
  }
  const table = el('table', 'taxonomy-summary-table taxonomy-suggestions-table');
  const head = el('thead'), header = el('tr');
  const selectHeading = el('th', 'suggestion-select-cell'); selectHeading.scope = 'col';
  const selectAll = el('input'); selectAll.type = 'checkbox';
  selectAll.setAttribute('aria-label', 'Select all suggestions');
  selectHeading.append(selectAll); header.append(selectHeading);
  ['Run', 'Failure taxonomy', 'Trace info'].forEach(title => {
    const cell = el('th', '', title); cell.scope = 'col'; header.append(cell);
  });
  head.append(header); table.append(head);
  const body = el('tbody');
  const selections = [];
  const updateSelection = () => {
    const selectedCount = pending.filter(suggestion => state.selectedSuggestions.has(suggestion.id)).length;
    count.textContent = `${selectedCount} selected`;
    selectAll.checked = pending.length > 0 && selectedCount === pending.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < pending.length;
    selectAll.disabled = !pending.length || state.suggestionBatchBusy || state.busy;
    accept.disabled = reject.disabled = !selectedCount || state.suggestionBatchBusy || state.busy;
    for (const {checkbox, row, id} of selections) {
      checkbox.checked = state.selectedSuggestions.has(id);
      checkbox.disabled = state.suggestionBatchBusy || state.busy;
      row.dataset.selected = String(checkbox.checked);
    }
  };
  selectAll.addEventListener('change', () => {
    for (const suggestion of pending) {
      if (selectAll.checked) state.selectedSuggestions.add(suggestion.id);
      else state.selectedSuggestions.delete(suggestion.id);
    }
    updateSelection();
  });
  for (const suggestion of pending) {
    const row = el('tr');
    const selectCell = el('td', 'suggestion-select-cell');
    const checkbox = el('input'); checkbox.type = 'checkbox';
    checkbox.setAttribute('aria-label', `Select suggestion for ${runName(suggestion)}`);
    selectCell.addEventListener('click', event => event.stopPropagation());
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.selectedSuggestions.add(suggestion.id);
      else state.selectedSuggestions.delete(suggestion.id);
      updateSelection();
    });
    selectCell.append(checkbox);
    selections.push({checkbox, row, id: suggestion.id});
    const run = el('td'), taxonomy = el('td'), info = el('td');
    run.append(el('span', 'taxonomy-run', runName(suggestion)));
    const mode = state.review.modes.find(item => item.id === suggestion.mode);
    taxonomy.append(el('span', 'taxonomy-label', mode?.name || (suggestion.mode || 'Unassigned').replaceAll('_', ' ')));
    info.append(el('em', 'taxonomy-suggestion-quote', `"${suggestion.anchor?.quote || suggestion.quote || 'No highlighted text'}"`));
    const comment = el('div', 'taxonomy-suggestion-comment');
    comment.append(el('span', 'taxonomy-comment-label', 'Comment:'), document.createTextNode(` ${suggestion.note || suggestion.reason || 'No comment'}`));
    info.append(comment);
    row.append(selectCell, run, taxonomy, info);
    row.tabIndex = 0;
    row.setAttribute('aria-label', `Open suggestion for ${runName(suggestion)}`);
    row.addEventListener('click', () => jumpTrace(suggestion.trace_id));
    row.addEventListener('keydown', event => {
      if (event.target === row && (event.key === 'Enter' || event.key === ' ')) {event.preventDefault(); jumpTrace(suggestion.trace_id);}
    });
    body.append(row);
  }
  updateSelection();
  const tableScroll = el('div', 'taxonomy-table-scroll');
  tableScroll.tabIndex = 0;
  tableScroll.setAttribute('role', 'region');
  tableScroll.setAttribute('aria-label', 'Agent suggestions');
  table.append(body); tableScroll.append(table); panel.append(tableScroll);
  if (!pending.length) panel.append(el('p', 'empty', state.taxonomyMode ? 'No pending suggestions in this group.' : 'No pending agent suggestions.'));
}
function editMode(mode = {}) {
  const slot = $('mode-editor'); slot.replaceChildren();
  const form = el('form', 'mode-form'); form.append(el('h3', '', mode.id ? 'Edit mode' : 'Define a mode'));
  const id = field(form, 'Mode ID (lowercase_with_underscores)', 'id', mode.id); id.required = true; id.pattern = '[a-z][a-z0-9_]{0,79}'; id.readOnly = !!mode.id;
  field(form, 'Binary definition', 'definition', mode.definition, true).required = true;
  field(form, 'Requirement ID or missing requirement', 'requirement', mode.requirement);
  field(form, 'Boundaries and close negatives', 'boundaries', mode.boundaries, true);
  field(form, 'Examples', 'examples', mode.examples, true);
  const support = el('div', 'support-picker'); support.append(el('p', 'quiet', 'Supporting human observations'));
  for (const note of state.review.annotations) {
    const label = el('label', 'check', note.note), checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.name = 'annotation_ids'; checkbox.value = note.id; checkbox.checked = (mode.annotation_ids || []).includes(note.id); label.prepend(checkbox); support.append(label);
  }
  form.append(support);
  const confirm = el('label', 'check', 'I confirm this definition as a final mode for structured labeling'), check = el('input');
  check.type = 'checkbox'; check.name = 'final'; check.checked = !!mode.final; confirm.prepend(check); form.append(confirm);
  const save = el('button', 'primary', 'Save mode'); save.type = 'submit'; form.append(save);
  form.onsubmit = async e => {e.preventDefault(); const data = new FormData(form);
    await act({action:'mode', ...Object.fromEntries(data), final:data.has('final'), annotation_ids:data.getAll('annotation_ids')});};
  slot.append(form);
}
function renderProgress() {
  const root = $('progress-view'); root.replaceChildren();
  const traces = allTraces(), modes = finalModes(), labels = traces.flatMap(t => modes.map(m => state.review.labels[t.id + ':' + m.id])).filter(Boolean);
  const reviewedCount = traces.filter(t => reviewed(t.id)).length;
  const metrics = el('div', 'metrics');
  for (const [count,title] of [[`${reviewedCount}/${traces.length}`,'Traces reviewed'], [state.review.annotations.length,'Human observations'], [traces.length * modes.length-labels.length,'Final judgments remaining'], [labels.filter(l => l.sync === 'pending').length,'Labels pending sync']]) {
    const metric = el('div', 'metric'); metric.append(el('strong', '', count), el('span', '', title)); metrics.append(metric);
  }
  root.append(el('h2', '', 'Review progress'), metrics);
  if (state.session) {
    const completion = el('div', 'panel');
    completion.append(el('h3', '', 'Current conversation review'));
    for (const turn of state.session.turns) {
      const item = el('div', 'review-record');
      item.append(el('p', 'quiet wide-id', turn.id));
      const prompt = turn.blocks.find(b => b.role === 'user')?.text;
      if (prompt) item.append(el('p', '', prompt));
      const status = state.review.reviews[turn.id]?.status || 'unreviewed';
      const actions = el('div', 'review-actions');
      actions.append(el('span', 'badge', {unreviewed:'Unreviewed', reviewed:'Reviewed · outcome not recorded', no_failure:'Reviewed · no failure observed', first_failure:'Reviewed · first failure noted'}[status]),
        button('First failure noted', () => act({action:'review', trace_id:turn.id, status:'first_failure'})),
        button('No failure observed', () => act({action:'review', trace_id:turn.id, status:'no_failure'})),
        button('Reopen', () => act({action:'review', trace_id:turn.id, status:'unreviewed'})));
      item.append(actions);
      const evidence = el('div');
      evidence.append(el('p', 'quiet', `Recorded: ${turn.timestamp || 'not captured'} · Latency: ${turn.raw.latency ?? 'not captured'} seconds · Cost: ${turn.raw.totalCost ?? 'not captured'} · Prompt: ${turn.meta['cartwheel.prompt_version'] || 'not captured'}`));
      if (state.catalog.langfuse_host && /^\/project\//.test(turn.raw.htmlPath || '')) {
        const link = el('a', '', 'Open in Langfuse');
        link.href = state.catalog.langfuse_host + turn.raw.htmlPath; link.target = '_blank'; link.rel = 'noopener noreferrer'; evidence.append(link);
      }
      evidence.append(el('pre', '', pretty(turn.raw)));
      item.append(details('Trace details & raw execution', evidence));
      completion.append(item);
    }
    root.append(completion);
  }
  if (!modes.length) root.append(el('p', 'warning', 'No final modes: structured labeling has not started. Zero remaining labels does not mean this stage is complete.'));
  const panel = el('div', 'panel'); panel.append(el('h3', '', 'Incomplete judgments'));
  for (const t of traces) {
    const missing = modes.filter(m => !state.review.labels[t.id + ':' + m.id]);
    if (!reviewed(t.id) || missing.length) panel.append(button(`${t.scenario || t.id} · ${t.id.slice(0,8)} · ${reviewed(t.id) ? 'open coded' : 'needs open coding'}${missing.length ? ' · missing: ' + missing.map(m=>m.id).join(', ') : ''}`, () => jumpTrace(t.id), 'conversation'));
  }
  root.append(panel);
  const suggestions = el('div', 'panel'); suggestions.append(el('h3', '', 'AI suggestions awaiting your decision'));
  const pending = state.review.suggestions.filter(s => !state.review.decisions[s.id]);
  if (!pending.length) suggestions.append(el('p', 'quiet', 'No pending suggestions.'));
  for (const suggestion of pending) {
    const card = noteCard(suggestion, 'suggestion'); card.append(button('Open trace', () => jumpTrace(suggestion.trace_id))); suggestions.append(card);
  }
  root.append(suggestions);
  const decided = Object.entries(state.review.decisions);
  if (decided.length) root.append(details('Suggestion decision history', el('pre', '', pretty(state.review.decisions))));
}
function render() {
  document.querySelector('main').classList.toggle('taxonomy-layout', state.view === 'taxonomy');
  $('sampling-controls').hidden = state.view !== 'read';
  if (!state.review || !state.catalog) return;
  renderQueue(); saveStatus();
  const header = $('session-header'); header.replaceChildren();
  if (state.session && state.view !== 'taxonomy') {
    const first = state.session.turns[0];
    const heading = el('div', 'session-heading');
    const title = el('div', 'session-title');
    title.append(el('h2', '', first.meta['cartwheel.scenario_id'] || 'Conversation'), roleBadge(first.meta['cartwheel.user_role']));
    heading.append(title);
    if (state.view === 'read') {
      const controls = el('div', 'conversation-review-controls');
      const traceIds = state.session.turns.map(turn => turn.id);
      const hasComment = traceIds.some(id => notesFor(id).length > 0);
      const complete = conversationReviewed(traceIds);
      const reviewButton = button(complete ? 'Reviewed' : 'For review', async () => {
        reviewButton.disabled = true;
        const saved = await act({action: 'toggle_review', trace_ids: traceIds});
        if (!saved) reviewButton.disabled = false;
      }, 'conversation-review-button');
      reviewButton.disabled = hasComment;
      reviewButton.setAttribute('aria-keyshortcuts', 'Space');
      reviewButton.dataset.reviewed = String(complete);
      reviewButton.title = hasComment ? 'Conversations with comments stay reviewed' : 'Toggle review status (Space)';
      controls.append(roleLegend(), reviewButton);
      heading.append(controls);
    }
    const metadata = el('div', 'meta');
    metadata.append(el('span', '', `Session: ${state.session.id}`), el('span', '', `Model: ${[...new Set(state.session.turns.flatMap(t=>t.models))].join(', ') || 'not captured'}`));
    heading.append(metadata);
    const session = state.catalog.sessions.find(session => session.id === state.session.id);
    const dimensionContent = el('div', 'conversation-dimensions');
    const dimensionList = el('dl');
    const names = [...$('sampling-dimensions').querySelectorAll('input[data-dimension]')].map(input => input.dataset.dimension);
    const traces = session?.traces || [];
    for (const name of names) {
      const values = dimensionValues(traces, name);
      const item = el('div', 'conversation-dimension');
      item.append(el('dt', '', name), el('dd', '', values.length ? values.map(value => value.replaceAll('_', ' ')).join(', ') : 'Not available'));
      dimensionList.append(item);
    }
    dimensionContent.append(dimensionList);
    const key = state.session.id + ':dimensions';
    const dimensionDisclosure = details('Dimensions', dimensionContent, false, key);
    dimensionDisclosure.addEventListener('toggle', () => state.disclosures.set(key, dimensionDisclosure.open));
    heading.append(dimensionDisclosure);
    header.append(heading);
  }
  if (state.view === 'read') renderRead();
  if (state.view === 'labels') renderLabels();
  if (state.view === 'taxonomy') renderTaxonomy();
  if (state.view === 'progress') renderProgress();
}
document.addEventListener('keydown', event => {
  if (state.view !== 'read' || !state.session || state.editor || state.busy || state.loading || !isReviewShortcut(event)) return;
  const control = document.querySelector('.conversation-review-button');
  if (!control) return;
  event.preventDefault();
  control.click();
});
function stashDraft() {
  if (!state.editor) return;
  state.editor.note = $('note-text').value;
  try {localStorage.setItem(backupKey(), JSON.stringify(state.editor));} catch {notice('Browser draft storage is unavailable. Keep this window open until the note is saved.');}
}
function refreshHighlights() {
  for (const node of $('read-view').querySelectorAll('.annotatable')) {
    node.replaceWith(anchored(node.textContent, node.dataset.trace, node.dataset.block, node.dataset.field, node.tagName === 'PRE'));
  }
  requestAnimationFrame(layoutNotes);
}
function positionNote() {
  if (!state.editor) return;
  const popover = $('note-popover');
  const mark = [...$('read-view').querySelectorAll('mark')].find(m => m.dataset.note === 'pending');
  const target = mark || state.noteTarget || $('session-header');
  const rects = target.getClientRects();
  const rect = rects[rects.length - 1] || target.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, innerWidth - popover.offsetWidth - 8));
  const reader = $('view-scroll').getBoundingClientRect();
  // Prefer below the evidence; flip above only when the viewport has no room.
  const top = rect.bottom + 8 + popover.offsetHeight <= reader.bottom ? rect.bottom + 8 : Math.max(reader.top + 8, rect.top - popover.offsetHeight - 8);
  popover.style.left = left + scrollX + 'px';
  popover.style.top = top + scrollY + 'px';
}
function editNote(note, target = null) {
  state.editor = {...note, id: note.id || crypto.randomUUID(), anchor:note.anchor || {}};
  state.noteTarget = target;
  $('note-text').value = note.note || '';
  $('note-title').textContent = note.note ? 'Edit note' : 'Add a note';
  $('note-quote').textContent = note.anchor?.quote ? '“' + note.anchor.quote + '”' : 'Note on this turn';
  stashDraft(); refreshHighlights();
  const mark = [...$('read-view').querySelectorAll('mark')].find(m => m.dataset.note === 'pending');
  for (let parent = mark?.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
  $('note-popover').hidden = false;
  positionNote(); $('note-text').focus({preventScroll:true});
}
function closeNote() {stashDraft(); state.editor = null; $('note-popover').hidden = true; refreshHighlights();}
$('note-text').addEventListener('input', stashDraft);
$('note-text').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {e.preventDefault(); $('note-form').requestSubmit();}
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && state.editor) {e.preventDefault(); closeNote(); state.noteTarget?.focus();}
});
document.addEventListener('pointerdown', e => {
  if (state.editor && !state.busy && !$('note-popover').contains(e.target)) closeNote();
});
$('note-form').onsubmit = async e => {
  e.preventDefault(); stashDraft();
  const saved = await act({action:'note', ...state.editor, note:$('note-text').value});
  if (saved) {try {localStorage.removeItem(backupKey());} catch {} state.editor = null; $('note-popover').hidden = true; renderRead();}
};
function selectEvidence() {
  if (state.view !== 'read' || state.editor || state.busy) return;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return;
  const range = selection.getRangeAt(0), container = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
  const block = container.closest('.annotatable');
  if (!block || !block.contains(range.startContainer) || !block.contains(range.endContainer)) return;
  const before = document.createRange(); before.selectNodeContents(block); before.setEnd(range.startContainer, range.startOffset);
  const quote = range.toString(); if (!quote.trim()) return;
  const start = before.toString().length;
  editNote({trace_id:block.dataset.trace, anchor:{block_id:block.dataset.block, field:block.dataset.field, quote, start, end:start + quote.length}});
}
$('read-view').addEventListener('mouseup', selectEvidence);
$('read-view').addEventListener('keyup', e => {if (e.shiftKey) selectEvidence();});
document.addEventListener('mouseover', e => {
  const mark = e.target.closest('mark');
  for (const card of document.querySelectorAll('.note-card')) card.classList.toggle('linked', !!mark && card.dataset.noteCard === mark.dataset.note);
});
document.addEventListener('toggle', e => {
  if (e.target.dataset.disclosure) state.disclosures.set(e.target.dataset.disclosure, e.target.open);
  requestAnimationFrame(layoutNotes);
}, true);
window.addEventListener('resize', () => {for (const card of document.querySelectorAll('.note-card')) card.style.marginTop = ''; requestAnimationFrame(layoutNotes); positionNote();});
$('view-scroll').addEventListener('scroll', () => {
  // Keep the compact editor beside its source as the conversation scrolls.
  if (!state.editor) return;
  const mark = $('read-view').querySelector('mark.pending');
  if (mark) {
    const source = mark.getBoundingClientRect(), reader = $('view-scroll').getBoundingClientRect();
    if (source.bottom < reader.top || source.top > reader.bottom) return closeNote();
  }
  positionNote();
}, {passive:true});
for (const nav of document.querySelectorAll('[data-view]')) nav.onclick = () => switchView(nav.dataset.view);
let queueScrollTimeout;
$('queue-list').addEventListener('scroll', () => {
  $('queue-list').classList.add('is-scrolling');
  clearTimeout(queueScrollTimeout);
  queueScrollTimeout = setTimeout(() => $('queue-list').classList.remove('is-scrolling'), 900);
}, {passive:true});

async function poll() {
  if (state.busy || state.loading || document.hidden || state.editor) return;
  try {
    const remote = await get('/api/state');
    if (JSON.stringify(remote) !== JSON.stringify(state.review)) {
      const editingMode = state.view === 'taxonomy' && $('mode-editor')?.contains(document.activeElement);
      if (editingMode) return;
      state.review = remote; render();
    }
  } catch { $('save-status').textContent = 'Server unavailable · browser draft retained'; }
}
async function boot() {
  try {
    [state.catalog, state.review] = await Promise.all([get('/api/catalog'), get('/api/state')]);
    initDimensionOptions();
    const initial = new URLSearchParams(location.hash.slice(1)).get('session');
    if (state.catalog.sessions.length) await openSession(state.catalog.sessions.some(s=>s.id === initial) ? initial : state.catalog.sessions[0].id);
    else {render(); notice('No scenario traces found in this source.');}
    try {
      const draft = JSON.parse(localStorage.getItem(backupKey()) || 'null');
      if (draft) {
        notice('An unsaved evidence note is available in this browser.');
        $('notice').append(button('Resume draft', () => editNote(draft)), button('Discard draft', () => {localStorage.removeItem(backupKey()); $('notice').hidden = true;}));
      }
    } catch { /* Draft recovery is optional; server state remains authoritative. */ }
    setInterval(poll, 5000);
  } catch (error) {notice(error.message); $('save-status').textContent = 'Connection failed';}
}
boot();
