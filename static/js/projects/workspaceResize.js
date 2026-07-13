/**
 * Drag-resize project workspace left + companion (right Chat|Run) columns.
 * Companion used to be a bottom footer; it now sits as a right column for
 * vertical editor real-estate. Storage still uses footerHeight/footerExpanded
 * keys for backward compatibility (mapped to right-column width).
 */
import workspaceState from './workspaceState.js';

const LEFT_MIN = 160;
const LEFT_MAX = 420;
const LEFT_DEFAULT = 220;
const LEFT_ICON = 48;

const RIGHT_MIN = 240;
const RIGHT_MAX = 560;
const RIGHT_DEFAULT = 320;
const RIGHT_EXPANDED = 420;
const RIGHT_SLIM = 44;

let _projectId = null;
let _grid = null;
let _leftPx = LEFT_DEFAULT;
let _rightPx = RIGHT_DEFAULT;
let _rightExpanded = false;
let _leftCollapsed = false;
let _rightMinimized = false;
let _expandBtn = null;

function _clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

function _effectiveLeftPx() {
  return _leftCollapsed ? LEFT_ICON : _leftPx;
}

function _effectiveRightPx() {
  if (_rightMinimized) return RIGHT_SLIM;
  return _rightPx;
}

function _applySizes({ animate = false } = {}) {
  if (!_grid) return;
  if (animate) _grid.classList.add('project-layout-animated');
  _grid.style.gridTemplateColumns =
    `${_effectiveLeftPx()}px minmax(0, 1fr) ${_effectiveRightPx()}px`;
  _grid.style.gridTemplateRows = 'minmax(0, 1fr)';
  if (animate) {
    window.setTimeout(() => _grid?.classList.remove('project-layout-animated'), 240);
  }
}

function _syncExpandButton() {
  if (!_expandBtn) return;
  const expanded = _rightExpanded && !_rightMinimized;
  _expandBtn.classList.toggle('active', expanded);
  _expandBtn.setAttribute('aria-pressed', expanded ? 'true' : 'false');
  _expandBtn.title = expanded ? 'Narrow panel' : 'Widen panel';
}

function _save() {
  if (!_projectId) return;
  workspaceState.saveLayoutSizes(_projectId, {
    leftWidth: _leftPx,
    // Persist as footerHeight for backward compat with older workspace state.
    footerHeight: _rightPx,
    footerExpanded: _rightExpanded,
    leftCollapsed: _leftCollapsed,
    footerMinimized: _rightMinimized,
    rightWidth: _rightPx,
  });
}

function _bindLeftHandle(handle) {
  if (!handle || handle.dataset.resizeBound) return;
  handle.dataset.resizeBound = '1';
  let startX = 0;
  let startW = 0;

  handle.addEventListener('mousedown', (e) => {
    if (_leftCollapsed) return;
    e.preventDefault();
    startX = e.clientX;
    startW = _leftPx;
    handle.classList.add('dragging');
    document.body.classList.add('project-workspace-resizing');
    const onMove = (ev) => {
      _leftPx = _clamp(startW + (ev.clientX - startX), LEFT_MIN, LEFT_MAX);
      _applySizes();
    };
    const onUp = () => {
      handle.classList.remove('dragging');
      document.body.classList.remove('project-workspace-resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      _save();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function _bindRightHandle(handle) {
  if (!handle || handle.dataset.resizeBound) return;
  handle.dataset.resizeBound = '1';
  let startX = 0;
  let startW = 0;

  handle.addEventListener('mousedown', (e) => {
    if (_rightMinimized) return;
    e.preventDefault();
    startX = e.clientX;
    startW = _rightPx;
    handle.classList.add('dragging');
    document.body.classList.add('project-workspace-resizing');
    const onMove = (ev) => {
      // Dragging the left edge of the right column: moving left grows width.
      const delta = startX - ev.clientX;
      _rightPx = _clamp(startW + delta, RIGHT_MIN, RIGHT_MAX);
      _rightExpanded = _rightPx >= RIGHT_EXPANDED - 24;
      _syncExpandButton();
      _applySizes();
    };
    const onUp = () => {
      handle.classList.remove('dragging');
      document.body.classList.remove('project-workspace-resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      _save();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function _bindExpandButton() {
  _expandBtn = document.getElementById('project-footer-expand-btn');
  if (!_expandBtn || _expandBtn.dataset.resizeBound) return;
  _expandBtn.dataset.resizeBound = '1';
  _expandBtn.addEventListener('click', () => {
    toggleFooterExpand();
  });
}

/** Toggle companion width between default and expanded (API kept for presets). */
export function toggleFooterExpand() {
  if (_rightMinimized) {
    setFooterMinimized(false);
    return;
  }
  _rightExpanded = !_rightExpanded;
  _rightPx = _rightExpanded ? RIGHT_EXPANDED : RIGHT_DEFAULT;
  _applySizes({ animate: true });
  _syncExpandButton();
  _save();
}

export function expandFooter() {
  _rightMinimized = false;
  _rightExpanded = true;
  _rightPx = RIGHT_EXPANDED;
  _applySizes({ animate: true });
  _syncExpandButton();
  _save();
}

export function collapseFooter() {
  _rightExpanded = false;
  _rightPx = RIGHT_DEFAULT;
  _applySizes({ animate: true });
  _syncExpandButton();
  _save();
}

export function setLeftCollapsed(collapsed) {
  _leftCollapsed = !!collapsed;
  _applySizes({ animate: true });
  _save();
}

export function setFooterMinimized(minimized) {
  _rightMinimized = !!minimized;
  if (_rightMinimized) _rightExpanded = false;
  _applySizes({ animate: true });
  _syncExpandButton();
  _save();
}

export function mount(projectId) {
  _projectId = projectId;
  _grid = document.getElementById('project-workspace-grid');
  const saved = workspaceState.getLayoutSizes(projectId);
  const preset = workspaceState.getLayoutPreset(projectId);
  _leftPx = _clamp(saved.leftWidth || LEFT_DEFAULT, LEFT_MIN, LEFT_MAX);

  // Prefer rightWidth; fall back to legacy footerHeight (was bottom band px).
  // Values below RIGHT_MIN were footer heights — remapped to default.
  const rawRight = typeof saved.rightWidth === 'number'
    ? saved.rightWidth
    : (typeof saved.footerHeight === 'number' ? saved.footerHeight : RIGHT_DEFAULT);
  _rightPx = rawRight >= RIGHT_MIN
    ? _clamp(rawRight, RIGHT_MIN, RIGHT_MAX)
    : RIGHT_DEFAULT;

  _leftCollapsed = preset.leftCollapsed === true;
  _rightMinimized = preset.footerMinimized === true;
  _rightExpanded = !_rightMinimized && (saved.footerExpanded === true || _rightPx >= RIGHT_EXPANDED - 24);
  if (_rightExpanded && _rightPx < RIGHT_EXPANDED - 24) {
    _rightPx = RIGHT_EXPANDED;
  }
  _applySizes();
  _bindLeftHandle(document.getElementById('project-resize-col'));
  _bindRightHandle(document.getElementById('project-resize-row'));
  _bindExpandButton();
  _syncExpandButton();
}

export function unmount() {
  _projectId = null;
  _grid = null;
  _expandBtn = null;
  _leftCollapsed = false;
  _rightMinimized = false;
}

export default {
  mount,
  unmount,
  toggleFooterExpand,
  expandFooter,
  collapseFooter,
  setLeftCollapsed,
  setFooterMinimized,
};
