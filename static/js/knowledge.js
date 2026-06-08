/**
 * Knowledge graph browser — search and explore conceptual links
 * (tasks, documents, memories, skills).
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
  paper: 'Paper',
  collection: 'Collection',
  research: 'Research',
  project: 'Project',
  note: 'Document', // legacy index rows
};

const MANUAL_EDGE_KINDS = new Set(['link', 'related', 'supports']);
const LINK_KIND_OPTIONS = ['link', 'related', 'supports'];

let _open = false;
let _activeType = '';
let _selectedId = null;
let _selectedNodeMeta = null;
let _searchTimer = null;
let _linkSearchTimer = null;

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

export async function createGraphLink(fromId, toId, kind = 'link') {
  const res = await fetch(`${API_BASE}/api/knowledge/links`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_id: fromId, to_id: toId, kind }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Link failed');
  window.dispatchEvent(new CustomEvent('knowledge-graph-refresh'));
  return data;
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
    (k) => `<option value="${esc(k)}">${esc(k)}</option>`,
  ).join('');
  return `<div class="kg-add-link" data-from-id="${esc(fromId)}">
    <div class="kg-add-link-head">
      <input type="search" class="settings-input kg-add-link-search" placeholder="Search to link…" autocomplete="off">
      <select class="kg-add-link-kind">${kindOpts}</select>
    </div>
    <div class="kg-add-link-results" data-linked="${esc([...linkedIds].join(','))}"></div>
  </div>`;
}

function _renderNodeRow(node, { active = false } = {}) {
  const id = node.id || '';
  const snip = (node.snippet || '').slice(0, 100);
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
    const kind = (row.edge && row.edge.kind) || 'link';
    const removable = _isManualEdgeKind(kind);
    let removeBtn = '';
    if (removable && nodeId) {
      const from = direction === 'out' ? nodeId : n.id;
      const to = direction === 'out' ? n.id : nodeId;
      removeBtn = `<button type="button" class="kg-link-remove" data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}" title="Remove link" aria-label="Remove link">×</button>`;
    }
    return `<div class="kg-link-row-wrap">
      <button type="button" class="kg-link-row" data-node-id="${esc(n.id)}">
        <span class="kg-link-kind">${esc(kind)}</span>
        ${_typeBadge(n)}
        <span class="kg-node-title">${esc(_nodeTitle(n))}</span>
      </button>
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
    const kind = kindSel?.value || 'link';
    hit.disabled = true;
    try {
      await createGraphLink(fromId, toId, kind);
      linkedSet().add(toId);
      results.dataset.linked = [...linkedSet(), toId].join(',');
      uiModule.showToast?.('Link added');
      input.value = '';
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
  const detail = document.getElementById('kg-detail');
  if (!detail) return;
  detail.innerHTML = '<div class="kg-loading">Loading links…</div>';
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
    const projectOpenBtn = node.type === 'project'
      ? `<button type="button" class="admin-btn-sm kg-project-workspace-btn" data-project-id="${esc(meta.project_id || nodeId.replace(/^project:/i, ''))}">Open workspace</button>`
      : '';
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
      <div class="kg-detail-snippet">${esc((node.snippet || '').slice(0, 420))}</div>
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
      const mod = await import('./projects/index.js');
      const open = mod.openProjectWorkspace || mod.default?.openProjectWorkspace;
      if (open) open(pid);
    });
  } catch (e) {
    detail.innerHTML = `<div class="kg-error">${esc(e.message || e)}</div>`;
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
      const emptyHint = _activeType === 'paper'
        ? 'No papers indexed — connect Zotero in Settings → Search, then Sync catalog.'
        : 'No links yet — add todos, documents, or memories, then Rebuild.';
      list.innerHTML = `<div class="kg-empty">${esc(emptyHint)}</div>`;
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
  if (!data?.from || !data?.to) return;
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
          <div class="kg-link-suggest-eyebrow">Connect in your graph?</div>
          <div class="kg-link-suggest-sub">Link these items so they show up together in Links.</div>
        </div>
        <button type="button" class="kg-link-suggest-close" aria-label="Dismiss">×</button>
      </div>
      <div class="kg-link-suggest-flow">
        ${_linkSuggestNode(data.from_type, fromTitle)}
        <span class="kg-link-suggest-arrow" aria-hidden="true">→</span>
        ${_linkSuggestNode(data.to_type, toTitle)}
      </div>
      ${reason ? `<p class="kg-link-suggest-reason">${esc(reason)}</p>` : ''}
      <div class="kg-link-suggest-foot">
        <span class="kg-link-kind kg-link-suggest-kind">${esc(kind)}</span>
        <div class="kg-link-suggest-actions">
          <button type="button" class="kg-link-suggest-dismiss">Not now</button>
          <button type="button" class="kg-link-suggest-accept">Link them</button>
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

  card.querySelector('.kg-link-suggest-dismiss')?.addEventListener('click', dismiss);
  card.querySelector('.kg-link-suggest-close')?.addEventListener('click', dismiss);

  card.querySelector('.kg-link-suggest-accept')?.addEventListener('click', (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    card.classList.add('kg-link-suggest-saving');
    _dismissLinkSuggestionCard(card, _finishLinkSuggestionPrompt);
    uiModule.showToast?.('Link saved', { duration: 1100, leadingIcon: 'check' });
    void createGraphLink(data.from, data.to, kind).catch((e) => {
      uiModule.showToast?.(e.message || 'Link failed', 4000);
    });
  });
}

/** Show approval toast when the agent suggests connecting two graph nodes. */
export function handleLinkSuggestion(data) {
  if (!data?.from || !data?.to) return;
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
    const mod = await import('./projects/index.js');
    const open = mod.openProjectWorkspace || mod.default?.openProjectWorkspace;
    const pid = raw || nodeId.replace(/^project:/i, '');
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
    if (_open) void _renderList();
  });
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
};
