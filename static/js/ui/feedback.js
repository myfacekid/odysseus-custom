/**
 * Shared loading / empty / setup / error feedback (U1–U2).
 */

import spinnerModule from '../spinner.js';
import { ZOTERO_SETUP_MSG } from '../setupStatus.js';

export { ZOTERO_SETUP_MSG };
export { ZOTERO_SETUP_PATH } from '../setupStatus.js';

export async function openSettingsTab(tab) {
  try {
    const mod = await import('../settings.js');
    const open = mod.open || mod.default?.open;
    if (open) open(tab);
  } catch { /* ignore */ }
}

/**
 * @param {{
 *   kind?: 'loading' | 'empty' | 'setup',
 *   title?: string,
 *   message?: string,
 *   actionLabel?: string,
 *   actionTab?: string,
 *   onAction?: () => void,
 * }} opts
 * @returns {HTMLElement}
 */
export function uiEmptyState(opts = {}) {
  const {
    kind = 'empty',
    title = '',
    message = '',
    actionLabel = 'Open Settings',
    actionTab = 'search',
    onAction,
  } = opts;

  const root = document.createElement('div');
  root.className = `ui-empty-state ui-empty-state--${kind}`;
  if (title) {
    const h = document.createElement('div');
    h.className = 'ui-empty-state-title';
    h.textContent = title;
    root.appendChild(h);
  }
  if (message) {
    const p = document.createElement('p');
    p.className = 'ui-empty-state-message';
    p.textContent = message;
    root.appendChild(p);
  }
  if (kind === 'setup' && (onAction || actionTab)) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'admin-btn-sm ui-empty-state-action';
    btn.textContent = actionLabel;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (onAction) onAction();
      else void openSettingsTab(actionTab);
    });
    root.appendChild(btn);
  }
  return root;
}

/** Replace container contents with a feedback block. */
export function mountEmptyState(parent, opts) {
  if (!parent) return null;
  const el = uiEmptyState(opts);
  parent.innerHTML = '';
  parent.appendChild(el);
  return el;
}

/** Alias for mountEmptyState — preferred name in U2. */
export const showEmptyState = mountEmptyState;

/** Whirlpool loading row (matches tasks.js / Library tabs). */
export function showLoadingRow(parent, text = 'Loading…') {
  if (!parent) return null;
  parent.innerHTML = '';
  const row = spinnerModule.createLoadingRow(text);
  parent.appendChild(row);
  return row;
}

/**
 * @param {HTMLElement | null} parent
 * @param {{ message?: string, retry?: () => void }} opts
 */
export function showError(parent, { message = 'Something went wrong', retry } = {}) {
  if (!parent) return null;
  const root = document.createElement('div');
  root.className = 'ui-feedback-error';
  const p = document.createElement('p');
  p.className = 'ui-feedback-error-message';
  p.textContent = message;
  root.appendChild(p);
  if (typeof retry === 'function') {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'admin-btn-sm ui-feedback-error-retry';
    btn.textContent = 'Retry';
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      retry();
    });
    root.appendChild(btn);
  }
  parent.innerHTML = '';
  parent.appendChild(root);
  return root;
}
