/**
 * Project workspace quick open (Phase G8) — Ctrl+P fuzzy picker for files and links.
 */
import uiModule from '../ui.js';

const esc = uiModule.esc;

let _getFiles = async () => [];
let _getLinks = () => [];
let _onOpenFile = null;
let _onOpenLink = null;
let _overlay = null;
let _filter = '';
let _highlightIdx = 0;
let _results = [];
let _cachedPaths = [];

function _score(query, label, hint) {
  const q = query.toLowerCase();
  const l = label.toLowerCase();
  const h = (hint || '').toLowerCase();
  if (!q) return 1;
  if (l === q) return 100;
  if (l.startsWith(q)) return 80;
  if (l.includes(q)) return 60;
  if (h.includes(q)) return 40;
  return 0;
}

function _buildResults(query) {
  const items = [];
  for (const path of _cachedPaths) {
    if (typeof path !== 'string' || !path.trim()) continue;
    const label = path.split('/').pop() || path;
    const score = _score(query, path, label);
    if (score > 0 || !query) {
      items.push({ kind: 'depth', id: `file:${path}`, label, hint: path, score: score || 1 });
    }
  }
  for (const link of _getLinks?.() || []) {
    if (!link?.id) continue;
    const label = link.label || link.id;
    const hint = link.type ? `${link.type} · ${link.id}` : link.id;
    const score = _score(query, label, hint);
    if (score > 0 || !query) {
      items.push({ kind: 'breadth', id: link.id, label, hint, meta: link.meta, score: score || 1 });
    }
  }
  items.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
  return items.slice(0, 40);
}

function _ensureOverlay() {
  if (_overlay) return _overlay;
  _overlay = document.createElement('div');
  _overlay.id = 'project-quick-open-overlay';
  _overlay.className = 'modal project-quick-open-overlay hidden';
  _overlay.innerHTML =
    '<div class="modal-content project-quick-open-box" role="dialog" aria-modal="true" aria-labelledby="project-quick-open-title">' +
      '<div class="project-quick-open-head">' +
        '<input type="search" id="project-quick-open-input" class="project-quick-open-input" ' +
          'placeholder="Open file or link…" autocomplete="off" spellcheck="false" aria-label="Quick open" />' +
        '<span class="project-quick-open-kbd">Ctrl+P</span>' +
      '</div>' +
      '<div id="project-quick-open-list" class="project-quick-open-list" role="listbox"></div>' +
      '<div class="project-quick-open-foot">' +
        '<span>↑↓ navigate · Enter open · Esc close</span>' +
      '</div>' +
    '</div>';
  document.body.appendChild(_overlay);
  _overlay.addEventListener('click', (e) => {
    if (e.target === _overlay) close();
  });
  _overlay.querySelector('#project-quick-open-input')?.addEventListener('input', (e) => {
    _filter = e.target.value || '';
    _highlightIdx = 0;
    _renderList();
  });
  _overlay.querySelector('#project-quick-open-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _highlightIdx = Math.min(_highlightIdx + 1, Math.max(0, _results.length - 1));
      _renderList();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      _highlightIdx = Math.max(_highlightIdx - 1, 0);
      _renderList();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const pick = _results[_highlightIdx];
      if (pick) void _pick(pick);
    }
  });
  _overlay.querySelector('#project-quick-open-list')?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-idx]');
    if (!row) return;
    const idx = parseInt(row.dataset.idx, 10);
    const pick = _results[idx];
    if (pick) void _pick(pick);
  });
  return _overlay;
}

function _renderList() {
  const list = _overlay?.querySelector('#project-quick-open-list');
  if (!list) return;
  _results = _buildResults(_filter.trim());
  if (!_results.length) {
    list.innerHTML = `<div class="project-quick-open-empty">${esc(_filter ? 'No matches' : 'No files or links in this project')}</div>`;
    return;
  }
  list.innerHTML = _results.map((item, idx) => {
    const icon = item.kind === 'depth' ? '◇' : '◆';
    const cls = item.kind === 'depth' ? 'project-tab--depth' : 'project-tab--breadth';
    const active = idx === _highlightIdx ? ' active' : '';
    return `<button type="button" class="project-quick-open-row${active} ${cls}" data-idx="${idx}" role="option">` +
      `<span class="project-quick-open-icon" aria-hidden="true">${icon}</span>` +
      `<span class="project-quick-open-label">${esc(item.label)}</span>` +
      `<span class="project-quick-open-hint">${esc(item.hint)}</span>` +
      `</button>`;
  }).join('');
  const activeRow = list.querySelector('.project-quick-open-row.active');
  activeRow?.scrollIntoView({ block: 'nearest' });
}

async function _pick(item) {
  close();
  if (item.kind === 'depth' && item.hint) {
    await _onOpenFile?.(item.hint);
  } else if (item.kind === 'breadth') {
    _onOpenLink?.(item.id, item.meta || { label: item.label });
  }
}

export async function open() {
  const panel = document.getElementById('project-workspace-panel');
  if (!panel || panel.classList.contains('hidden')) return;
  _ensureOverlay();
  _filter = '';
  _highlightIdx = 0;
  try {
    _cachedPaths = await _getFiles();
  } catch {
    _cachedPaths = [];
  }
  _overlay.classList.remove('hidden');
  _overlay.style.display = '';
  _renderList();
  const input = _overlay.querySelector('#project-quick-open-input');
  if (input) {
    input.value = '';
    input.focus();
  }
}

export function close() {
  if (!_overlay) return;
  _overlay.classList.add('hidden');
  _overlay.style.display = 'none';
}

export function mount({ getFiles, getLinks, onOpenFile, onOpenLink } = {}) {
  _getFiles = getFiles || (async () => []);
  _getLinks = getLinks || (() => []);
  _onOpenFile = onOpenFile || null;
  _onOpenLink = onOpenLink || null;
}

export function unmount() {
  close();
  _getFiles = async () => [];
  _getLinks = () => [];
  _onOpenFile = null;
  _onOpenLink = null;
}

export default { mount, unmount, open, close };
