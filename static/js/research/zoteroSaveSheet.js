/**
 * Save-to-Zotero compose sheet: pick papers + destination collection.
 * Shared by Research panel, Library preview, and visual report.
 */
import uiModule from '../ui.js';

const CHECK_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
const FOLDER_SVG = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>`;

function _esc(s) {
  return uiModule.esc
    ? uiModule.esc(s)
    : String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
}

/** Inject sheet chrome when style.css is not loaded (e.g. visual report). */
function _ensureStyles() {
  let style = document.getElementById('zotero-save-sheet-styles');
  if (!style) {
    style = document.createElement('style');
    style.id = 'zotero-save-sheet-styles';
    document.head.appendChild(style);
  }
  style.textContent = `
.zotero-save-sheet.modal {
  position: fixed; inset: 0; z-index: 12000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.45); padding: 16px;
}
.zotero-save-sheet.modal.hidden { display: none; }
.zotero-save-sheet .modal-content {
  background: var(--bg-surface, var(--panel, #1a1a1a));
  color: var(--text, var(--fg, #eee));
  border: 1px solid var(--border, rgba(127,127,127,0.35));
  border-radius: var(--radius, 4px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
}
.zotero-save-sheet .modal-close {
  border: none; background: transparent; color: inherit; font-size: 22px;
  line-height: 1; cursor: pointer; opacity: 0.6; padding: 0 4px;
}
.zotero-save-sheet .modal-close:hover { opacity: 1; }
.zotero-save-sheet .zotero-save-sheet-content {
  width: min(760px, 96vw); max-height: min(820px, 94vh);
  display: flex; flex-direction: column; padding: 16px 18px 14px; gap: 12px;
  box-sizing: border-box;
}
.zotero-save-sheet.zotero-save-sheet-enter .zotero-save-sheet-content {
  animation: zotero-save-sheet-in 0.26s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes zotero-save-sheet-in {
  from { opacity: 0; transform: translateY(12px) scale(0.985); }
  to { opacity: 1; transform: none; }
}
.zotero-save-sheet-header { display: flex; align-items: flex-start; gap: 12px; }
.zotero-save-sheet-header-text { flex: 1; min-width: 0; }
.zotero-save-sheet-header h3 { margin: 0; font-size: 1.05rem; }
.zotero-save-sheet-sub { margin: 4px 0 0; font-size: 12px; opacity: 0.65; line-height: 1.4; }
.zotero-save-sheet-body {
  display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 14px; min-height: 0; flex: 1; overflow: hidden;
}
@media (max-width: 640px) {
  .zotero-save-sheet-body { grid-template-columns: 1fr; overflow: auto; }
}
.zotero-save-papers, .zotero-save-folder {
  display: flex; flex-direction: column; gap: 8px; min-height: 0; min-width: 0;
}
.zotero-save-section-head {
  display: flex; align-items: baseline; gap: 8px; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.04em; opacity: 0.7;
}
.zotero-save-section-label { font-weight: 700; }
.zotero-save-section-count, .zotero-save-folder-current {
  font-weight: 500; text-transform: none; letter-spacing: 0; opacity: 0.85; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.zotero-save-clear {
  margin-left: auto; border: none; background: transparent; color: inherit; opacity: 0.55;
  cursor: pointer; font: inherit; font-size: 11px; text-transform: none; letter-spacing: 0;
}
.zotero-save-clear:hover { opacity: 1; }
.zotero-save-empty { font-size: 12px; opacity: 0.5; padding: 6px 2px; }
.zotero-save-search-wrap { margin: 0; }
.zotero-save-paper-list {
  flex: 1; min-height: 280px; overflow: auto;
  display: flex; flex-direction: column; gap: 6px;
}
.zotero-save-folder-list {
  flex: 1; min-height: 280px; overflow: auto;
  border: 1px solid var(--border, rgba(127,127,127,0.35));
  border-radius: var(--radius-tech, 2px);
}
.zotero-save-folder-item {
  display: grid; grid-template-columns: 18px 1fr; gap: 2px 8px; align-items: start;
  width: 100%; text-align: left;
}
.zotero-save-folder-path {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  font-weight: 550;
  word-break: break-word;
}
.zotero-save-folder-item .styled-list-pick-item-hint { grid-column: 2; }
.zotero-save-folder-item.is-selected {
  background: color-mix(in srgb, var(--accent, var(--red, #c44)) 12%, transparent);
}
.zotero-save-folder-icon { opacity: 0.55; margin-top: 2px; }
.zotero-save-in-library { opacity: 0.55; cursor: default; pointer-events: none; }
.zotero-save-skip-check { font-size: 12px; opacity: 0.8; }
.zotero-save-card-top {
  display: flex; align-items: flex-start; gap: 8px; width: 100%;
}
.zotero-save-card-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.zotero-save-card-badges {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
}
.zotero-save-badge {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 1px 6px; border: 1px solid var(--border, rgba(127,127,127,0.4));
  border-radius: 2px; white-space: nowrap; line-height: 1.4;
}
.zotero-save-badge-tier-adequate {
  border-color: color-mix(in srgb, var(--green, #3fb950) 40%, var(--border, #666));
  color: color-mix(in srgb, var(--green, #3fb950) 80%, currentColor);
}
.zotero-save-badge-tier-abstract {
  border-color: color-mix(in srgb, var(--gold, #d4a017) 45%, var(--border, #666));
  color: color-mix(in srgb, var(--gold, #d4a017) 85%, currentColor);
}
.zotero-save-badge-tier-thin, .zotero-save-badge-tier-unknown {
  border-color: color-mix(in srgb, var(--error, #e5534b) 35%, var(--border, #666));
  color: color-mix(in srgb, var(--error, #e5534b) 80%, currentColor);
}
.zotero-save-badge-cited {
  border-color: color-mix(in srgb, var(--accent, var(--red, #c44)) 40%, var(--border, #666));
  color: color-mix(in srgb, var(--accent, var(--red, #c44)) 85%, currentColor);
}
.zotero-save-badge-seed, .zotero-save-badge-meta { opacity: 0.85; }
.zotero-save-card-meta { font-size: 11px; opacity: 0.55; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.zotero-save-sheet-footer {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px;
}
.zotero-save-sheet-status { flex: 1; margin: 0; font-size: 12px; opacity: 0.7; min-width: 120px; }
.zotero-save-sheet .confirm-btn {
  border: 1px solid var(--border, rgba(127,127,127,0.4));
  background: var(--panel, transparent); color: inherit;
  padding: 7px 14px; font: inherit; font-size: 13px; cursor: pointer; border-radius: 2px;
}
.zotero-save-sheet .confirm-btn-primary {
  background: var(--accent, var(--red, #c44)); color: #fff; border-color: transparent;
}
.zotero-save-sheet .confirm-btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.zotero-save-sheet .research-seed-picker-list { display: flex; flex-direction: column; gap: 6px; }
.zotero-save-sheet .research-seed-picker-card {
  display: flex; gap: 10px; align-items: flex-start; width: 100%; text-align: left;
  padding: 10px 12px; border: 1px solid var(--border, rgba(127,127,127,0.35));
  border-radius: 2px; background: var(--panel, transparent); color: inherit; cursor: pointer; font: inherit;
  box-sizing: border-box;
}
.zotero-save-sheet .research-seed-picker-card.is-selected {
  border-color: var(--green, #3fb950);
  background: color-mix(in srgb, var(--green, #3fb950) 10%, transparent);
}
.zotero-save-sheet .research-seed-picker-check { flex-shrink: 0; margin-top: 2px; }
.zotero-save-sheet .research-seed-picker-title { font-size: 13px; font-weight: 600; line-height: 1.35; }
.zotero-save-sheet .research-seed-input {
  width: 100%; box-sizing: border-box; padding: 7px 10px; font: inherit; font-size: 13px;
  border: 1px solid var(--border, rgba(127,127,127,0.35)); border-radius: 2px;
  background: var(--panel, transparent); color: inherit;
}
.zotero-save-sheet .styled-list-pick-item {
  display: block; width: 100%; text-align: left; padding: 9px 12px;
  border: none; border-bottom: 1px solid var(--border, rgba(127,127,127,0.25));
  background: transparent; color: inherit; cursor: pointer; font: inherit;
}
.zotero-save-sheet .styled-list-pick-item-label { display: block; font-size: 13px; font-weight: 550; }
.zotero-save-sheet .styled-list-pick-item-hint { display: block; font-size: 11px; opacity: 0.55; margin-top: 2px; }
.zotero-save-sheet .styled-list-pick-empty,
.zotero-save-sheet .research-seed-picker-empty,
.zotero-save-sheet .research-seed-picker-loading {
  padding: 14px 10px; font-size: 12px; opacity: 0.55; text-align: center;
}
@media (prefers-reduced-motion: reduce) {
  .zotero-save-sheet.zotero-save-sheet-enter .zotero-save-sheet-content { animation: none !important; }
}`;
}

function _ensureOverlay() {
  _ensureStyles();
  let el = document.getElementById('zotero-save-sheet');
  if (el) {
    el.querySelector('#zotero-save-chips')?.remove();
    return el;
  }
  el = document.createElement('div');
  el.id = 'zotero-save-sheet';
  el.className = 'modal zotero-save-sheet hidden';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-labelledby', 'zotero-save-sheet-title');
  el.innerHTML = `
    <div class="modal-content zotero-save-sheet-content">
      <div class="modal-header zotero-save-sheet-header">
        <div class="zotero-save-sheet-header-text">
          <h3 id="zotero-save-sheet-title">Save to Zotero</h3>
          <p class="zotero-save-sheet-sub">Choose sources and a folder. Items already in your library are skipped.</p>
        </div>
        <button type="button" class="modal-close" id="zotero-save-sheet-close" aria-label="Close">&times;</button>
      </div>
      <div class="zotero-save-sheet-body">
        <section class="zotero-save-papers" aria-label="Sources to save">
          <div class="zotero-save-section-head">
            <span class="zotero-save-section-label">Sources</span>
            <span class="zotero-save-section-count" id="zotero-save-paper-count"></span>
            <button type="button" class="zotero-save-clear" id="zotero-save-clear-papers" hidden>Clear</button>
          </div>
          <div class="research-seed-search-wrap zotero-save-search-wrap">
            <input type="search" class="research-seed-input" id="zotero-save-paper-filter"
              placeholder="Filter sources…" autocomplete="off" />
          </div>
          <div class="zotero-save-paper-list research-seed-picker-list" id="zotero-save-paper-list" role="listbox" aria-multiselectable="true"></div>
        </section>
        <section class="zotero-save-folder" aria-label="Zotero folder">
          <div class="zotero-save-section-head">
            <span class="zotero-save-section-label">Folder</span>
            <span class="zotero-save-folder-current" id="zotero-save-folder-label">Library root</span>
          </div>
          <div class="research-seed-search-wrap zotero-save-search-wrap">
            <input type="search" class="research-seed-input" id="zotero-save-folder-filter"
              placeholder="Filter folders…" autocomplete="off" />
          </div>
          <div class="zotero-save-folder-list styled-list-pick-list" id="zotero-save-folder-list" role="listbox"></div>
        </section>
      </div>
      <div class="zotero-save-sheet-footer modal-footer">
        <p class="zotero-save-sheet-status" id="zotero-save-status" hidden></p>
        <button type="button" class="confirm-btn confirm-btn-secondary" id="zotero-save-cancel">Cancel</button>
        <button type="button" class="confirm-btn confirm-btn-primary" id="zotero-save-do">Save</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  return el;
}

function _detailMessage(data, fallback) {
  const d = data && data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d[0]?.msg) return d.map((x) => x.msg).join('; ');
  return fallback;
}

function _peerLabel(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'preprint') return 'Preprint';
  if (key === 'peer_reviewed' || key === 'peer-reviewed') return 'Peer reviewed';
  return '';
}

function _sourceBadgesHtml(src, { inLibrary = false } = {}) {
  const badges = [];
  if (inLibrary) {
    badges.push('<span class="zotero-save-badge zotero-save-badge-meta">In library</span>');
  }
  const citeCount = Number(src.cite_count) || 0;
  if (citeCount > 0) {
    badges.push(
      `<span class="zotero-save-badge zotero-save-badge-cited" title="Cited ${citeCount}× in the report">` +
      `Cited ×${citeCount}</span>`
    );
  } else if (src.cited) {
    badges.push('<span class="zotero-save-badge zotero-save-badge-cited">Cited</span>');
  } else {
    badges.push('<span class="zotero-save-badge zotero-save-badge-meta">Not cited</span>');
  }
  if (src.is_seed) {
    badges.push('<span class="zotero-save-badge zotero-save-badge-seed">Seed</span>');
  }
  const tierCls = src.sourcing_tier_class || 'unknown';
  const tierLabel = src.sourcing_tier_label || '';
  if (tierLabel) {
    badges.push(
      `<span class="zotero-save-badge zotero-save-badge-tier-${_esc(tierCls)}" ` +
      `title="Retrieval depth used for this source">${_esc(tierLabel)}</span>`
    );
  }
  const peer = _peerLabel(src.peer_review_status);
  if (peer) {
    badges.push(`<span class="zotero-save-badge zotero-save-badge-meta">${_esc(peer)}</span>`);
  }
  if (src.study_type) {
    badges.push(`<span class="zotero-save-badge zotero-save-badge-meta">${_esc(src.study_type)}</span>`);
  }
  return badges.length
    ? `<div class="zotero-save-card-badges">${badges.join('')}</div>`
    : '';
}

function _sourceMetaLine(src) {
  const bits = [src.authors, src.year].filter(Boolean).map((v) => String(v));
  return bits.length ? `<div class="zotero-save-card-meta">${_esc(bits.join(' · '))}</div>` : '';
}

/**
 * Open the Save-to-Zotero compose sheet.
 * @param {{ sessionId: string, apiBase?: string, initialCitationNums?: number[] }} opts
 * @returns {Promise<{ ok: boolean, created?: number, cancelled?: boolean, error?: string }>}
 */
export async function openZoteroSaveSheet(opts = {}) {
  const sessionId = (opts.sessionId || '').trim();
  if (!sessionId) return { ok: false, error: 'Missing research session' };
  const apiBase = (opts.apiBase || window.API_BASE || window.location.origin || '').replace(/\/$/, '');

  const overlay = _ensureOverlay();
  const paperList = overlay.querySelector('#zotero-save-paper-list');
  const folderList = overlay.querySelector('#zotero-save-folder-list');
  const paperCountEl = overlay.querySelector('#zotero-save-paper-count');
  const clearBtn = overlay.querySelector('#zotero-save-clear-papers');
  const folderLabelEl = overlay.querySelector('#zotero-save-folder-label');
  const statusEl = overlay.querySelector('#zotero-save-status');
  const saveBtn = overlay.querySelector('#zotero-save-do');
  const paperFilter = overlay.querySelector('#zotero-save-paper-filter');
  const folderFilter = overlay.querySelector('#zotero-save-folder-filter');

  let saveable = [];
  let inLibrary = [];
  let collections = [];
  let selected = new Set();
  let collectionKey = null;
  let paperQuery = '';
  let folderQuery = '';
  let closed = false;

  function cleanup(result) {
    if (closed) return result;
    closed = true;
    overlay.classList.add('hidden');
    overlay.classList.remove('zotero-save-sheet-enter');
    overlay.removeEventListener('click', onBackdrop);
    document.removeEventListener('keydown', onKey);
    paperList.onclick = null;
    folderList.onclick = null;
    paperFilter.oninput = null;
    folderFilter.oninput = null;
    overlay.querySelector('#zotero-save-sheet-close').onclick = null;
    overlay.querySelector('#zotero-save-cancel').onclick = null;
    clearBtn.onclick = null;
    saveBtn.onclick = null;
    return result;
  }

  function onBackdrop(e) {
    if (e.target === overlay) finish({ ok: false, cancelled: true });
  }
  function onKey(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      finish({ ok: false, cancelled: true });
    }
  }
  function finish(result) {
    resolvePromise(cleanup(result));
  }

  let resolvePromise;
  const done = new Promise((resolve) => { resolvePromise = resolve; });

  function folderDisplayPath(col) {
    if (!col) return 'folder';
    return String(col.path || col.name || 'folder')
      .replace(/ \/? /g, '/')
      .replace(/\/+/g, '/');
  }

  function updateFooter() {
    const n = selected.size;
    const dest = collectionKey
      ? folderDisplayPath(collections.find((c) => c.key === collectionKey))
      : 'Library root';
    saveBtn.disabled = n === 0;
    saveBtn.textContent = n === 0 ? 'Save' : `Save ${n} to ${dest}`;
    paperCountEl.textContent = n ? `${n} selected` : '';
    clearBtn.hidden = n === 0;
    folderLabelEl.textContent = dest;
  }

  function renderPapers() {
    const q = paperQuery.trim().toLowerCase();
    const match = (row) => {
      if (!q) return true;
      const hay = [
        row.title, row.authors, row.year, row.study_type,
        row.sourcing_tier_label, row.peer_review_status,
        String(row.citation_num),
      ].join(' ').toLowerCase();
      return hay.includes(q);
    };
    const parts = [];
    for (const src of saveable.filter(match)) {
      const on = selected.has(src.citation_num);
      parts.push(`<button type="button" class="research-seed-picker-item research-seed-picker-card${on ? ' is-selected' : ''}"
        role="option" aria-selected="${on ? 'true' : 'false'}" data-cite="${src.citation_num}">
        <span class="research-seed-picker-check" aria-hidden="true">${CHECK_SVG}</span>
        <div class="zotero-save-card-main">
          <div class="zotero-save-card-top">
            <span class="research-seed-picker-title">[${src.citation_num}] ${_esc(src.title)}</span>
          </div>
          ${_sourceMetaLine(src)}
          ${_sourceBadgesHtml(src)}
        </div>
      </button>`);
    }
    for (const src of inLibrary.filter(match)) {
      parts.push(`<div class="research-seed-picker-item research-seed-picker-card zotero-save-in-library" role="option" aria-disabled="true">
        <span class="research-seed-picker-check zotero-save-skip-check" aria-hidden="true">✓</span>
        <div class="zotero-save-card-main">
          <div class="zotero-save-card-top">
            <span class="research-seed-picker-title">[${src.citation_num}] ${_esc(src.title)}</span>
          </div>
          ${_sourceMetaLine(src)}
          ${_sourceBadgesHtml(src, { inLibrary: true })}
        </div>
      </div>`);
    }
    if (!parts.length) {
      paperList.innerHTML = `<div class="research-seed-picker-empty">${
        saveable.length || inLibrary.length ? 'No matches' : 'No saveable sources in this research'
      }</div>`;
      return;
    }
    paperList.innerHTML = parts.join('');
  }

  function renderFolders() {
    const q = folderQuery.trim().toLowerCase();
    const items = [
      { key: '', path: 'Library root', name: 'Library root', depth: 0, hint: 'Default — top level of your library' },
      ...collections
        .filter((c) => !q || (c.path || '').toLowerCase().includes(q) || (c.name || '').toLowerCase().includes(q))
        .map((c) => {
          const path = String(c.path || c.name || 'Untitled').replace(/ \/? /g, '/').replace(/\/+/g, '/');
          const depth = Number.isFinite(c.depth) ? c.depth : (path.includes('/') ? path.split('/').length - 1 : 0);
          return {
            key: c.key,
            path,
            name: c.name || path.split('/').pop(),
            depth,
            hint: depth > 0 ? c.name : '',
          };
        }),
    ];
    folderList.innerHTML = items.map((item) => {
      const selectedFolder = (collectionKey || '') === (item.key || '');
      const pad = item.key ? Math.min(item.depth || 0, 6) * 12 : 0;
      return `<button type="button" class="styled-list-pick-item zotero-save-folder-item${selectedFolder ? ' is-selected' : ''}"
        role="option" aria-selected="${selectedFolder ? 'true' : 'false'}" data-key="${_esc(item.key)}"
        style="padding-left:${12 + pad}px" title="${_esc(item.path)}">
        <span class="zotero-save-folder-icon">${FOLDER_SVG}</span>
        <span class="styled-list-pick-item-label zotero-save-folder-path">${_esc(item.path || item.name)}</span>
        ${!item.key && item.hint
          ? `<span class="styled-list-pick-item-hint">${_esc(item.hint)}</span>`
          : ''}
      </button>`;
    }).join('');
  }

  paperList.onclick = (e) => {
    const btn = e.target.closest('[data-cite]');
    if (!btn || btn.getAttribute('aria-disabled') === 'true') return;
    const num = parseInt(btn.getAttribute('data-cite'), 10);
    if (!(num > 0)) return;
    if (selected.has(num)) selected.delete(num);
    else selected.add(num);
    renderPapers();
    updateFooter();
  };
  folderList.onclick = (e) => {
    const btn = e.target.closest('[data-key]');
    if (!btn) return;
    const key = btn.getAttribute('data-key') || '';
    collectionKey = key || null;
    renderFolders();
    updateFooter();
  };
  paperFilter.oninput = () => {
    paperQuery = paperFilter.value || '';
    renderPapers();
  };
  folderFilter.oninput = () => {
    folderQuery = folderFilter.value || '';
    renderFolders();
  };
  clearBtn.onclick = () => {
    selected.clear();
    renderPapers();
    updateFooter();
  };
  overlay.querySelector('#zotero-save-sheet-close').onclick = () => finish({ ok: false, cancelled: true });
  overlay.querySelector('#zotero-save-cancel').onclick = () => finish({ ok: false, cancelled: true });
  overlay.addEventListener('click', onBackdrop);
  document.addEventListener('keydown', onKey);

  saveBtn.onclick = async () => {
    if (!selected.size) return;
    saveBtn.disabled = true;
    statusEl.hidden = false;
    statusEl.textContent = 'Saving…';
    try {
      const body = {
        scope: 'cited',
        citation_nums: Array.from(selected).sort((a, b) => a - b),
      };
      if (collectionKey) body.collection_key = collectionKey;
      const res = await fetch(`${apiBase}/api/research/${encodeURIComponent(sessionId)}/save-to-zotero`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(_detailMessage(data, 'Save failed'));
      const created = data.created || 0;
      const skipped = data.skipped_in_library
        ? ` (${data.skipped_in_library} already in library)`
        : '';
      uiModule.showToast?.(`Saved ${created} to Zotero${skipped}`, { duration: 4000, leadingIcon: 'check' });
      finish({ ok: true, created, skipped_in_library: data.skipped_in_library || 0 });
    } catch (err) {
      statusEl.textContent = err.message || 'Save failed';
      uiModule.showError?.(err.message || 'Save to Zotero failed');
      saveBtn.disabled = selected.size === 0;
      updateFooter();
    }
  };

  statusEl.hidden = true;
  statusEl.textContent = '';
  paperFilter.value = '';
  folderFilter.value = '';
  paperList.innerHTML = '<div class="research-seed-picker-loading">Loading sources…</div>';
  folderList.innerHTML = '<div class="styled-list-pick-empty">Loading folders…</div>';
  saveBtn.disabled = true;
  saveBtn.textContent = 'Save';

  overlay.classList.remove('hidden');
  overlay.classList.remove('zotero-save-sheet-enter');
  void overlay.offsetWidth;
  overlay.classList.add('zotero-save-sheet-enter');

  try {
    const [previewRes, colsRes] = await Promise.all([
      fetch(`${apiBase}/api/research/${encodeURIComponent(sessionId)}/save-to-zotero/preview?scope=cited`, {
        credentials: 'same-origin',
      }),
      fetch(`${apiBase}/api/zotero/collections`, { credentials: 'same-origin' }),
    ]);
    const preview = await previewRes.json().catch(() => ({}));
    if (!previewRes.ok) throw new Error(_detailMessage(preview, 'Could not load sources'));
    saveable = Array.isArray(preview.saveable) ? preview.saveable : [];
    inLibrary = Array.isArray(preview.in_library) ? preview.in_library : [];

    if (colsRes.ok) {
      const colsData = await colsRes.json().catch(() => ({}));
      collections = Array.isArray(colsData.collections) ? colsData.collections : [];
    } else {
      collections = [];
    }

    const initial = Array.isArray(opts.initialCitationNums) && opts.initialCitationNums.length
      ? opts.initialCitationNums.map((n) => parseInt(n, 10)).filter((n) => n > 0)
      : (preview.default_citation_nums || []);
    const saveableNums = new Set(saveable.map((s) => s.citation_num));
    selected = new Set(initial.filter((n) => saveableNums.has(n)));
    if (!selected.size && saveable.length) {
      for (const s of saveable) {
        if (s.cited) selected.add(s.citation_num);
      }
    }
    if (!selected.size && saveable.length) {
      selected.add(saveable[0].citation_num);
    }

    renderPapers();
    renderFolders();
    updateFooter();
    paperFilter.focus();
  } catch (err) {
    paperList.innerHTML = `<div class="research-seed-picker-empty">${_esc(err.message || 'Failed to load')}</div>`;
    folderList.innerHTML = '';
    uiModule.showError?.(err.message || 'Could not open Save to Zotero');
    finish({ ok: false, error: err.message || 'Failed to load' });
  }

  return done;
}

export default { openZoteroSaveSheet };
