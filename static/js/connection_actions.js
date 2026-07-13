/** Shared learned-connection API actions (L3 anti-sprawl). */

import uiModule from './ui.js';

const API_BASE = window.API_BASE || window.location.origin || '';
const esc = uiModule.esc;

export const KIND_LABELS = {
  derives_from: 'Derives from',
  refutes: 'Refutes',
  supports: 'Supports',
  relates: 'Relates',
  depends_on: 'Depends on',
  summarizes: 'Summarizes',
};

export function kindLabel(kind) {
  return KIND_LABELS[kind] || (kind || 'relates').replace(/_/g, ' ');
}

export function sourceLabel(source) {
  const s = (source || 'agent').toLowerCase();
  if (s === 'compare_papers') return 'Paper compare';
  if (s === 'library_compare') return 'Library compare';
  if (s === 'session_extract') return 'Session extract';
  if (s === 'research' || s === 'deep_research') return 'Research';
  if (s === 'paper_summary_pipeline') return 'Summary';
  if (s === 'agent' || s === 'suggest_link') return 'Chat';
  return source || 'Learned';
}

export function sourceSessionHref(row) {
  const sid = (row?.source_session || '').trim();
  if (!sid) return null;
  if (sid.startsWith('research:')) {
    return `${API_BASE}/api/research/report/${encodeURIComponent(sid.split(':', 1)[1])}`;
  }
  return `${API_BASE}/api/research/report/${encodeURIComponent(sid)}`;
}

export function evidenceHtml(row) {
  const bits = [];
  if (row?.section_ref) {
    bits.push(`<span class="learned-conn-evidence-ref">§ ${esc(row.section_ref)}</span>`);
  }
  if (row?.evidence) {
    bits.push(`<span class="learned-conn-evidence">${esc(String(row.evidence).slice(0, 220))}</span>`);
  }
  if (!bits.length) return '';
  return `<div class="learned-conn-evidence-block">${bits.join(' ')}</div>`;
}

const AUDIT_STATUS_LABELS = {
  conflict: 'Conflict',
  missing_node: 'Missing node',
  invalid: 'Invalid',
  duplicate: 'Already linked',
};

export function auditHtml(row) {
  const status = (row?.audit_status || '').trim();
  if (!status || status === 'ok') return '';
  const label = AUDIT_STATUS_LABELS[status] || status.replace(/_/g, ' ');
  const errs = (row?.audit_errors || []).filter(Boolean);
  const title = errs.length ? errs.join('; ') : label;
  return `<span class="learned-conn-audit learned-conn-audit--${esc(status)}" title="${esc(title)}">${esc(label)}</span>`;
}

export async function fetchPendingConnections(filters = {}) {
  const params = new URLSearchParams();
  if (filters.project_id) params.set('project_id', filters.project_id);
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.source) params.set('source', filters.source);
  if (filters.min_confidence != null && filters.min_confidence !== '') {
    params.set('min_confidence', String(filters.min_confidence));
  }
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/knowledge/pending${qs ? `?${qs}` : ''}`, {
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Failed to load connections');
  return data.rows || [];
}

export async function enqueuePendingProposals(proposals, source = 'agent', opts = {}) {
  const body = { proposals, source };
  if (opts.project_id) body.project_id = opts.project_id;
  const res = await fetch(`${API_BASE}/api/knowledge/pending/enqueue`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Could not save for later');
  window.dispatchEvent(new CustomEvent('learned-connections-refresh'));
  return data;
}

export async function rejectPendingProposal(proposal) {
  const res = await fetch(`${API_BASE}/api/knowledge/pending/reject`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(proposal),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Reject failed');
  window.dispatchEvent(new CustomEvent('learned-connections-refresh'));
  return data;
}

export async function rejectPendingProposals(proposals) {
  const res = await fetch(`${API_BASE}/api/knowledge/pending/reject-batch`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposals }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Reject failed');
  window.dispatchEvent(new CustomEvent('learned-connections-refresh'));
  return data;
}

export async function acceptPendingProposals(proposals) {
  const res = await fetch(`${API_BASE}/api/knowledge/pending/accept-batch`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposals }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Accept failed');
  window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
  window.dispatchEvent(new CustomEvent('learned-connections-refresh'));
  return data;
}

export async function acceptPendingRow(row) {
  const res = await fetch(`${API_BASE}/api/knowledge/pending/${encodeURIComponent(row.id)}/accept`, {
    method: 'POST',
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Accept failed');
  window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
  window.dispatchEvent(new CustomEvent('learned-connections-refresh'));
  return data;
}

export function filterPendingRows(rows, { q = '', kind = '', source = '' } = {}) {
  const query = (q || '').trim().toLowerCase();
  const kindF = (kind || '').trim().toLowerCase();
  const srcF = (source || '').trim().toLowerCase();
  return (rows || []).filter((row) => {
    if (kindF && (row.kind || '').toLowerCase() !== kindF) return false;
    if (srcF && (row.source || '').toLowerCase() !== srcF) return false;
    if (!query) return true;
    const hay = [
      row.from, row.to, row.from_title, row.to_title, row.reason,
      row.evidence, row.section_ref, row.source,
    ].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(query);
  });
}

export default {
  fetchPendingConnections,
  enqueuePendingProposals,
  rejectPendingProposal,
  rejectPendingProposals,
  acceptPendingProposals,
  acceptPendingRow,
  filterPendingRows,
  kindLabel,
  sourceLabel,
  sourceSessionHref,
  evidenceHtml,
};
