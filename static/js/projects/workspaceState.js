/**
 * Per-project workspace UI persistence (Phase D3).
 * Stores last open file + active chat in localStorage (keyed by project id).
 */
import Storage from '../storage.js';

const STATE_PREFIX = 'odysseus_project_workspace:';
export const LAST_OPEN_PROJECT_KEY = 'odysseus_project_last_open';

function _key(projectId) {
  return `${STATE_PREFIX}${projectId || ''}`;
}

export function loadState(projectId) {
  if (!projectId) return {};
  return Storage.getJSON(_key(projectId), {}) || {};
}

export function saveState(projectId, patch) {
  if (!projectId || !patch || typeof patch !== 'object') return;
  const next = { ...loadState(projectId), ...patch };
  Storage.setJSON(_key(projectId), next);
}

export function getOpenFile(projectId) {
  const path = loadState(projectId).openFile;
  return typeof path === 'string' && path.trim() ? path.trim() : null;
}

export function saveOpenFile(projectId, path) {
  saveState(projectId, { openFile: path || null });
}

export function getActiveChat(projectId) {
  const id = loadState(projectId).activeChatId;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

export function saveActiveChat(projectId, sessionId) {
  saveState(projectId, { activeChatId: sessionId || null });
}

export function getLeftTab(projectId) {
  const tab = loadState(projectId).leftTab;
  return tab === 'files' ? 'files' : 'links';
}

export function saveLeftTab(projectId, tab) {
  saveState(projectId, { leftTab: tab === 'files' ? 'files' : 'links' });
}

export function getBottomTab(projectId) {
  const tab = loadState(projectId).bottomTab;
  return tab === 'run' ? 'run' : 'chat';
}

export function saveBottomTab(projectId, tab) {
  saveState(projectId, { bottomTab: tab === 'run' ? 'run' : 'chat' });
}

export function getCenterTabs(projectId) {
  const raw = loadState(projectId).centerTabs;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((t) => t && typeof t.id === 'string' && (t.kind === 'depth' || t.kind === 'breadth'))
    .map((t) => ({
      id: t.id,
      kind: t.kind,
      label: typeof t.label === 'string' ? t.label : t.id,
      shortLabel: typeof t.shortLabel === 'string' ? t.shortLabel : undefined,
      meta: t.meta && typeof t.meta === 'object' ? t.meta : undefined,
      pinned: !!t.pinned,
    }));
}

export function saveCenterTabs(projectId, tabs) {
  if (!Array.isArray(tabs)) return;
  saveState(projectId, { centerTabs: tabs });
}

export function getActiveCenterTab(projectId) {
  const id = loadState(projectId).activeCenterTab;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

export function saveActiveCenterTab(projectId, tabId) {
  saveState(projectId, { activeCenterTab: tabId || null });
}

export function getLayoutSizes(projectId) {
  const s = loadState(projectId).layout || {};
  return {
    leftWidth: typeof s.leftWidth === 'number' ? s.leftWidth : null,
    footerHeight: typeof s.footerHeight === 'number' ? s.footerHeight : null,
    footerExpanded: s.footerExpanded === true,
  };
}

export function saveLayoutSizes(projectId, { leftWidth, footerHeight, footerExpanded } = {}) {
  const prev = loadState(projectId).layout || {};
  saveState(projectId, {
    layout: {
      ...prev,
      ...(typeof leftWidth === 'number' ? { leftWidth } : {}),
      ...(typeof footerHeight === 'number' ? { footerHeight } : {}),
      ...(typeof footerExpanded === 'boolean' ? { footerExpanded } : {}),
    },
  });
}

export function getCenterSplit(projectId) {
  return !!loadState(projectId).centerSplit;
}

export function saveCenterSplit(projectId, enabled) {
  saveState(projectId, { centerSplit: !!enabled });
}

export function getSplitDepthTab(projectId) {
  const id = loadState(projectId).splitDepthTab;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

export function getSplitBreadthTab(projectId) {
  const id = loadState(projectId).splitBreadthTab;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

export function saveSplitTabs(projectId, { depthId, breadthId } = {}) {
  saveState(projectId, {
    splitDepthTab: depthId || null,
    splitBreadthTab: breadthId || null,
  });
}

export function saveLastOpenProject(projectId) {
  if (!projectId) {
    clearLastOpenProject();
    return;
  }
  try {
    Storage.set(LAST_OPEN_PROJECT_KEY, projectId);
  } catch {}
}

export function clearLastOpenProject() {
  try {
    Storage.remove(LAST_OPEN_PROJECT_KEY);
  } catch {}
}

export function getLastOpenProject() {
  try {
    return Storage.get(LAST_OPEN_PROJECT_KEY, null);
  } catch {
    return null;
  }
}

export default {
  loadState,
  saveState,
  getOpenFile,
  saveOpenFile,
  getActiveChat,
  saveActiveChat,
  getLeftTab,
  saveLeftTab,
  getBottomTab,
  saveBottomTab,
  getCenterTabs,
  saveCenterTabs,
  getActiveCenterTab,
  saveActiveCenterTab,
  getLayoutSizes,
  saveLayoutSizes,
  getCenterSplit,
  saveCenterSplit,
  getSplitDepthTab,
  getSplitBreadthTab,
  saveSplitTabs,
  saveLastOpenProject,
  getLastOpenProject,
  clearLastOpenProject,
};
