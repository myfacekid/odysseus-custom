/**
 * Inline link detail viewer for project center pane (Phase G3/G4).
 */
import uiModule from '../ui.js';
import knowledgeModule from '../knowledge.js';

const API_BASE = window.API_BASE || window.location.origin;
const esc = uiModule.esc;

let _pane = null;
let _nodeId = null;
let _loadGen = 0;
let _onLinkRemoved = null;
let _onCloseTab = null;

const LINK_TYPE_LABELS = {
  paper: 'Paper',
  research: 'Research',
  document: 'Document',
  task: 'Task',
  memory: 'Memory',
  skill: 'Skill',
  collection: 'Collection',
  project: 'Project',
};

function _typeBadge(type) {
  const t = (type || 'unknown').toLowerCase();
  return `<span class="kg-type kg-type-${esc(t)}">${esc(LINK_TYPE_LABELS[t] || t)}</span>`;
}

function _snippetLang(type) {
  const t = (type || '').toLowerCase();
  if (t === 'research' || t === 'document') return 'markdown';
  if (t === 'paper') return 'plaintext';
  return 'plaintext';
}

function _highlightSnippet(snippet, type) {
  const trimmed = (snippet || '').trim();
  if (!trimmed) return '';
  const lang = _snippetLang(type);
  if (window.hljs && lang && lang !== 'plaintext') {
    try {
      const { value } = window.hljs.highlight(trimmed, { language: lang });
      return `<pre class="project-link-viewer-snippet"><code class="hljs language-${esc(lang)}">${value}</code></pre>`;
    } catch {
      /* fall through */
    }
  }
  return `<pre class="project-link-viewer-snippet">${esc(trimmed)}</pre>`;
}

async function _fetchNeighbors(nodeId) {
  const res = await fetch(
    `${API_BASE}/api/knowledge/neighbors?${new URLSearchParams({ id: nodeId })}`,
    { credentials: 'same-origin' },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to load link');
  return data;
}

function _title(node, nodeId, tabMeta) {
  if (node?.title) return node.title;
  if (tabMeta?.label) return tabMeta.label;
  return nodeId.replace(/^[^:]+:/, '') || 'Untitled';
}

function _metaGrid(type, meta) {
  const rows = [];
  const t = (type || '').toLowerCase();
  if (t === 'paper') {
    if (meta.zotero_key) rows.push(['Zotero key', meta.zotero_key]);
    if (meta.authors) rows.push(['Authors', meta.authors]);
    if (meta.year) rows.push(['Year', String(meta.year)]);
    if (meta.doi) rows.push(['DOI', meta.doi]);
  } else if (t === 'research') {
    if (meta.research_mode_label) rows.push(['Mode', meta.research_mode_label]);
    if (meta.session_id) rows.push(['Session', meta.session_id]);
  } else if (t === 'document') {
    if (meta.path) rows.push(['Path', meta.path]);
    if (meta.doc_id) rows.push(['Document', meta.doc_id]);
  } else if (t === 'task') {
    if (meta.status) rows.push(['Status', meta.status]);
    if (meta.due) rows.push(['Due', meta.due]);
  }
  if (!rows.length) return '';
  return `<dl class="project-link-viewer-grid">${rows.map(([k, v]) =>
    `<div class="project-link-viewer-grid-row"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`,
  ).join('')}</dl>`;
}

function _typeIntro(type) {
  const t = (type || '').toLowerCase();
  if (t === 'paper') return 'Linked paper from your knowledge graph.';
  if (t === 'research') return 'Deep research session linked to this project.';
  if (t === 'document') return 'Document node — open in Links for full editing.';
  if (t === 'task') return 'Task linked to this project.';
  return 'Graph link attached to this project.';
}

function _bindActions(nodeId, node, meta, tabMeta) {
  _pane.querySelector('#project-link-viewer-report-btn')?.addEventListener('click', () => {
    const sid = meta.session_id || nodeId.replace(/^research:/i, '');
    if (sid) {
      window.open(`${API_BASE}/api/research/report/${encodeURIComponent(sid)}`, '_blank', 'noopener,noreferrer');
    }
  });
  _pane.querySelector('#project-link-viewer-remove-btn')?.addEventListener('click', () => {
    void (async () => {
      const removeMeta = tabMeta?.stale ? tabMeta : null;
      if (!removeMeta?.removeFrom || !removeMeta?.removeTo) return;
      const btn = _pane.querySelector('#project-link-viewer-remove-btn');
      if (btn) btn.disabled = true;
      try {
        await knowledgeModule.removeGraphLink(
          removeMeta.removeFrom,
          removeMeta.removeTo,
          removeMeta.edgeKind || 'related',
        );
        uiModule.showToast?.('Stale link removed');
        _onLinkRemoved?.();
        if (_onCloseTab) _onCloseTab(nodeId);
      } catch (e) {
        uiModule.showToast?.(e.message || 'Remove failed', 4000);
      } finally {
        if (btn) btn.disabled = false;
      }
    })();
  });
}

export function mount(pane, { onLinkRemoved, onCloseTab } = {}) {
  _pane = pane;
  _onLinkRemoved = onLinkRemoved || null;
  _onCloseTab = onCloseTab || null;
}

export function unmount() {
  if (_pane) _pane.innerHTML = '';
  _pane = null;
  _nodeId = null;
  _onLinkRemoved = null;
  _onCloseTab = null;
}

export async function show(nodeId, tabMeta) {
  if (!_pane || !nodeId) return;
  const gen = ++_loadGen;
  _nodeId = nodeId;
  _pane.innerHTML = '<div class="project-link-viewer-loading">Loading…</div>';
  _pane.classList.remove('hidden');

  const staleFromMeta = !!tabMeta?.stale;

  try {
    const data = await _fetchNeighbors(nodeId);
    if (gen !== _loadGen) return;
    const node = data.node || {};
    const meta = node.meta || {};
    const type = (node.type || nodeId.split(':')[0] || 'unknown').toLowerCase();
    const stale = staleFromMeta || !node.id;
    const title = _title(node, nodeId, tabMeta);
    const snippet = (node.snippet || '').trim();
    const intro = _typeIntro(type);
    const metaGrid = _metaGrid(type, meta);
    const snippetHtml = _highlightSnippet(snippet, type);

    _pane.innerHTML =
      `<div class="project-link-viewer project-link-viewer--breadth project-link-viewer--${esc(type)}">` +
        `<div class="project-link-viewer-head">` +
          `<div class="project-link-viewer-head-main">` +
            `<span class="project-link-viewer-boundary">Breadth</span>` +
            `${_typeBadge(type)}` +
            `<h3 class="project-link-viewer-title">${esc(title)}</h3>` +
            `<div class="project-link-viewer-id">${esc(nodeId)}</div>` +
          `</div>` +
          `<div class="project-link-viewer-actions">` +
            (type === 'research' && meta.session_id
              ? `<button type="button" class="admin-btn-sm" id="project-link-viewer-report-btn">Open report</button>`
              : '') +
          `</div>` +
        `</div>` +
        (stale
          ? `<div class="project-link-viewer-stale">` +
              `This node is missing from the graph.` +
              (tabMeta?.removeFrom && tabMeta?.removeTo
                ? ` <button type="button" class="admin-btn-sm" id="project-link-viewer-remove-btn">Remove link</button>`
                : '') +
            `</div>`
          : '') +
        `<div class="project-link-viewer-intro">${esc(intro)}</div>` +
        (metaGrid || '') +
        (snippetHtml
          ? `<div class="project-link-viewer-body">${snippetHtml}</div>`
          : `<div class="project-link-viewer-body project-link-viewer-empty">No preview text for this link.</div>`) +
      `</div>`;

    _bindActions(nodeId, node, meta, tabMeta);
  } catch (e) {
    if (gen !== _loadGen) return;
    _pane.innerHTML = `<div class="project-link-viewer-error">${esc(e.message || 'Could not load link')}</div>`;
  }
}

export function hide() {
  if (!_pane) return;
  _loadGen += 1;
  _pane.classList.add('hidden');
  _pane.innerHTML = '';
  _nodeId = null;
}

export function getNodeId() {
  return _nodeId;
}

export default { mount, unmount, show, hide, getNodeId };
