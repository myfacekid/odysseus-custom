/**
 * Generic tab strip for project center pane (Phase G3/G6/G7).
 */
import uiModule from '../ui.js';

const esc = uiModule.esc;
const MAX_TABS = 10;

let _strip = null;
let _tabs = [];
let _activeId = null;
let _onSelect = null;
let _onClose = null;
let _onChange = null;
let _dragId = null;
let _overflowBtn = null;
let _overflowMenu = null;

function _emitChange() {
  if (_onChange) _onChange(_tabs.slice(), _activeId);
}

function _moveTab(fromId, beforeId) {
  const fromIdx = _tabs.findIndex((t) => t.id === fromId);
  const toIdx = _tabs.findIndex((t) => t.id === beforeId);
  if (fromIdx < 0 || toIdx < 0 || fromIdx === toIdx) return;
  const [tab] = _tabs.splice(fromIdx, 1);
  _tabs.splice(toIdx, 0, tab);
  _render();
  _emitChange();
}

function _bindDragDrop() {
  if (!_strip) return;
  _strip.querySelectorAll('.project-center-tab').forEach((btn) => {
    btn.addEventListener('dragstart', (e) => {
      if (e.target.closest('[data-close-tab]') || e.target.closest('[data-pin-tab]')) {
        e.preventDefault();
        return;
      }
      _dragId = btn.dataset.tabId;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', _dragId || '');
      btn.classList.add('dragging');
    });
    btn.addEventListener('dragend', () => {
      btn.classList.remove('dragging');
      _dragId = null;
    });
    btn.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });
    btn.addEventListener('drop', (e) => {
      e.preventDefault();
      const targetId = btn.dataset.tabId;
      if (_dragId && targetId && _dragId !== targetId) _moveTab(_dragId, targetId);
    });
  });
}

function _render() {
  if (!_strip) return;
  _strip.innerHTML = _tabs.map((t) => {
    const active = t.id === _activeId;
    const cls = [
      'project-center-tab',
      t.kind === 'depth' ? 'project-tab--depth' : 'project-tab--breadth',
      active ? 'active' : '',
      t.pinned ? 'is-pinned' : '',
    ].filter(Boolean).join(' ');
    const icon = t.kind === 'depth' ? '◇' : '◆';
    const dirtyDot = t.dirty
      ? '<span class="project-center-tab-dirty" aria-label="Unsaved changes" title="Unsaved">●</span>'
      : '';
    return `<button type="button" role="tab" class="${cls}" data-tab-id="${esc(t.id)}" draggable="true" ` +
      `title="${esc(t.label)}" aria-selected="${active ? 'true' : 'false'}">` +
      `<span class="project-center-tab-pin${t.pinned ? ' pinned' : ''}" data-pin-tab="${esc(t.id)}" ` +
        `aria-label="${t.pinned ? 'Unpin tab' : 'Pin tab'}" title="${t.pinned ? 'Unpin' : 'Pin'}">` +
        `${t.pinned ? '▪' : '○'}</span>` +
      `<span class="project-center-tab-icon" aria-hidden="true">${icon}</span>` +
      `<span class="project-center-tab-label">${esc(t.shortLabel || t.label)}</span>` +
      dirtyDot +
      `<span class="project-center-tab-close" data-close-tab="${esc(t.id)}" aria-label="Close tab">×</span>` +
      `</button>`;
  }).join('');

  _strip.querySelectorAll('.project-center-tab').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      if (e.target.closest('[data-close-tab]') || e.target.closest('[data-pin-tab]')) return;
      const id = btn.dataset.tabId;
      if (id) _activate(id, { user: true });
    });
    btn.addEventListener('mousedown', (e) => {
      if (e.button !== 1) return;
      e.preventDefault();
      const id = btn.dataset.tabId;
      if (id) closeTab(id);
    });
  });
  _strip.querySelectorAll('[data-close-tab]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const id = el.dataset.closeTab;
      if (id) closeTab(id);
    });
  });
  _strip.querySelectorAll('[data-pin-tab]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const id = el.dataset.pinTab;
      if (id) togglePin(id);
    });
  });
  _bindDragDrop();
  _syncOverflowButton();
}

function _closeOverflowMenu() {
  if (!_overflowMenu) return;
  _overflowMenu.remove();
  _overflowMenu = null;
  document.removeEventListener('click', _onOverflowOutside, true);
  document.removeEventListener('keydown', _onOverflowEscape, true);
}

function _onOverflowOutside(e) {
  if (_overflowMenu?.contains(e.target) || _overflowBtn?.contains(e.target)) return;
  _closeOverflowMenu();
}

function _onOverflowEscape(e) {
  if (e.key !== 'Escape') return;
  e.preventDefault();
  _closeOverflowMenu();
}

function _syncOverflowButton() {
  if (!_overflowBtn) return;
  const hidden = _tabs.length < 2;
  _overflowBtn.classList.toggle('hidden', hidden);
  _overflowBtn.disabled = hidden;
}

function _openOverflowMenu() {
  _closeOverflowMenu();
  if (!_overflowBtn || _tabs.length < 2) return;

  const menu = document.createElement('div');
  menu.id = 'project-tab-overflow-menu';
  menu.className = 'doc-overflow-menu open project-tab-overflow-menu';
  menu.setAttribute('role', 'menu');

  for (const t of _tabs) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'doc-overflow-item project-tab-overflow-item';
    item.dataset.tabId = t.id;
    item.setAttribute('role', 'menuitem');
    const icon = t.kind === 'depth' ? '◇' : '◆';
    const dirty = t.dirty ? ' ●' : '';
    item.innerHTML =
      `<span class="project-tab-overflow-kind">${icon}</span>` +
      `<span class="project-tab-overflow-label">${esc(t.shortLabel || t.label)}${dirty}</span>` +
      (t.id === _activeId ? '<span class="overflow-active-dot"></span>' : '');
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      _closeOverflowMenu();
      _activate(t.id, { user: true });
    });
    menu.appendChild(item);
  }

  const sep = document.createElement('div');
  sep.className = 'project-tab-overflow-sep';
  menu.appendChild(sep);

  const closeOthers = document.createElement('button');
  closeOthers.type = 'button';
  closeOthers.className = 'doc-overflow-item';
  closeOthers.textContent = 'Close other tabs';
  closeOthers.addEventListener('click', (e) => {
    e.stopPropagation();
    _closeOverflowMenu();
    closeOtherTabs(_activeId);
  });
  menu.appendChild(closeOthers);

  const closeRight = document.createElement('button');
  closeRight.type = 'button';
  closeRight.className = 'doc-overflow-item';
  closeRight.textContent = 'Close tabs to the right';
  closeRight.disabled = !_activeId || _tabs.findIndex((t) => t.id === _activeId) >= _tabs.length - 1;
  closeRight.addEventListener('click', (e) => {
    e.stopPropagation();
    _closeOverflowMenu();
    closeTabsToRight(_activeId);
  });
  menu.appendChild(closeRight);

  document.body.appendChild(menu);
  _overflowMenu = menu;
  const rect = _overflowBtn.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.right = `${Math.max(8, window.innerWidth - rect.right)}px`;
  menu.style.left = 'auto';
  menu.style.zIndex = '9999';

  setTimeout(() => {
    document.addEventListener('click', _onOverflowOutside, true);
    document.addEventListener('keydown', _onOverflowEscape, true);
  }, 0);
}

export function closeOtherTabs(keepId) {
  if (!keepId) return;
  [..._tabs].filter((t) => t.id !== keepId).forEach((t) => closeTab(t.id));
}

export function closeTabsToRight(fromId) {
  const idx = _tabs.findIndex((t) => t.id === fromId);
  if (idx < 0) return;
  [..._tabs.slice(idx + 1)].forEach((t) => closeTab(t.id));
}

export function setTabDirty(id, dirty) {
  const tab = _tabs.find((t) => t.id === id);
  if (!tab || !!tab.dirty === !!dirty) return;
  tab.dirty = !!dirty;
  _render();
}

export function bindOverflow(btn) {
  _overflowBtn = btn;
  if (!btn || btn.dataset.overflowBound) return;
  btn.dataset.overflowBound = '1';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (_overflowMenu) _closeOverflowMenu();
    else _openOverflowMenu();
  });
  _syncOverflowButton();
}

function _activate(id, { user = false, emit = true } = {}) {
  if (!_tabs.some((t) => t.id === id)) return;
  _activeId = id;
  _render();
  const tab = _tabs.find((t) => t.id === id);
  if (_onSelect && tab) _onSelect(tab, { user, restored: false });
  if (emit) _emitChange();
}

export function init(stripEl, { onSelect, onClose, onChange } = {}) {
  _strip = stripEl;
  _onSelect = onSelect || null;
  _onClose = onClose || null;
  _onChange = onChange || null;
  _tabs = [];
  _activeId = null;
  _render();
}

export function openTab({ id, kind, label, shortLabel, meta, pinned, activate = true }) {
  if (!id || !kind) return null;
  const existing = _tabs.find((t) => t.id === id);
  if (existing) {
    if (meta) existing.meta = { ...existing.meta, ...meta };
    if (pinned !== undefined) existing.pinned = !!pinned;
    if (activate !== false) _activate(id);
    else _emitChange();
    return existing;
  }
  if (_tabs.length >= MAX_TABS) {
    const drop = _tabs.find((t) => t.id !== _activeId && !t.pinned);
    if (!drop) return null;
    closeTab(drop.id, { evict: true });
  }
  const tab = {
    id,
    kind,
    label: label || id,
    shortLabel: shortLabel || (label || id).split('/').pop() || id.replace(/^[^:]+:/, ''),
    meta: meta || undefined,
    pinned: !!pinned,
    dirty: false,
  };
  _tabs.push(tab);
  if (activate !== false) _activate(id);
  else {
    _render();
    _emitChange();
  }
  return tab;
}

export function togglePin(id) {
  const tab = _tabs.find((t) => t.id === id);
  if (!tab) return;
  tab.pinned = !tab.pinned;
  _render();
  _emitChange();
}

export function closeTab(id, { silent = false, evict = false } = {}) {
  const idx = _tabs.findIndex((t) => t.id === id);
  if (idx < 0) return;
  const closed = _tabs[idx];
  _tabs.splice(idx, 1);
  if (_activeId === id) {
    _activeId = _tabs[idx]?.id || _tabs[idx - 1]?.id || null;
    if (_activeId) _activate(_activeId, { user: true, emit: false });
    else if (_onSelect) _onSelect(null, { user: true });
  }
  _render();
  if (_onClose && (!silent || evict)) _onClose(closed, { evict: !!evict });
  _emitChange();
}

export function restoreTabs(tabs, activeId) {
  _tabs = (Array.isArray(tabs) ? tabs : [])
    .filter((t) => t && t.id && (t.kind === 'depth' || t.kind === 'breadth'))
    .slice(0, MAX_TABS)
    .map((t) => ({
      id: t.id,
      kind: t.kind,
      label: t.label || t.id,
      shortLabel: t.shortLabel || (t.label || t.id).split('/').pop() || t.id.replace(/^[^:]+:/, ''),
      meta: t.meta || undefined,
      pinned: !!t.pinned,
      dirty: false,
    }));
  _activeId = _tabs.some((t) => t.id === activeId) ? activeId : (_tabs[0]?.id || null);
  _render();
  if (_activeId) {
    const tab = _tabs.find((t) => t.id === _activeId);
    if (_onSelect && tab) _onSelect(tab, { user: false, restored: true });
  } else if (_onSelect) _onSelect(null, { user: false, restored: true });
  _emitChange();
}

export function getActiveTab() {
  return _tabs.find((t) => t.id === _activeId) || null;
}

export function getTabs() {
  return _tabs.slice();
}

export function reset() {
  _closeOverflowMenu();
  _tabs = [];
  _activeId = null;
  _render();
  if (_onSelect) _onSelect(null, { user: false });
  _emitChange();
}

export default {
  init,
  openTab,
  closeTab,
  togglePin,
  restoreTabs,
  getActiveTab,
  getTabs,
  reset,
  setTabDirty,
  closeOtherTabs,
  closeTabsToRight,
  bindOverflow,
};
