/**
 * Knowledge graph browser — search and explore conceptual links
 * (tasks, documents, memories, skills; vault markdown lives under documents).
 */
import uiModule from './ui.js';
import sessionModule from './sessions.js';

const API_BASE = window.API_BASE || '';
const esc = uiModule.esc;

const TYPE_LABELS = {
  task: 'Task',
  document: 'Document',
  memory: 'Memory',
  skill: 'Skill',
  note: 'Document', // legacy index rows
};

let _open = false;
let _activeType = '';
let _selectedId = null;
let _searchTimer = null;

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

function _nodeMeta(node) {
  if (node?.meta?.source === 'vault' && node.meta.path) {
    return node.meta.path;
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
  const res = await fetch(
    `${API_BASE}/api/knowledge/nodes/${encodeURIComponent(nodeId)}/neighbors`,
    { credentials: 'same-origin' },
  );
  if (!res.ok) throw new Error('Failed to load links');
  return res.json();
}

function _renderNodeRow(node, { active = false } = {}) {
  const id = node.id || '';
  const snip = (node.snippet || '').slice(0, 160);
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

function _renderLinkSection(title, rows) {
  if (!rows?.length) {
    return `<div class="kg-link-section"><div class="kg-link-heading">${esc(title)}</div><div class="kg-link-empty">None</div></div>`;
  }
  const items = rows.map((row) => {
    const n = row.node;
    if (!n) return '';
    const kind = (row.edge && row.edge.kind) || 'link';
    return `<button type="button" class="kg-link-row" data-node-id="${esc(n.id)}">
      <span class="kg-link-kind">${esc(kind)}</span>
      ${_typeBadge(n)}
      <span class="kg-node-title">${esc(_nodeTitle(n))}</span>
    </button>`;
  }).join('');
  return `<div class="kg-link-section"><div class="kg-link-heading">${esc(title)}</div>${items}</div>`;
}

async function _showDetail(nodeId) {
  _selectedId = nodeId;
  const detail = document.getElementById('kg-detail');
  if (!detail) return;
  detail.innerHTML = '<div class="kg-loading">Loading links…</div>';
  document.querySelectorAll('.kg-node-row').forEach((el) => {
    el.classList.toggle('active', el.dataset.nodeId === nodeId);
  });
  try {
    const nb = await _fetchNeighbors(nodeId);
    const node = nb.node || {};
    const meta = node.meta || {};
    let metaHtml = '';
    if (node.type === 'task' && meta.horizon_label) {
      metaHtml = `<div class="kg-meta">${esc(meta.horizon_label)}${meta.due_date ? ' · due ' + esc(meta.due_date) : ''}</div>`;
    } else if (meta.source === 'vault' && meta.path) {
      metaHtml = `<div class="kg-meta">${esc(meta.path)}</div>`;
    }
    detail.innerHTML = `
      <div class="kg-detail-head">
        ${_typeBadge(node)}
        <h3 class="kg-detail-title">${esc(_nodeTitle(node))}</h3>
        ${metaHtml}
        <div class="kg-detail-actions">
          <button type="button" class="admin-btn-sm kg-open-btn" data-node-id="${esc(nodeId)}">Open</button>
        </div>
      </div>
      <div class="kg-detail-snippet">${esc(node.snippet || '')}</div>
      ${_renderLinkSection('Links to', nb.outgoing)}
      ${_renderLinkSection('Linked from', nb.incoming)}
    `;
  } catch (e) {
    detail.innerHTML = `<div class="kg-error">${esc(e.message || e)}</div>`;
  }
}

async function _renderList({ query = '', type = _activeType } = {}) {
  const list = document.getElementById('kg-node-list');
  const stats = document.getElementById('kg-stats');
  if (!list) return;
  list.innerHTML = '<div class="kg-loading">Loading…</div>';
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
      list.innerHTML = '<div class="kg-empty">No links yet — add todos, documents, or memories, then Rebuild.</div>';
      const detail = document.getElementById('kg-detail');
      if (detail) detail.innerHTML = '';
      return;
    }
    list.innerHTML = nodes.map((n) => _renderNodeRow(n, { active: n.id === _selectedId })).join('');
    list.querySelectorAll('.kg-node-row').forEach((btn) => {
      btn.addEventListener('click', () => _showDetail(btn.dataset.nodeId));
    });
    if (_selectedId && nodes.some((n) => n.id === _selectedId)) {
      await _showDetail(_selectedId);
    } else if (nodes[0]) {
      await _showDetail(nodes[0].id);
    }
  } catch (e) {
    list.innerHTML = `<div class="kg-error">${esc(e.message || e)}</div>`;
  }
}

async function _openDocumentNode(nodeId) {
  const [, raw] = nodeId.includes(':') ? nodeId.split(':', 2) : ['document', nodeId];
  const isEditorDoc = nodeId.startsWith('document:') && !raw.startsWith('vault:')
    && /^[0-9a-f-]{36}$/i.test(raw);
  if (isEditorDoc) {
    const mod = await import('./document.js');
    const open = mod.loadDocument || mod.default?.loadDocument;
    if (open) open(raw);
    return;
  }
  try {
    const res = await fetch(
      `${API_BASE}/api/knowledge/nodes/${encodeURIComponent(nodeId)}/content`,
      { credentials: 'same-origin' },
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not load document');
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

async function openKnowledgeNode(nodeId) {
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
      await _renderList();
    } catch (e) {
      uiModule.showToast?.(e.message || 'Rebuild failed', 4000);
    }
  });

  modal.querySelector('#kg-search-input')?.addEventListener('input', (ev) => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _renderList({ query: ev.target.value, type: _activeType });
    }, 250);
  });

  modal.querySelectorAll('.kg-type-filter').forEach((btn) => {
    btn.addEventListener('click', () => {
      _activeType = btn.dataset.type || '';
      modal.querySelectorAll('.kg-type-filter').forEach((b) => b.classList.toggle('active', b === btn));
      const q = modal.querySelector('#kg-search-input')?.value || '';
      _renderList({ query: q, type: _activeType });
    });
  });

  modal.addEventListener('click', (ev) => {
    const openBtn = ev.target.closest('.kg-open-btn');
    if (openBtn?.dataset.nodeId) {
      openKnowledgeNode(openBtn.dataset.nodeId);
      return;
    }
    const linkRow = ev.target.closest('.kg-link-row');
    if (linkRow?.dataset.nodeId) {
      _showDetail(linkRow.dataset.nodeId);
    }
  });
}

export function openKnowledgeModal() {
  let modal = document.getElementById('knowledge-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  _open = true;
  _wireModalEvents(modal);
  _renderList();
}

export function closeKnowledgeModal() {
  const modal = document.getElementById('knowledge-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  _open = false;
}

export function isKnowledgeOpen() {
  return _open;
}

export default {
  openKnowledgeModal,
  closeKnowledgeModal,
  isKnowledgeOpen,
  openKnowledgeNode,
};
