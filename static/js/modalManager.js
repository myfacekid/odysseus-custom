/**
 * ModalManager — unified open/minimize/close behavior for tool modals.
 *
 * Goals:
 *  - Tab-down (swipe) and the `_` button MINIMIZE: modal hidden, JS state preserved.
 *  - The ✕ button CLOSES: tears down via the registered closeFn.
 *  - Sidebar/rail click handler: closed → open, minimized → restore, open → minimize.
 *  - Rail icon shows a "minimized" badge when state is held.
 *
 * Usage from a tool module:
 *
 *   import * as Modals from './modalManager.js';
 *
 *   // After building the modal element and adding it to the body:
 *   Modals.register('gallery-modal', {
 *     railBtnId: 'tool-gallery-btn',
 *     restoreFn: () => { ...whatever the tool needs to do when un-hiding... },
 *     closeFn:   () => { ...full teardown — remove modal element etc... },
 *   });
 *
 *   // From the sidebar/rail button click handler:
 *   if (!Modals.toggle('gallery-modal')) {
 *     // No registered modal — build and open it fresh.
 *     openGallery();
 *   }
 */

import { suspendDock, resumeDock, clearRightDock, applyEdgeDock } from './modalSnap.js';
import { dismissOrRemove } from './escMenuStack.js';

const _state = new Map(); // id -> { restoreFn, closeFn, railBtnId, isMinimized, restoreMinHeight }

const _rememberedDockKey = (id) => `nobody-modal-remembered-dock-${id}`;
function _rememberDock(id, side) {
  if (!id || !side) return;
  try { localStorage.setItem(_rememberedDockKey(id), side); } catch (_) {}
}
function _forgetDock(id) {
  if (!id) return;
  try { localStorage.removeItem(_rememberedDockKey(id)); } catch (_) {}
}
function _getRememberedDock(id) {
  try {
    const side = localStorage.getItem(_rememberedDockKey(id));
    return (side === 'left' || side === 'right') ? side : null;
  } catch (_) {
    return null;
  }
}
function _applyRememberedDock(id) {
  const side = _getRememberedDock(id);
  if (!side) return;
  const modal = document.getElementById(id);
  if (!modal || modal.classList.contains('hidden') || modal.classList.contains('modal-minimized')) return;
  try { applyEdgeDock(modal, side); } catch (e) { console.warn('apply remembered dock failed', e); }
}

// Monotonic stacking counter so the most-recently-surfaced tool window always
// sits on top. Tool modals otherwise carry fixed CSS z-indexes (base .modal
// = 250, cookbook/theme = 260, …), so restoring one from the dock could leave
// it BEHIND an already-open tool with a higher static z-index. Start above
// those statics and bump on every bring-to-front.
let _modalTopZ = 300;
function _bringToFront(modal) {
  if (modal) modal.style.setProperty('z-index', String(++_modalTopZ), 'important');
}

function _emitModalOpened(id, modal) {
  try {
    window.dispatchEvent(new CustomEvent('nobody:modal-opened', {
      detail: { id, modal },
    }));
  } catch (_) {}
}

function _captureRestoreHeight(modal, state) {
  if (!modal || !state) return;
  const content = modal.querySelector('.modal-content');
  if (!content) return;
  if (modal.id === 'email-lib-modal'
      && (modal.classList.contains('modal-left-docked')
          || modal.classList.contains('email-snap-left')
          || document.body.classList.contains('email-doc-split-active'))) {
    delete state.restoreMinHeight;
    return;
  }
  const rect = content.getBoundingClientRect();
  if (!rect || rect.height < 120) return;
  const maxHeight = Math.max(180, window.innerHeight - 24);
  const minHeight = modal.id === 'email-lib-modal' && window.innerWidth > 768
    ? Math.min(560, maxHeight)
    : 0;
  state.restoreMinHeight = `${Math.round(Math.max(minHeight, Math.min(rect.height, maxHeight)))}px`;
}

function _applyRestoreHeight(modal, state) {
  if (!modal || !state?.restoreMinHeight) return;
  const content = modal.querySelector('.modal-content');
  if (!content) return;
  const maxHeight = Math.max(180, window.innerHeight - 24);
  const requested = parseInt(state.restoreMinHeight, 10);
  const minHeight = modal.id === 'email-lib-modal' && window.innerWidth > 768
    ? Math.min(560, maxHeight)
    : 0;
  const height = Number.isFinite(requested) ? Math.max(minHeight, Math.min(requested, maxHeight)) : null;
  if (height) content.style.minHeight = `${height}px`;
}

function _setBadge(btnIds, on) {
  if (!btnIds) return;
  const ids = Array.isArray(btnIds) ? btnIds : [btnIds];
  for (const id of ids) {
    const btn = document.getElementById(id);
    if (btn) btn.classList.toggle('rail-minimized', on);
  }
}

// ── Minimized strip — corner tray of minimized tool windows ──

const _LABELS = {
  'cookbook-modal':    { label: 'Cookbook',  icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>' },
  'calendar-modal':    { label: 'Calendar',  icon: 'M3 4h18v18H3zM16 2v4M8 2v4M3 10h18' },
  'gallery-modal':     { label: 'Gallery',   icon: 'M3 3h18v18H3zM8.5 8.5l3 3M21 15l-5-5L5 21' },
  'tasks-modal':       { label: 'Tasks',     icon: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11' },
  'doclib-modal':      { label: 'Library',   icon: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2zM9 7h6M9 11h4' },
  'project-files-sheet': { label: 'Project files', icon: 'M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z' },
  // Full SVG markup (not a single path-d) — the rounded-lobe brain needs
  // three sub-paths, which the dock renderer supports when the icon string
  // contains '<'.
  'memory-modal':      { label: 'Memory',    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/></svg>' },
  'knowledge-modal':   { label: 'Links',     icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><line x1="7" y1="12" x2="17" y2="7"/><line x1="7" y1="12" x2="17" y2="17"/></svg>' },
  'notes-panel':       { label: 'Todos',     icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5"/><path d="M8 17.5 15.5 10l2.5 2.5L10.5 20H8z"/></svg>' },
  'email-lib-modal':   { label: 'Email',     icon: 'M2 4h20v16H2zM22 7l-9.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7' },
  // The Prompt window (characters / inject / group). Syringe = "prompt" icon,
  // matching its title bar. Full SVG markup (multi-path) per the dock renderer.
  'custom-preset-modal': { label: 'Prompt',  icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 2 4 4"/><path d="m17 7 3-3"/><path d="M19 9 8.7 19.3c-1 1-2.5 1-3.4 0l-.6-.6c-1-1-1-2.5 0-3.4L15 5"/><path d="m9 11 4 4"/><path d="m5 19-3 3"/><path d="m14 4 6 6"/></svg>' },
  'research-overlay':  { label: 'Research',  icon: 'M3 11a8 8 0 1 0 16 0a8 8 0 1 0-16 0M21 21l-4.35-4.35M11 8L11 14M8 11L14 11' },
  'theme-modal':       { label: 'Theme',     icon: 'M12 2a10 10 0 1 0 10 10c0-1-1-2-2-2h-2a2 2 0 0 1 0-4h1a2 2 0 0 0 0-4 10 10 0 0 0-7-2zM7.5 12a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM12 7.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM16.5 12a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z' },
  'compare-model-overlay': { label: 'Compare',  icon: 'M8 3v18M16 3v18M3 8h5M16 16h5' },
  'settings-modal':    { label: 'Settings',  icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.4.4.62.94.6 1.51V11a2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z' },
  'ge-shortcuts-modal':{ label: 'Shortcuts', icon: 'M2 6h20v12H2zM6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10' },
  // Virtual id — the doc editor pane isn't a modal, but it minimizes via
  // the same strip infrastructure.
  'doc-panel':         { label: 'Document', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8' },
};

// Stable display order across minimize → restore → minimize cycles.
let _dockOrder = [];
let _stripExpanded = false;
let _stripOutsideClickWired = false;
let _stripPill = null;
let _stripPanel = null;
let _stripCountEl = null;

function _ensureDock() {
  let dock = document.getElementById('minimized-dock');
  if (dock) {
    if (!_stripPanel) _stripPanel = dock.querySelector('.minimized-strip-panel');
    if (!_stripPill) _stripPill = dock.querySelector('.minimized-strip-pill');
    if (!_stripCountEl) _stripCountEl = dock.querySelector('.minimized-strip-count');
    // Rebuild if a legacy empty dock node is still hanging around.
    if (_stripPanel && _stripPill && _stripCountEl) return dock;
    dock.remove();
  }

  // Drop legacy free-float dock positions so they never resurrect over the prompt.
  try {
    localStorage.removeItem('nobody.mobileDockState.v1');
  } catch {}

  dock = document.createElement('div');
  dock.id = 'minimized-dock';

  _stripPanel = document.createElement('div');
  _stripPanel.className = 'minimized-strip-panel';
  _stripPanel.setAttribute('role', 'list');

  _stripPill = document.createElement('button');
  _stripPill.className = 'minimized-strip-pill';
  _stripPill.type = 'button';
  _stripPill.setAttribute('aria-expanded', 'false');
  _stripPill.setAttribute('aria-label', 'Minimized tools');

  _stripCountEl = document.createElement('span');
  _stripCountEl.className = 'minimized-strip-count';
  _stripCountEl.textContent = '0';

  const labelEl = document.createElement('span');
  labelEl.className = 'minimized-strip-label';
  labelEl.textContent = 'minimized';

  _stripPill.appendChild(_stripCountEl);
  _stripPill.appendChild(labelEl);

  dock.appendChild(_stripPanel);
  dock.appendChild(_stripPill);
  document.body.appendChild(dock);

  _stripPill.addEventListener('click', (e) => {
    e.stopPropagation();
    _stripExpanded = !_stripExpanded;
    dock.classList.toggle('expanded', _stripExpanded);
    _stripPill.setAttribute('aria-expanded', String(_stripExpanded));
  });

  if (!_stripOutsideClickWired) {
    _stripOutsideClickWired = true;
    document.addEventListener('click', (e) => {
      if (!_stripExpanded) return;
      const d = document.getElementById('minimized-dock');
      if (d && !d.contains(e.target)) {
        _stripExpanded = false;
        d.classList.remove('expanded');
        if (_stripPill) _stripPill.setAttribute('aria-expanded', 'false');
      }
    });
  }

  return dock;
}

function _iconHtml(meta) {
  return (typeof meta.icon === 'string' && meta.icon.includes('<'))
    ? meta.icon
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${meta.icon || ''}"/></svg>`;
}

function _renderDock() {
  const dock = _ensureDock();
  if (!_stripPanel) _stripPanel = dock.querySelector('.minimized-strip-panel');
  if (!_stripPill) _stripPill = dock.querySelector('.minimized-strip-pill');
  if (!_stripCountEl) _stripCountEl = dock.querySelector('.minimized-strip-count');
  if (!_stripPanel || !_stripPill || !_stripCountEl) return;

  const minimizedIds = [..._state.entries()]
    .filter(([, s]) => s.isMinimized)
    .map(([id]) => id);

  // Keep order for every still-registered modal so re-minimize restores the slot.
  _dockOrder = _dockOrder.filter((id) => _state.has(id));
  for (const id of minimizedIds) {
    if (!_dockOrder.includes(id)) _dockOrder.push(id);
  }
  const renderIds = _dockOrder.filter((id) => minimizedIds.includes(id));

  // Preserve external data-* attrs (e.g. email slot badges) across re-render.
  const oldData = new Map();
  dock.querySelectorAll('.minimized-strip-row[data-modal-id]').forEach((row) => {
    const id = row.dataset.modalId;
    if (!id) return;
    const data = {};
    for (const a of row.attributes) {
      if (a.name.startsWith('data-') && a.name !== 'data-modal-id') {
        data[a.name] = a.value;
      }
    }
    if (Object.keys(data).length) oldData.set(id, data);
  });

  if (!renderIds.length) {
    _stripPanel.innerHTML = '';
    dock.classList.remove('active', 'expanded');
    _stripExpanded = false;
    _stripPill.setAttribute('aria-expanded', 'false');
    _stripCountEl.textContent = '0';
    return;
  }

  dock.classList.add('active');
  _stripCountEl.textContent = String(renderIds.length);
  _stripPanel.innerHTML = '';

  for (const id of renderIds) {
    const meta = _LABELS[id] || { label: id, icon: '' };
    const row = document.createElement('div');
    row.className = 'minimized-strip-row';
    row.setAttribute('role', 'listitem');
    row.dataset.modalId = id;
    row.title = `Restore ${meta.label}`;

    const prevAttrs = oldData.get(id);
    if (prevAttrs) {
      for (const [name, val] of Object.entries(prevAttrs)) {
        row.setAttribute(name, val);
      }
    }

    const iconWrap = document.createElement('span');
    iconWrap.className = 'minimized-strip-row-icon';
    iconWrap.innerHTML = _iconHtml(meta);

    const main = document.createElement('span');
    main.className = 'minimized-strip-row-main';
    const title = document.createElement('span');
    title.className = 'minimized-strip-row-title';
    title.textContent = meta.label;
    main.appendChild(title);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'minimized-strip-row-x';
    closeBtn.title = 'Close';
    closeBtn.setAttribute('aria-label', `Close ${meta.label}`);
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      close(id);
    });

    row.addEventListener('click', () => { restore(id); });

    row.appendChild(iconWrap);
    row.appendChild(main);
    row.appendChild(closeBtn);
    _stripPanel.appendChild(row);
  }
}

// Tracks which _LABELS entries were created by `register(..., {label, icon})`
// (vs. the built-in static ones). Only these should be removed in
// `unregister` — built-in labels stay for the lifetime of the page.
const _customLabelIds = new Set();

export function register(id, { restoreFn, closeFn, railBtnId, sidebarBtnId, label, icon } = {}) {
  // railBtnId can be a single id or an array; we accept both rail and sidebar separately too.
  const btnIds = [];
  if (railBtnId) btnIds.push(...(Array.isArray(railBtnId) ? railBtnId : [railBtnId]));
  if (sidebarBtnId) btnIds.push(...(Array.isArray(sidebarBtnId) ? sidebarBtnId : [sidebarBtnId]));
  _state.set(id, {
    restoreFn: restoreFn || (() => {}),
    closeFn:   closeFn   || (() => {}),
    btnIds,
    isMinimized: false,
    restoreMinHeight: '',
  });
  // Auto-stack: whichever modal becomes visible last sits on top of any
  // already-open modals. The various tool open() functions (gallery,
  // memory/brain, tasks, etc.) all just toggle `.hidden` or `display` —
  // observe both and bump the z-index on the visible→hidden→visible
  // transition. Idempotent on re-register.
  const _modalEl = document.getElementById(id);
  if (_modalEl && !_modalEl._mmAutoStackObs) {
    const _isVisible = () => !_modalEl.classList.contains('hidden')
        && getComputedStyle(_modalEl).display !== 'none';
    _modalEl._mmAutoStackLast = _isVisible();
    const obs = new MutationObserver(() => {
      const vis = _isVisible();
      if (vis && !_modalEl._mmAutoStackLast) {
        _bringToFront(_modalEl);
        _applyRememberedDock(id);
        _emitModalOpened(id, _modalEl);
      }
      _modalEl._mmAutoStackLast = vis;
    });
    obs.observe(_modalEl, { attributes: true, attributeFilter: ['class', 'style'] });
    _modalEl._mmAutoStackObs = obs;
    // If it's already visible at register time (e.g. modal opened before
    // register completes), bump it once now too.
    if (_modalEl._mmAutoStackLast) {
      _bringToFront(_modalEl);
      _applyRememberedDock(id);
      _emitModalOpened(id, _modalEl);
    }
  }
  // Allow callers to supply their own chip label/icon (path d="..." or
  // full <svg>...</svg>) so ephemeral things like FX popups can dock
  // into the same chain without needing an entry in the built-in
  // _LABELS table. Track the id so `unregister` can drop the entry
  // and avoid an unbounded-growth leak (v2 review HIGH-3).
  if (label || icon) {
    _LABELS[id] = { label: label || id, icon: icon || '' };
    _customLabelIds.add(id);
  }
  // If a docked window was minimized and its chip was closed, reopen the
  // window in the same side dock next time. Defer until the caller finishes
  // removing `.hidden` / applying initial display styles.
  if (_getRememberedDock(id)) {
    requestAnimationFrame(() => requestAnimationFrame(() => _applyRememberedDock(id)));
  }
}

export function unregister(id) {
  const s = _state.get(id);
  if (s) _setBadge(s.btnIds, false);
  _state.delete(id);
  // Drop any per-popup _LABELS entry created at register-time.
  if (_customLabelIds.has(id)) {
    delete _LABELS[id];
    _customLabelIds.delete(id);
  }
  // Also prune the order list so a re-rendered strip doesn't try
  // to draw a row for a now-dead id.
  const idx = _dockOrder.indexOf(id);
  if (idx >= 0) _dockOrder.splice(idx, 1);
  _renderDock();
}

export function isRegistered(id)  { return _state.has(id); }
export function isMinimized(id)   { return _state.get(id)?.isMinimized === true; }

export function minimize(id) {
  // Lazy-register if a known modal isn't yet registered (e.g. user clicked `_`
  // on a tool that doesn't pre-register itself).
  if (!_state.has(id) && _AUTO_WIRE[id]) _autoRegister(id);
  const s = _state.get(id);
  if (!s) return false;
  // The id may refer to a virtual tool (e.g. the document panel) that has no
  // actual modal element — in that case we just track the minimized state
  // and let the chip drive restore/close via the registered functions.
  const modal = document.getElementById(id);
  if (modal) {
    _captureRestoreHeight(modal, s);
    // If this window is edge-docked (right/left), SUSPEND the dock: release
    // the body push so the chat returns to full width while the window is
    // minimized, but keep the dock so restoring the chip snaps it back in.
    if (modal.classList.contains('modal-right-docked')
        || modal.classList.contains('modal-left-docked')
        || modal.classList.contains('email-snap-left')) {
      try { suspendDock(modal); } catch (e) { console.warn('suspendDock on minimize failed', e); }
    }
    modal.classList.add('hidden');
    modal.classList.add('modal-minimized');
    const content = modal.querySelector('.modal-content');
    if (content) {
      content.classList.remove('sheet-ready', 'modal-closing');
      content.style.transform = '';
      content.style.transition = '';
      content.style.animation = '';
    }
  }
  s.isMinimized = true;
  _setBadge(s.btnIds, true);
  _ensureDock();
  _renderDock();
  return true;
}

export function restore(id) {
  const s = _state.get(id);
  if (!s) return false;
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.remove('hidden', 'modal-minimized');
    modal.style.display = '';
    _applyRestoreHeight(modal, s);
    // Surface above any already-open tool window — restoring from the dock
    // should bring this tool to the front, not leave it stuck behind one with
    // a higher static z-index.
    _bringToFront(modal);
    // If the window was edge-docked when minimized, re-apply the dock so the
    // chat nudges back in and the window returns exactly where it was.
    try { resumeDock(modal); } catch (e) { console.warn('resumeDock on restore failed', e); }
    _emitModalOpened(id, modal);
  }
  s.isMinimized = false;
  _setBadge(s.btnIds, false);
  _renderDock();
  try { s.restoreFn(); } catch (e) { console.error('restoreFn:', e); }
  return true;
}

/**
 * If the modal is currently MINIMIZED, restore it and return true.
 * Otherwise return false so the caller falls through to its own
 * open/close handling. We deliberately do NOT minimize on toggle —
 * that's the `_` button's job, not the rail/sidebar button's job.
 */
export function toggle(id) {
  const s = _state.get(id);
  if (!s) return false;
  const modal = document.getElementById(id);
  if (!modal) { _state.delete(id); return false; }
  if (s.isMinimized) return restore(id);
  return false;
}

/** Full close — calls closeFn (which should tear down DOM + state) and unregisters. */
export function close(id) {
  const s = _state.get(id);
  if (!s) return;
  const modalBeforeClose = document.getElementById(id);
  const contentBeforeClose = modalBeforeClose?.querySelector?.('.modal-content');
  const suspendedDockSide = contentBeforeClose?._dockSuspended
    || (modalBeforeClose?.classList?.contains('modal-left-docked') ? 'left'
        : modalBeforeClose?.classList?.contains('modal-right-docked') ? 'right'
          : null);
  const shouldRememberDock = s.isMinimized && !!suspendedDockSide;
  if (shouldRememberDock) _rememberDock(id, suspendedDockSide);
  else _forgetDock(id);
  try { s.closeFn(); } catch (e) { console.error('closeFn:', e); }
  // Some tools (cookbook) animate their close over ~250ms before adding
  // .hidden. If the user re-opens the tool before that finishes, open()
  // sees the modal as "still visible" and takes its no-op early-return
  // path — making the tool feel unresponsive. Force the modal into a
  // fully-closed state synchronously so subsequent open() calls always
  // hit the real open path.
  const modal = document.getElementById(id);
  if (modal) {
    // Tear down the live dock push/classes before hiding. If this close came
    // from a minimized dock chip, the side was persisted above and register()
    // will intentionally re-apply it on the next open.
    if (modal.classList.contains('modal-right-docked') || modal.classList.contains('modal-left-docked')) {
      try { clearRightDock(modal); } catch (e) { console.warn('clearRightDock on close failed', e); }
    }
    modal.classList.add('hidden');
    modal.classList.remove('modal-minimized');
    const content = modal.querySelector('.modal-content');
    if (content) {
      content.classList.remove('modal-closing', 'sheet-ready');
      content.style.transform = '';
      content.style.transition = '';
      content.style.animation = '';
      content.style.opacity = '';
    }
  }
  _setBadge(s.btnIds, false);
  _state.delete(id);
  const orderIdx = _dockOrder.indexOf(id);
  if (orderIdx >= 0) _dockOrder.splice(orderIdx, 1);
  _renderDock();
}

/** Inject a minimize (`_`) button next to the close button in a modal.
 * Skips if a minimize button already exists (any class containing "minimize"). */
export function injectMinimizeButton(modal, modalId) {
  const header = modal.querySelector('.modal-header');
  if (!header) return;
  if (header.querySelector('.modal-minimize-btn, .minimize-btn, [data-minimize]')) {
    // An existing minimize button is present — wire it to the manager instead
    const existing = header.querySelector('.minimize-btn, [data-minimize]');
    if (existing && !existing.dataset._modalsBound) {
      existing.dataset._modalsBound = '1';
      existing.addEventListener('click', (e) => {
        e.stopPropagation();
        minimize(modalId);
      }, true);
    }
    return;
  }
  const closeBtn = header.querySelector('.close-btn, .modal-close');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'modal-minimize-btn';
  btn.title = 'Minimize';
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="18" x2="19" y2="18"/></svg>';
  // Anchor the _/X pair to the right edge regardless of the header's
  // justify-content. Some headers (cookbook) use `space-between`, which
  // would otherwise distribute three children as left/center/right and
  // strand the `_` in the middle. `margin-left:auto` eats the free space
  // to the left so `_` + close sit snug at the right.
  btn.style.flexShrink = '0';
  btn.style.marginLeft = 'auto';
  if (closeBtn) {
    // The close button may carry its own left margin (e.g. compare's inline
    // "margin-left:8px") meant to separate it from the title when it stood
    // alone. Now that `_` sits to its left, that margin becomes a stray gap
    // between the two buttons — zero it. The minimize button's own
    // margin-right (2px, from .modal-minimize-btn) provides the gap.
    closeBtn.style.marginLeft = '0';
    closeBtn.style.flexShrink = '0';
  }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    minimize(modalId);
  });
  if (closeBtn && closeBtn.parentNode) closeBtn.parentNode.insertBefore(btn, closeBtn);
  else header.appendChild(btn);
}

// ── Auto-wire fallback for modals not explicitly registered ──
// Maps modal-id → { rail btn id, sidebar btn id }. Used to auto-register any
// modal that gets swipe-dismissed so the rail/sidebar shows the badge and
// clicking the same button restores it. Tools that need rebuild-on-restore
// can still register explicitly with custom restoreFn/closeFn.
const _AUTO_WIRE = {
  'cookbook-modal':       { rail: 'rail-cookbook',  sidebar: 'tool-cookbook-btn' },
  'calendar-modal':       { rail: 'rail-calendar',  sidebar: 'tool-calendar-btn' },
  'gallery-modal':        { rail: 'rail-gallery',   sidebar: 'tool-gallery-btn' },
  'tasks-modal':          { rail: 'rail-tasks',     sidebar: 'tool-tasks-btn' },
  'doclib-modal':         { rail: 'rail-archive',   sidebar: 'tool-library-btn' },
  'project-files-sheet':  { rail: 'rail-project-files', sidebar: 'tool-project-files-btn' },
  'memory-modal':         { rail: 'rail-memory',      sidebar: 'tool-memory-btn' },
  'knowledge-modal':      { rail: 'rail-knowledge',   sidebar: 'tool-knowledge-btn' },
  'notes-panel':          { rail: 'rail-notes',     sidebar: 'tool-notes-btn' },
  'research-overlay':     { rail: 'rail-research',  sidebar: 'tool-research-btn' },
  'theme-modal':          { rail: null,             sidebar: 'tool-theme-btn' },
  'settings-modal':       { rail: null,             sidebar: 'tool-settings-btn' },
  'compare-model-overlay':{ rail: 'rail-compare',   sidebar: 'tool-compare-btn' },
  'ge-shortcuts-modal':   { rail: null,             sidebar: null },
  // Prompt window opens from the overflow menu (no rail/sidebar button), but
  // wiring it here makes tab-down use the minimized corner strip instead of
  // the legacy .modal-dock-item.
  'custom-preset-modal':  { rail: null,             sidebar: null },
};

function _autoRegister(id) {
  if (_state.has(id)) return _state.get(id);
  const wire = _AUTO_WIRE[id];
  if (!wire) return null;
  // Default close: try to invoke the tool's own close button (so it tears down
  // properly), then hide as a fallback.
  register(id, {
    railBtnId: wire.rail,
    sidebarBtnId: wire.sidebar,
    closeFn: () => {
      const m = document.getElementById(id);
      if (!m) return;
      const closeBtn = m.querySelector('.close-btn, .modal-close, [data-close]');
      if (closeBtn) {
        closeBtn.click();
      } else {
        m.classList.add('hidden');
        m.style.display = 'none';
      }
    },
    restoreFn: () => {},
  });
  return _state.get(id);
}

// Watch the document for tool modals being added/shown and inject the `_`
// button next to the close button. We do NOT pre-register here — only inject
// the button. Registration happens when the modal is actually minimized,
// either via the `_` button click or via swipe-dismiss.
function _scanAndWire() {
  for (const id of Object.keys(_AUTO_WIRE)) {
    const modal = document.getElementById(id);
    if (!modal) continue;
    injectMinimizeButton(modal, id);
  }
}
const _scanTimer = setInterval(_scanAndWire, 1000);
// First scan after DOM ready
if (document.readyState !== 'loading') {
  setTimeout(_scanAndWire, 100);
} else {
  document.addEventListener('DOMContentLoaded', () => setTimeout(_scanAndWire, 100));
}

// Tools that survive a swipe-down as a dock chip. Anything else falls
// through to the legacy close handler and goes away entirely.
const _SWIPE_DOWN_MINIMIZES = new Set([
  'cookbook-modal',
  'calendar-modal',
  'email-lib-modal',
]);
// Same idea but matched by id prefix — so dynamically-created modals
// (per-email reader tabs) survive swipe-down too.
const _SWIPE_DOWN_MINIMIZES_PREFIX = ['email-reader-'];

function _clearEmailSplitAfterMinimize() {
  document.body.classList.remove('email-doc-split-active', 'email-front');
  document.documentElement.style.removeProperty('--email-doc-split-left-x');
  document.documentElement.style.removeProperty('--email-doc-split-email-w');
  document.documentElement.style.removeProperty('--email-doc-split-right-x');
  const docPane = document.getElementById('doc-editor-pane');
  if (docPane) {
    [
      'position', 'left', 'right', 'top', 'bottom', 'width', 'max-width',
      'height', 'z-index', 'transform',
    ].forEach(prop => docPane.style.removeProperty(prop));
  }
  const divider = document.getElementById('doc-divider');
  if (divider) divider.style.display = '';
  requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
}

// Re-route swipe-dismiss to minimize-rather-than-close — but only for the
// allowlisted tools above. For every other modal, return early so the
// default close handler runs and the modal goes away.
// Close any open body-mounted popups (kebab dropdowns, split-button menus,
// etc.) when the cookbook modal is swiped away. Otherwise the dropdowns
// stay floating in the middle of the page with no anchor.
window.addEventListener('modal-dismissed', (e) => {
  const id = e.detail?.id;
  if (id === 'cookbook-modal') {
    document.querySelectorAll(
      '.cookbook-task-dropdown, .cookbook-gpu-split-menu, .hwfit-cached-dropdown, .cookbook-saved-menu, .cookbook-dep-menu'
    ).forEach(dismissOrRemove);
  }
});

window.addEventListener('modal-dismissed', (e) => {
  const id = e.detail?.id;
  if (!id) return;
  if (!_SWIPE_DOWN_MINIMIZES.has(id) && !_SWIPE_DOWN_MINIMIZES_PREFIX.some(p => id.startsWith(p))) return;
  // Auto-register if it's a known tool modal
  if (!_state.has(id)) _autoRegister(id);
  const s = _state.get(id);
  if (!s) return;
  s.isMinimized = true;
  _setBadge(s.btnIds, true);
  const modal = document.getElementById(id);
  if (modal) {
    const isEmailModal = id === 'email-lib-modal' || id.startsWith('email-reader-');
    if (modal.classList.contains('modal-right-docked')
        || modal.classList.contains('modal-left-docked')
        || modal.classList.contains('email-snap-left')) {
      try { suspendDock(modal); } catch (err) { console.warn('suspendDock on dismissed failed', err); }
    }
    if (isEmailModal) _clearEmailSplitAfterMinimize();
    modal.classList.add('modal-minimized');
  }
  _ensureDock();
  _renderDock();
  // Stop legacy listeners that reset internal `_open` state
  e.stopImmediatePropagation();
});

// Capture-phase intercept: if user clicks a sidebar/rail button whose
// associated modal is currently MINIMIZED, restore it and stop the click
// before the tool's own toggle handler runs (which would try to re-open or
// close it).
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[id]');
  if (!btn) return;
  const btnId = btn.id;
  for (const [modalId, s] of _state.entries()) {
    if (!s.isMinimized) continue;
    if (s.btnIds.includes(btnId)) {
      restore(modalId);
      e.stopImmediatePropagation();
      e.preventDefault();
      return;
    }
  }
}, true);

export default { register, unregister, isRegistered, isMinimized, minimize, restore, toggle, close, injectMinimizeButton };
