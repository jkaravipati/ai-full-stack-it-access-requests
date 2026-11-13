'use strict';
const $ = id => document.getElementById(id);
const state = {records: [], selected: null, signature: null, busy: false};
const labels = {'review-request': 'Review request', 'review-risk-then-owner': 'Review risk, then owner', clarify: 'Clarify with requester', 'inspect-message': 'Inspect message', 'confirm-withdrawal': 'Confirm withdrawal', 'retry-extraction': 'Retry extraction'};
const statusLabels = {review: 'Ready for review', 'needs-information': 'Needs information', error: 'Extraction error', pending: 'In progress'};
function node(tag, text, className) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The operation could not be completed.');
  return data;
}
function notify(message, failure = false) { $('notice').textContent = message; $('notice').className = 'notice' + (failure ? ' failure' : ''); $('notice').hidden = false; }
function render() {
  const query = $('search').value.toLowerCase().trim(), filter = $('filter').value;
  const visible = state.records.filter(r => {
    const e = r.extraction || {}, status = r.status || 'pending';
    return (filter === 'all' || filter === status) && [r.document_id, e.request_id, e.requester, e.team, e.system].some(v => String(v || '').toLowerCase().includes(query));
  });
  $('rows').replaceChildren();
  for (const r of visible) {
    const e = r.extraction || {}, row = node('tr'), first = node('td');
    const link = node('button', e.request_id || r.document_id, 'request-link');
    link.type = 'button'; link.addEventListener('click', () => openDetails(r.document_id)); first.append(link);
    first.append(node('span', [e.requester || r.document_id, e.team].filter(Boolean).join(' · '), 'subline'));
    const system = node('td'); system.append(node('span', e.system || 'Awaiting extraction', 'system-name'));
    system.append(node('span', [e.environment, e.permission].filter(Boolean).join(' / ') || '—', 'subline access-tag'));
    const status = r.status || 'pending', badgeCell = node('td'); badgeCell.append(node('span', statusLabels[status] || status, 'badge ' + status));
    row.append(first, system, badgeCell, node('td', r.owner || 'Processing'), node('td', labels[r.next_action] || 'Preparing request'));
    $('rows').append(row);
  }
  $('empty').hidden = visible.length > 0;
  const title = $('empty').querySelector('h3'), subtitle = $('empty').querySelector('p');
  title.textContent = state.records.length ? 'No requests match your filters' : 'Your queue is ready for its first request';
  subtitle.textContent = state.records.length ? 'Try another search or choose all statuses.' : 'Start intake from the configured exports or upload your own JSON files.';
  $('shown').textContent = `${visible.length} of ${state.records.length} requests`;
}
async function refresh() {
  try {
    const data = await api('/api/queue'); state.records = data.records;
    for (const key of ['total', 'review', 'needs_information', 'errors']) $(key).textContent = data.counts[key];
    $('pending').hidden = !data.counts.pending; $('pending').textContent = `${data.counts.pending} in progress`;
    $('connection').textContent = 'Queue connected'; $('updated').textContent = 'Refreshed ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    render();
    if (state.selected && $('details').open) {
      const selected = state.records.find(r => r.document_id === state.selected);
      const signature = selected ? `${selected.attempt_id}:${selected.processing_state}` : '';
      if (signature !== state.signature) await loadDetails(state.selected);
    }
  } catch (error) { $('connection').textContent = 'Connection interrupted'; notify(error.message, true); }
}
async function action(button, path, body = {}) {
  if (state.busy) return;
  state.busy = true; button.disabled = true;
  try { const result = await api(path, body); notify(result.message || `Snapshot exported · ${result.document_count} requests`); if (path === '/api/export') $('downloads').hidden = false; await refresh(); }
  catch (error) { notify(error.message, true); }
  finally { state.busy = false; const current = state.records.find(r => r.document_id === state.selected); button.disabled = button.id === 'retry' && ['queued', 'running'].includes(current?.processing_state); }
}
async function openDetails(id) { state.selected = id; state.signature = null; try { await loadDetails(id); if (!$('details').open) $('details').showModal(); } catch (error) { notify(error.message, true); } }
async function loadDetails(id) {
  const data = await api('/api/documents/' + encodeURIComponent(id)), r = data.record, e = r.extraction || {};
  const history = await api('/api/documents/' + encodeURIComponent(id) + '/history');
  state.signature = `${r.attempt_id}:${r.processing_state}`; $('detail-title').textContent = e.request_id || id;
  $('detail-route').textContent = r.status ? `${statusLabels[r.status]} · ${r.owner} · ${labels[r.next_action]}` : 'This source version is still being prepared. Its previous result is reference only.';
  $('facts').replaceChildren();
  const meta = r.metadata || {};
  const fields = [['Requester', e.requester], ['Team', e.team], ['System', e.system], ['Environment', e.environment], ['Permission', e.permission], ['Request date', e.request_date], ['Access starts', e.start_date], ['Access ends', e.end_date], ['Manager contact', e.manager], ['Request type', e.kind], ['Business purpose', e.business_purpose], ['Document', id], ['Subject', meta.subject], ['Channel', meta.source_channel], ['Exported at', meta.exported_at], ['Export version', meta.export_version], ['Source SHA-256', r.source_sha256], ['Response source', r.response_source]];
  for (const [label, value] of fields) { const item = node('div'); item.append(node('dt', label), node('dd', value || 'Not supplied / unresolved')); $('facts').append(item); }
  $('issues').replaceChildren();
  const issues = [...(e.issues || [])]; if (r.error) issues.push(`${r.error.stage}: ${r.error.message}`, r.error.retry_command);
  for (const issue of issues.length ? issues : ['No issues recorded.']) $('issues').append(node('li', issue));
  $('quotes').replaceChildren(); for (const quote of e.supporting_quotes || []) $('quotes').append(node('blockquote', quote));
  if (!e.supporting_quotes?.length) $('quotes').append(node('p', 'No validated extraction evidence yet.', 'muted'));
  $('source-message').textContent = data.message;
  $('history').replaceChildren();
  for (const attempt of history.attempts.slice().reverse()) {
    const item = node('details', undefined, 'history-entry');
    item.append(node('summary', `Attempt ${attempt.attempt_id} · revision ${attempt.target_generation} · ${attempt.processing_state}`));
    item.append(node('pre', JSON.stringify(attempt, null, 2))); $('history').append(item);
  }
  $('previous-section').hidden = !r.previous; $('previous').textContent = r.previous ? JSON.stringify(r.previous, null, 2) : '';
  $('detail-state').textContent = `Attempt ${r.attempt_id} · revision ${r.target_generation} · ${r.processing_state}`;
  $('retry').disabled = ['queued', 'running'].includes(r.processing_state);
}
$('start').addEventListener('click', () => action($('start'), '/api/intake'));
$('resume').addEventListener('click', () => action($('resume'), '/api/resume'));
$('export').addEventListener('click', () => action($('export'), '/api/export'));
$('retry').addEventListener('click', () => action($('retry'), '/api/documents/' + encodeURIComponent(state.selected) + '/retry'));
$('close-details').addEventListener('click', () => $('details').close());
$('details').addEventListener('close', () => { state.selected = null; });
$('search').addEventListener('input', render); $('filter').addEventListener('change', render);
$('upload').addEventListener('click', () => $('files').click());
$('files').addEventListener('change', async () => {
  try {
    const files = Array.from($('files').files); if (!files.length) return;
    if (files.length > 2000 || files.some(f => f.size > 128 * 1024) || files.reduce((n, f) => n + f.size, 0) > 5 * 1024 * 1024) throw new Error('Upload up to 2,000 exports, with each file under 128 KB and a batch under 5 MB.');
    const exports = await Promise.all(files.map(async file => { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte); return {filename: file.name, data_base64: btoa(binary)}; }));
    await action($('upload'), '/api/intake', {exports});
  } catch (error) { notify(error.message, true); }
  finally { $('files').value = ''; }
});
api('/api/config').then(config => { $('mode').textContent = config.provider === 'mock' ? 'MOCK RESPONSES' : 'LIVE PROVIDER'; $('source-label').textContent = `Configured source: ${config.source_label} · uploads preserve original file bytes`; }).catch(error => notify(error.message, true));
refresh();
setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 2000);
