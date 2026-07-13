/** Batch graph edge merge review UI (Edge Taxonomy T2). */

import uiModule from './ui.js';

const esc = uiModule.esc;

const API_BASE = window.API_BASE || window.location.origin || '';
const KIND_OPTIONS = ['relates', 'derives_from', 'refutes', 'supports', 'depends_on'];
const KIND_LABELS = {
  relates: 'Relates',
  derives_from: 'Derives from',
  refutes: 'Refutes',
  supports: 'Supports',
  depends_on: 'Depends on',
};

let _previewRows = [];
let _mergeSessionId = '';

function _kindLabel(kind) {
  return KIND_LABELS[kind] || kind;
}

function _statusBadge(status) {
  const cls = `kg-merge-status kg-merge-status--${esc(status || 'unknown')}`;
  return `<span class="${cls}">${esc(status || '?')}</span>`;
}

function _renderMergeTable(rows) {
  if (!rows?.length) {
    return '<div class="kg-merge-empty">No proposals to review.</div>';
  }
  const head = `<thead><tr>
    <th><input type="checkbox" id="kg-merge-select-all" checked aria-label="Select all"></th>
    <th>From → To</th>
    <th>Kind</th>
    <th>Reason</th>
    <th>Status</th>
  </tr></thead>`;
  const body = rows.map((row, idx) => {
    const kindOpts = KIND_OPTIONS.map(
      (k) => `<option value="${esc(k)}"${row.kind === k ? ' selected' : ''}>${_kindLabel(k)}</option>`,
    ).join('');
    const err = (row.errors || []).concat(row.warnings || []).join('; ');
    return `<tr class="kg-merge-row" data-row-index="${idx}">
      <td><input type="checkbox" class="kg-merge-select" data-row-index="${idx}"${row.selected !== false ? ' checked' : ''}></td>
      <td class="kg-merge-endpoints">
        <div class="kg-merge-title">${esc(row.from_title || row.from)}</div>
        <div class="kg-merge-arrow">→ ${esc(row.to_title || row.to)}</div>
      </td>
      <td><select class="kg-merge-kind" data-row-index="${idx}">${kindOpts}</select></td>
      <td><input type="text" class="settings-input kg-merge-reason" data-row-index="${idx}" value="${esc(row.reason || '')}" maxlength="280"></td>
      <td>${_statusBadge(row.status)}${err ? `<div class="kg-merge-note">${esc(err)}</div>` : ''}</td>
    </tr>`;
  }).join('');
  return `<table class="kg-merge-table">${head}<tbody>${body}</tbody></table>`;
}

function _collectAcceptedRows() {
  const modal = document.getElementById('kg-merge-modal');
  if (!modal) return [];
  return _previewRows.map((row, idx) => {
    const cb = modal.querySelector(`.kg-merge-select[data-row-index="${idx}"]`);
    const kindSel = modal.querySelector(`.kg-merge-kind[data-row-index="${idx}"]`);
    const reasonInput = modal.querySelector(`.kg-merge-reason[data-row-index="${idx}"]`);
    const selected = cb?.checked !== false;
    const kind = kindSel?.value || row.kind;
    const reason = reasonInput?.value?.trim() || '';
    const action = row.status === 'duplicate' && row.can_update_reason ? 'update_reason' : 'add';
    return {
      ...row,
      selected,
      kind,
      reason,
      action: selected ? action : 'skip',
      skip: !selected,
      update_reason: action === 'update_reason',
    };
  });
}

async function _runPreview(proposals) {
  const res = await fetch(`${API_BASE}/api/knowledge/merge/preview`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposals }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Preview failed');
  _previewRows = data.rows || [];
  _mergeSessionId = data.merge_session_id || '';
  const summary = data.summary || {};
  const summaryEl = document.getElementById('kg-merge-summary');
  if (summaryEl) {
    summaryEl.textContent = `${summary.total || 0} proposals — ${summary.ready || 0} ready, ${summary.conflicts || 0} conflicts, ${summary.duplicates || 0} duplicates`;
  }
  const mount = document.getElementById('kg-merge-table-mount');
  if (mount) mount.innerHTML = _renderMergeTable(_previewRows);
  const applyBtn = document.getElementById('kg-merge-apply-btn');
  if (applyBtn) applyBtn.disabled = !_previewRows.length;
}

async function _runApply() {
  const accepted = _collectAcceptedRows().filter((r) => r.selected !== false);
  if (!accepted.length) {
    uiModule.showToast?.('Select at least one row to apply', 3000);
    return;
  }
  const res = await fetch(`${API_BASE}/api/knowledge/merge/apply`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accepted }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Apply failed');
  uiModule.showToast?.(
    `Merge complete — added ${data.applied || 0}, updated ${data.updated || 0}, skipped ${data.skipped || 0}`,
  );
  window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
  closeGraphMergeModal();
}

function _wireMergeModal(modal) {
  if (modal.dataset.kgMergeWired === '1') return;
  modal.dataset.kgMergeWired = '1';

  modal.querySelector('#close-kg-merge-modal')?.addEventListener('click', closeGraphMergeModal);
  modal.querySelector('#kg-merge-preview-btn')?.addEventListener('click', () => {
    void (async () => {
      const raw = modal.querySelector('#kg-merge-json-input')?.value?.trim() || '';
      if (!raw && !_previewRows.length) {
        uiModule.showToast?.('Add proposals via Import JSON or open from Connections', 3000);
        return;
      }
      try {
        const proposals = raw ? JSON.parse(raw) : _previewRows.map((r) => ({
          from: r.from,
          to: r.to,
          kind: r.kind,
          reason: r.reason,
        }));
        if (!Array.isArray(proposals)) throw new Error('Expected a JSON array');
        await _runPreview(proposals);
      } catch (e) {
        uiModule.showToast?.(e.message || 'Invalid JSON', 4000);
      }
    })();
  });

  modal.querySelector('#kg-merge-apply-btn')?.addEventListener('click', () => {
    void _runApply().catch((e) => uiModule.showToast?.(e.message || 'Apply failed', 4000));
  });

  modal.addEventListener('change', (ev) => {
    if (ev.target?.id === 'kg-merge-select-all') {
      modal.querySelectorAll('.kg-merge-select').forEach((cb) => {
        cb.checked = ev.target.checked;
      });
    }
  });
}

export function openGraphMergeReview(proposals = [], { rows: preloadedRows = null } = {}) {
  let modal = document.getElementById('kg-merge-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  _wireMergeModal(modal);
  _previewRows = [];
  const input = modal.querySelector('#kg-merge-json-input');
  if (input) {
    input.value = proposals?.length && !preloadedRows ? JSON.stringify(proposals, null, 2) : '';
    const adv = document.getElementById('kg-merge-advanced');
    if (adv && proposals?.length && !preloadedRows) adv.open = true;
  }
  const mount = document.getElementById('kg-merge-table-mount');
  if (mount) mount.innerHTML = '';
  const summaryEl = document.getElementById('kg-merge-summary');
  if (summaryEl) summaryEl.textContent = '';
  const applyBtn = document.getElementById('kg-merge-apply-btn');
  if (applyBtn) applyBtn.disabled = true;
  if (preloadedRows?.length) {
    _previewRows = preloadedRows;
    if (summaryEl) {
      const ready = preloadedRows.filter((r) => r.status === 'ready').length;
      const conflicts = preloadedRows.filter((r) => r.status === 'conflict').length;
      const duplicates = preloadedRows.filter((r) => r.status === 'duplicate').length;
      summaryEl.textContent = `${preloadedRows.length} proposals — ${ready} ready, ${conflicts} conflicts, ${duplicates} duplicates`;
    }
    if (mount) mount.innerHTML = _renderMergeTable(_previewRows);
    if (applyBtn) applyBtn.disabled = false;
  } else if (proposals?.length) {
    void _runPreview(proposals).catch((e) => uiModule.showToast?.(e.message || 'Preview failed', 4000));
  }
}

export function closeGraphMergeModal() {
  document.getElementById('kg-merge-modal')?.classList.add('hidden');
}

export function initGraphMergeListeners() {
  window.addEventListener('graph-merge-proposals', (ev) => {
    const detail = ev.detail || {};
    if (detail.rows?.length) {
      openGraphMergeReview([], { rows: detail.rows });
    } else {
      openGraphMergeReview(detail.proposals || []);
    }
  });
  document.getElementById('kg-merge-btn')?.addEventListener('click', () => {
    openGraphMergeReview([]);
  });
}
