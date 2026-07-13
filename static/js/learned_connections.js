/** Connections tab (in Brain) — review deferred link proposals. */

import uiModule from './ui.js';
import { openGraphMergeReview } from './graph_merge.js';
import {
  acceptPendingProposals,
  acceptPendingRow,
  auditHtml,
  evidenceHtml,
  fetchPendingConnections,
  filterPendingRows,
  kindLabel,
  rejectPendingProposals,
  sourceLabel,
  sourceSessionHref,
} from './connection_actions.js';
import { showLoadingRow, showEmptyState, showError } from './ui/feedback.js';

const esc = uiModule.esc;

let _allRows = [];
let _filters = { q: '', kind: '', source: '' };

export async function fetchPendingConnectionsForBrain() {
  return fetchPendingConnections();
}

export async function updatePendingCountBadge() {
  try {
    const rows = await fetchPendingConnections();
    const n = rows.length;
    for (const id of ['connections-count', 'connections-count-h2']) {
      const el = document.getElementById(id);
      if (el) el.textContent = n ? String(n) : '0';
    }
    document.querySelectorAll('.memory-tab[data-memory-tab="connections"]').forEach((tab) => {
      tab.classList.toggle('memory-tab--has-pending', n > 0);
    });
    const label = n > 99 ? '99+' : String(n);
    document.querySelectorAll('.brain-connections-badge').forEach((badge) => {
      if (n > 0) {
        badge.textContent = label;
        badge.hidden = false;
        badge.setAttribute('aria-label', `${n} pending connection${n === 1 ? '' : 's'}`);
      } else {
        badge.textContent = '';
        badge.hidden = true;
        badge.removeAttribute('aria-label');
      }
    });
  } catch {
    /* ignore */
  }
}

export function openBrainConnectionsTab() {
  document.getElementById('tool-memory-btn')?.click()
    || document.getElementById('rail-memory')?.click();
  setTimeout(() => {
    document.querySelector('.memory-tab[data-memory-tab="connections"]')?.click();
  }, 80);
}

function _filteredRows() {
  return filterPendingRows(_allRows, _filters);
}

function _renderRow(row) {
  const fromTitle = row.from_title || row.from;
  const toTitle = row.to_title || row.to;
  const sessionHref = sourceSessionHref(row);
  const sessionLink = sessionHref
    ? `<a class="learned-pending-session" href="${esc(sessionHref)}" target="_blank" rel="noopener">Open source</a>`
    : '';
  const conf = row.confidence != null
    ? `<span class="learned-pending-conf">${Math.round(Number(row.confidence) * 100)}%</span>`
    : '';
  return `<div class="kg-link-row-wrap learned-pending-row" data-proposal-id="${esc(row.id)}">
    <div class="learned-pending-flow">
      <span class="kg-link-kind">${esc(kindLabel(row.kind))}</span>
      <span class="kg-node-title" title="${esc(fromTitle)}">${esc(fromTitle)}</span>
      <span class="learned-pending-arrow" aria-hidden="true">→</span>
      <span class="kg-node-title" title="${esc(toTitle)}">${esc(toTitle)}</span>
    </div>
    ${row.reason ? `<div class="kg-link-reason">${esc(row.reason)}</div>` : ''}
    ${evidenceHtml(row)}
    <div class="learned-pending-meta">
      <span class="learned-pending-source">${esc(sourceLabel(row.source))}</span>
      ${auditHtml(row)}
      ${conf}
      ${sessionLink}
    </div>
    <div class="learned-pending-actions">
      <button type="button" class="kg-link-suggest-reject learned-pending-reject">Reject</button>
      <button type="button" class="kg-link-suggest-accept learned-pending-accept">Accept</button>
    </div>
  </div>`;
}

function _wireRowActions(list, rows) {
  list.querySelectorAll('.learned-pending-accept').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.learned-pending-row');
      const id = card?.dataset?.proposalId;
      const row = rows.find((r) => r.id === id);
      if (!row) return;
      btn.disabled = true;
      void acceptPendingRow(row)
        .then(() => {
          uiModule.showToast?.('Added to Links');
          return loadLearnedConnections();
        })
        .catch((e) => {
          btn.disabled = false;
          uiModule.showToast?.(e.message || 'Accept failed', 4000);
        });
    });
  });
  list.querySelectorAll('.learned-pending-reject').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.learned-pending-row');
      const id = card?.dataset?.proposalId;
      const row = rows.find((r) => r.id === id);
      if (!row) return;
      btn.disabled = true;
      void rejectPendingProposals([row])
        .then(() => loadLearnedConnections())
        .catch((e) => {
          btn.disabled = false;
          uiModule.showToast?.(e.message || 'Reject failed', 4000);
        });
    });
  });
}

function _renderList(cascade = false) {
  const list = document.getElementById('connections-list');
  if (!list) return;
  const rows = _filteredRows();
  if (!rows.length) {
    list.innerHTML = '<div class="kg-link-empty" style="padding:12px">No connections match your filters.</div>';
    return;
  }
  list.innerHTML = rows.map(_renderRow).join('');
  if (cascade) list.classList.add('memory-list-cascade');
  _wireRowActions(list, rows);
}

function _wireToolbar() {
  const toolbar = document.getElementById('connections-toolbar');
  if (!toolbar || toolbar.dataset.bound === '1') return;
  toolbar.dataset.bound = '1';

  const qEl = document.getElementById('connections-filter-q');
  const kindEl = document.getElementById('connections-filter-kind');
  const sourceEl = document.getElementById('connections-filter-source');

  const apply = () => {
    _filters = {
      q: qEl?.value || '',
      kind: kindEl?.value || '',
      source: sourceEl?.value || '',
    };
    _renderList();
  };
  qEl?.addEventListener('input', apply);
  kindEl?.addEventListener('change', apply);
  sourceEl?.addEventListener('change', apply);

  document.getElementById('connections-bulk-accept')?.addEventListener('click', () => {
    const rows = _filteredRows();
    if (!rows.length) return;
    void acceptPendingProposals(rows)
      .then((out) => {
        const added = (out.applied || 0) + (out.updated || 0);
        uiModule.showToast?.(`Added ${added} link${added === 1 ? '' : 's'} to Links`);
        return loadLearnedConnections();
      })
      .catch((e) => uiModule.showToast?.(e.message || 'Accept failed', 4000));
  });

  document.getElementById('connections-bulk-reject')?.addEventListener('click', () => {
    const rows = _filteredRows();
    if (!rows.length) return;
    void rejectPendingProposals(rows)
      .then(() => {
        uiModule.showToast?.('Connections dismissed');
        return loadLearnedConnections();
      })
      .catch((e) => uiModule.showToast?.(e.message || 'Reject failed', 4000));
  });

  document.getElementById('connections-edit-table')?.addEventListener('click', () => {
    const rows = _filteredRows();
    if (!rows.length) {
      uiModule.showToast?.('Nothing to edit', 2500);
      return;
    }
    openGraphMergeReview(rows.map((r) => ({
      from: r.from,
      to: r.to,
      kind: r.kind,
      reason: r.reason,
      id: r.id,
    })));
  });
}

export async function loadLearnedConnections(cascade = false) {
  const list = document.getElementById('connections-list');
  if (!list) return;
  _wireToolbar();
  showLoadingRow(list, 'Loading…');
  try {
    _allRows = await fetchPendingConnections();
    await updatePendingCountBadge();
    if (!_allRows.length) {
      showEmptyState(list, {
        kind: 'empty',
        message: 'No pending connections. When chat or research suggests links, choose Review later to queue them here.',
      });
      return;
    }
    _renderList(cascade);
  } catch (e) {
    showError(list, { message: e.message || String(e), retry: () => loadLearnedConnections(cascade) });
  }
}

export function initLearnedConnectionsListeners() {
  window.addEventListener('learned-connections-refresh', () => {
    void updatePendingCountBadge();
    const panel = document.querySelector('.memory-tab-panel[data-memory-panel="connections"]');
    if (panel && !panel.classList.contains('hidden')) void loadLearnedConnections();
  });
  window.addEventListener('knowledge-graph-refresh', () => { void updatePendingCountBadge(); });
}

export default {
  loadLearnedConnections,
  fetchPendingConnections: fetchPendingConnectionsForBrain,
  openBrainConnectionsTab,
  updatePendingCountBadge,
  initLearnedConnectionsListeners,
};
