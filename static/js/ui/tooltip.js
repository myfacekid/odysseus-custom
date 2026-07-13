// ============================================
// Nobody UI — Shared tooltip component (U6)
// ============================================
// One lightweight, touch-friendly tooltip used across icon-only surfaces (the
// icon rail today; reusable for toolbars and chips). It consumes an element's
// existing `title` (or an explicit `data-tooltip`) at runtime and removes the
// native `title` so the browser's own tooltip doesn't double up. It also fills
// in a missing `aria-label` from the tooltip text, improving screen-reader
// coverage for icon-only controls.
//
// Usage:
//   import { initTooltips } from './ui/tooltip.js';
//   initTooltips(document.getElementById('icon-rail'));

let _tip = null;
let _hideTimer = 0;
let _current = null;

function _ensureTip() {
  if (_tip) return _tip;
  _tip = document.createElement('div');
  _tip.className = 'app-tooltip';
  _tip.setAttribute('role', 'tooltip');
  _tip.setAttribute('aria-hidden', 'true');
  document.body.appendChild(_tip);
  return _tip;
}

function _text(elm) {
  return elm.getAttribute('data-tooltip') || elm.__tooltipText || '';
}

function _position(elm) {
  const tip = _ensureTip();
  const r = elm.getBoundingClientRect();
  // Measure after content is set.
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  const gap = 8;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  // Prefer to the right (good for a left-edge rail); flip left if no room;
  // fall back to below.
  let left = r.right + gap;
  let placement = 'right';
  if (left + tw > vw - 4) {
    const leftTry = r.left - gap - tw;
    if (leftTry >= 4) { left = leftTry; placement = 'left'; }
    else { left = Math.min(Math.max(4, r.left), vw - tw - 4); placement = 'below'; }
  }
  let top;
  if (placement === 'below') {
    top = r.bottom + gap;
    if (top + th > vh - 4) top = r.top - gap - th;
  } else {
    top = r.top + (r.height - th) / 2;
    top = Math.min(Math.max(4, top), vh - th - 4);
  }
  tip.style.left = Math.round(left) + 'px';
  tip.style.top = Math.round(top) + 'px';
  tip.dataset.placement = placement;
}

function _show(elm) {
  const text = _text(elm);
  if (!text) return;
  clearTimeout(_hideTimer);
  _current = elm;
  const tip = _ensureTip();
  tip.textContent = text;
  tip.classList.add('visible');
  tip.setAttribute('aria-hidden', 'false');
  _position(elm);
}

function _hide() {
  if (!_tip) return;
  _current = null;
  _tip.classList.remove('visible');
  _tip.setAttribute('aria-hidden', 'true');
}

/** Enhance a single element: stash + strip its title, wire show/hide. */
export function enhanceTooltip(elm) {
  if (!elm || elm.__tooltipReady) return;
  const title = elm.getAttribute('data-tooltip') || elm.getAttribute('title');
  if (!title) return;
  elm.__tooltipReady = true;
  elm.__tooltipText = title;
  // Remove native title so it doesn't double with our tooltip.
  if (elm.hasAttribute('title')) elm.removeAttribute('title');
  // A11y: give icon-only controls an accessible name if they lack one.
  if (!elm.getAttribute('aria-label') && !elm.textContent.trim()) {
    elm.setAttribute('aria-label', title);
  }

  elm.addEventListener('mouseenter', () => _show(elm));
  elm.addEventListener('mouseleave', () => { _hideTimer = setTimeout(_hide, 60); });
  elm.addEventListener('focus', () => _show(elm));
  elm.addEventListener('blur', _hide);
  // Touch: reveal briefly on press without blocking the click.
  elm.addEventListener('touchstart', () => {
    _show(elm);
    clearTimeout(_hideTimer);
    _hideTimer = setTimeout(_hide, 1600);
  }, { passive: true });
  // Hide once the control is actually activated.
  elm.addEventListener('click', _hide);
}

/**
 * Enhance every eligible element within `root`. Elements opt in via an existing
 * `title` or an explicit `data-tooltip`.
 * @param {ParentNode} [root]
 * @param {string} [selector]
 */
export function initTooltips(root = document, selector = '[data-tooltip], [title]') {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(selector).forEach(enhanceTooltip);
}

// Hide on scroll/resize/escape so a stale tooltip never lingers.
if (typeof window !== 'undefined') {
  window.addEventListener('scroll', () => { if (_current) _hide(); }, true);
  window.addEventListener('resize', () => { if (_current) _hide(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _current) _hide(); });
}
