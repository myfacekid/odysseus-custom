/**
 * Drag-resize project workspace left column + footer (Phase G7).
 */
import workspaceState from './workspaceState.js';

const LEFT_MIN = 160;
const LEFT_MAX = 420;
const LEFT_DEFAULT = 220;
const FOOTER_MIN = 120;
const FOOTER_MAX = 560;
const FOOTER_DEFAULT = 200;
const FOOTER_EXPANDED = 380;

let _projectId = null;
let _grid = null;
let _leftPx = LEFT_DEFAULT;
let _footerPx = FOOTER_DEFAULT;
let _footerExpanded = false;
let _expandBtn = null;

function _clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

function _applySizes() {
  if (!_grid) return;
  _grid.style.gridTemplateColumns = `${_leftPx}px minmax(0, 1fr)`;
  _grid.style.gridTemplateRows = `minmax(0, 1fr) ${_footerPx}px`;
}

function _syncExpandButton() {
  if (!_expandBtn) return;
  _expandBtn.classList.toggle('active', _footerExpanded);
  _expandBtn.setAttribute('aria-pressed', _footerExpanded ? 'true' : 'false');
  _expandBtn.title = _footerExpanded ? 'Collapse panel' : 'Expand panel';
}

function _save() {
  if (!_projectId) return;
  workspaceState.saveLayoutSizes(_projectId, {
    leftWidth: _leftPx,
    footerHeight: _footerPx,
    footerExpanded: _footerExpanded,
  });
}

function _bindColHandle(handle) {
  if (!handle || handle.dataset.resizeBound) return;
  handle.dataset.resizeBound = '1';
  let startX = 0;
  let startW = 0;

  handle.addEventListener('mousedown', (e) => {
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

function _bindRowHandle(handle) {
  if (!handle || handle.dataset.resizeBound) return;
  handle.dataset.resizeBound = '1';
  let startY = 0;
  let startH = 0;

  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    startY = e.clientY;
    startH = _footerPx;
    handle.classList.add('dragging');
    document.body.classList.add('project-workspace-resizing');
    const onMove = (ev) => {
      const delta = startY - ev.clientY;
      _footerPx = _clamp(startH + delta, FOOTER_MIN, FOOTER_MAX);
      _footerExpanded = _footerPx >= FOOTER_EXPANDED - 24;
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

export function toggleFooterExpand() {
  _footerExpanded = !_footerExpanded;
  _footerPx = _footerExpanded ? FOOTER_EXPANDED : FOOTER_DEFAULT;
  _applySizes();
  _syncExpandButton();
  _save();
}

export function mount(projectId) {
  _projectId = projectId;
  _grid = document.getElementById('project-workspace-grid');
  const saved = workspaceState.getLayoutSizes(projectId);
  _leftPx = _clamp(saved.leftWidth || LEFT_DEFAULT, LEFT_MIN, LEFT_MAX);
  if (typeof saved.footerHeight === 'number') {
    _footerPx = _clamp(saved.footerHeight, FOOTER_MIN, FOOTER_MAX);
  } else {
    _footerPx = FOOTER_DEFAULT;
  }
  _footerExpanded = saved.footerExpanded === true
    || _footerPx >= FOOTER_EXPANDED - 24;
  if (_footerExpanded && _footerPx < FOOTER_EXPANDED - 24) {
    _footerPx = FOOTER_EXPANDED;
  }
  _applySizes();
  _bindColHandle(document.getElementById('project-resize-col'));
  _bindRowHandle(document.getElementById('project-resize-row'));
  _bindExpandButton();
  _syncExpandButton();
}

export function unmount() {
  _projectId = null;
  _grid = null;
  _expandBtn = null;
}

export default { mount, unmount, toggleFooterExpand };
