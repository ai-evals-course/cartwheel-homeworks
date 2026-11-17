/* Saved evaluator artifacts are read-only. Content is always rendered as text. */
const EvaluatorPanel = (() => {
  let snapshot = null, loading = false, error = '';
  const selectedJudges = new Map();
  const percent = value => Number.isFinite(value) ? (value * 100).toFixed(1) + '%' : 'Not available';
  function table(caption, headings, rows) {
    const wrap = el('div', 'table-wrap'), grid = el('table', 'evaluator-table');
    grid.append(el('caption', 'sr-only', caption));
    const head = el('thead'), tr = el('tr');
    for (const title of headings) {const th = el('th', '', title); th.scope = 'col'; tr.append(th);}
    head.append(tr); grid.append(head);
    const body = el('tbody');
    for (const row of rows) {
      const line = el('tr');
      row.forEach((value, i) => {const cell = el(i ? 'td' : 'th', '', value); if (!i) cell.scope = 'row'; line.append(cell);});
      body.append(line);
    }
    grid.append(body); wrap.append(grid); return wrap;
  }
  function selector(labelText, id, values, selected, change) {
    const label = el('label', '', labelText), select = el('select');
    select.id = id;
    for (const [value, title] of values) {const option = el('option', '', title); option.value = value; select.append(option);}
    select.value = selected;
    select.onchange = () => {change(select.value); render(); $(id)?.focus();};
    label.append(select); return label;
  }
  async function refresh() {
    if (loading) return;
    loading = true; error = ''; render();
    try {snapshot = await get('/api/evaluator');}
    catch (failure) {error = failure.message;}
    finally {loading = false; render();}
  }
  async function showTraces(judge) {
    const opener = document.activeElement;
    const dialog = el('dialog', 'evaluator-trace-dialog');
    dialog.setAttribute('aria-labelledby', 'evaluator-trace-title');
    const header = el('header', 'evaluator-dialog-header');
    const title = el('h2', '', 'Validation traces'); title.id = 'evaluator-trace-title';
    const close = button('Close', () => dialog.close()); close.autofocus = true;
    header.append(title, close);
    const toolbar = el('div', 'evaluator-trace-toolbar');
    const filterLabel = el('label', '', 'Show');
    const filter = el('select'); filter.disabled = true;
    filterLabel.append(filter); toolbar.append(filterLabel);
    const identity = el('div', 'evaluator-run-heading');
    const body = el('div', 'evaluator-trace-body');
    const count = el('span', 'quiet', 'Loading validation traces…');
    count.setAttribute('role', 'status');
    const footer = el('footer', 'evaluator-dialog-footer');
    const previous = button('Previous', () => move(-1));
    const next = button('Next', () => move(1));
    previous.disabled = next.disabled = true;
    footer.append(previous, count, next);
    dialog.append(header, toolbar, identity, body, footer);
    dialog.addEventListener('close', () => {dialog.remove(); if (opener?.isConnected) opener.focus();});
    document.body.append(dialog); dialog.showModal();
    let traces = [], index = 0;
    const visible = () => traces.filter(trace => filter.value === 'all' || trace.disagreement);
    function move(delta) {
      const cases = visible();
      index = Math.max(0, Math.min(cases.length - 1, index + delta));
      draw();
    }
    function draw() {
      const cases = visible(), trace = cases[index];
      identity.replaceChildren(); body.replaceChildren(); body.scrollTop = 0;
      previous.disabled = !trace || index === 0;
      next.disabled = !trace || index === cases.length - 1;
      count.textContent = trace ? `${index + 1} of ${cases.length}` : '0 traces';
      if (!trace) return body.append(el('p', 'empty', 'No validation traces match this filter.'));
      identity.append(el('code', 'evaluator-run-id', trace.trace_id));
      for (const [name, verdict] of [['Judge', trace.judge_verdict], ['Human', trace.human_verdict]]) {
        const badge = el('span', 'evaluator-verdict', `${name}: ${verdict || 'Pending'}`);
        badge.dataset.verdict = (verdict || 'pending').toLowerCase(); identity.append(badge);
      }
      const critique = el('section', 'evaluator-critique');
      critique.append(el('h3', '', 'Judge critique'), el('p', '', trace.critique || 'No saved critique.'));
      body.append(critique);
      if (!trace.trace.length) body.append(el('p', 'empty', 'The saved input for this trace is unavailable.'));
      const lastAssistant = trace.trace.findLastIndex(message => message.role === 'assistant');
      trace.trace.forEach((message, i) => {
        if (['tool_call', 'tool_result'].includes(message.role)) {
          const label = message.role === 'tool_call' ? `Tool call: ${message.name || 'unnamed'}` : 'Tool result';
          body.append(details(label, el('pre', '', pretty(message.role === 'tool_call' ? message.arguments : message.content))));
          return;
        }
        const block = el('section', 'evaluator-trace-message');
        const final = message.role === 'assistant' && i === lastAssistant;
        const role = final ? 'Agent · final reply being judged' : message.role === 'assistant' ? 'Agent · context' : message.role === 'user' ? 'User' : message.role;
        block.dataset.final = String(final);
        block.append(el('h3', '', role), el('div', 'prose', message.text ?? message.content ?? ''));
        body.append(block);
      });
    }
    filter.onchange = () => {index = 0; draw();};
    dialog.addEventListener('keydown', event => {
      if (event.target.closest('input, select, textarea') || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1);
      }
    });
    try {
      const data = await get('/api/evaluator/traces?judge_id=' + encodeURIComponent(judge.judge_id));
      if (!dialog.open) return;
      traces = data.traces;
      for (const [value, text] of [['disagreements', `Disagreements (${traces.filter(t => t.disagreement).length})`], ['all', `All validation traces (${traces.length})`]]) {
        const option = el('option', '', text); option.value = value; filter.append(option);
      }
      filter.disabled = false; draw();
    } catch (failure) {
      if (!dialog.open) return;
      count.textContent = 'Could not load traces';
      const message = el('p', 'warning', failure.message); message.setAttribute('role', 'alert'); body.append(message);
    }
  }
  function render() {
    const root = $('evaluator-view'); root.replaceChildren();
    root.setAttribute('aria-busy', String(loading));
    const heading = el('div', 'evaluator-heading');
    heading.append(el('h2', '', 'Evaluator'));
    root.append(heading);
    if (error) {const message = el('p', 'warning', 'Could not load evaluator data: ' + error); message.setAttribute('role', 'alert'); root.append(message);}
    if (!snapshot) return root.append(el('p', 'empty', loading ? 'Loading evaluator data…' : 'Open Evaluator to load saved evaluations.'));
    if (!snapshot.modes.length) return root.append(el('p', 'empty', 'No HW5 evaluator data yet. Export confirmed HW5 labels and save the split to see it here.'));
    const cards = el('div', 'evaluator-cards');
    for (const mode of snapshot.modes) cards.append(modeCard(mode));
    root.append(cards);
  }
  function modeCard(mode) {
    const card = el('article', 'panel evaluator-card');
    const titleId = 'evaluator-title-' + encodeURIComponent(mode.id);
    card.setAttribute('aria-labelledby', titleId);
    const title = el('h3', '', `${mode.name} (LLM judge)`); title.id = titleId;
    card.append(title, el('p', 'evaluator-description', mode.definition || 'No saved definition.'));
    const columns = el('div', 'evaluator-card-columns');
    const prompt = el('section', 'evaluator-card-section evaluator-prompt-column');
    const promptHeading = el('h4', '', 'Judge prompt');
    prompt.append(promptHeading);
    const data = el('div', 'evaluator-data-column');
    columns.append(prompt, data); card.append(columns);
    const setsHeading = el('header', 'evaluator-set-heading');
    setsHeading.append(el('h4', '', 'Train / validation / test'));
    columns.insertBefore(setsHeading, data);
    const sets = el('section', 'evaluator-card-section');
    sets.append(table('Dataset split counts', ['Set', 'Planned share', 'Pass', 'Fail', 'Total'],
      Object.entries(mode.splits).map(([name, split]) => [name === 'dev' ? 'Validation' : name === 'train' ? 'Training' : 'Test',
        percent(split.fraction), split.pass, split.fail, split.total])));
    data.append(sets);
    const results = el('section', 'evaluator-card-section'); results.append(el('h4', '', 'Validation / test results'));
    if (!mode.judges.length) {
      prompt.append(el('p', 'quiet', 'No judge prompt saved yet.'));
      results.append(el('p', 'empty', 'No judge registered for this mode yet.'));
      data.append(results); return card;
    }
    const judge = mode.judges.find(j => j.judge_id === selectedJudges.get(mode.id)) || mode.judges[0];
    selectedJudges.set(mode.id, judge.judge_id);
    const sha = judge.prompt_sha256 ? ` - ${judge.prompt_sha256.slice(-7)}` : '';
    promptHeading.textContent = `Judge prompt (v${judge.version}${sha})`;
    prompt.append(judge.prompt_text ? el('pre', 'evaluator-prompt', judge.prompt_text)
      : el('p', 'quiet', 'No judge prompt saved yet.'));
    if (mode.judges.length > 1) results.append(selector('Judge version', 'evaluator-judge-' + encodeURIComponent(mode.id),
      mode.judges.map(j => [j.judge_id, j.judge_id]), judge.judge_id, value => selectedJudges.set(mode.id, value)));
    const metric = (split, format) => judge[split] ? format(judge[split]) : split === 'test' && judge.status !== 'frozen' ? 'Locked until frozen' : 'Pending';
    const matrices = el('div', 'evaluator-confusion-matrices');
    for (const [split, title] of [['dev', 'Validation'], ['test', 'Test']]) {
      const matrix = table(`${title} confusion matrix`, ['Judge verdict', 'Pass', 'Fail'], [
        ['Pass (1)', metric(split, r => `TP: ${r.tp}`), metric(split, r => `FP: ${r.fp}`)],
        ['Fail (0)', metric(split, r => `FN: ${r.fn}`), metric(split, r => `TN: ${r.tn}`)],
      ]);
      const head = matrix.querySelector('thead');
      const judgeHeading = head.querySelector('th');
      judgeHeading.rowSpan = 2;
      const humanHeading = el('th', '', 'Human');
      humanHeading.colSpan = 2;
      humanHeading.scope = 'colgroup';
      const group = el('tr');
      group.append(judgeHeading, humanHeading);
      head.prepend(group);
      matrix.classList.add('evaluator-confusion');
      const captionRow = el('div', 'evaluator-matrix-heading');
      captionRow.append(el('span', '', `${title} confusion matrix`));
      if (split === 'dev') {
        const show = button('Show traces', () => showTraces(judge));
        show.setAttribute('aria-haspopup', 'dialog'); show.disabled = !judge.dev;
        captionRow.append(show);
      }
      matrix.prepend(captionRow);
      matrices.append(matrix);
    }
    results.append(matrices, el('h5', 'evaluator-results-heading', 'Results'));
    const rows = [
      ['Evaluated conversations', r => r.n],
      ['TPR · Pass agreement', r => percent(r.tpr)],
      ['TNR · Fail detection', r => percent(r.tnr)],
    ];
    results.append(table('Judge evaluation results', ['Measure', 'Validation', 'Test'],
      rows.map(([title, format]) => [title, metric('dev', format), metric('test', format)])));
    columns.append(el('p', 'quiet evaluator-footnote', 'TPR = TP / (TP + FN). TNR = TN / (TN + FP). Pass is the positive class.'));
    data.append(results);
    return card;
  }
  return {render, refresh};
})();
