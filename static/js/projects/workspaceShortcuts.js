/**
 * Project workspace keyboard shortcuts (Phase G6).
 */
import workspaceShell from './workspaceShell.js';
import tabHost from './tabHost.js';

let _bound = false;

function _isWorkspaceActive() {
  const panel = document.getElementById('project-workspace-panel');
  return panel && !panel.classList.contains('hidden');
}

function _onKeyDown(e) {
  if (!_isWorkspaceActive()) return;
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;

  if (e.key === '1') {
    e.preventDefault();
    workspaceShell.setLeftTab('links');
    return;
  }
  if (e.key === '2') {
    e.preventDefault();
    workspaceShell.setLeftTab('files');
    return;
  }
  if (e.key === 'w' || e.key === 'W') {
    const active = tabHost.getActiveTab();
    if (!active) return;
    e.preventDefault();
    tabHost.closeTab(active.id);
  }
}

export function mount() {
  if (_bound) return;
  document.addEventListener('keydown', _onKeyDown);
  _bound = true;
}

export function unmount() {
  if (!_bound) return;
  document.removeEventListener('keydown', _onKeyDown);
  _bound = false;
}

export default { mount, unmount };
