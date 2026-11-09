/* No trace content is interpreted as HTML. Anchors refer to source fields. */
const $ = (id) => document.getElementById(id);
const state = {catalog: null, review: null, session: null, view: 'read', busy: false, loading: false, request: 0, editor: null, disclosures: new Map(), noteTarget: null};
const allTraces = () => state.catalog.sessions.flatMap(s => s.traces);
const finalModes = () => state.review.modes.filter(m => m.final);
const reviewed = id => ['first_failure', 'no_failure'].includes(state.review.reviews[id]?.status);
const notesFor = id => state.review.annotations.filter(n => n.trace_id === id);
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
    if (!response.ok) throw new Error(data.error || 'Save failed');
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
  for (const [name, color] of [['User', 'user'], ['Assistant', 'assistant'], ['Tool', 'tool']]) {
    const span = el('span', '', name);
    span.style.setProperty('--role-color', `var(--${color})`);
    row.append(span);
  }
  return row;
}
function renderQueue() {
  const query = $('search').value.trim().toLowerCase();
  const role = $('role-filter').value, tool = $('tool-filter').value, status = $('status-filter').value;
  const groups = state.catalog.sessions.filter(s => {
    const done = s.traces.every(t => reviewed(t.id));
    const incompleteLabels = s.traces.some(t => finalModes().some(m => !state.review.labels[t.id + ':' + m.id]));
    return (!role || s.traces.some(t => t.role === role)) && (!tool || s.traces.some(t => t.tools.includes(tool))) &&
      (!query || JSON.stringify(s).toLowerCase().includes(query)) &&
      (!status || (status === 'reviewed' ? done : status === 'labels' ? incompleteLabels : !done));
  });
  $('queue-count').textContent = `${groups.length} / ${state.catalog.sessions.length}`;
  const list = $('queue-list');
  list.replaceChildren();
  for (const session of groups) {
    const first = session.traces[0], done = session.traces.filter(t => reviewed(t.id)).length;
    const item = button('', () => openSession(session.id), 'conversation' + (state.session?.id === session.id ? ' active' : ''));
    item.setAttribute('aria-current', state.session?.id === session.id ? 'true' : 'false');
    item.append(el('strong', '', `${first.scenario || 'Unassigned scenario'} · ${first.role || 'Unknown role'}`),
      el('span', 'preview', first.preview || 'Input not captured'),
      el('span', 'quiet', `${session.traces.length} trace(s) · ${done} reviewed`));
    list.append(item);
  }
  if (!groups.length) list.append(el('p', 'empty', 'No conversations match these filters.'));
}
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
  state.view = view;
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
  const node = el('details', 'block tool-disclosure'); node.dataset.role = 'tool'; node.dataset.blockId = block.id;
  const key = tid + ':' + block.id;
  node.dataset.disclosure = key;
  node.open = state.disclosures.get(key) ?? false;
  const result = block.result;
  const heading = el('summary', 'tool-heading');
  heading.append(el('span', 'tool-name', block.name + '()'));
  const status = result?.error || result?.status || (result?.ok === true ? 'ok' : result?.ok === false ? 'failed' : 'result not captured');
  heading.append(el('span', 'tool-summary-status', String(status)));
  node.append(heading);
  const body = el('div', 'tool-body');
  const args = anchored(pretty(block.arguments), tid, block.id, 'input', true);
  body.append(details('Arguments', args, false, key + ':arguments'));
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    const important = ['ok', 'error', 'reason', 'status', 'order_id', 'refund_id', 'amount_usd', 'note', 'count'];
    const summary = important.filter(k => k in result).map(k => k + ': ' + pretty(result[k])).join('\n');
    if (summary) body.append(anchored(summary, tid, block.id, 'result_summary', true));
    if (Array.isArray(result.results)) for (let i = 0; i < result.results.length; i++) {
      const hit = result.results[i], hitNode = el('div', 'retrieval');
      hitNode.append(el('strong', '', `${i+1}. ${hit.policy_id} · ${hit.title}`), el('p', 'quiet', `Retrieval score: ${hit.score}`));
      hitNode.append(anchored(hit.snippet || 'Snippet not captured', tid, block.id, `output.results.${i}.snippet`));
      body.append(hitNode);
    }
  }
  body.append(details('Complete result · preserves empty and null fields', anchored(pretty(result), tid, block.id, 'output', true), false, key + ':result'));
  body.append(el('div', 'quiet', `Observation ${block.observation_id} · match: ${block.match}${block.call_id ? ' · ' + block.call_id : ''}`));
  if (['ambiguous', 'unmatched'].includes(block.match)) body.append(el('p', 'warning', 'No unique generation call match. The tool observation is shown as captured; check raw execution details.'));
  node.append(body);
  return node;
}
function noteCard(note, kind = 'human') {
  const node = el('div', 'note-card ' + (kind === 'suggestion' ? 'suggestion' : kind === 'legacy' ? 'legacy' : ''));
  node.dataset.noteCard = note.id;
  node.append(el('strong', '', kind === 'suggestion' ? 'AI suggestion · unaccepted' : kind === 'legacy' ? 'Existing annotation · read only' : note.source === 'human_accepted_ai' ? 'Human accepted · AI origin' : 'Human observation'));
  const quote = note.anchor?.quote || note.quote;
  if (quote) node.append(el('blockquote', '', quote));
  node.append(el('p', '', note.note || note.reason || 'No note text'));
  if (!note.anchor?.block_id) node.append(el('p', 'quiet', 'Trace-level evidence · no precise source anchor'));
  const actions = el('div', 'actions');
  if (kind === 'suggestion') {
    actions.append(button('Accept', () => act({action:'suggestion', id: note.id, decision:'accept'})), button('Reject', () => act({action:'suggestion', id: note.id, decision:'reject'})));
  } else if (kind !== 'legacy') actions.append(button('Edit note', e => editNote(note, e.currentTarget)));
  node.append(actions);
  node.onmouseenter = () => {for (const m of document.querySelectorAll('mark')) if (m.dataset.note === note.id) m.classList.add('pending');};
  node.onmouseleave = () => {for (const m of document.querySelectorAll('mark')) if (m.dataset.note === note.id) m.classList.remove('pending');};
  return node;
}
function renderRead() {
  for (const disclosure of $('read-view').querySelectorAll('[data-disclosure]')) state.disclosures.set(disclosure.dataset.disclosure, disclosure.open);
  const root = $('read-view'); root.replaceChildren();
  if (!state.session) return root.append(el('p', 'empty', 'No session selected.'));
  root.append(roleLegend(), el('p', 'quiet', 'Read chronologically. Select evidence to add a note; stop initial reading at the first failure. Tool results remain available in full.'));
  state.session.turns.forEach((turn, index) => {
    const article = el('article', 'trace'); article.id = 'trace-' + turn.id;
    const heading = el('div', 'turn-heading');
    heading.append(el('h3', '', `Turn ${index+1}`), el('span', 'wide-id', `${turn.id} · ${turn.timestamp || 'time not captured'}`));
    if (state.catalog.langfuse_host && /^\/project\//.test(turn.raw.htmlPath || '')) {
      const link = el('a', '', 'Open in Langfuse');
      link.href = state.catalog.langfuse_host + turn.raw.htmlPath; link.target = '_blank'; link.rel = 'noopener noreferrer'; heading.append(link);
    }
    article.append(heading);
    const grid = el('div', 'turn-grid'), body = el('div', 'evidence'), notes = el('aside', 'notes');
    notes.setAttribute('aria-label', `Evidence notes for turn ${index+1}`);
    for (const warning of turn.warnings) body.append(el('p', 'warning', warning));
    const systems = [...new Set((turn.raw.observations || []).filter(o => o.type === 'GENERATION').flatMap(o => (o.input?.messages || []).filter(m => m.role === 'system').flatMap(m => (m.parts || []).filter(p => p.type === 'text').map(p => p.content))))];
    if (systems.length) {
      const wrapper = el('div');
      systems.forEach((s,i) => wrapper.append(anchored(s, turn.id, 'system-' + i, 'system', true)));
      const instructions = details(`System instructions · ${systems.length} distinct captured version(s) · includes authenticated identity`, wrapper);
      instructions.className = 'system'; body.append(instructions);
    }
    for (const block of turn.blocks) {
      if (block.role === 'tool') {body.append(renderTool(block, turn.id)); continue;}
      const item = el('div', 'block'); item.dataset.role = block.role; item.dataset.blockId = block.id;
      item.append(el('div', 'role-label', block.role), anchored(block.text, turn.id, block.id, block.field));
      body.append(item);
    }
    const raw = details('Raw trace & execution hierarchy', el('pre', '', pretty(turn.raw)));
    body.append(raw);
    body.append(el('p', 'quiet', `Latency: ${turn.raw.latency ?? 'not captured'} seconds · Cost: ${turn.raw.totalCost ?? 'not captured'} · Prompt: ${turn.meta['cartwheel.prompt_version'] || 'not captured'}`));
    notesFor(turn.id).forEach(n => notes.append(noteCard(n)));
    state.catalog.legacy_annotations.filter(n => n.trace_id === turn.id).forEach(n => notes.append(noteCard(n, 'legacy')));
    pendingFor(turn.id).forEach(n => notes.append(noteCard(n, 'suggestion')));
    if (!notes.children.length) notes.append(el('p', 'quiet', 'Select text in this turn to attach an observation here.'));
    grid.append(body, notes); article.append(grid);
    const actions = el('div', 'review-actions');
    const status = state.review.reviews[turn.id]?.status || 'unreviewed';
    actions.append(el('span', 'badge', {unreviewed:'Unreviewed', no_failure:'Reviewed · no failure observed', first_failure:'Reviewed · first failure noted'}[status]),
      button('Add turn note', e => editNote({trace_id:turn.id, anchor:{}}, e.currentTarget)),
      button('First failure noted', () => act({action:'review', trace_id:turn.id, status:'first_failure'})),
      button('No failure observed', () => act({action:'review', trace_id:turn.id, status:'no_failure'})),
      button('Reopen', () => act({action:'review', trace_id:turn.id, status:'unreviewed'})));
    article.append(actions); root.append(article);
  });
  requestAnimationFrame(layoutNotes);
}
function layoutNotes() {
  for (const article of document.querySelectorAll('.trace')) {
    const column = article.querySelector('.notes');
    if (!column || getComputedStyle(column).display === 'flex') continue;
    let lastBottom = 0;
    for (const card of column.querySelectorAll('.note-card')) {
      const mark = [...article.querySelectorAll('mark')].find(m => m.dataset.note === card.dataset.noteCard);
      const target = mark ? mark.getBoundingClientRect().top - column.getBoundingClientRect().top : lastBottom;
      const currentTop = card.offsetTop;
      card.style.marginTop = Math.max(0, target - currentTop) + 'px';
      lastBottom = card.offsetTop + card.offsetHeight + 12;
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
  root.append(el('h2', '', 'Failure taxonomy'), el('p', 'quiet', 'Group human observations after open coding. You decide the definitions, boundaries and final modes. Existing taxonomy suggestions remain provisional until you confirm them.'));
  for (const mode of state.review.modes) {
    const panel = el('div', 'panel');
    panel.append(el('h3', '', mode.id + (mode.final ? ' · Final' : ' · Draft')), el('p', 'mode-definition', mode.definition || 'Definition pending'),
      el('p', 'quiet', 'Requirement: ' + (mode.requirement || 'Not recorded')), el('p', 'mode-definition', 'Boundaries: ' + (mode.boundaries || 'Not recorded')),
      el('p', 'mode-definition', 'Examples: ' + (mode.examples || 'Not recorded')), button('Edit definition & supporting notes', () => editMode(mode)));
    const supporting = state.review.annotations.filter(n => (mode.annotation_ids || []).includes(n.id));
    const notes = el('div', 'mode-notes');
    notes.append(el('p', 'quiet', `${supporting.length} supporting human observation(s)`));
    supporting.forEach(n => notes.append(button(n.note, () => jumpTrace(n.trace_id), 'jump')));
    panel.append(notes); root.append(panel);
  }
  const slot = el('div', 'panel'); slot.id = 'mode-editor'; root.append(slot); editMode();
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
  for (const [count,title] of [[`${reviewedCount}/${traces.length}`,'Traces open coded'], [state.review.annotations.length,'Human observations'], [traces.length * modes.length-labels.length,'Final judgments remaining'], [labels.filter(l => l.sync === 'pending').length,'Labels pending sync']]) {
    const metric = el('div', 'metric'); metric.append(el('strong', '', count), el('span', '', title)); metrics.append(metric);
  }
  root.append(el('h2', '', 'Review progress'), metrics);
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
  if (!state.review || !state.catalog) return;
  renderQueue(); saveStatus();
  const header = $('session-header'); header.replaceChildren();
  if (state.session) {
    const first = state.session.turns[0];
    const heading = el('div', 'session-heading');
    heading.append(el('h2', '', `${first.meta['cartwheel.scenario_id'] || 'Conversation'} · ${state.session.turns.length} turn(s)`));
    const metadata = el('div', 'meta');
    metadata.append(el('span', '', `Role: ${first.meta['cartwheel.user_role'] || 'not captured'}`),
      el('span', '', `Session: ${state.session.id}`), el('span', '', `Model: ${[...new Set(state.session.turns.flatMap(t=>t.models))].join(', ') || 'not captured'}`));
    heading.append(metadata); header.append(heading);
  }
  if (state.view === 'read') renderRead();
  if (state.view === 'labels') renderLabels();
  if (state.view === 'taxonomy') renderTaxonomy();
  if (state.view === 'progress') renderProgress();
}
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
  // Prefer below the evidence; flip above only when the viewport has no room.
  const top = rect.bottom + 8 + popover.offsetHeight <= innerHeight ? rect.bottom + 8 : Math.max(8, rect.top - popover.offsetHeight - 8);
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
for (const nav of document.querySelectorAll('[data-view]')) nav.onclick = () => switchView(nav.dataset.view);
for (const id of ['search', 'role-filter', 'tool-filter', 'status-filter']) $(id).addEventListener('input', renderQueue);

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
    $('source').textContent = state.catalog.source;
    for (const [id, values] of [['role-filter', allTraces().map(t=>t.role)], ['tool-filter', allTraces().flatMap(t=>t.tools)]]) {
      for (const value of [...new Set(values.filter(Boolean))].sort()) {const option = el('option', '', value); option.value = value; $(id).append(option);}
    }
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
