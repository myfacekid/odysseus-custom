/**
 * Split center view — link + file side by side (Phase G7).
 */
import workspaceState from './workspaceState.js';

let _projectId = null;
let _enabled = false;
let _lastDepthId = null;
let _lastBreadthId = null;
let _toggleBtn = null;

function _syncToggleUi() {
  if (!_toggleBtn) return;
  _toggleBtn.classList.toggle('active', _enabled);
  _toggleBtn.setAttribute('aria-pressed', _enabled ? 'true' : 'false');
}

export function mount(projectId) {
  _projectId = projectId;
  _enabled = !!workspaceState.getCenterSplit(projectId);
  _lastDepthId = workspaceState.getSplitDepthTab(projectId);
  _lastBreadthId = workspaceState.getSplitBreadthTab(projectId);
  _toggleBtn = document.getElementById('project-split-toggle');
  _syncToggleUi();
}

export function unmount() {
  _projectId = null;
  _toggleBtn = null;
}

export function isEnabled() {
  return _enabled;
}

export function noteTab(tab) {
  if (!tab) return;
  if (tab.kind === 'depth') _lastDepthId = tab.id;
  if (tab.kind === 'breadth') _lastBreadthId = tab.id;
  if (_projectId) {
    workspaceState.saveSplitTabs(_projectId, {
      depthId: _lastDepthId,
      breadthId: _lastBreadthId,
    });
  }
}

export function setEnabled(on, { persist = true } = {}) {
  _enabled = !!on;
  _syncToggleUi();
  if (persist && _projectId) workspaceState.saveCenterSplit(_projectId, _enabled);
}

export function toggle() {
  setEnabled(!_enabled);
  return _enabled;
}

export function getSplitTabIds(getTabs) {
  const tabs = getTabs?.() || [];
  const depthId = _lastDepthId || tabs.find((t) => t.kind === 'depth')?.id || null;
  const breadthId = _lastBreadthId || tabs.find((t) => t.kind === 'breadth')?.id || null;
  return { depthId, breadthId };
}

export function canSplit(getTabs) {
  const { depthId, breadthId } = getSplitTabIds(getTabs);
  return !!(depthId && breadthId);
}

export default {
  mount,
  unmount,
  isEnabled,
  noteTab,
  setEnabled,
  toggle,
  getSplitTabIds,
  canSplit,
};
