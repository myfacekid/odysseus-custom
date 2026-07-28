/**
 * toolbarPalette.js — optional undock of a toolbar into a small tiled palette window.
 *
 * Usage:
 *   undockToolbarAsWindow(toolbarEl, { id, title, preferredZone: 'right-half' })
 *   redockToolbarWindow(id)   // or click the "re-dock" control in the placeholder
 *
 * Persists undocked state in localStorage under `odysseus-toolbar-undock:<id>`.
 * Desktop only (>768). Does not touch transient menus.
 */

import { makeWindowDraggable } from './windowDrag.js';
import { markTileWindow, snapModalToZone } from './tileManager.js';

const STORAGE_PREFIX = 'odysseus-toolbar-undock:';
const _palettes = new Map(); // id → { shell, placeholder, toolbar, host, opts }

function _storageKey(id) {
  return STORAGE_PREFIX + id;
}

function _readPersisted(id) {
  try { return localStorage.getItem(_storageKey(id)) === '1'; } catch (_) { return false; }
}

function _writePersisted(id, undocked) {
  try {
    if (undocked) localStorage.setItem(_storageKey(id), '1');
    else localStorage.removeItem(_storageKey(id));
  } catch (_) { /* ignore */ }
}

/**
 * Detach `toolbarEl` into a tile-window shell. Leaves a slim placeholder
 * with a "re-dock" control in the original host.
 *
 * @param {HTMLElement} toolbarEl
 * @param {{ id?: string, title?: string, preferredZone?: string, host?: HTMLElement }} opts
 * @returns {HTMLElement|null} the palette shell, or null if skipped
 */
export function undockToolbarAsWindow(toolbarEl, opts = {}) {
  if (!toolbarEl || window.innerWidth <= 768) return null;
  const id = opts.id || toolbarEl.id || `toolbar-${Math.random().toString(36).slice(2, 8)}`;
  if (_palettes.has(id)) return _palettes.get(id).shell;

  const host = opts.host || toolbarEl.parentElement;
  const title = opts.title || toolbarEl.getAttribute('aria-label') || 'Palette';
  const preferredZone = opts.preferredZone || 'right-half';

  const placeholder = document.createElement('div');
  placeholder.className = 'toolbar-undock-placeholder';
  placeholder.dataset.toolbarPaletteId = id;
  placeholder.innerHTML = `
    <span class="toolbar-undock-placeholder-label">${_esc(title)} undocked</span>
    <button type="button" class="toolbar-undock-redock-btn" title="Re-dock toolbar">Re-dock</button>
  `;
  placeholder.querySelector('.toolbar-undock-redock-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    redockToolbarWindow(id);
  });

  const shell = document.createElement('div');
  shell.id = `toolbar-palette-${id}`;
  shell.className = 'tile-window toolbar-palette-window';
  shell.setAttribute('data-tile-window', '1');
  shell.innerHTML = `
    <div class="modal-header tile-window-header toolbar-palette-header">
      <span class="toolbar-palette-title">${_esc(title)}</span>
      <button type="button" class="toolbar-palette-redock-btn doc-action-icon-btn" title="Re-dock">↩</button>
    </div>
    <div class="tile-window-content toolbar-palette-body"></div>
  `;
  const body = shell.querySelector('.toolbar-palette-body');
  const header = shell.querySelector('.toolbar-palette-header');

  // Remember original display so redock restores visibility correctly
  toolbarEl.dataset._preUndockDisplay = toolbarEl.style.display || '';
  host?.insertBefore(placeholder, toolbarEl);
  body.appendChild(toolbarEl);
  toolbarEl.style.display = '';
  document.body.appendChild(shell);

  markTileWindow(shell, { content: shell });
  makeWindowDraggable(shell, {
    content: shell,
    header,
    skipSelector: 'button, input, select, textarea, label',
    enableDock: true,
    enableLeftDock: true,
    onEnterFullscreen: () => snapModalToZone(shell, { name: 'fullscreen' }),
    onExitFullscreen: (cx, cy) => {
      const w = shell.offsetWidth || 280;
      const h = shell.offsetHeight || 120;
      shell.style.position = 'fixed';
      shell.style.left = `${Math.max(0, (cx || window.innerWidth / 2) - w / 2)}px`;
      shell.style.top = `${Math.max(0, (cy || 80) - 20)}px`;
      shell.style.width = `${w}px`;
      shell.style.height = `${h}px`;
      shell.style.right = 'auto';
      shell.style.bottom = 'auto';
      shell.style.maxWidth = 'none';
      shell.style.zIndex = '170';
    },
  });

  shell.querySelector('.toolbar-palette-redock-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    redockToolbarWindow(id);
  });

  snapModalToZone(shell, { name: preferredZone });
  _writePersisted(id, true);
  _palettes.set(id, { shell, placeholder, toolbar: toolbarEl, host, opts: { ...opts, id, title, preferredZone } });
  return shell;
}

/** Put the toolbar back into its original host and remove the palette shell. */
export function redockToolbarWindow(id) {
  const entry = _palettes.get(id);
  if (!entry) return;
  const { shell, placeholder, toolbar, host } = entry;
  if (placeholder?.parentElement && toolbar) {
    placeholder.parentElement.insertBefore(toolbar, placeholder);
  } else if (host && toolbar) {
    host.appendChild(toolbar);
  }
  if (toolbar && toolbar.dataset._preUndockDisplay !== undefined) {
    toolbar.style.display = toolbar.dataset._preUndockDisplay;
    delete toolbar.dataset._preUndockDisplay;
  }
  placeholder?.remove();
  shell?.remove();
  _writePersisted(id, false);
  _palettes.delete(id);
}

export function isToolbarUndocked(id) {
  return _palettes.has(id);
}

/**
 * If this toolbar was undocked last session, restore that state.
 * Call after the toolbar is in the DOM.
 */
export function restoreToolbarUndockIfNeeded(toolbarEl, opts = {}) {
  if (!toolbarEl || window.innerWidth <= 768) return null;
  const id = opts.id || toolbarEl.id;
  if (!id || !_readPersisted(id)) return null;
  return undockToolbarAsWindow(toolbarEl, { ...opts, id });
}

function _esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
