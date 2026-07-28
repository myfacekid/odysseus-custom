/**
 * geTileWindows.js — promote gallery-editor floaters to first-class tile windows.
 *
 * Targets durable popouts (not transient menus like `.ge-fx-menu`):
 *   .ge-adj-popup, .ge-fx-popup, .ge-transform-popup, .ge-inpaint-popup,
 *   #ge-history-panel
 *
 * Call `promoteGeFloater(el)` after appending a floater to the document, or
 * `promoteAllGeFloaters(root)` to scan. Idempotent via data-ge-tile-wired.
 *
 * Minimize chips continue to use modalManager (#minimized-dock). The legacy
 * #ge-fx-dock is left in place for any leftover chips; restores still go
 * through modalManager restoreFn which re-shows the floater.
 */

import { makeWindowDraggable } from './windowDrag.js';
import { markTileWindow, snapModalToZone } from './tileManager.js';

const FLOATER_SELECTOR = [
  '.ge-adj-popup',
  '.ge-fx-popup',
  '.ge-transform-popup',
  '.ge-inpaint-popup',
  '#ge-history-panel',
].join(', ');

const HEADER_SELECTOR = [
  '.ge-adj-head',
  '.ge-fx-popup-head',
  '.ge-history-head',
  '.ge-transform-popup-head',
  '[data-adj-drag]',
  '[data-history-drag]',
  '[data-transform-drag]',
].join(', ');

function _headerFor(el) {
  return el.querySelector(HEADER_SELECTOR);
}

/**
 * Mark + wire drag/dock/tile for one gallery-editor floater.
 * @param {HTMLElement} el
 */
export function promoteGeFloater(el) {
  if (!el || el.dataset.geTileWired === '1') return;
  if (window.innerWidth <= 768) return;
  const header = _headerFor(el);
  if (!header) return;

  el.dataset.geTileWired = '1';
  // Reparent to body if stuck inside an overflow-hidden host (escape overflow).
  if (el.parentElement && el.parentElement !== document.body) {
    const cs = getComputedStyle(el.parentElement);
    if (cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflowY === 'hidden') {
      document.body.appendChild(el);
    }
  }

  markTileWindow(el, { content: el });
  header.classList.add('tile-window-header');
  if (!header.classList.contains('modal-header')) {
    // tileManager also matches .ge-adj-head etc.; modal-header helps shared CSS
    header.classList.add('modal-header');
  }

  makeWindowDraggable(el, {
    content: el,
    header,
    skipSelector: 'button, input, select, textarea, label, .ge-head-btns',
    enableDock: true,
    enableLeftDock: true,
    enableFullscreen: true,
    onEnterFullscreen: () => snapModalToZone(el, { name: 'fullscreen' }),
    onExitFullscreen: (cx, cy) => {
      const w = el.offsetWidth || 320;
      const h = el.offsetHeight || 280;
      el.style.position = 'fixed';
      el.style.left = `${Math.max(0, (cx || window.innerWidth / 2) - w / 2)}px`;
      el.style.top = `${Math.max(0, (cy || 80) - 20)}px`;
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
      el.style.right = 'auto';
      el.style.bottom = 'auto';
      el.style.maxWidth = 'none';
      el.style.transform = 'none';
      el.style.zIndex = el.style.zIndex || '10003';
    },
  });
}

/** Scan `root` (default document) for un-wired floaters and promote them. */
export function promoteAllGeFloaters(root = document) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(FLOATER_SELECTOR).forEach(promoteGeFloater);
}

/**
 * Observe DOM insertions under `root` and auto-promote matching floaters.
 * Returns a disconnect function.
 */
export function observeGeFloaters(root = null) {
  const target = root
    || document.getElementById('gallery-editor-container')
    || document.body;
  if (!target || typeof MutationObserver === 'undefined') return () => {};
  promoteAllGeFloaters(target);
  // Scope tightly — observing document.body subtree was a major slowdown.
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches?.(FLOATER_SELECTOR)) promoteGeFloater(node);
        else if (node.querySelector?.(FLOATER_SELECTOR)) promoteAllGeFloaters(node);
      }
    }
  });
  obs.observe(target, { childList: true, subtree: true });
  return () => obs.disconnect();
}

export { FLOATER_SELECTOR };
