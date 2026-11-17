/* Saved evaluator artifacts are read-only. Content is always rendered as text. */
const EvaluatorPanel = (() => {
  let snapshot = null, loading = false, error = '';
  const selectedJudges = new Map();
  const percent = value => Number.isFinite(value) ? (value * 100).toFixed(1) + '%' : 'Not available';
  const interval = values => Array.isArray(values) && values.every(Number.isFinite)
    ? `${percent(values[0])}–${percent(values[1])}` : 'Not available';
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
  function render() {
    const root = $('evaluator-view'); root.replaceChildren();
    root.setAttribute('aria-busy', String(loading));
    const heading = el('div', 'evaluator-heading');
    heading.append(el('h2', '', 'Evaluator'));
    const reload = button(loading ? 'Refreshing…' : 'Refresh results', refresh); reload.disabled = loading;
    heading.append(reload); root.append(heading);
    root.append(el('p', 'quiet', 'Saved HW5 labels, data splits, and judge results. Pass = failure absent; Fail = failure present.'));
    if (error) {const message = el('p', 'warning', 'Could not load evaluator data: ' + error); message.setAttribute('role', 'alert'); root.append(message);}
    if (!snapshot) return root.append(el('p', 'empty', loading ? 'Loading evaluator data…' : 'Choose Refresh results to load saved evaluations.'));
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
    prompt.append(el('h4', '', 'Judge prompt'));
    const data = el('div', 'evaluator-data-column');
    columns.append(prompt, data); card.append(columns);
    const sets = el('section', 'evaluator-card-section'); sets.append(el('h4', '', 'Train / development / test'));
    const assigned = Object.values(mode.splits).reduce((total, split) => total + split.total, 0);
    sets.append(el('p', 'quiet', `${assigned} assigned conversations · ${mode.label_count} saved labels · Seed ${mode.seed ?? 'not saved'}`));
    sets.append(table('Dataset split counts', ['Set', 'Planned share', 'Pass', 'Fail', 'Total'],
      Object.entries(mode.splits).map(([name, split]) => [name === 'dev' ? 'Development' : name === 'train' ? 'Training' : 'Test',
        percent(split.fraction), split.pass, split.fail, split.total])));
    data.append(sets);
    const results = el('section', 'evaluator-card-section'); results.append(el('h4', '', 'Development / test results'));
    if (!mode.judges.length) {
      prompt.append(el('p', 'quiet', 'No judge prompt saved yet.'));
      results.append(el('p', 'empty', 'No judge registered for this mode yet.'));
      data.append(results); return card;
    }
    const judge = mode.judges.find(j => j.judge_id === selectedJudges.get(mode.id)) || mode.judges[0];
    selectedJudges.set(mode.id, judge.judge_id);
    prompt.append(judge.prompt_text ? el('pre', 'evaluator-prompt', judge.prompt_text)
      : el('p', 'quiet', 'No judge prompt saved yet.'));
    if (mode.judges.length > 1) results.append(selector('Judge version', 'evaluator-judge-' + encodeURIComponent(mode.id),
      mode.judges.map(j => [j.judge_id, j.judge_id]), judge.judge_id, value => selectedJudges.set(mode.id, value)));
    else results.append(el('p', 'quiet evaluator-version', judge.judge_id));
    results.append(el('p', 'quiet', `Model: ${judge.model || 'Not saved'} · Status: ${judge.status || 'Not saved'}`));
    const metric = (split, format) => judge[split] ? format(judge[split]) : split === 'test' && judge.status !== 'frozen' ? 'Locked until frozen' : 'Pending';
    const matrices = el('div', 'evaluator-confusion-matrices');
    for (const [split, title] of [['dev', 'Development'], ['test', 'Test']]) {
      const matrix = table(`${title} confusion matrix`, ['Judge ↓ / Human →', 'Pass (1)', 'Fail (0)'], [
        ['Pass (1)', metric(split, r => `TP: ${r.tp}`), metric(split, r => `FP: ${r.fp}`)],
        ['Fail (0)', metric(split, r => `FN: ${r.fn}`), metric(split, r => `TN: ${r.tn}`)],
      ]);
      matrix.classList.add('evaluator-confusion');
      matrix.querySelector('caption').className = '';
      matrices.append(matrix);
    }
    results.append(matrices, el('h5', 'evaluator-results-heading', 'Results'));
    const rows = [
      ['Evaluated conversations', r => r.n],
      ['TPR · Pass agreement', r => percent(r.tpr)], ['TPR · 95% Wilson interval', r => interval(r.tpr_interval)],
      ['TNR · Fail detection', r => percent(r.tnr)], ['TNR · 95% Wilson interval', r => interval(r.tnr_interval)],
    ];
    results.append(table('Judge evaluation results', ['Measure', 'Development', 'Test'],
      rows.map(([title, format]) => [title, metric('dev', format), metric('test', format)])));
    results.append(el('p', 'quiet', 'TPR = TP / (TP + FN). TNR = TN / (TN + FP). Pass is the positive class.'));
    data.append(results);
    return card;
  }
  return {render, refresh};
})();
