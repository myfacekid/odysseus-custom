/**
 * Links browser — search and explore confirmed connections
 * (tasks, documents, memories, skills).
 */
import uiModule from './ui.js';
import sessionModule from './sessions.js';
import { initGraphMergeListeners, openGraphMergeReview } from './graph_merge.js';
import {
  acceptPendingProposals,
  enqueuePendingProposals,
  rejectPendingProposal,
} from './connection_actions.js';
import { mountEmptyState, showLoadingRow, showError, ZOTERO_SETUP_MSG } from './ui/feedback.js';
import { isZoteroCatalogReady } from './setupStatus.js';
import { isProjectsUiEnabled, isProjectsContextLayerEnabled } from './projects/featureFlag.js';
import { setActiveProjectFromId } from './projects/activeChip.js';

export { openGraphMergeReview };

const API_BASE = window.API_BASE || '';
const esc = uiModule.esc;

const TYPE_LABELS = {
  task: 'Task',
  document: 'Document',
  memory: 'Memory',
  skill: 'Skill',
  paper: 'Paper',
  collection: 'Collection',
  research: 'Research',
  project: 'Project',
  note: 'Document', // legacy index rows
};

const MANUAL_EDGE_KINDS = new Set([
  'derives_from', 'refutes', 'supports', 'relates', 'depends_on', 'link', 'related',
]);
const LINK_KIND_OPTIONS = [
  'relates', 'derives_from', 'refutes', 'supports', 'depends_on',
];
const EDGE_KIND_LABELS = {
  derives_from: 'Derives from',
  refutes: 'Refutes',
  supports: 'Supports',
  relates: 'Relates',
  depends_on: 'Depends on',
  link: 'Link',
  related: 'Related',
  parent: 'Parent',
  wikilink: 'Wikilink',
  in_collection: 'Collection',
  summarizes: 'Summarizes',
};

function _edgeKindLabel(kind) {
  const k = (kind || 'relates').toLowerCase();
  return EDGE_KIND_LABELS[k] || k.replace(/_/g, ' ');
}

let _open = false;
let _activeType = '';
let _selectedId = null;
let _selectedNodeMeta = null;
let _searchTimer = null;
let _linkSearchTimer = null;
let _graphView = null;

function _effectiveType(node) {
  const t = node?.type || '';
  if (t === 'note') return 'document';
  return t;
}

function _typeBadge(node) {
  const type = _effectiveType(node);
  return `<span class="kg-type kg-type-${esc(type || 'document')}">${esc(TYPE_LABELS[type] || type || '?')}</span>`;
}

function _nodeTitle(node) {
  return node?.title || node?.id || 'Untitled';
}

/** Body snippets belong in Open — not the compact Links list/preview panes. */
function _compactSnippet(node) {
  const type = node?.type === 'note' ? 'document' : (node?.type || '');
  if (type === 'document') return '';
  const snip = (node?.snippet || '').trim();
  if (!snip) return '';
  const limit = (type === 'paper' || type === 'research') ? 200 : 100;
  return snip.slice(0, limit);
}

const _RESEARCH_REASON_MARKERS = [
  /from research report/i,
  /deep research/i,
  /compare-mode research/i,
  /compared in deep research/i,
  /gap-analysis source/i,
  /^research «/i,
  /linked from deep research/i,
];

function _isResearchSourcedEdge(edge) {
  const src = (edge?.source || '').trim();
  if (src === 'research_auto' || src === 'research') return true;
  const reason = (edge?.reason || '').trim();
  return reason && _RESEARCH_REASON_MARKERS.some((re) => re.test(reason));
}

/** Compact link reason for the small preview pane — research rows become a chip. */
function _compactLinkReason(edge) {
  const reason = (edge?.reason || '').trim();
  if (!reason) return null;
  if (_isResearchSourcedEdge(edge)) {
    return { text: 'Research', chip: true, title: reason };
  }
  const short = reason.length > 56 ? `${reason.slice(0, 55)}…` : reason;
  return { text: short, chip: false, title: reason.length > 56 ? reason : '' };
}

function _nodeMeta(node) {
  const meta = node?.meta || {};
  if (meta.source === 'vault' && meta.path) {
    return meta.path;
  }
  if (node?.type === 'paper') {
    const bits = [];
    if (meta.authors) bits.push(meta.authors);
    if (meta.year) bits.push(meta.year);
    if (meta.collection_paths?.length) bits.push(meta.collection_paths.slice(0, 2).join(', '));
    return bits.join(' · ');
  }
  if (node?.type === 'collection' && meta.path) {
    return meta.path;
  }
  return '';
}

async function _fetchGraph(type) {
  const params = new URLSearchParams({ limit: '250' });
  if (type) params.set('type', type);
  const res = await fetch(`${API_BASE}/api/knowledge/graph?${params}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Failed to load graph');
  return res.json();
}

async function _fetchSearch(q, type) {
  const params = new URLSearchParams({ q: q || '', limit: '40', expand_hops: '1' });
  if (type) params.set('types', type);
  const res = await fetch(`${API_BASE}/api/knowledge/search?${params}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Search failed');
  return res.json();
}

async function _fetchNeighbors(nodeId) {
  const params = new URLSearchParams({ id: nodeId || '' });
  const res = await fetch(
    `${API_BASE}/api/knowledge/neighbors?${params}`,
    { credentials: 'same-origin' },
  );
  if (!res.ok) throw new Error('Failed to load links');
  return res.json();
}

function _isManualEdgeKind(kind) {
  return MANUAL_EDGE_KINDS.has((kind || 'link').toLowerCase());
}

function _editorDocumentId(node) {
  const meta = node?.meta || {};
  if (meta.source === 'editor' && meta.document_id) return meta.document_id;
  const id = node?.id || '';
  if (!id.startsWith('document:')) return null;
  const raw = id.slice('document:'.length);
  if (raw.startsWith('vault:')) return null;
  if (/^[0-9a-f-]{36}$/i.test(raw)) return raw;
  return null;
}

export async function createGraphLink(fromId, toId, kind = 'relates', reason = '') {
  const payload = { from_id: fromId, to_id: toId, kind: kind || 'relates' };
  const reasonText = (reason || '').trim();
  if (reasonText) payload.reason = reasonText.slice(0, 280);
  const res = await fetch(`${API_BASE}/api/knowledge/links`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Link failed');
  window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
  return data;
}

async function _enqueuePendingProposals(proposals, source = 'agent', opts = {}) {
  return enqueuePendingProposals(proposals, source, opts);
}

async function _rejectPendingProposal(proposal) {
  return rejectPendingProposal(proposal);
}

async function _acceptPendingProposals(proposals) {
  return acceptPendingProposals(proposals);
}

export async function removeGraphLink(fromId, toId, kind) {
  const params = new URLSearchParams({ from_id: fromId, to_id: toId });
  if (kind) params.set('kind', kind);
  const res = await fetch(`${API_BASE}/api/knowledge/links?${params}`, {
    method: 'DELETE',
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Remove link failed');
  return data;
}

function _renderAddLinkPicker(fromId, linkedIds) {
  const kindOpts = LINK_KIND_OPTIONS.map(
    (k) => `<option value="${esc(k)}">${esc(_edgeKindLabel(k))}</option>`,
  ).join('');
  return `<div class="kg-add-link" data-from-id="${esc(fromId)}">
    <div class="kg-add-link-head">
      <input type="search" class="settings-input kg-add-link-search" placeholder="Search to link…" autocomplete="off">
      <select class="kg-add-link-kind">${kindOpts}</select>
    </div>
    <input type="text" class="settings-input kg-add-link-reason" placeholder="Why linked? (recommended)" maxlength="280" autocomplete="off">
    <div class="kg-add-link-results" data-linked="${esc([...linkedIds].join(','))}"></div>
  </div>`;
}

function _renderNodeRow(node, { active = false } = {}) {
  const id = node.id || '';
  const snip = _compactSnippet(node);
  const meta = _nodeMeta(node);
  return `<button type="button" class="kg-node-row${active ? ' active' : ''}" data-node-id="${esc(id)}">
    <div class="kg-node-head">
      ${_typeBadge(node)}
      <span class="kg-node-title">${esc(_nodeTitle(node))}</span>
    </div>
    ${meta ? `<span class="kg-node-meta">${esc(meta)}</span>` : ''}
    ${snip ? `<span class="kg-node-snippet">${esc(snip)}</span>` : ''}
  </button>`;
}

function _renderLinkSection(title, rows, { nodeId, direction = 'out' } = {}) {
  if (!rows?.length) {
    return `<div class="kg-link-section"><div class="kg-link-heading">${esc(title)}</div><div class="kg-link-empty">None</div></div>`;
  }
  const items = rows.map((row) => {
    const n = row.node;
    if (!n) return '';
    const kind = (row.edge && row.edge.kind) || 'relates';
    const reasonInfo = _compactLinkReason(row.edge || {});
    const kindLabel = _edgeKindLabel(kind);
    const removable = _isManualEdgeKind(kind);
    let removeBtn = '';
    if (removable && nodeId) {
      const from = direction === 'out' ? nodeId : n.id;
      const to = direction === 'out' ? n.id : nodeId;
      removeBtn = `<button type="button" class="kg-link-remove" data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}" title="Remove link" aria-label="Remove link">×</button>`;
    }
    return `<div class="kg-link-row-wrap">
      <button type="button" class="kg-link-row" data-node-id="${esc(n.id)}">
        <span class="kg-link-kind" title="${esc(kind)}">${esc(kindLabel)}</span>
        ${_typeBadge(n)}
        <span class="kg-node-title">${esc(_nodeTitle(n))}</span>
        ${reasonInfo?.chip ? `<span class="kg-link-source-chip" title="${esc(reasonInfo.title)}">${esc(reasonInfo.text)}</span>` : ''}
      </button>
      ${reasonInfo && !reasonInfo.chip ? `<div class="kg-link-reason"${reasonInfo.title ? ` title="${esc(reasonInfo.title)}"` : ''}>${esc(reasonInfo.text)}</div>` : ''}
      ${removeBtn}
    </div>`;
  }).join('');
  return `<div class="kg-link-section"><div class="kg-link-heading">${esc(title)}</div>${items}</div>`;
}

async function _wireAddLinkPicker(container, fromId, onLinked) {
  if (!container || container.dataset.kgPickerWired === '1') return;
  container.dataset.kgPickerWired = '1';
  const input = container.querySelector('.kg-add-link-search');
  const kindSel = container.querySelector('.kg-add-link-kind');
  const results = container.querySelector('.kg-add-link-results');
  if (!input || !results) return;

  const linkedSet = () => new Set(
    (results.dataset.linked || '').split(',').filter(Boolean),
  );

  const renderHits = (nodes) => {
    const linked = linkedSet();
    const hits = (nodes || []).filter((n) => n?.id && n.id !== fromId && !linked.has(n.id));
    if (!hits.length) {
      results.innerHTML = `<div class="kg-add-link-empty">${input.value.trim() ? 'No matches' : 'Type to search'}</div>`;
      return;
    }
    results.innerHTML = hits.map((n) => `<button type="button" class="kg-add-link-hit" data-node-id="${esc(n.id)}">
      ${_typeBadge(n)}<span class="kg-node-title">${esc(_nodeTitle(n))}</span>
    </button>`).join('');
  };

  input.addEventListener('input', () => {
    clearTimeout(_linkSearchTimer);
    _linkSearchTimer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) {
        results.innerHTML = '<div class="kg-add-link-empty">Type to search</div>';
        return;
      }
      try {
        const data = await _fetchSearch(q, '');
        const nodes = [...(data.hits || []), ...(data.neighbors || [])];
        renderHits(nodes);
      } catch (e) {
        results.innerHTML = `<div class="kg-add-link-empty">${esc(e.message || 'Search failed')}</div>`;
      }
    }, 220);
  });

  container.addEventListener('click', async (ev) => {
    const hit = ev.target.closest('.kg-add-link-hit');
    if (!hit?.dataset.nodeId) return;
    const toId = hit.dataset.nodeId;
    const kind = kindSel?.value || 'relates';
    const reasonInput = container.querySelector('.kg-add-link-reason');
    const reason = reasonInput?.value?.trim() || '';
    hit.disabled = true;
    try {
      await createGraphLink(fromId, toId, kind, reason);
      linkedSet().add(toId);
      results.dataset.linked = [...linkedSet(), toId].join(',');
      uiModule.showToast?.('Link added');
      input.value = '';
      if (reasonInput) reasonInput.value = '';
      results.innerHTML = '<div class="kg-add-link-empty">Type to search</div>';
      if (onLinked) await onLinked();
    } catch (e) {
      uiModule.showToast?.(e.message || 'Link failed', 4000);
    } finally {
      hit.disabled = false;
    }
  });
}

/** Mount graph link picker in Todos links tab or other containers. */
export async function mountGraphLinkPicker(container, fromNodeId, { onUpdate } = {}) {
  if (!container || !fromNodeId) return;
  let nb;
  try {
    nb = await _fetchNeighbors(fromNodeId);
  } catch {
    container.innerHTML = '<div class="kg-add-link-empty">Rebuild links to enable graph connections.</div>';
    return;
  }
  const linked = new Set();
  for (const row of [...(nb.outgoing || []), ...(nb.incoming || [])]) {
    if (row?.node?.id) linked.add(row.node.id);
  }
  container.innerHTML = `
    <div class="kg-task-links-block">
      <div class="kg-link-heading">Related in graph</div>
      ${_renderAddLinkPicker(fromNodeId, linked)}
    </div>`;
  await _wireAddLinkPicker(container.querySelector('.kg-add-link'), fromNodeId, onUpdate);
}

async function _showDetail(nodeId) {
  _selectedId = nodeId;
  try { localStorage.setItem('nobody-links-selected', nodeId); } catch { /* ignore */ }
  _graphView?.setSelected(nodeId);
  const detail = document.getElementById('kg-detail');
  if (!detail) return;
  detail.innerHTML = '';
  showLoadingRow(detail, 'Loading links…');
  document.querySelectorAll('.kg-node-row').forEach((el) => {
    el.classList.toggle('active', el.dataset.nodeId === nodeId);
  });
  try {
    const nb = await _fetchNeighbors(nodeId);
    const node = nb.node || {};
    _selectedNodeMeta = node.meta || null;
    const meta = node.meta || {};
    let metaHtml = '';
    if (node.type === 'task' && meta.horizon_label) {
      metaHtml = `<div class="kg-meta">${esc(meta.horizon_label)}${meta.due_date ? ' · due ' + esc(meta.due_date) : ''}</div>`;
    } else if (meta.source === 'editor' && meta.document_id) {
      metaHtml = `<div class="kg-meta">Library document</div>`;
    } else if (meta.source === 'vault' && meta.path) {
      metaHtml = `<div class="kg-meta">${esc(meta.path)}</div>`;
    } else if (node.type === 'paper') {
      const bits = [];
      if (meta.authors) bits.push(meta.authors);
      if (meta.year) bits.push(`(${meta.year})`);
      if (meta.doi) bits.push(meta.doi);
      if (meta.collection_paths?.length) {
        bits.push(`in ${meta.collection_paths.slice(0, 2).join(', ')}`);
      }
      if (bits.length) metaHtml = `<div class="kg-meta">${esc(bits.join(' · '))}</div>`;
      if (meta.has_pdf) {
        metaHtml += '<div class="kg-meta">PDF attached — read via search_knowledge on this paper id extracts full text</div>';
      }
    } else if (node.type === 'research') {
      const bits = [];
      if (meta.research_mode_label) bits.push(meta.research_mode_label);
      else if (meta.research_mode) bits.push(meta.research_mode.replace(/_/g, ' '));
      const br = meta.source_breakdown || {};
      if (br.total) bits.push(`${br.total} sources`);
      if (meta.seed_count) bits.push(`${meta.seed_count} seed(s)`);
      if (bits.length) metaHtml = `<div class="kg-meta">${esc(bits.join(' · '))}</div>`;
    } else if (node.type === 'collection') {
      metaHtml = `<div class="kg-meta">Zotero folder${meta.path ? ` · ${esc(meta.path)}` : ''}</div>`;
    } else if (node.type === 'project') {
      const bits = [];
      if (meta.working_dir) bits.push(`cwd: ${meta.working_dir}`);
      if (meta.working_dir_status && meta.working_dir_status !== 'ok') {
        bits.push(`status: ${meta.working_dir_status}`);
      }
      if (bits.length) metaHtml = `<div class="kg-meta">${esc(bits.join(' · '))}</div>`;
      if (meta.description) {
        metaHtml += `<div class="kg-meta">${esc(meta.description.slice(0, 200))}</div>`;
      }
    }
    const linked = new Set();
    for (const row of [...(nb.outgoing || []), ...(nb.incoming || [])]) {
      if (row?.node?.id) linked.add(row.node.id);
    }
    const paperSeedBtn = node.type === 'paper'
      ? `<button type="button" class="admin-btn-sm kg-seed-btn" data-node-id="${esc(nodeId)}">Use as research seed</button>`
      : '';
    const researchOpenBtn = node.type === 'research'
      ? `<button type="button" class="admin-btn-sm kg-research-report-btn" data-session-id="${esc(meta.session_id || nodeId.replace(/^research:/i, ''))}">Open report</button>`
      : '';
    const projectOpenBtn = (node.type === 'project' && (isProjectsUiEnabled() || isProjectsContextLayerEnabled()))
      ? `<button type="button" class="admin-btn-sm kg-project-workspace-btn" data-project-id="${esc(meta.project_id || nodeId.replace(/^project:/i, ''))}">${isProjectsContextLayerEnabled() && !isProjectsUiEnabled() ? 'Set active' : 'Open workspace'}</button>`
      : '';
    const snippet = _compactSnippet(node);
    detail.innerHTML = `
      <div class="kg-detail-head">
        ${_typeBadge(node)}
        <h3 class="kg-detail-title">${esc(_nodeTitle(node))}</h3>
        ${metaHtml}
        <div class="kg-detail-actions">
          <button type="button" class="admin-btn-sm kg-open-btn" data-node-id="${esc(nodeId)}">Open</button>
          ${paperSeedBtn}
          ${researchOpenBtn}
          ${projectOpenBtn}
        </div>
      </div>
      ${snippet ? `<div class="kg-detail-snippet">${esc(snippet)}</div>` : ''}
      <div class="kg-add-link-block">
        <div class="kg-link-heading">Add link</div>
        ${_renderAddLinkPicker(nodeId, linked)}
      </div>
      ${_renderLinkSection('Links to', nb.outgoing, { nodeId, direction: 'out' })}
      ${_renderLinkSection('Linked from', nb.incoming, { nodeId, direction: 'in' })}
    `;
    await _wireAddLinkPicker(detail.querySelector('.kg-add-link'), nodeId, () => _showDetail(nodeId));
    detail.querySelector('.kg-seed-btn')?.addEventListener('click', () => {
      void _usePaperAsResearchSeed(nodeId, node);
    });
    detail.querySelector('.kg-research-report-btn')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const sid = ev.currentTarget?.dataset?.sessionId || nodeId.replace(/^research:/i, '');
      if (sid) window.open(`${API_BASE}/api/research/report/${encodeURIComponent(sid)}`, '_blank', 'noopener,noreferrer');
    });
    detail.querySelector('.kg-project-workspace-btn')?.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const pid = ev.currentTarget?.dataset?.projectId || nodeId.replace(/^project:/i, '');
      if (!pid) return;
      if (isProjectsContextLayerEnabled() && !isProjectsUiEnabled()) {
        await setActiveProjectFromId(pid);
        return;
      }
      const mod = await import('./projects/index.js');
      const open = mod.openProjectWorkspace || mod.default?.openProjectWorkspace;
      if (open) open(pid);
    });
  } catch (e) {
    showError(detail, { message: e.message || String(e), retry: () => _showDetail(nodeId) });
  }
}

async function _usePaperAsResearchSeed(nodeId, node) {
  const meta = node?.meta || {};
  const [, rawKey] = nodeId.includes(':') ? nodeId.split(':', 2) : ['paper', nodeId];
  const zoteroKey = (meta.zotero_key || rawKey || '').trim();
  const doi = (meta.doi || '').trim();
  if (!zoteroKey && !doi) {
    uiModule.showToast?.('No Zotero key or DOI for this paper', 3500);
    return;
  }
  try {
    const mod = await import('./research/panel.js');
    const addSeed = mod.addSeedPaper;
    if (!addSeed) {
      uiModule.showToast?.('Research panel unavailable', 3000);
      return;
    }
    const added = addSeed({
      zotero_key: zoteroKey,
      title: _nodeTitle(node),
      authors: meta.authors || '',
      year: meta.year || '',
      doi,
      has_pdf: !!meta.has_pdf,
    });
    uiModule.showToast?.(
      added ? 'Added as research seed' : 'Already in seed list — opened research panel',
      3500,
    );
  } catch (e) {
    uiModule.showToast?.(e.message || 'Could not add research seed', 4000);
  }
}

async function _renderList({ query = '', type = _activeType } = {}) {
  const list = document.getElementById('kg-node-list');
  const stats = document.getElementById('kg-stats');
  if (!list) return;
  showLoadingRow(list, 'Loading…');
  try {
    let nodes = [];
    let edgeCount = 0;
    if (query.trim()) {
      const data = await _fetchSearch(query.trim(), type);
      nodes = [...(data.hits || []), ...(data.neighbors || [])];
      edgeCount = data.total_nodes || 0;
    } else {
      const data = await _fetchGraph(type || null);
      nodes = data.nodes || [];
      edgeCount = data.edge_count || 0;
    }
    const seen = new Set();
    nodes = nodes.filter((n) => {
      if (!n?.id || seen.has(n.id)) return false;
      seen.add(n.id);
      return true;
    });
    if (stats) {
      stats.textContent = `${nodes.length} shown · ${edgeCount} links indexed`;
    }
    if (!nodes.length) {
      const detail = document.getElementById('kg-detail');
      if (detail) detail.innerHTML = '';
      if (query.trim()) {
        mountEmptyState(list, { kind: 'empty', message: 'No matches.' });
        return;
      }
      if (_activeType === 'paper') {
        const ready = await isZoteroCatalogReady();
        if (!ready) {
          mountEmptyState(list, {
            kind: 'setup',
            title: 'Setup needed',
            message: ZOTERO_SETUP_MSG,
            actionLabel: 'Fix',
            actionTab: 'search',
          });
          return;
        }
        mountEmptyState(list, { kind: 'empty', message: 'No papers in catalog yet.' });
        return;
      }
      mountEmptyState(list, {
        kind: 'empty',
        message: 'No links yet — add todos, documents, or memories, then Rebuild.',
      });
      return;
    }
    list.innerHTML = nodes.map((n) => _renderNodeRow(n, { active: n.id === _selectedId })).join('');
    list.querySelectorAll('.kg-node-row').forEach((btn) => {
      btn.addEventListener('click', () => _selectFromList(btn.dataset.nodeId));
    });
    if (_selectedId && nodes.some((n) => n.id === _selectedId)) {
      await _showDetail(_selectedId);
    } else if (nodes[0]) {
      await _showDetail(nodes[0].id);
    }
  } catch (e) {
    showError(list, { message: e.message || String(e), retry: () => _renderList({ query, type }) });
  }
}

// Clicking a row in the list should behave exactly like clicking the node in
// the graph: preview it *and* light up its ripple trace (auto-select on open
// deliberately does not, to keep the graph neutral at rest).
function _selectFromList(nodeId) {
  if (!nodeId) return;
  _graphView?.focusNode(nodeId, { center: true });
  void _showDetail(nodeId);
}

async function _ensureGraphView() {
  if (_graphView) return _graphView;
  const host = document.getElementById('kg-graph');
  if (!host) return null;
  const mod = await import('./knowledgeGraphView.js');
  _graphView = new mod.KnowledgeGraphView(host, {
    onSelect: (id) => { void _showDetail(id); },
    onOpen: (id) => { void openKnowledgeNode(id, { navigate: true }); },
    onAddLink: (id) => { void _focusAddLink(id); },
    onRemoveLink: async (fromId, toId, kind) => {
      try {
        await removeGraphLink(fromId, toId, kind);
        uiModule.showToast?.('Link removed');
        window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
      } catch (e) {
        uiModule.showToast?.(e.message || 'Remove failed', 4000);
      }
    },
    onRebuild: () => { document.getElementById('kg-rebuild-btn')?.click(); },
  });
  return _graphView;
}

// Open a node's detail and drop focus into its "add link" search box (used by
// the graph's right-click → "Add link from here").
async function _focusAddLink(nodeId) {
  await _showDetail(nodeId);
  const input = document.querySelector('#kg-detail .kg-add-link-search');
  if (input) {
    input.focus();
    input.scrollIntoView({ block: 'nearest' });
  }
}

const _FILTER_LABELS = {
  '': 'All', task: 'Tasks', document: 'Documents', paper: 'Papers',
  research: 'Research', project: 'Projects', memory: 'Memories', skill: 'Skills',
};

function _updateFilterCounts(data) {
  const counts = data?.type_counts || null;
  const total = data?.node_count;
  document.querySelectorAll('.kg-type-filter').forEach((btn) => {
    const type = btn.dataset.type || '';
    const base = _FILTER_LABELS[type] || type;
    let n;
    if (!type) n = total;
    else if (counts) n = (counts[type] || 0) + (type === 'document' ? (counts.note || 0) : 0);
    btn.textContent = (n != null) ? `${base} ${n}` : base;
  });
}

// The graph always shows the full cross-type graph — the type filters and
// search box are controls for the node list on the right. Search additionally
// highlights matching graph nodes (see the search handler), but filtering by
// type would strip out the cross-type edges that make the graph worth showing.
async function _renderGraph() {
  const view = await _ensureGraphView();
  if (!view) return;
  view.setActive(true);
  try {
    const data = await _fetchGraph(null);
    const nodes = data.nodes || [];
    const edges = data.edges_sample || [];
    view.setData(nodes, edges);
    view.setQuery(document.getElementById('kg-search-input')?.value || '');
    if (_selectedId) view.setSelected(_selectedId);
    _updateFilterCounts(data);
  } catch {
    // The graph is a secondary surface; the list pane owns error/stat display.
  }
}

// Render both surfaces (list on the right, graph on the left). Used on open,
// rebuild, and graph-refresh events.
async function _renderAll() {
  const q = document.getElementById('kg-search-input')?.value || '';
  await _renderList({ query: q, type: _activeType });
  await _renderGraph();
}

async function _openDocumentNode(nodeId, nodeMeta) {
  const meta = nodeMeta || _selectedNodeMeta || {};
  const docId = _editorDocumentId({ id: nodeId, meta });
  if (docId) {
    const mod = await import('./document.js');
    const open = mod.loadDocument || mod.default?.loadDocument;
    if (open) open(docId);
    return;
  }
  const [, raw] = nodeId.includes(':') ? nodeId.split(':', 2) : ['document', nodeId];
  if (nodeId.startsWith('document:') && !raw.startsWith('vault:')
    && /^[0-9a-f-]{36}$/i.test(raw)) {
    const mod = await import('./document.js');
    const open = mod.loadDocument || mod.default?.loadDocument;
    if (open) open(raw);
    return;
  }
  try {
    const params = new URLSearchParams({ id: nodeId || '' });
    const res = await fetch(
      `${API_BASE}/api/knowledge/content?${params}`,
      { credentials: 'same-origin' },
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not load document');
    const editorId = data.meta?.document_id || _editorDocumentId({ id: nodeId, meta: data.meta });
    if (editorId) {
      const mod = await import('./document.js');
      const open = mod.loadDocument || mod.default?.loadDocument;
      if (open) open(editorId);
      return;
    }
    const sessionId = sessionModule?.getCurrentSessionId() || '';
    const title = data.title || data.meta?.path || 'Document';
    const createRes = await fetch(`${API_BASE}/api/document`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        session_id: sessionId,
        title,
        language: data.meta?.language || 'markdown',
        content: data.body || '',
      }),
    });
    const doc = await createRes.json();
    const mod = await import('./document.js');
    if (mod.injectFreshDoc) mod.injectFreshDoc(doc);
    else if (mod.loadDocument) mod.loadDocument(doc.id);
  } catch (e) {
    uiModule.showError?.(e.message || 'Could not open document');
  }
}

const _linkSuggestionQueue = [];
const _dismissedLinkSuggestions = new Set();
let _linkSuggestionShowing = false;
// The batch connection card currently on screen (if any). Tracked so callers
// (e.g. the research "Review graph connections" button) can toggle it closed.
let _currentBatchCard = null;

function _linkSuggestHost() {
  let host = document.getElementById('kg-link-suggest-host');
  if (!host) {
    host = document.createElement('div');
    host.id = 'kg-link-suggest-host';
    host.className = 'kg-link-suggest-host';
    host.setAttribute('aria-live', 'polite');
    document.body.appendChild(host);
  }
  return host;
}

function _linkSuggestNode(type, title) {
  const t = _effectiveType({ type: type || 'document' });
  return `<div class="kg-link-suggest-node">
    <span class="kg-type kg-type-${esc(t || 'document')}">${esc(TYPE_LABELS[t] || t || '?')}</span>
    <span class="kg-link-suggest-title">${esc(title || 'Untitled')}</span>
  </div>`;
}

function _dismissLinkSuggestionCard(card, onDone) {
  if (!card || card.dataset.kgDismissed === '1') return;
  card.dataset.kgDismissed = '1';
  card.classList.remove('kg-link-suggest-in');
  card.classList.add('kg-link-suggest-out');
  window.setTimeout(() => {
    card.remove();
    if (onDone) onDone();
  }, 260);
}

function _finishLinkSuggestionPrompt() {
  _linkSuggestionShowing = false;
  _showNextLinkSuggestion();
}

function _showNextLinkSuggestion() {
  if (_linkSuggestionShowing) return;
  const data = _linkSuggestionQueue.shift();
  if (!data) return;
  if (data._batch || ((!data.from || !data.to) && (data.rows?.length || data.proposals?.length))) {
    _showConnectionBatchCard(data);
    return;
  }
  if (!data?.from || !data?.to) {
    _showNextLinkSuggestion();
    return;
  }
  _linkSuggestionShowing = true;

  const fromTitle = data.from_title || data.from;
  const toTitle = data.to_title || data.to;
  const kind = data.kind || 'related';
  const reason = (data.reason || '').trim();

  const card = document.createElement('div');
  card.className = 'kg-link-suggest-card';
  card.innerHTML = `
    <div class="kg-link-suggest-accent" aria-hidden="true"></div>
    <div class="kg-link-suggest-inner">
      <div class="kg-link-suggest-head">
        <span class="kg-link-suggest-icon" aria-hidden="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
        </span>
        <div class="kg-link-suggest-copy">
          <div class="kg-link-suggest-eyebrow">${esc(data.eyebrow || 'Learned connection')}</div>
          <div class="kg-link-suggest-sub">${esc(data.subtitle || 'Add this connection to Links?')}</div>
        </div>
        <button type="button" class="kg-link-suggest-close" aria-label="Close">×</button>
      </div>
      <div class="kg-link-suggest-flow">
        ${_linkSuggestNode(data.from_type, fromTitle)}
        <span class="kg-link-suggest-arrow" aria-hidden="true">→</span>
        ${_linkSuggestNode(data.to_type, toTitle)}
      </div>
      ${reason ? `<p class="kg-link-suggest-reason">${esc(reason)}</p>` : ''}
      <div class="kg-link-suggest-foot">
        <span class="kg-link-kind kg-link-suggest-kind">${esc(_edgeKindLabel(kind))}</span>
        <div class="kg-link-suggest-actions kg-link-suggest-actions--triple">
          <button type="button" class="kg-link-suggest-reject">Reject</button>
          <button type="button" class="kg-link-suggest-later">Review later</button>
          <button type="button" class="kg-link-suggest-accept">Accept</button>
        </div>
      </div>
    </div>`;

  const host = _linkSuggestHost();
  host.appendChild(card);
  requestAnimationFrame(() => card.classList.add('kg-link-suggest-in'));

  const dismiss = () => {
    if (data.suggestion_id) _dismissedLinkSuggestions.add(data.suggestion_id);
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
  };

  const proposalPayload = {
    from: data.from,
    to: data.to,
    kind,
    reason: data.reason || reason,
    from_title: fromTitle,
    to_title: toTitle,
    source: data.source || 'suggest_link',
    suggestion_id: data.suggestion_id,
    project_id: data.project_id,
  };

  card.querySelector('.kg-link-suggest-close')?.addEventListener('click', dismiss);

  card.querySelector('.kg-link-suggest-reject')?.addEventListener('click', () => {
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
    void _rejectPendingProposal(proposalPayload).catch((e) => {
      uiModule.showToast?.(e.message || 'Reject failed', 4000);
    });
  });

  card.querySelector('.kg-link-suggest-later')?.addEventListener('click', () => {
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
    void _enqueuePendingProposals([proposalPayload], proposalPayload.source, {
      project_id: data.project_id,
    }).then((out) => {
      uiModule.showToast?.(
        out.added
          ? 'Saved to Connections'
          : 'Already queued or linked',
        2800,
      );
    }).catch((e) => uiModule.showToast?.(e.message || 'Save failed', 4000));
  });

  card.querySelector('.kg-link-suggest-accept')?.addEventListener('click', (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    card.classList.add('kg-link-suggest-saving');
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
    uiModule.showToast?.('Added to Links', { duration: 1100, leadingIcon: 'check' });
    void createGraphLink(data.from, data.to, kind, data.reason || reason).catch((e) => {
      uiModule.showToast?.(e.message || 'Link failed', 4000);
    });
  });
}

function _normalizeProposalRows(data) {
  const projectId = data.project_id || null;
  if (data.rows?.length) {
    return data.rows.map((row) => ({
      from: row.from,
      to: row.to,
      kind: row.kind || 'relates',
      reason: row.reason || '',
      from_title: row.from_title,
      to_title: row.to_title,
      id: row.proposal_id || row.id,
      project_id: row.project_id || projectId,
    }));
  }
  return (data.proposals || []).map((row) => ({
    ...row,
    project_id: row.project_id || projectId,
  }));
}

function _showConnectionBatchCard(data) {
  if (_linkSuggestionShowing) {
    // Avoid stacking duplicate cards for the same research session when the
    // toggle button is clicked repeatedly while another card is on screen.
    const sid = data.research_session_id;
    const dup = sid && _linkSuggestionQueue.some(
      (q) => q._batch && q.research_session_id === sid,
    );
    if (!dup) _linkSuggestionQueue.push({ _batch: true, ...data });
    return;
  }
  const proposals = _normalizeProposalRows(data);
  if (!proposals.length) return;
  _linkSuggestionShowing = true;

  const source = data.source || 'compare_papers';
  const subCopy = source === 'research'
    ? 'From this research — accept to add to Links, or review later in Connections.'
    : source === 'library_compare'
      ? 'From library compare — accept to add to Links, or review later in Connections.'
      : 'From this comparison — accept to add to Links, or review later in Connections.';
  const preview = proposals.slice(0, 3).map((p) => {
    const a = p.from_title || p.from;
    const b = p.to_title || p.to;
    return `<li>${esc(a)} → ${esc(b)} <span class="kg-link-kind">${esc(_edgeKindLabel(p.kind))}</span></li>`;
  }).join('');
  const more = proposals.length > 3 ? `<li class="kg-link-suggest-more">+ ${proposals.length - 3} more</li>` : '';

  const anchorEl = (data.anchorEl instanceof Element && data.anchorEl.isConnected)
    ? data.anchorEl : null;
  const card = document.createElement('div');
  card.className = 'kg-link-suggest-card kg-link-suggest-card--batch'
    + (anchorEl ? ' kg-link-suggest-card--anchored' : '');
  card.innerHTML = `
    <div class="kg-link-suggest-accent" aria-hidden="true"></div>
    <div class="kg-link-suggest-inner">
      <div class="kg-link-suggest-head">
        <span class="kg-link-suggest-icon" aria-hidden="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="5" cy="12" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="19" cy="18" r="2"/>
            <line x1="7" y1="12" x2="17" y2="7"/><line x1="7" y1="12" x2="17" y2="17"/>
          </svg>
        </span>
        <div class="kg-link-suggest-copy">
          <div class="kg-link-suggest-eyebrow">${proposals.length} learned connection${proposals.length === 1 ? '' : 's'}</div>
          <div class="kg-link-suggest-sub">${subCopy}</div>
        </div>
        <button type="button" class="kg-link-suggest-close" aria-label="Close">×</button>
      </div>
      <ul class="kg-link-suggest-batch-list">${preview}${more}</ul>
      <div class="kg-link-suggest-foot">
        <div class="kg-link-suggest-actions kg-link-suggest-actions--triple">
          <button type="button" class="kg-link-suggest-reject">Reject all</button>
          <button type="button" class="kg-link-suggest-later">Review later</button>
          <button type="button" class="kg-link-suggest-accept">Accept all</button>
        </div>
      </div>
    </div>`;

  if (data.research_session_id != null) {
    card.dataset.researchSession = String(data.research_session_id);
  }
  _currentBatchCard = card;

  const host = _linkSuggestHost();
  host.appendChild(card);
  if (anchorEl) _positionAnchoredCard(card, anchorEl);
  requestAnimationFrame(() => card.classList.add('kg-link-suggest-in'));

  const finish = () => {
    if (_currentBatchCard === card) _currentBatchCard = null;
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
  };

  card.querySelector('.kg-link-suggest-close')?.addEventListener('click', finish);

  card.querySelector('.kg-link-suggest-reject')?.addEventListener('click', () => {
    finish();
    void Promise.all(proposals.map((p) => _rejectPendingProposal(p))).then(() => {
      data.onResolved?.();
      uiModule.showToast?.('Connections dismissed', 2200);
    }).catch((e) => uiModule.showToast?.(e.message || 'Reject failed', 4000));
  });

  card.querySelector('.kg-link-suggest-later')?.addEventListener('click', () => {
    finish();
    if (data.alreadyEnqueued) {
      uiModule.showToast?.(
        `${proposals.length} saved to Connections`,
        3000,
      );
      return;
    }
    void _enqueuePendingProposals(proposals, source, {
      project_id: data.project_id,
    }).then((out) => {
      uiModule.showToast?.(
        out.added
          ? `${out.added} saved to Connections`
          : 'Nothing new to queue',
        3000,
      );
    }).catch((e) => uiModule.showToast?.(e.message || 'Save failed', 4000));
  });

  card.querySelector('.kg-link-suggest-accept')?.addEventListener('click', () => {
    finish();
    void _acceptPendingProposals(proposals).then((out) => {
      data.onResolved?.();
      const added = (out.applied || 0) + (out.updated || 0);
      uiModule.showToast?.(
        `Added ${added} link${added === 1 ? '' : 's'} to Links`,
        2800,
      );
    }).catch((e) => uiModule.showToast?.(e.message || 'Accept failed', 4000));
  });
}

/** Anchor a batch card as a popover emanating from its trigger button. */
function _positionAnchoredCard(card, anchorEl) {
  try {
    const r = anchorEl.getBoundingClientRect();
    const margin = 12;
    const cardW = Math.min(392, window.innerWidth - margin * 2);
    card.style.width = `${cardW}px`;

    let left = r.left + r.width / 2 - cardW / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - cardW - margin));
    card.style.left = `${left}px`;
    card.style.right = 'auto';

    // Arrow + transform-origin track the button's horizontal centre.
    const centreX = Math.max(18, Math.min(r.left + r.width / 2 - left, cardW - 18));
    card.style.setProperty('--kg-anchor-x', `${centreX}px`);

    const spaceBelow = window.innerHeight - r.bottom;
    if (spaceBelow >= 260 || spaceBelow >= r.top) {
      card.classList.add('kg-anchor-below');
      card.style.top = `${Math.round(r.bottom + 10)}px`;
      card.style.bottom = 'auto';
    } else {
      card.classList.add('kg-anchor-above');
      card.style.bottom = `${Math.round(window.innerHeight - r.top + 10)}px`;
      card.style.top = 'auto';
    }
  } catch { /* fall back to default host placement */ }
}

/** True when a batch connection card is on screen (optionally for a session). */
export function isConnectionBatchOpen(sessionId) {
  if (!_currentBatchCard || _currentBatchCard.dataset.kgDismissed === '1') return false;
  if (sessionId == null) return true;
  return _currentBatchCard.dataset.researchSession === String(sessionId);
}

/** Dismiss the currently-shown batch connection card, if any. */
export function closeConnectionBatchCard() {
  const card = _currentBatchCard;
  if (!card) return false;
  _currentBatchCard = null;
  _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
  return true;
}

/** Batch learned connections from compare_papers / merge preview. */
export function handleConnectionProposals(data) {
  if (!data?.rows?.length && !data?.proposals?.length) return;
  _showConnectionBatchCard({
    ...data,
    source: data.source || (data.rows?.length ? 'merge_subgraph' : 'compare_papers'),
  });
}

/** Show approval toast when the agent suggests connecting two graph nodes. */
export function handleLinkSuggestion(data) {
  if (!data?.from || !data?.to) return;
  if (data._batch) {
    handleConnectionProposals(data);
    return;
  }
  if (data.suggestion_id && _dismissedLinkSuggestions.has(data.suggestion_id)) return;
  if (data.suggestion_id) {
    const dup = _linkSuggestionQueue.some((q) => q.suggestion_id === data.suggestion_id);
    if (dup) return;
  }
  _linkSuggestionQueue.push(data);
  _showNextLinkSuggestion();
}

async function openKnowledgeNode(nodeId, opts = {}) {
  if (!nodeId) return;
  const [type, raw] = nodeId.includes(':') ? nodeId.split(':', 2) : ['document', nodeId];
  const effective = type === 'note' ? 'document' : type;
  if (effective === 'document') {
    await _openDocumentNode(nodeId);
    return;
  }
  if (effective === 'task') {
    const notes = await import('./notes.js');
    const open = notes.openPanel || notes.default?.openPanel;
    if (open) open();
    setTimeout(() => {
      const row = document.querySelector(`.one-thing-row[data-task-id="${CSS.escape(raw)}"]`);
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('task-card-flash');
        setTimeout(() => row.classList.remove('task-card-flash'), 2000);
      }
    }, 300);
    return;
  }
  if (effective === 'memory') {
    document.getElementById('tool-memory-btn')?.click();
    return;
  }
  if (effective === 'skill') {
    const mod = await import('./skills.js');
    const open = mod.openSkill || mod.default?.openSkill;
    if (open) open(raw);
    return;
  }
  if (effective === 'paper') {
    if (opts.navigate) {
      await openKnowledgeAtNode(nodeId);
      return;
    }
    let url = _selectedNodeMeta?.url;
    if (!url) {
      try {
        const nb = await _fetchNeighbors(nodeId);
        url = nb.node?.meta?.url;
      } catch { /* ignore */ }
    }
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
      return;
    }
    uiModule.showToast?.('No URL for this paper', 3000);
    return;
  }
  if (effective === 'research') {
    if (opts.navigate) {
      await openKnowledgeAtNode(nodeId, { type: 'research' });
      return;
    }
    const sid = raw || nodeId.replace(/^research:/i, '');
    if (sid) {
      window.open(`${API_BASE}/api/research/report/${encodeURIComponent(sid)}`, '_blank', 'noopener,noreferrer');
    }
    return;
  }
  if (effective === 'collection') {
    _activeType = 'paper';
    document.querySelectorAll('.kg-type-filter').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.type === 'paper');
    });
    let path = _selectedNodeMeta?.path || '';
    if (!path) {
      try {
        const nb = await _fetchNeighbors(nodeId);
        path = nb.node?.meta?.path || '';
      } catch { /* ignore */ }
    }
    const search = document.getElementById('kg-search-input');
    const q = path.split('/').pop()?.trim() || path;
    if (search && q) search.value = q;
    await _renderList({ query: search?.value || '', type: 'paper' });
    return;
  }
  if (effective === 'project') {
    const pid = raw || nodeId.replace(/^project:/i, '');
    if (isProjectsContextLayerEnabled() && !isProjectsUiEnabled()) {
      if (pid) await setActiveProjectFromId(pid);
      return;
    }
    if (!isProjectsUiEnabled()) return;
    const mod = await import('./projects/index.js');
    const open = mod.openProjectWorkspace || mod.default?.openProjectWorkspace;
    if (open && pid) open(pid);
    return;
  }
}

function _wireModalEvents(modal) {
  if (modal.dataset.kgWired === '1') return;
  modal.dataset.kgWired = '1';

  modal.querySelector('#close-knowledge-modal')?.addEventListener('click', closeKnowledgeModal);
  modal.querySelector('#kg-rebuild-btn')?.addEventListener('click', async () => {
    const msg = document.getElementById('kg-stats');
    if (msg) msg.textContent = 'Rebuilding…';
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/rebuild`, { method: 'POST', credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Rebuild failed');
      uiModule.showToast?.(`Graph rebuilt — ${data.nodes} nodes, ${data.edges} links`);
      await _renderAll();
    } catch (e) {
      uiModule.showToast?.(e.message || 'Rebuild failed', 4000);
    }
  });

  // Enter in the search box jumps the graph to the first matching node.
  modal.querySelector('#kg-search-input')?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      _graphView?.focusSearchMatch(ev.target.value);
    }
  });

  modal.querySelector('#kg-search-input')?.addEventListener('input', (ev) => {
    const value = ev.target.value;
    // Graph highlight is a live dim with no fetch, so update it instantly; the
    // list re-fetches on a short debounce.
    _graphView?.setQuery(value);
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _renderList({ query: value, type: _activeType });
    }, 250);
  });

  modal.querySelectorAll('.kg-type-filter').forEach((btn) => {
    btn.addEventListener('click', () => {
      _activeType = btn.dataset.type || '';
      modal.querySelectorAll('.kg-type-filter').forEach((b) => b.classList.toggle('active', b === btn));
      const q = modal.querySelector('#kg-search-input')?.value || '';
      // Filters scope the node list; the graph keeps showing the full graph.
      void _renderList({ query: q, type: _activeType });
    });
  });

  modal.addEventListener('click', (ev) => {
    const openBtn = ev.target.closest('.kg-open-btn');
    if (openBtn?.dataset.nodeId) {
      openKnowledgeNode(openBtn.dataset.nodeId);
      return;
    }
    const removeBtn = ev.target.closest('.kg-link-remove');
    if (removeBtn?.dataset.from && removeBtn?.dataset.to) {
      void (async () => {
        removeBtn.disabled = true;
        try {
          await removeGraphLink(removeBtn.dataset.from, removeBtn.dataset.to, removeBtn.dataset.kind);
          uiModule.showToast?.('Link removed');
          if (_selectedId) await _showDetail(_selectedId);
        } catch (e) {
          uiModule.showToast?.(e.message || 'Remove failed', 4000);
        } finally {
          removeBtn.disabled = false;
        }
      })();
      return;
    }
    const linkRow = ev.target.closest('.kg-link-row');
    if (linkRow?.dataset.nodeId) {
      _selectFromList(linkRow.dataset.nodeId);
    }
  });
}

export function openKnowledgeModal() {
  let modal = document.getElementById('knowledge-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  _open = true;
  // Restore the previously previewed node so reopening feels continuous.
  if (!_selectedId) {
    try {
      const saved = localStorage.getItem('nobody-links-selected');
      if (saved) _selectedId = saved;
    } catch { /* ignore */ }
  }
  _wireModalEvents(modal);
  void _renderAll();
  import('./tourHints.js').then((m) => m.maybeNavHint?.('connectionsVsLinks')).catch(() => {});
}

/** Open Links hub focused on a node (project workspace rail, deep links). */
export async function openKnowledgeAtNode(nodeId, { type } = {}) {
  if (!nodeId) return;
  openKnowledgeModal();
  if (type) {
    _activeType = type;
    document.querySelectorAll('.kg-type-filter').forEach((btn) => {
      btn.classList.toggle('active', (btn.dataset.type || '') === type);
    });
    await _renderList({ type });
  }
  await _showDetail(nodeId);
}

if (typeof window !== 'undefined') {
  window.addEventListener('knowledge-graph-refresh', () => {
    if (_open) void _renderAll();
  });
  initGraphMergeListeners();
}

export function closeKnowledgeModal() {
  const modal = document.getElementById('knowledge-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  _open = false;
  _graphView?.setActive(false);
}

export function isKnowledgeOpen() {
  return _open;
}

if (typeof window !== 'undefined') {
  window.addEventListener('message', (e) => {
    if (e.origin !== window.location.origin) return;
    const data = e.data;
    if (!data || data.type !== 'odysseus-open-knowledge' || !data.nodeId) return;
    openKnowledgeNode(data.nodeId);
  });
}

export default {
  openKnowledgeModal,
  closeKnowledgeModal,
  isKnowledgeOpen,
  openKnowledgeNode,
  openKnowledgeAtNode,
  createGraphLink,
  removeGraphLink,
  mountGraphLinkPicker,
  handleLinkSuggestion,
  handleConnectionProposals,
  openGraphMergeReview,
};
